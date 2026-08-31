"""The board/port/variant database MicroPython's own `board.json` files
describe -- vendored from `mpbuild`, not depended on (docs/0000-TRACKER.md D7).

`mpbuild` (https://github.com/mattytrentini/mpbuild, PyPI `mpbuild`) has a
board database worth reusing, but the package itself drags in `rich` +
`textual` + `typer` and requires Python >=3.12 -- a TUI stack this project
has stayed standard-library-only since M1/M2 specifically to avoid. This
module is a vendored copy of its `src/mpbuild/board_database.py`
(stdlib-only: `glob`, `json`, `dataclasses`, `pathlib`), not an import of
the package.

Vendored from:
  https://github.com/mattytrentini/mpbuild
  commit 972d8319f90dd5a70e3ab6fd1660b9d5a01017fe (v1.2.0)
  src/mpbuild/board_database.py

Deliberately NOT vendored: `mpbuild`'s own port -> Docker-image resolution
(its `BUILD_CONTAINERS` table and `docker_build_cmd()`, both in its
`build.py`, not `board_database.py`) and command construction. That layer
is `cibuildmp`'s own job to resolve (D3), and verifying it directly against
`mpbuild`'s source confirmed the boundary holds exactly at the file level:
`board_database.py` has zero Docker references. `Board.images` below is
board *photographs* from the `micropython-media` repo, not container
images -- easy to misread as a hit on a `docker`/`image` grep.

Also NOT covered here: `zephyr` (D22). `ports/zephyr` ships no `board.json`
at all -- board selection there is a flat `<board>.conf` + optional
`<board>.overlay` pair, MicroPython's own zephyr-specific convention. The
scan below finds zero zephyr boards, which is correct: there is nothing in
that shape for this scanner to find, not a gap in the scan itself.

Changed from upstream, deliberately:
- `MpbuildMpyDirectoryException` is `BoardDatabaseError` here, matching
  this project's `<Module>Error` convention (SourceError, ConfigError,
  ToolchainError, ...); the `assert_mpy_root_direcory` typo is fixed to
  `assert_mpy_root_directory`.
- `Database.check_board_json` is a module-level `check_board_json()`, not
  a staticmethod -- this file otherwise has no other use for `Database` as
  a namespace, and the rest of `cibuildmp` favours free functions
  (targets.py, sources.py) over classes-as-namespaces.
- `Board.find_variant()` no longer prints to stdout when the variant is
  not found; it just returns None, same as any other lookup miss here.
  Printing on a miss is a caller's decision, not this module's.

Everything else -- class shapes, field names, the board.json schema read,
the unix/webassembly/windows "special port" handling -- is unchanged, so a
future upstream diff stays easy to read against this file.

---

Original module docstring, kept for context:

The micropython git repo contains many 'board.json' files.

This is an example:
ports/stm32/boards/PYBV11/board.json

{
    "deploy": [
        "../PYBV10/deploy.md"
    ],
    "docs": "",
    "features": [],
    "images": [
        "PYBv1_1.jpg",
        "PYBv1_1-C.jpg",
        "PYBv1_1-E.jpg"
    ],
    "mcu": "stm32f4",
    "product": "Pyboard v1.1",
    "thumbnail": "",
    "url": "https://store.micropython.org/product/PYBv1.1",
    "variants": {
        "DP": "Double-precision float",
        "DP_THREAD": "Double precision float + Threads",
        "NETWORK": "Wiznet 5200 Driver",
        "THREAD": "Threading"
    },
    "vendor": "George Robotics"
}

This module implements `class Database` which reads all 'board.json' files
and provides a way to browse it's data.

---

MIT License

Copyright (c) 2024 Matt Trentini

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to
deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
sell copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from glob import glob
from pathlib import Path

# Ports with no board.json at all: they select a `variant:` (from
# `variants/*/`) instead of a `board:`. See docs/0000-TRACKER.md, "Two different
# selector axes". `zephyr` is NOT one of these -- it has neither a board.json
# nor a variants/ directory in this sense (D22).
_VARIANT_ONLY_PORTS = ("unix", "webassembly", "windows")


class BoardDatabaseError(Exception):
    """Raised when `mpy_root_directory` does not point at a MicroPython
    checkout (upstream: `MpbuildMpyDirectoryException`)."""


@dataclass(order=True)
class Variant:
    name: str
    """Example: "DP_THREAD" """

    text: str
    """Example: "Double precision float + Threads" """

    board: Board = field(repr=False)


@dataclass(order=True)
class Board:
    name: str
    """Example: "PYBV11" """

    variants: list[Variant]
    """Variants available for this board, sorted. Empty list if none."""

    url: str
    """Primary URL to link to this board."""

    mcu: str
    """Example: "stm32f4" """

    product: str
    """Example: "Pyboard v1.1" """

    vendor: str
    """Example: "George Robotics" """

    images: list[str]
    """Board photographs, stored in the micropython-media repository --
    NOT container images. Example: ["PYBv1_1.jpg", "PYBv1_1-C.jpg"]."""

    deploy: list[str]
    """Files explaining how to deploy this board.
    Example: ["../PYBV10/deploy.md"]"""

    physical_board: bool
    """False for the 'special' variant-only ports (_VARIANT_ONLY_PORTS),
    True for every regular board.json-backed board."""

    port: Port = field(compare=False)

    @staticmethod
    def factory(port: Port, filename_json: Path) -> Board:
        with filename_json.open() as f:
            board_json = json.load(f)

        board = Board(
            name=filename_json.parent.name,
            variants=[],
            url=board_json.get("url", "http://micropython.org"),
            mcu=board_json.get("mcu", ""),
            product=board_json.get("product", ""),
            vendor=board_json.get("vendor", ""),
            images=board_json.get("images", []),
            deploy=board_json.get("deploy", []),
            physical_board=True,
            port=port,
        )
        board.variants.extend(
            sorted(
                [
                    Variant(name=name, text=text, board=board)
                    for name, text in board_json.get("variants", {}).items()
                ]
            )
        )
        return board

    @property
    def directory(self) -> Path:
        """Example: ports/stm32/boards/PYBV11"""
        if self.physical_board:
            directory_ = self.port.directory / "boards" / self.name
        else:
            directory_ = self.port.directory
        if not directory_.is_dir():
            raise ValueError(f"Directory does not exist: {directory_}")
        return directory_

    @property
    def deploy_filename(self) -> Path | None:
        """The deploy-markdown's filename, or None."""
        return self.directory / self.deploy[0] if self.deploy else None

    def find_variant(self, variant: str) -> Variant | None:
        """The named variant, or None if this board has no such variant."""
        for v in self.variants:
            if v.name == variant:
                return v
        return None


@dataclass(order=True)
class Port:
    name: str
    """Example: "stm32" """

    directory: Path
    """The port source directory. Example: "ports/stm32" """

    boards: dict[str, Board] = field(default_factory=dict, repr=False)
    """Keyed by board name, e.g. "PYBV11"."""

    @property
    def directory_repo(self) -> Path:
        """The top directory of the MicroPython repo this port lives in."""
        repo = self.directory.parent.parent
        Database.assert_mpy_root_directory(repo)
        return repo


@dataclass
class Database:
    """Every board.json under `mpy_root_directory`, plus the variant-only
    ports (_VARIANT_ONLY_PORTS) that have none."""

    mpy_root_directory: Path = field(repr=False)
    port_filter: str = field(default="", repr=False)

    ports: dict[str, Port] = field(default_factory=dict)
    boards: dict[str, Board] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Does NOT require a git checkout: only `(root / "ports").is_dir()`
        # is checked, nothing here touches git -- a release tarball (M1)
        # satisfies this just as well as a clone.
        if not (self.mpy_root_directory / "ports").is_dir():
            raise BoardDatabaseError(
                "'mpy_root_directory' should point to the top of a MicroPython "
                f"repo: {self.mpy_root_directory}"
            )

        # Path.glob was measured 15x slower for this upstream -- kept as glob().
        for p in glob(f"{self.mpy_root_directory}/ports/*/boards/*/board.json"):
            filename_json = Path(p)
            port_directory = filename_json.parent.parent.parent
            port_name = port_directory.name
            if self.port_filter and self.port_filter != port_name:
                continue

            port = self.ports.get(port_name)
            if port is None:
                port = Port(name=port_name, directory=port_directory)
                self.ports[port_name] = port

            board = Board.factory(port=port, filename_json=filename_json)
            port.boards[board.name] = board
            self.boards[board.name] = board

        for special_port_name in _VARIANT_ONLY_PORTS:
            if self.port_filter and self.port_filter != special_port_name:
                continue
            path = self.mpy_root_directory / "ports" / special_port_name
            variant_names = [
                var.name for var in path.glob("variants/*") if var.is_dir()
            ]
            port = Port(name=special_port_name, directory=path)
            board = Board(
                name=special_port_name,
                variants=[],
                url=(
                    "https://github.com/micropython/micropython/blob/master/"
                    f"ports/{special_port_name}/README.md"
                ),
                mcu="",
                product="",
                vendor="",
                images=[],
                deploy=[],
                physical_board=False,
                port=port,
            )
            port.boards = {special_port_name: board}
            board.variants = [
                Variant(name=v, text="", board=board) for v in variant_names
            ]
            self.ports[special_port_name] = port
            self.boards[board.name] = board

    @staticmethod
    def assert_mpy_root_directory(directory: Path) -> None:
        """Raise BoardDatabaseError if `directory` is not a MicroPython repo."""
        if not (directory / "ports").is_dir():
            raise BoardDatabaseError(
                f"Directory does not point to the top of a MicroPython repo: {directory}"
            )


def check_board_json(board_json: dict, board_name: str, port_name: str) -> list[str]:
    """Check a board.json's already-parsed contents for missing or invalid
    keys. Returns a list of human-readable issues, empty if none."""
    issues = []
    required_keys = ["mcu", "product", "vendor", "images", "deploy"]

    for key in required_keys:
        if key not in board_json:
            issues.append(f"{port_name}/{board_name}: missing required key '{key}'")

    if "url" not in board_json:
        issues.append(f"{port_name}/{board_name}: missing URL key")

    if "variants" in board_json and not isinstance(board_json["variants"], dict):
        issues.append(f"{port_name}/{board_name}: 'variants' is not a dictionary")

    if "images" in board_json and not isinstance(board_json["images"], list):
        issues.append(f"{port_name}/{board_name}: 'images' is not a list")

    if "deploy" in board_json and not isinstance(board_json["deploy"], list):
        issues.append(f"{port_name}/{board_name}: 'deploy' is not a list")

    return issues

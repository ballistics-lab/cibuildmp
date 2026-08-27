#!/usr/bin/env -S uv run --script

"""Print the real, per-tag esp32 board fact table as TOML.

Fact-first, not axis-first (record 0052): rather than declaring one board
list and crossing it against every MicroPython tag, this shallow-clones
each tag given on the command line and reads its own real
`ports/esp32/boards/*/board.json` files -- reusing
`cibuildmp.platforms.usermod.boards.Database`, the same vendored `mpbuild`
board-database reader `usermod/build.py` already trusts, rather than
parsing the JSON a second time by hand.

    bin/refresh_esp32_boards.py v1.20.0 v1.21.0 v1.24.0 v1.29.0 > /tmp/esp32.toml

Unlike `bin/refresh_natmod_archs.py`, this does NOT auto-discover tags:
board.json scanning needs a real directory tree per tag (a sparse clone,
not a couple of raw-file fetches), which is expensive enough that walking
every tag MicroPython has ever had is not something to do by default --
the caller decides which tags matter (record 0052's own tag-pruning
policy: every stable release >= v1.20.0, plus the single newest preview,
applied by the caller, not baked in here).

Output is `[usermod.esp32]` / `identifiers = [ {...}, {...}, ... ]`, one
compact inline table per board, matching every other section already in
`resources/build-platforms.toml`. This script does not write that file
itself -- same reasoning as `refresh_natmod_archs.py`: redirect and
review by hand.

Board counts and even the naming scheme are real, verified-live facts
that change across tags, not something to assume stable: v1.20.0 uses a
bare `GENERIC*` prefix (41 boards), v1.24.0 switched to `ESP32_GENERIC*`
(32 boards), and the count is not monotonic after that either (29 at
v1.24.1, 81 at v1.29.0) -- every tag given is walked independently, never
extrapolated from a neighbor.

`variants` (a board's real sub-variants, e.g. `SPIRAM`/`OTA`) is recorded
as metadata (board.json's own dict, kept here as just the name list) --
cibuildmp has no variant-selection axis in its own code yet
(`Esp32BuildOptions.board: str`, no `variant` field), so this is a fact
about the board, not something usermod/targets.py's own identifier scheme
resolves through today.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from cibuildmp.platforms.usermod.boards import BoardDatabaseError, Database

REPO_URL = "https://github.com/micropython/micropython"
PORT = "esp32"


def clone_sparse(tag: str, dest: Path) -> None:
    """A shallow clone of `tag`, checked out to `ports/{PORT}` only --
    board.json scanning needs that whole subtree, nothing else here does.
    """
    subprocess.run(
        [
            "git", "clone", "--quiet", "--depth", "1", "--branch", tag,
            "--filter=blob:none", "--sparse", REPO_URL, str(dest),
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(dest), "sparse-checkout", "set", f"ports/{PORT}"],
        check=True,
    )


def commit_date(dest: Path) -> str:
    out = subprocess.run(
        ["git", "-C", str(dest), "log", "-1", "--format=%cI"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()[:10]


def board_rows(tag: str, date: str, checkout: Path) -> list[dict]:
    try:
        db = Database(mpy_root_directory=checkout, port_filter=PORT)
    except BoardDatabaseError as exc:
        print(f"!! {tag}: {exc}", file=sys.stderr)
        return []

    rows = []
    for name in sorted(db.boards):
        board = db.boards[name]
        rows.append(
            {
                "tag": tag,
                "date": date,
                "board": name,
                "mcu": board.mcu,
                "product": board.product,
                "vendor": board.vendor,
                "variants": [v.name for v in board.variants],
                "identifier": f"{tag}-{PORT}-{name}",
            }
        )
    return rows


def _toml_str(value: str) -> str:
    """A TOML basic string, escaped by hand -- same reasoning as
    refresh_natmod_archs.py's own _toml_str: stdlib has no TOML writer,
    and this project stays off third-party dependencies for anything that
    isn't the native-.mpy link step itself."""
    out = ['"']
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _toml_str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"unsupported TOML value type: {type(value)!r}")


def _inline_row(row: dict) -> str:
    parts = [f"{key} = {_toml_value(value)}" for key, value in row.items() if value not in (None, "")]
    return "{ " + ", ".join(parts) + " }"


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("tags", nargs="+", help="MicroPython tags to walk, e.g. v1.20.0 v1.29.0")
    parser.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help="reuse clones already present here instead of a fresh temp dir "
        "(skips re-cloning a tag whose subdirectory already exists)",
    )
    args = parser.parse_args()

    workdir = args.workdir
    cleanup = False
    if workdir is None:
        workdir = Path(tempfile.mkdtemp(prefix="cibuildmp-esp32-boards-"))
        cleanup = True
    workdir.mkdir(parents=True, exist_ok=True)

    rows = []
    try:
        for tag in args.tags:
            dest = workdir / tag
            if not dest.exists():
                print(f"cloning {tag}...", file=sys.stderr)
                clone_sparse(tag, dest)
            date = commit_date(dest)
            rows.extend(board_rows(tag, date, dest))
    finally:
        if cleanup:
            shutil.rmtree(workdir, ignore_errors=True)

    print("[usermod.esp32]")
    print("identifiers = [")
    for row in rows:
        print("    " + _inline_row(row) + ",")
    print("]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

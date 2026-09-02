#!/usr/bin/env -S uv run --script

"""Print the real, per-tag board fact table for a board.json-backed
usermod port, as TOML.

Fact-first, not axis-first (record 0052): rather than declaring one board
list and crossing it against every MicroPython tag, this shallow-clones
each tag given on the command line and reads its own real
`ports/<port>/boards/*/board.json` files -- reusing
`cibuildmp.platforms.usermod.boards.Database`, the same vendored `mpbuild`
board-database reader `usermod/build_<port>.py` already trusts, rather than
parsing the JSON a second time by hand.

    bin/refresh_usermod_boards.py esp32 v1.20.0 v1.21.0 v1.24.0 v1.29.0 > /tmp/esp32.toml
    bin/refresh_usermod_boards.py stm32 v1.20.0 v1.28.0 v1.29.0 > /tmp/stm32.toml

Generalized from an esp32-only predecessor (since deleted) once
a second board.json-backed port (rp2) needed the exact same treatment --
`Database`'s own `port_filter` was already port-agnostic, only this
script's own PORT constant was not. `port` is a plain positional
argument, so any board.json-backed port needs no code change here, only
a new `[usermod.<port>]` section built by running this against it. Every
port `resources/build-platforms.toml` has such a section for as of this
writing went through this exact tool: Tier 1's esp32/rp2/mimxrt/samd/
stm32, and Tier 2's psoc-edge.

Unlike `bin/refresh_natmod_archs.py`, this does NOT auto-discover tags:
board.json scanning needs a real directory tree per tag (a sparse clone,
not a couple of raw-file fetches), which is expensive enough that walking
every tag MicroPython has ever had is not something to do by default --
the caller decides which tags matter.

Output is a `[tags]` table (tag -> {date, sha}, the pure per-tag facts
`resources/build-platforms.toml` keeps in one shared place rather than
repeated on every row -- merge this into that file's own existing [tags]
table rather than replacing it) followed by `[usermod.<port>]` /
`identifiers = [ {...}, {...}, ... ]`, one compact inline table per board.
This script does not write build-platforms.toml itself -- redirect and
review by hand.

Board counts, and even the naming scheme, are real per-port, per-tag
facts, never assumed stable across tags: esp32 alone went from a bare
`GENERIC*` prefix (v1.20.0) to `ESP32_GENERIC*` (v1.24.0+), and board
counts are not monotonic either. Every tag given is walked independently,
never extrapolated from a neighbor.

`variants` (a board's real sub-variants, e.g. esp32's `SPIRAM`/`OTA`, rp2's
`RISCV`) is recorded as metadata (board.json's own dict, kept here as just
the name list) -- neither esp32 nor rp2 has a variant-selection axis in
cibuildmp's own code today (`Esp32BuildOptions`/a future `Rp2BuildOptions`
take a board name only), so this is a fact about the board, not something
usermod/targets.py's own identifier scheme resolves through yet.

No submodule-pin flag here (an earlier version had one, --submodule PATH
--submodule-field NAME, covering rp2's lib/pico-sdk, mimxrt's
lib/nxp_driver, samd's lib/asf4): a submodule pin is itself a pure
function of the MicroPython tag/sha already in [tags] -- checking it out
is one `git ls-tree HEAD <path>` against a checkout of that same sha away,
not a separate fact worth storing on every row. Dropped rather than kept
around unused.

`cross` (this port's own `ports/<port>/Makefile` `CROSS_COMPILE`
default) is read per tag too now -- see parse_cross_compile()'s own
docstring for why some ports genuinely have none to report (rp2, alif)
rather than one silently missed.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

from cibuildmp.platforms.usermod.boards import BoardDatabaseError, Database

# The rows in `resources/build-platforms.toml` are not all produced here.
# `gcc` (nine usermod scopes plus natmod), `idf_version` (esp32) and
# `toolchain_version` (alif) are per-row facts merged in by hand from
# `bin/refresh_toolchain_pins.py`, which by the pipeline's own stated
# convention "reads both files; it writes neither". So a plain
# regeneration of a section prints only the keys below and silently drops
# every one of those -- 374 `gcc` values for `rp2` alone -- and nothing
# would notice: no refresh script runs in CI, in the tests, or in
# pre-commit. Hence carrying them forward here, unconditionally.
#
# Unconditional, and not behind an opt-in flag, because a flag nobody
# remembers to pass is a description of the bug rather than a fix for it.
# `--no-merge` is the deliberate reset, for when a hand-merged fact is
# meant to disappear.
MERGE_SOURCE = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "cibuildmp"
    / "resources"
    / "build-platforms.toml"
)


def carry_forward(
    rows: list[dict], section: tuple[str, ...], source: Path
) -> list[dict]:
    """Re-attach per-row keys the existing table has and this script does
    not produce, matched by `identifier` (verified unique within every
    section, natmod's included). Generated values always win; only keys
    absent from the generated row are taken. Reports what it carried to
    stderr, so a silent carry is as visible as a silent loss would be.
    """
    try:
        with source.open("rb") as handle:
            data = tomllib.load(handle)
    except OSError as exc:
        print(f"!! --merge: cannot read {source}: {exc}", file=sys.stderr)
        return rows
    for key in section:
        data = data.get(key) or {}
    existing = {row["identifier"]: row for row in data.get("identifiers") or []}
    if not existing:
        print(
            f"!! --merge: {'.'.join(section)} has no rows in {source.name}",
            file=sys.stderr,
        )
        return rows

    carried: dict[str, int] = {}
    for row in rows:
        previous = existing.get(row["identifier"])
        if not previous:
            continue
        for key, value in previous.items():
            if key not in row:
                row[key] = value
                carried[key] = carried.get(key, 0) + 1
    if carried:
        summary = ", ".join(f"{key} x{count}" for key, count in sorted(carried.items()))
        print(f"carried forward from {source.name}: {summary}", file=sys.stderr)
    else:
        print(f"carried forward from {source.name}: nothing", file=sys.stderr)
    return rows


REPO_URL = "https://github.com/micropython/micropython"


def clone_sparse(tag: str, port: str, dest: Path) -> None:
    """A shallow clone of `tag`, checked out to `ports/{port}` only --
    board.json scanning needs that whole subtree, nothing else here does.
    """
    subprocess.run(
        [
            "git",
            "clone",
            "--quiet",
            "--depth",
            "1",
            "--branch",
            tag,
            "--filter=blob:none",
            "--sparse",
            REPO_URL,
            str(dest),
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(dest), "sparse-checkout", "set", f"ports/{port}"],
        check=True,
    )


def commit_date(dest: Path) -> str:
    out = subprocess.run(
        ["git", "-C", str(dest), "log", "-1", "--format=%cI"],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()[:10]


def commit_sha(dest: Path) -> str:
    out = subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def parse_cross_compile(port: str, checkout: Path) -> str | None:
    """This port's own `CROSS_COMPILE` default from its real
    `ports/<port>/Makefile`, or None wherever that Makefile sets none --
    confirmed live to be a real, meaningful distinction, not a scan gap:
    `py/mkenv.mk` (every port's own Makefile includes it) sets no default
    of its own (`AS = $(CROSS_COMPILE)as` etc, `CROSS_COMPILE` itself
    unset), so a port that never assigns it (rp2 -- a CMake wrapper, its
    real toolchain is resolved inside the vendored `lib/pico-sdk`
    submodule, not this Makefile; alif -- no default anywhere, must be
    passed in externally) genuinely has none to report here, the same
    way `parse_cross_prefixes()` in refresh_natmod_archs.py already
    leaves a natmod arch's own `cross` absent rather than guessed.

    Checked stable across every tag this project has scanned so far for
    every port that does set one (mimxrt/samd/stm32/psoc-edge/cc3200/
    renesas-ra/nrf: `arm-none-eabi-`; esp8266: `xtensa-lx106-elf-`) --
    still read per tag, not cached across tags, since nothing here
    guarantees it never changes (esp32's own idf_version already proved
    a per-tag/per-MCU toolchain fact can vary within this same project).
    """
    makefile = checkout / "ports" / port / "Makefile"
    try:
        text = makefile.read_text(errors="ignore")
    except OSError:
        return None
    match = re.search(r"^CROSS_COMPILE\s*[?:]?=\s*(\S+)\s*$", text, re.MULTILINE)
    return match.group(1) if match else None


def board_rows(tag: str, port: str, checkout: Path) -> list[dict]:
    try:
        db = Database(mpy_root_directory=checkout, port_filter=port)
    except BoardDatabaseError as exc:
        print(f"!! {tag}: {exc}", file=sys.stderr)
        return []

    cross = parse_cross_compile(port, checkout)

    rows = []
    for name in sorted(db.boards):
        board = db.boards[name]
        rows.append(
            {
                "tag": tag,
                "board": name,
                "mcu": board.mcu,
                "product": board.product,
                "vendor": board.vendor,
                "variants": [v.name for v in board.variants],
                "cross": cross,
                "identifier": f"{tag}-{port}-{name}",
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
    parts = [
        f"{key} = {_toml_value(value)}"
        for key, value in row.items()
        if value not in (None, "")
    ]
    return "{ " + ", ".join(parts) + " }"


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("port", help="usermod port to walk, e.g. esp32, rp2")
    parser.add_argument(
        "tags", nargs="+", help="MicroPython tags to walk, e.g. v1.20.0 v1.29.0"
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="print only this script's own keys, dropping hand-merged per-row facts",
    )
    parser.add_argument(
        "--merge-from",
        type=Path,
        default=MERGE_SOURCE,
        metavar="PATH",
        help=f"default: {MERGE_SOURCE}",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help="reuse clones already present here instead of a fresh temp dir "
        "(skips re-cloning a tag whose subdirectory already exists; "
        "clones are namespaced by port, so one --workdir is safe to reuse "
        "across ports)",
    )
    args = parser.parse_args()

    workdir = args.workdir
    cleanup = False
    if workdir is None:
        workdir = Path(tempfile.mkdtemp(prefix="cibuildmp-usermod-boards-"))
        cleanup = True
    workdir.mkdir(parents=True, exist_ok=True)

    rows = []
    tags: dict[str, dict[str, str]] = {}
    try:
        for tag in args.tags:
            dest = workdir / args.port / tag
            if not dest.exists():
                print(f"cloning {tag} ({args.port})...", file=sys.stderr)
                clone_sparse(tag, args.port, dest)
            tags[tag] = {"date": commit_date(dest), "sha": commit_sha(dest)}
            rows.extend(board_rows(tag, args.port, dest))
    finally:
        if cleanup:
            shutil.rmtree(workdir, ignore_errors=True)

    print("[tags]")
    for tag, info in tags.items():
        print(f'"{tag}" = {_inline_row(info)}')
    print()
    if not args.no_merge:
        rows = carry_forward(rows, ("usermod", args.port), args.merge_from)
    print(f"[usermod.{args.port}]")
    print("identifiers = [")
    for row in rows:
        print("    " + _inline_row(row) + ",")
    print("]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

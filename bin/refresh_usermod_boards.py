#!/usr/bin/env -S uv run --script

"""Print the real, per-tag board fact table for a board.json-backed
usermod port, as TOML.

Fact-first, not axis-first (record 0052): rather than declaring one board
list and crossing it against every MicroPython tag, this shallow-clones
each tag given on the command line and reads its own real
`ports/<port>/boards/*/board.json` files -- reusing
`cibuildmp.platforms.usermod.boards.Database`, the same vendored `mpbuild`
board-database reader `usermod/build.py` already trusts, rather than
parsing the JSON a second time by hand.

    bin/refresh_usermod_boards.py esp32 v1.20.0 v1.21.0 v1.24.0 v1.29.0 > /tmp/esp32.toml
    bin/refresh_usermod_boards.py rp2 v1.20.0 v1.28.0 v1.29.0 > /tmp/rp2.toml

Generalized from an esp32-only version (`bin/refresh_esp32_boards.py`) once
a second board.json-backed port (rp2) needed the exact same treatment --
`Database`'s own `port_filter` was already port-agnostic, only this
script's own PORT constant was not.

Unlike `bin/refresh_natmod_archs.py`, this does NOT auto-discover tags:
board.json scanning needs a real directory tree per tag (a sparse clone,
not a couple of raw-file fetches), which is expensive enough that walking
every tag MicroPython has ever had is not something to do by default --
the caller decides which tags matter.

Output is `[usermod.<port>]` / `identifiers = [ {...}, {...}, ... ]`, one
compact inline table per board, matching every other section already in
`resources/build-platforms.toml`. This script does not write that file
itself -- redirect and review by hand.

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

Optional `--submodule PATH --submodule-field NAME [--submodule-repo URL]`
adds one more per-row fact: that submodule's own pin at each tag (`git
ls-tree HEAD <PATH>`), stored under `NAME`. This covers the three ports
seen so far that vendor their SDK as a real git submodule (rp2's
lib/pico-sdk, mimxrt's lib/nxp_driver, samd's lib/asf4) -- NOT esp32,
whose ESP-IDF pin is not a submodule at all (resolved from tools/ci.sh /
ports/esp32/lockfiles/dependencies.lock.esp32 instead, a genuinely
different mechanism this flag does not cover). If `--submodule-repo` is
given, the pinned commit is cross-checked against that repo's own real
tags (`git ls-remote --tags`) and the matching tag name is stored instead
of the raw sha when one exists -- exactly the by-hand resolution rp2's
own pico_sdk_version already used, now reusable. Omit `--submodule-repo`
(or when no tag matches) and the raw sha is stored, matching mimxrt's
nxp_driver_sha and samd's asf4_sha -- neither of their own upstream repos
carries any tags to resolve against.
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


def clone_sparse(tag: str, port: str, dest: Path) -> None:
    """A shallow clone of `tag`, checked out to `ports/{port}` only --
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
        ["git", "-C", str(dest), "sparse-checkout", "set", f"ports/{port}"],
        check=True,
    )


def commit_date(dest: Path) -> str:
    out = subprocess.run(
        ["git", "-C", str(dest), "log", "-1", "--format=%cI"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()[:10]


def commit_sha(dest: Path) -> str:
    """The MicroPython tag's own commit sha -- refresh_natmod_archs.py's
    rows already carry this (a side effect of fetching per-ref content
    there); this script had no equivalent until this field was pointed
    out as missing, an oversight rather than a deliberate omission."""
    out = subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def submodule_pin(checkout: Path, submodule: str) -> str | None:
    """The commit sha `submodule` (e.g. "lib/pico-sdk") is pinned at in
    this checkout, or None if that path isn't a submodule here at all
    (e.g. esp32 -- its ESP-IDF pin lives outside .gitmodules entirely)."""
    out = subprocess.run(
        ["git", "-C", str(checkout), "ls-tree", "HEAD", submodule],
        capture_output=True, text=True, check=True,
    )
    line = out.stdout.strip()
    if not line:
        return None
    # "160000 commit <sha>\t<path>" -- a submodule entry's own mode/type.
    fields = line.split()
    if len(fields) < 3 or fields[1] != "commit":
        return None
    return fields[2]


def load_upstream_tags(repo_url: str) -> dict[str, str]:
    """{sha: tag_name} for every tag `repo_url` has, fetched once and
    reused across every row that shares the same --submodule-repo."""
    out = subprocess.run(
        ["git", "ls-remote", "--tags", repo_url],
        capture_output=True, text=True, check=True,
    )
    tags: dict[str, str] = {}
    for line in out.stdout.splitlines():
        fields = line.split()
        if len(fields) != 2 or fields[1].endswith("^{}"):
            continue
        tags[fields[0]] = fields[1].removeprefix("refs/tags/")
    return tags


def board_rows(
    tag: str,
    port: str,
    date: str,
    sha: str,
    checkout: Path,
    *,
    submodule_field: str | None = None,
    submodule_value: str | None = None,
) -> list[dict]:
    try:
        db = Database(mpy_root_directory=checkout, port_filter=port)
    except BoardDatabaseError as exc:
        print(f"!! {tag}: {exc}", file=sys.stderr)
        return []

    rows = []
    for name in sorted(db.boards):
        board = db.boards[name]
        row: dict[str, object] = {"tag": tag, "date": date, "sha": sha}
        if submodule_field and submodule_value is not None:
            row[submodule_field] = submodule_value
        row.update(
            {
                "board": name,
                "mcu": board.mcu,
                "product": board.product,
                "vendor": board.vendor,
                "variants": [v.name for v in board.variants],
                "identifier": f"{tag}-{port}-{name}",
            }
        )
        rows.append(row)
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
    parser.add_argument("port", help="usermod port to walk, e.g. esp32, rp2")
    parser.add_argument("tags", nargs="+", help="MicroPython tags to walk, e.g. v1.20.0 v1.29.0")
    parser.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help="reuse clones already present here instead of a fresh temp dir "
        "(skips re-cloning a tag whose subdirectory already exists; "
        "clones are namespaced by port, so one --workdir is safe to reuse "
        "across ports)",
    )
    parser.add_argument(
        "--submodule",
        default=None,
        help="path of a git submodule to record the per-tag pin of, e.g. "
        "lib/pico-sdk (see the module docstring -- covers rp2/mimxrt/samd, "
        "NOT esp32, which vendors ESP-IDF outside .gitmodules entirely)",
    )
    parser.add_argument(
        "--submodule-field",
        default=None,
        help="row field name for --submodule's value, e.g. pico_sdk_version",
    )
    parser.add_argument(
        "--submodule-repo",
        default=None,
        help="optional upstream repo URL to resolve --submodule's pinned "
        "commit against real tags (git ls-remote --tags); the raw sha is "
        "stored instead when omitted or when no tag matches",
    )
    args = parser.parse_args()

    if bool(args.submodule) != bool(args.submodule_field):
        parser.error("--submodule and --submodule-field must be given together")

    upstream_tags = load_upstream_tags(args.submodule_repo) if args.submodule_repo else {}

    workdir = args.workdir
    cleanup = False
    if workdir is None:
        workdir = Path(tempfile.mkdtemp(prefix="cibuildmp-usermod-boards-"))
        cleanup = True
    workdir.mkdir(parents=True, exist_ok=True)

    rows = []
    try:
        for tag in args.tags:
            dest = workdir / args.port / tag
            if not dest.exists():
                print(f"cloning {tag} ({args.port})...", file=sys.stderr)
                clone_sparse(tag, args.port, dest)
            date = commit_date(dest)
            sha = commit_sha(dest)
            submodule_value = None
            if args.submodule:
                pin = submodule_pin(dest, args.submodule)
                if pin is None:
                    print(f"!! {tag}: {args.submodule!r} is not a submodule here", file=sys.stderr)
                else:
                    submodule_value = upstream_tags.get(pin, pin)
            rows.extend(
                board_rows(
                    tag, args.port, date, sha, dest,
                    submodule_field=args.submodule_field,
                    submodule_value=submodule_value,
                )
            )
    finally:
        if cleanup:
            shutil.rmtree(workdir, ignore_errors=True)

    print(f"[usermod.{args.port}]")
    print("identifiers = [")
    for row in rows:
        print("    " + _inline_row(row) + ",")
    print("]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

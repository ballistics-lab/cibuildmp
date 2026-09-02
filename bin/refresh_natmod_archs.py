#!/usr/bin/env -S uv run --script

"""Print the real, per-tag natmod arch fact table as TOML.

Fact-first, not axis-first (record 0052): rather than declaring "natmod
supports these N arches" once and crossing it against every MicroPython
tag, this walks each tag's own real source directly --
`py/persistentcode.h`'s `MP_NATIVE_ARCH_*` enum for the arch names/codes,
`py/dynruntime.mk` for which of those are actually buildable ARCH=
targets and their cross-compiler prefix -- and prints one row per
verified (tag, arch) pair it actually found.

    bin/refresh_natmod_archs.py > /tmp/natmod-archs.toml

Output is a `[tags]` table (tag -> {sha, date}, the pure per-tag facts
`resources/build-platforms.toml` keeps in one shared place rather than
repeated on every row that references a tag -- merge this into that
file's own existing [tags] table rather than replacing it) followed by
`[natmod]` / `identifiers = [ {...}, {...}, ... ]`, one compact inline
table per row. This script does not write build-platforms.toml itself --
redirect and review by hand.

Two things every row is deliberately careful about, both found by hand
this way rather than assumed:

* `armv7emsp`/`armv7emdp` are two independent arch names, not a shared
  base `armv7em` plus a 0/1/2 flag -- confirmed against both
  `dynruntime.mk` (two separate `ifeq ($(ARCH),...)` branches with
  different `-mcpu`/`-mfpu` flags) and `tools/mpy_ld.py`'s `ARCH_DATA`
  (two separate keys, no `armv7em` key at all). Bare `armv7em` is a real
  enum entry (used elsewhere, e.g. to describe a no-FPU firmware build)
  but not a valid natmod `ARCH=` target, so it is filtered out along with
  `none`, bare `armv6`, and `debug` -- all real enum entries, none of
  them buildable natmod arches.
* `arch_flags` is always 0 here and `cross` is omitted (not `null` --
  TOML has no null) wherever it could not be read for that specific tag.
  Neither is guessed from a neighboring tag or a different arch's row.

Needs a GitHub token to avoid the unauthenticated API's 60-requests/hour
limit (this makes roughly four requests per tag -- one more than before
for the commit-date lookup [tags] needs, since the tags endpoint itself
carries a sha but no date): set `GITHUB_TOKEN` in the environment, or run
without one and expect to get rate-limited past ~15 tags.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "https://api.github.com/repos/micropython/micropython"
RAW_BASE = "https://raw.githubusercontent.com/micropython/micropython"
USER_AGENT = "cibuildmp-refresh-natmod-archs"

# The real buildable set -- confirmed directly against py/dynruntime.mk's
# literal ifeq ($(ARCH), ...) branches and tools/mpy_ld.py's ARCH_DATA
# keys (see the module docstring).
NATMOD_BUILDABLE_ARCHES = frozenset(
    {
        "x86",
        "x64",
        "armv6m",
        "armv7m",
        "armv7emsp",
        "armv7emdp",
        "xtensa",
        "xtensawin",
        "rv32imc",
        "rv64imc",
    }
)


def _headers(token: str | None, *, accept_json: bool = False) -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT}
    if accept_json:
        headers["Accept"] = "application/vnd.github.v3+json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_raw(path: str, ref: str, token: str | None) -> str | None:
    """Raw text of `path` at `ref`, or None if it doesn't exist there.

    Some paths moved or didn't exist yet on older tags -- absence is a
    fact this returns, not an error to raise past.
    """
    url = f"{RAW_BASE}/{ref}/{path}"
    request = urllib.request.Request(url, headers=_headers(token))
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise RuntimeError(f"{url} -> HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{url} -> {exc.reason}") from exc


def fetch_tags(token: str | None) -> list[dict]:
    url = f"{API_BASE}/tags?per_page=100"
    request = urllib.request.Request(url, headers=_headers(token, accept_json=True))
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{url} -> HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{url} -> {exc.reason}") from exc


def fetch_commit_date(sha: str, token: str | None) -> str | None:
    """YYYY-MM-DD for `sha`'s own commit date, or None if the API call
    fails -- the tags endpoint itself carries no date, only a commit sha,
    so this is one extra request per tag."""
    url = f"{API_BASE}/commits/{sha}"
    request = urllib.request.Request(url, headers=_headers(token, accept_json=True))
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read())
    except (urllib.error.HTTPError, urllib.error.URLError):
        return None
    date = data.get("commit", {}).get("committer", {}).get("date")
    return date[:10] if date else None


def parse_arch_data(text: str) -> list[dict]:
    """Parse the MP_NATIVE_ARCH_* enum, keeping only entries that are real
    natmod ARCH= targets (NATMOD_BUILDABLE_ARCHES). arch_code is the
    enum's own 0-based position, not a flag.

    arch_flags is always 0 -- this enum carries no such information
    (rv32imc's real zba/zcmp flags live elsewhere: mpy_ld.py's own
    --arch-flags / persistentcode.c's asm_rv32_allowed_extensions()). The
    key stays in the row for schema consistency and as an explicit "not
    computed here", not simply absent.
    """
    enum_match = re.search(r"enum\s*\{([^}]+MP_NATIVE_ARCH_[^}]+)\}", text)
    if not enum_match:
        return []

    enum_body = enum_match.group(1)
    arch_list = []
    current_val = 0

    for line in enum_body.split("\n"):
        item = re.search(r"MP_NATIVE_ARCH_(\w+)(?:\s*=\s*(0x[0-9a-fA-F]+|\d+))?", line)
        if item:
            arch_name = item.group(1).lower()
            if item.group(2):
                value = item.group(2)
                current_val = int(value, 16) if value.startswith("0x") else int(value)

            if arch_name in NATMOD_BUILDABLE_ARCHES:
                arch_list.append(
                    {"arch": arch_name, "arch_code": current_val, "arch_flags": 0}
                )
            current_val += 1

    return arch_list


def parse_cross_prefixes(text: str) -> dict[str, str]:
    """{arch_name: cross_prefix} from py/dynruntime.mk's own
    `ifeq ($(ARCH),<name>)` / `else ifeq ($(ARCH),<name>)` branches, each
    holding its own `CROSS = ...` line. Purely textual split on the
    branches themselves, independent of persistentcode.h's enum order.

    The value can be genuinely empty -- x86/x64 build with the host's own
    gcc, no prefix (`CROSS =`, confirmed live against v1.20.0) -- so the
    match is anchored to one line (`[ \\t]`, not `\\s`, around `=`) rather
    than `\\s*(\\S+)`, which would silently skip the blank line and slurp
    the next line's first token (`CFLAGS` from the following line) as the
    "prefix" instead. An empty match still means "found, and it's empty",
    kept as `""`, not the same as absent (a tag with no dynruntime.mk at
    all, or no branch for that arch) which stays out of the map entirely.
    """
    cross_map: dict[str, str] = {}
    parts = re.split(r"(?:else\s+)?ifeq\s*\(\$\(ARCH\),\s*(\w+)\)", text)
    for name, body in zip(parts[1::2], parts[2::2]):
        match = re.search(r"^CROSS[ \t]*=[ \t]*(\S*)[ \t]*$", body, re.MULTILINE)
        if match:
            cross_map[name] = match.group(1)
    return cross_map


def fetch_rv32_extensions(ref: str, token: str | None) -> dict[str, int] | None:
    """{extension_name: bit_value} from tools/mpy_ld.py's own
    RV32_EXTENSIONS dict, or None if this tag's mpy_ld.py doesn't have one
    yet -- confirmed live: absent at v1.27.0, present (zba=1, zcmp=2) from
    v1.28.0 onward, even though rv32imc itself is natmod-buildable from
    v1.24.0 -- --arch-flags support arrived four tags after the arch
    itself did, a real gap, not a scan miss.

    This is the vocabulary of what --arch-flags values are even
    expressible at this tag, not a build's own choice of which to use --
    cibuildmp requests none by default, so this is what lets
    identifiers() enumerate the real, distinct natmod targets a value
    like `zba` or `zba,zcmp` actually produces, matching
    tools/mpy_ld.py's own validate_arch_flags() bitwise-OR parsing.
    """
    text = fetch_raw("tools/mpy_ld.py", ref, token)
    if text is None:
        return None
    match = re.search(r"RV32_EXTENSIONS\s*=\s*\{([^}]*)\}", text)
    if not match:
        return None
    extensions: dict[str, int] = {}
    for name, shift in re.findall(r'"(\w+)"\s*:\s*1\s*<<\s*(\d+)', match.group(1)):
        extensions[name] = 1 << int(shift)
    return extensions or None


def get_mpy_info(ref: str, token: str | None) -> dict | None:
    text = fetch_raw("py/persistentcode.h", ref, token)
    if text is None:
        text = fetch_raw("py/mpconfig.h", ref, token)
    if text is None:
        return None

    major = re.search(r"#define\s+MPY_VERSION\s+(\d+)", text)
    minor = re.search(r"#define\s+MPY_SUB_VERSION\s+(\d+)", text)
    if not major:
        return None

    mpy_ver = f"{major.group(1)}.{minor.group(1)}" if minor else major.group(1)
    arch_data = parse_arch_data(text)

    # None wherever this tag has no py/dynruntime.mk, or no branch for a
    # given arch in it -- never guessed from another tag's prefix.
    dynruntime_text = fetch_raw("py/dynruntime.mk", ref, token)
    cross_map = parse_cross_prefixes(dynruntime_text) if dynruntime_text else {}
    for item in arch_data:
        item["cross"] = cross_map.get(item["arch"])

    return {"mpy": mpy_ver, "archs": arch_data}


def identifiers(token: str | None):
    """Yields (tag_info, row) pairs -- tag_info carries the tag's own sha
    (for the caller to resolve a date from and place in [tags], shared
    across every section rather than repeated per row: sha/date are pure
    per-tag facts, never varying by arch within one tag). Each row itself
    no longer carries sha -- [natmod]'s own rows read it back from [tags]
    by tag name instead of repeating it.

    One row per (tag, arch), identifier unaffected by arch_flags --
    arch_flags is a real compatibility fact (which --arch-flags bits a
    .mpy built for this row's arch would carry, checked as a bitmask
    subset at load time, see py/persistentcode.c), not a naming axis:
    identifying which extensions are even expressible at a given tag is
    main()'s own `[natmod.rv32imc-extensions]` table's job
    (fetch_rv32_extensions()), kept separate from this per-arch row.
    """
    for tag_info in fetch_tags(token):
        tag_name = tag_info["name"]
        sha = tag_info["commit"]["sha"]

        info = get_mpy_info(sha, token)
        if not info:
            continue

        for item in info["archs"]:
            identifier = f"mpy{info['mpy']}-{tag_name}-{item['arch']}"
            yield (
                tag_info,
                {
                    "tag": tag_name,
                    "mpy": info["mpy"],
                    "arch": item["arch"],
                    "arch_code": item["arch_code"],
                    "arch_flags": item["arch_flags"],
                    "cross": item["cross"],
                    "identifier": identifier,
                },
            )


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


def _toml_str(value: str) -> str:
    """A TOML basic string, escaped by hand -- stdlib has no TOML writer
    (tomllib only reads), and this project deliberately stays off
    third-party dependencies for anything that isn't the native-.mpy link
    step itself (pyproject.toml's own dependencies comment)."""
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
    raise TypeError(f"unsupported TOML value type: {type(value)!r}")


def _inline_row(row: dict) -> str:
    # None means "not extracted for this row" -- the key is left out
    # entirely, never written as a fabricated null (TOML has none).
    parts = [
        f"{key} = {_toml_value(value)}"
        for key, value in row.items()
        if value is not None
    ]
    return "{ " + ", ".join(parts) + " }"


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
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
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")

    rows = []
    tags: dict[str, dict[str, str]] = {}
    for tag_info, row in identifiers(token):
        tag_name = tag_info["name"]
        if tag_name not in tags:
            sha = tag_info["commit"]["sha"]
            date = fetch_commit_date(sha, token)
            entry = {"sha": sha}
            if date is not None:
                entry["date"] = date
            tags[tag_name] = entry
        rows.append(row)

    print("[tags]")
    for tag_name, entry in tags.items():
        print(f'"{tag_name}" = {_inline_row(entry)}')
    print()
    if not args.no_merge:
        rows = carry_forward(rows, ("natmod",), args.merge_from)
    print("[natmod]")
    print("identifiers = [")
    for row in rows:
        print("    " + _inline_row(row) + ",")
    print("]")

    # Real --arch-flags vocabulary per tag (name -> bit value), fetched
    # only for tags that actually have an rv32imc row -- every other
    # arch's arch_flags stays structurally 0, nothing to look up for it.
    # A separate table, not folded into `identifiers` above: this is a
    # per-tag fact about which flags are *expressible* at all (which
    # cibuildmp does not itself request by default), not a naming axis
    # for the rows themselves -- see identifiers()'s own docstring.
    rv32imc_tags = list(
        dict.fromkeys(row["tag"] for row in rows if row["arch"] == "rv32imc")
    )
    if rv32imc_tags:
        print()
        print("[natmod.rv32imc-extensions]")
        for tag_name in rv32imc_tags:
            sha = tags[tag_name]["sha"]
            extensions = fetch_rv32_extensions(sha, token)
            if not extensions:
                continue
            entries = ", ".join(
                _inline_row({"name": name, "arch_flags": flags})
                for name, flags in extensions.items()
            )
            print(f'"{tag_name}" = [{entries}]')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

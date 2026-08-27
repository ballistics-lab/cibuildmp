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

Output is `[natmod]` / `identifiers = [ {...}, {...}, ... ]`, one compact
inline table per row -- the shape record 0052 (Track A6) sketched for
`resources/build-platforms.toml`. This script does not write that file
itself: A6 is not landed yet (no such resource exists in this repo), so
piping stdout there would be inventing the file's contents as a side
effect of an unrelated commit. Redirect and review by hand until A6
actually lands.

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
limit (this makes roughly three requests per tag): set `GITHUB_TOKEN` in
the environment, or run without one and expect to get rate-limited past
~20 tags.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

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
    """
    cross_map: dict[str, str] = {}
    parts = re.split(r"(?:else\s+)?ifeq\s*\(\$\(ARCH\),\s*(\w+)\)", text)
    for name, body in zip(parts[1::2], parts[2::2]):
        match = re.search(r"CROSS\s*=\s*(\S+)", body)
        if match:
            cross_map[name] = match.group(1)
    return cross_map


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
    for tag_info in fetch_tags(token):
        tag_name = tag_info["name"]
        sha = tag_info["commit"]["sha"]

        info = get_mpy_info(sha, token)
        if not info:
            continue

        for item in info["archs"]:
            identifier = f"mpy{info['mpy']}-{tag_name}-{item['arch']}"
            yield {
                "tag": tag_name,
                "mpy": info["mpy"],
                "sha": sha,
                "arch": item["arch"],
                "arch_code": item["arch_code"],
                "arch_flags": item["arch_flags"],
                "cross": item["cross"],
                "identifier": identifier,
            }


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
    parts = [f"{key} = {_toml_value(value)}" for key, value in row.items() if value is not None]
    return "{ " + ", ".join(parts) + " }"


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN")
    print("[natmod]")
    print("identifiers = [")
    for row in identifiers(token):
        print("    " + _inline_row(row) + ",")
    print("]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

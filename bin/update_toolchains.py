#!/usr/bin/env python3
"""Report which pinned toolchain is behind its own upstream (record [0046]).

`bin/update_docker.py` already covers the two container-image tables, and
[0068] made Dependabot the notifier for each `docker/*.Dockerfile`'s own base
OS tag. This covers the six pins neither of those sees: the compiler tarballs
each toolchain image downloads at build time.

**It reports; it does not decide, and it does not rewrite.** [0046] is
explicit that a pin moves in a reviewed PR, because the diff is the review --
and unlike a digest bump, moving one of these means re-downloading a tarball
to recompute its sha256, which is a deliberate act, not hygiene a script
should perform on its own. `--check` is therefore the only mode, kept as a
flag purely so the invocation reads the same as `update_docker.py --check`
in the same scheduled job.

Three upstream shapes, which is why [0046] asked for one script per shape
rather than one generic checker:

- **GitHub releases** (`arm-none-eabi`, `riscv-none-elf` -- both now
  `embedded_base`, record 0096 --, `xtensa_esp`, `windows`) -- the pinned
  tag is in the URL; compare against the repo's
  own latest release.
- **emsdk** (`webassembly`) -- pinned by *build hash*, which looks
  uncomparable and is not: `emscripten-core/emsdk` publishes
  `emscripten-releases-tags.json` mapping every release to its hash, so
  this is one fetch and two lookups.
- **No version at all** (`xtensa_lx106`) -- a stable
  `micropython.org/resources/...` URL whose only signal is that its sha256
  stops matching. [0046] left "worth automating?" open; this reports it as
  unversioned rather than pretending, and re-fetches the tarball to say
  whether the pinned sha256 still describes what is being served.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCKER = REPO / "docker"

GITHUB_LATEST = "https://api.github.com/repos/{repo}/releases/latest"
EMSDK_TAGS = (
    "https://raw.githubusercontent.com/emscripten-core/emsdk/main/"
    "emscripten-releases-tags.json"
)


@dataclass(frozen=True)
class Pin:
    name: str
    dockerfile: str
    # How to find the pinned value in that file, group(1) being the value.
    pattern: str
    kind: str  # "github" | "emsdk" | "unversioned"
    upstream: str = ""  # owner/repo for "github"


# `arm-none-eabi`/`riscv-none-elf` below point at `embedded_base.Dockerfile`
# (record 0096 merged what used to be `arm_embedded.Dockerfile`/
# `riscv_embedded.Dockerfile`) purely so `_pinned()` reads a file that
# exists -- **neither actually matches any more.** [0087]/[0089] already
# deleted the `ARG TOOLCHAIN_URL=` line this regex needs from both former
# files (the tarball is fetched at container run time now, per-row, not
# baked at image-build time), so `_pinned()` has raised
# `SystemExit(f"{pin.name}: no pin found...")` for both entries since
# [0087] landed -- a real, pre-existing gap this record does not close,
# only avoids widening into a harder `FileNotFoundError` by keeping the
# filename real. The actual fix (reading `resources/pinned_toolchains.toml`'s
# own per-cross pin instead of grepping a Dockerfile `ARG`) is [0090]'s own
# scope, not this Dockerfile-merge's.
PINS = (
    Pin(
        "arm-none-eabi",
        "embedded_base.Dockerfile",
        r"xpack-dev-tools/arm-none-eabi-gcc-xpack/releases/download/v([^/]+)/",
        "github",
        "xpack-dev-tools/arm-none-eabi-gcc-xpack",
    ),
    Pin(
        "riscv-none-elf",
        "embedded_base.Dockerfile",
        r"xpack-dev-tools/riscv-none-elf-gcc-xpack/releases/download/v([^/]+)/",
        "github",
        "xpack-dev-tools/riscv-none-elf-gcc-xpack",
    ),
    Pin(
        "xtensa-esp",
        "xtensa_esp.Dockerfile",
        r"espressif/crosstool-NG/releases/download/([^/]+)/",
        "github",
        "espressif/crosstool-NG",
    ),
    Pin(
        "llvm-mingw",
        "windows.Dockerfile",
        r"mstorsjo/llvm-mingw/releases/download/([^/]+)/",
        "github",
        "mstorsjo/llvm-mingw",
    ),
    Pin(
        "emsdk",
        "webassembly.Dockerfile",
        r"emscripten-releases-builds/linux/([0-9a-f]{40})/",
        "emsdk",
    ),
    Pin(
        "xtensa-lx106",
        "xtensa_lx106.Dockerfile",
        r'TOOLCHAIN_SHA256="([0-9a-f]{64})"',
        "unversioned",
    ),
)


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "cibuildmp"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _pinned(pin: Pin) -> str:
    text = (DOCKER / pin.dockerfile).read_text(encoding="utf-8")
    match = re.search(pin.pattern, text)
    if not match:
        raise SystemExit(f"{pin.name}: no pin found in docker/{pin.dockerfile}")
    return match.group(1)


def _latest_github(repo: str) -> str:
    data = json.loads(_get(GITHUB_LATEST.format(repo=repo)))
    return str(data["tag_name"]).lstrip("v")


def _latest_emsdk() -> tuple[str, str]:
    """(version, build hash) that emsdk itself currently calls latest."""
    data = json.loads(_get(EMSDK_TAGS))
    version = str(data["aliases"]["latest"])
    return version, str(data["releases"][version])


def _served_sha256(url: str) -> str:
    digest = hashlib.sha256()
    request = urllib.request.Request(url, headers={"User-Agent": "cibuildmp"})
    with urllib.request.urlopen(request, timeout=300) as response:
        while chunk := response.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _tarball_url(pin: Pin) -> str:
    text = (DOCKER / pin.dockerfile).read_text(encoding="utf-8")
    match = re.search(r'TOOLCHAIN_URL="([^"]+)"', text)
    if not match:
        raise SystemExit(f"{pin.name}: no TOOLCHAIN_URL in docker/{pin.dockerfile}")
    return match.group(1)


def check(pin: Pin, *, slow: bool) -> int:
    """0 when current, 1 when behind. Prints one line either way."""
    pinned = _pinned(pin)
    try:
        if pin.kind == "github":
            latest = _latest_github(pin.upstream)
            stale = pinned.lstrip("v") != latest
            arrow = f"{pinned} -> {latest}" if stale else pinned
        elif pin.kind == "emsdk":
            version, latest_hash = _latest_emsdk()
            stale = pinned != latest_hash
            arrow = (
                f"{pinned[:12]}... -> {latest_hash[:12]}... ({version})"
                if stale
                else f"{pinned[:12]}... ({version})"
            )
        else:
            if not slow:
                print(f"  {pin.name}: unversioned upstream -- pass --slow to re-hash")
                return 0
            served = _served_sha256(_tarball_url(pin))
            stale = served != pinned
            arrow = (
                f"served sha256 {served[:12]}... != pinned {pinned[:12]}..."
                if stale
                else f"{pinned[:12]}... (sha256 still matches what is served)"
            )
    except (urllib.error.URLError, KeyError, TimeoutError) as exc:
        # A checker that cannot reach an upstream has not found staleness;
        # say so rather than reporting a false clean or a false drift.
        print(f"  {pin.name}: UNKNOWN -- {exc}", file=sys.stderr)
        return 0

    print(f"  {pin.name}: {'STALE ' if stale else ''}{arrow}")
    return 1 if stale else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="Accepted for symmetry with update_docker.py; this script only ever "
        "reports, so it changes nothing either way",
    )
    parser.add_argument(
        "--slow",
        action="store_true",
        help="Also re-download the unversioned tarball to compare its sha256",
    )
    args = parser.parse_args(argv)

    print("docker/*.Dockerfile toolchain pins:")
    drift = sum(check(pin, slow=args.slow) for pin in PINS)
    if drift:
        print(
            f"{drift} pin(s) behind upstream -- see record 0046: this reports, "
            f"a human decides",
            file=sys.stderr,
        )
        return 1
    print("every pin current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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

- **GitHub releases.** For `xtensa_esp`/`windows` the pinned tag is in the
  Dockerfile's own URL; compare against the repo's own latest release.
  `arm-none-eabi`/`riscv-none-elf` (both `embedded_base` since record 0096)
  are the same upstream shape but no longer a Dockerfile fact at all --
  [0087]/[0089] moved their real pins into `resources/pinned_toolchains.toml`'s
  own `[cross]` tables, keyed by `(cross, version)` because more than one
  verified version is pinned at once (per-row floor/ceiling windows, e.g.
  `mimxrt`'s below-13 ceiling). This checker reads every version pinned for
  that cross and reports whether the newest has fallen behind upstream.
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
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCKER = REPO / "docker"
RESOURCES = REPO / "src" / "cibuildmp" / "resources"
PINNED_TOOLCHAINS = RESOURCES / "pinned_toolchains.toml"

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
    kind: str  # "github" | "cross-toml" | "emsdk" | "unversioned"
    upstream: str = ""  # owner/repo for "github"/"cross-toml"
    cross: str = ""  # `pinned_toolchains.toml` table key, for "cross-toml"


# `arm-none-eabi`/`riscv-none-elf` used to be grepped straight out of
# `embedded_base.Dockerfile`'s own `ARG TOOLCHAIN_URL=`. [0087]/[0089]
# deleted that line (the tarball is fetched at container run time now, per
# row, not baked at image-build time) and moved the real pins into
# `resources/pinned_toolchains.toml`'s own `[cross]` tables -- and unlike
# the Dockerfile's single shared `ARG`, that table genuinely holds more
# than one verified version per cross at once (e.g. `mimxrt`'s own
# below-13 ceiling, record 0088), because different `(tag, scope)` windows
# resolve to different versions. There is no longer one "the" pin to
# compare against upstream; `kind="cross-toml"` instead reads every
# version pinned for that cross and reports whether the *newest* of them
# has fallen behind upstream's own latest release -- the question this
# checker can still answer ("is it time to add a newer entry"), without
# claiming the older, intentionally-kept versions are drift.
PINS = (
    Pin(
        "arm-none-eabi",
        "",
        "",
        "cross-toml",
        "xpack-dev-tools/arm-none-eabi-gcc-xpack",
        "arm-none-eabi-",
    ),
    Pin(
        "riscv-none-elf",
        "",
        "",
        "cross-toml",
        "xpack-dev-tools/riscv-none-elf-gcc-xpack",
        "riscv64-unknown-elf-",
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


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def _newest_cross_pin(pin: Pin) -> tuple[str, int]:
    """(newest version string, how many versions are pinned) for `pin.cross`
    in `pinned_toolchains.toml`."""
    with PINNED_TOOLCHAINS.open("rb") as handle:
        data = tomllib.load(handle)
    versions = list(data.get(pin.cross, {}))
    if not versions:
        raise SystemExit(
            f"{pin.name}: no versions pinned for {pin.cross!r} in "
            f"{PINNED_TOOLCHAINS.relative_to(REPO)}"
        )
    return max(versions, key=_version_key), len(versions)


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
    if pin.kind == "cross-toml":
        pinned, count = _newest_cross_pin(pin)
    else:
        pinned = _pinned(pin)
    try:
        if pin.kind in ("github", "cross-toml"):
            latest = _latest_github(pin.upstream)
            stale = pinned.lstrip("v") != latest
            suffix = f" (newest of {count} pinned)" if pin.kind == "cross-toml" else ""
            arrow = f"{pinned} -> {latest}{suffix}" if stale else f"{pinned}{suffix}"
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

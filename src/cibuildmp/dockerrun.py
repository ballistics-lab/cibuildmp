"""Sibling-container execution for every build -- D26's own design,
Docker-only (D30). All six wired usermod ports and every natmod arch
resolve an image through `image_for()` and run here; the one thing left
on the host is `qemu`'s own `mpy-cross`
(`_HOST_MPY_CROSS_PORTS`, `usermod/orchestrate.py`). This docstring
tracked the ports one at a time while they were being wired and said
`esp32` had no image and `qemu` was an open gap long after [0028] and
[0058] closed both.

The design this exists to prove out: `cibuildmp` itself stays on the bare
host (no Docker-in-Docker) and launches an ordinary sibling `docker run`
for a port's own build command, instead of that command running directly
on the host. Volume mounts land at identical absolute paths inside the
container, so the existing make/deplibs command lists (built for the bare
host) need no path translation at all -- every path they reference already
lives under `mpy_dir` or the caller's own module directory, both passed
here as `mounts`.

**cibuildmp itself never builds a Docker image.** The user's own call,
checked against cibuildwheel's real source before deciding, not assumed:
cibuildwheel's own container runtime (`oci_container.py`) holds nothing
but the resolved image reference itself -- no separate preload/cache step
of its own -- and only ever does a plain `docker pull` of an
already-published, digest-pinned image
(`resources/pinned_docker_images.cfg`) the first time it is actually
used; building one is a rare, out-of-band maintainer task
(`bin/update_docker.py`), never part of a consumer's own build. This
module follows that exactly: the per-target Dockerfiles live at the repo
root (`docker/*.Dockerfile`, not shipped in the installed wheel -- see
pyproject.toml's own comment), published by
`.github/workflows/publish-docker-images.yml` to GHCR, digest-pinned in
`resources/pinned_docker_images.toml`. `ensure_image()` just resolves
which reference to use; `run()`'s own `--pull missing` is what actually
fetches it, lazily -- the same division of labour cibuildwheel's own code
has. Docker's local image store is the only cache involved. Nothing
registered for a target is a clear, immediate error, not a slow last
resort.

Adding a target's Docker support is "write `docker/<tag>.Dockerfile`, let
publish-docker-images.yml publish it, record the digest in
`resources/pinned_docker_images.toml`" -- a maintainer edits *data*, not
something an end user configures via cibuildmp.toml. There is no
config-file knob here and deliberately never will be: these images are
cibuildmp's own build infrastructure (D28).
`CIBMP_<PORT>_<TARGET>_DOCKER_IMAGE` stays purely as a
local-testing/override knob (point it at a `:local` tag you just built,
or swap in a fork's image without touching source), and always wins.

**Record 0043** is what shaped the two things this module resolves;
**record 0058** later corrected which *key* picks an image.

*Which image.* Not the port -- the toolchain a build needs, named at
each port's own table level in `resources/build-platforms.toml`
(`_image_group_for()`). `unix` is keyed by **platform tag** --
`manylinux_2_28_x86_64`, `musllinux_1_2_aarch64`, `manylinux_2_41_mipsel`
-- pypa's own names, which are real PEP 600 / PEP 656 tags rather than
the decorative "manylinux" label record 0031 flagged, and an identity map
onto the group of the same name: this is the one port whose image axis
and build-target axis coincide. `natmod` is keyed by **arch** and `qemu`
by **board** -- both span more than one toolchain (ten `dynruntime.mk`
arches, three ISAs across `qemu`'s boards), so a bare port name would
have meant either wrong-architecture images or one Dockerfile per row.
`windows` (all three arches share one image, D28 step 3), `webassembly`
and `esp32` are keyed by the port name alone: they cross-compile to
Windows, wasm and (via ESP-IDF, installed at build time rather than
baked in) two Xtensa/RISC-V ISAs, but each needs only one image.

*Which platform.* `run()` passes `--platform`, cibuildwheel's own
`OCIContainer` behaviour. For `unix` that platform **is** the build
target, because each image is native to its own architecture. For the
cross-compiling ports it is `linux/amd64`, a statement about the image
rather than about any build target. Before 0043 no `--platform` was
passed at all, so a pinned reference resolved by accident-of-host --
correct on `ubuntu-latest`, and on `ubuntu-24.04-arm` a bare `exec format
error` from inside `make`. Stating it per image is what makes the same
pins work unchanged on an x86_64 host and an arm64 one, with the
non-native side emulated. Host architecture is recorded nowhere:
`host_oci_platform()` is the only place `platform.machine()` is consulted
at all, and only to decide whether a missing binfmt is worth naming
(`_probe_platform()`).
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Self

from .platforms.usermod.build_common import UsermodBuildError
from .resources import build_platforms_data, pinned_docker_images, pinned_pypa_images


# ── where the pins live now ───────────────────────────────────────────
#
# `resources/pinned_docker_images.toml` used to be a dict literal right here: a maintainer-edited
# table of digest-pinned references sitting in the middle of resolver
# logic. It is gone, and its contents now live in
# `resources/pinned_docker_images.toml` -- **record 0010** ("pinned data
# lives in `resources/`, not in Python"), applied to the one table that
# had escaped it, and the same split cibuildwheel itself keeps between
# `oci_container.py` and `resources/pinned_docker_images.cfg`.
# `cibuildmp/resources.py`'s own module docstring already stated the reason
# before this file complied with it: every value in that table goes stale
# on an upstream's schedule, so bumping one should be a reviewable data
# diff, not a patch to code.
#
# What this module keeps is only what is genuinely logic rather than
# data: how a (port, target) pair becomes a key, which env var overrides
# it, and which OCI platform an architecture means. Which *group* a
# (port, target) pair names is not logic either, any more -- record 0058
# moved it into `resources/build-platforms.toml`'s own `image`/`images`
# keys (`_image_group_for()`), so this module only resolves a group name
# to a pinned reference.
#
# ── the two shapes a target has ───────────────────────────────────────
#
# `unix` is keyed by **platform tag** -- `manylinux_2_28_x86_64`,
# `musllinux_1_2_aarch64`, `manylinux_2_41_mipsel` -- pypa's own names, which are
# real PEP 600 / PEP 656 tags rather than the decorative "manylinux"
# label record 0031 flagged (**0043**, which also renamed `x64`/`x86`/
# `armhf` to `x86_64`/`i686`/`armv7l` so the labels stop needing
# translation). The tag is both the identifier suffix (`unix-manylinux_
# 2_28_x86_64`) and, unsplit, its own image group name -- an identity map.
#
# `natmod` (by arch) and `qemu` (by board) also have a real image axis,
# just not one shaped like `unix`'s: several arches/boards share one
# toolchain group rather than each naming its own (record 0058). Every
# other port is keyed by the port name alone -- `windows` (all three
# arches share one image, D28 step 3), `webassembly`, `esp32`. They
# cross-compile to Windows and wasm, or install their toolchain at build
# time (`esp32`), which no Linux container is native to, so they have no
# per-build image axis at all and 0043
# does not touch them.
def _pins() -> dict[str, Any]:
    return pinned_docker_images()


# Target architecture -> the OCI platform Docker must be asked for.
# cibuildwheel's own `ARCHITECTURE_OCI_PLATFORM_MAP` (`platforms/
# linux.py`), which `OCIContainer` passes straight through as
# `--platform=`; kept as code rather than data because it is a fixed
# property of the architecture, not something that goes stale.
#
# For `unix` this is the *build target*: the image is native to it, so
# the container platform and the target arch are the same fact
# (**0043**'s whole model). `mipsel` is the exception -- there is no
# 32-bit mipsel image to be native to, so it stays an amd64 cross host,
# and saying that here is exactly why the exception stays visible instead
# of hiding inside a Dockerfile.
ARCH_OCI_PLATFORM: dict[str, str] = {
    "x86_64": "linux/amd64",
    "i686": "linux/386",
    "aarch64": "linux/arm64",
    "armv7l": "linux/arm/v7",
    "ppc64le": "linux/ppc64le",
    "s390x": "linux/s390x",
    "riscv64": "linux/riscv64",
    "mipsel": "linux/amd64",  # cross host, not a native target -- see 0043
}

# The cross-compiling ports are all amd64 Linux toolchain hosts. Stating
# it is what lets them run on an arm64 host at all (emulated) instead of
# resolving by accident-of-host and failing with `exec format error`.
_PORT_OCI_PLATFORM = "linux/amd64"

# `platform.machine()` -> the OCI platform Docker resolves as native
# here. Used for exactly one thing -- deciding whether a run needs
# emulation, so a missing binfmt can be *named* (`_probe_platform()`)
# instead of surfacing as `exec format error` from inside `make`. It
# never reaches an image name, a pin key or a build identifier: 0043's
# "host architecture never appears anywhere" is what makes the same pins
# work unchanged on an x86_64 and an arm64 host, and this dict is not an
# exception to it.
#
# Docker Desktop on macOS/Windows runs a Linux VM matching the host CPU,
# so `platform.machine()` still names the right container platform there.
# An unmapped value means "assume nothing", not "assume amd64".
_HOST_MACHINE_PLATFORMS: dict[str, str] = {
    "x86_64": "linux/amd64",
    "amd64": "linux/amd64",
    "AMD64": "linux/amd64",
    "aarch64": "linux/arm64",
    "arm64": "linux/arm64",
    "ARM64": "linux/arm64",
    "armv7l": "linux/arm/v7",
    "armv8l": "linux/arm/v7",
    "i386": "linux/386",
    "i686": "linux/386",
    "ppc64le": "linux/ppc64le",
    "s390x": "linux/s390x",
    "riscv64": "linux/riscv64",
}


def host_oci_platform() -> str | None:
    """This host's own native OCI platform, or `None` when
    `platform.machine()` returns something unmapped.

    Deliberately the only place host architecture is consulted at all,
    and it never leaves this module -- see `_HOST_MACHINE_PLATFORMS`.
    """
    return _HOST_MACHINE_PLATFORMS.get(platform.machine())


def unix_targets() -> tuple[str, ...]:
    """Every `unix` platform tag the matrix declares, in table order --
    `("manylinux_2_28_x86_64", "musllinux_1_2_x86_64", ...)`.

    `resources/build-platforms.toml`'s own `[usermod.unix].images` keys
    *are* the matrix (record 0058 moved them there from the pin file):
    which libc floor each architecture is curated onto, the same decision
    cibuildwheel makes in its own `resources/defaults.toml`
    (`manylinux-x86_64-image = "manylinux_2_28"`). "What targets exist"
    and "what has a published image" are two different questions now --
    this answers the first. A target whose `image_for()` comes back empty
    is still a declared cell with nothing published for it yet, and it
    still counts here: `--print-build-identifiers` must list it, and
    asking to build it must fail with "no image registered", not with
    "unknown architecture". Those are different errors, and conflating
    them is how a half-published matrix quietly starts looking like a
    smaller one.

    Pure: the packaged resource and nothing else, no Docker, no network
    -- `targets.py`'s own discipline, which `--print-build-identifiers`
    depends on.
    """
    return tuple(build_platforms_data()["usermod"]["unix"]["images"])


def _image_group_for(port: str, target: str | None) -> str | None:
    """The toolchain-group name (record 0058) `port`'s build at `target`
    resolves to, or `None` when `target` is required and missing.

    Reads `resources/build-platforms.toml`'s own table-level policy, not
    a row: a scalar `image = "..."` for a port with no per-build image
    axis (`windows`, `webassembly`, `esp32`, every `embedded_base`-toolchain
    usermod port), an `images.<...>` map for one that has one (`natmod`
    keyed by `arch`, `qemu` by `board`, `unix` by its own platform tag --
    an identity map, since that port's image axis and build-target axis
    coincide). One rule for every port, no `if port == "unix"` special
    case: which shape a port's row has is what decides whether `target`
    is consulted at all.
    """
    row = (
        build_platforms_data()["natmod"]
        if port == "natmod"
        else build_platforms_data()["usermod"].get(port, {})
    )
    images = row.get("images")
    if images is not None:
        return None if target is None else images.get(target)
    return row.get("image")


def split_tag(tag: str) -> tuple[str, str]:
    """`"manylinux_2_28_x86_64"` -> `("manylinux_2_28", "x86_64")`.

    Split against the known architecture list rather than on a separator:
    both halves contain underscores (`manylinux_2_28`, `x86_64`), so
    there is no character to split on and no positional rule that holds
    for `manylinux_2_41_mipsel` and `musllinux_1_2_ppc64le` at once.
    """
    for arch in ARCH_OCI_PLATFORM:
        suffix = f"_{arch}"
        if tag.endswith(suffix):
            return tag[: -len(suffix)], arch
    raise UsermodBuildError(
        f"{tag!r} does not name a known architecture. Known: "
        f"{', '.join(ARCH_OCI_PLATFORM)}"
    )


def image_for(port: str, target: str | None = None) -> str | None:
    """The image `port`'s build should run in for `target`, or `None` when
    nothing resolves -- an env override first, then
    `resources/build-platforms.toml`'s own group name, then
    `resources/pinned_docker_images.toml`.

    `target` is the platform tag for `unix` (`manylinux_2_28_aarch64`),
    the arch for `natmod` and `windows` (all three `windows` arches share
    one image, since its own row names a scalar group), the board for
    `qemu`, and omitted entirely for a port with no per-build axis at all
    (`webassembly`, `esp32`) -- omit it rather than passing `""`, so the
    key and env name carry no separator that means nothing.

    Pure and side-effect-free: no `docker` invocation, no filesystem
    access beyond the packaged resources, which is what lets
    `tests/test_usermod_dockerrun.py` cover the precedence rules with no
    Docker daemon at all. `run()` is what actually fetches the resolved
    reference, lazily, the first time it is used.

    `CIBMP_<PORT>_<TARGET>_DOCKER_IMAGE` (e.g.
    `CIBMP_UNIX_MANYLINUX_2_28_X86_64_DOCKER_IMAGE=manylinux_2_28_x86_64:local`,
    or `CIBMP_WEBASSEMBLY_DOCKER_IMAGE` with no target segment) always
    wins over the pinned default -- local testing against a freshly-built
    image, or swapping in a fork's image, without touching source or
    resources.
    """
    override = os.environ.get(_env_name(_key_parts(port, target), "DOCKER_IMAGE"))
    if override:
        return override
    group = _image_group_for(port, target)
    if group is None:
        return None
    # `or None`: a declared-but-empty group means "this target exists,
    # nothing published for it yet" and must resolve exactly the way an
    # unregistered one does -- each build_<port>() raises its own "no
    # image registered" error on None. Returning `""` would sail straight
    # into `docker run ... "" make`.
    return _pins()["image_group"].get(group) or None


def base_image_for(target: str) -> str | None:
    """The upstream pypa image `docker/<target>.Dockerfile` should say
    `FROM`, or `None` when this target has no pypa counterpart.

    `resources/pinned_pypa_images.toml`, keyed the same `[<arch>]` /
    `<floor>` way `image_for()` reads the published table -- the two
    files describe the same matrix from either side of the `FROM`.

    Nothing in a *build* calls this: it exists so
    `publish-docker-images.yml` and anyone building an image by hand
    resolve the base from the pinned mirror rather than from a string
    typed into a Dockerfile. `manylinux_2_41_mipsel` is the one `None` -- pypa
    publishes no 32-bit mipsel image, so that Dockerfile names its own
    base (record 0043's own documented exception).
    """
    floor, arch = split_tag(target)
    return pinned_pypa_images().get(arch, {}).get(floor)


def platform_for(port: str, target: str | None = None) -> str | None:
    """The OCI platform this (port, target)'s image is published for, or
    `None` to let Docker resolve by itself.

    For `unix` it comes from the tag's own architecture (`ARCH_OCI_
    PLATFORM`) -- under 0043 the image is native to its build target, so
    the two are one fact and there is nothing separate to record. For
    every other port it is `linux/amd64`, a statement about the image (a
    Linux cross-compile host) rather than about any build target.

    `CIBMP_<PORT>_<TARGET>_DOCKER_PLATFORM` overrides, for the same
    reason `image_for()`'s override exists and *because* it exists:
    point `..._DOCKER_IMAGE` at a locally-built image and the registered
    platform may no longer describe it.
    """
    override = os.environ.get(_env_name(_key_parts(port, target), "DOCKER_PLATFORM"))
    if override:
        return override
    if port == "unix":
        if target is None:
            return None
        return ARCH_OCI_PLATFORM.get(split_tag(target)[1])
    return _PORT_OCI_PLATFORM


def needs_linux32(port: str, target: str | None = None) -> bool:
    """Whether this target is one of the 32-bit ones whose container may
    need a `linux32` personality wrapper -- `i686` and `armv7l`.

    cibuildwheel's own `OCIContainer` behaviour, copied rather than
    reinvented: for those two platforms it runs `uname -m` inside the
    container first and, if the kernel still reports a 64-bit machine
    (which it does whenever a 32-bit image runs on a 64-bit kernel --
    the normal case, emulated or not), wraps commands in `linux32` so
    the build sees the architecture its image is for. 0043's own step 3:
    "copying cibuildwheel's probe-then-wrap rather than assuming when it
    is needed". `run()` does the probing; this only says which targets
    are candidates.
    """
    if port != "unix" or target is None:
        return False
    return split_tag(target)[1] in ("i686", "armv7l")


def _key_parts(port: str, target: str | None) -> list[str]:
    return [port, *([target] if target else [])]


def _env_name(parts: list[str], suffix: str) -> str:
    return "CIBMP_" + "_".join(p.upper() for p in parts) + f"_{suffix}"


def timeout_for(port: str, target: str | None = None) -> float | None:
    """Seconds `run()` should let this (port, target)'s own
    container run before killing it, or `None` for no limit at all --
    the default the user's own call insisted on: a container hanging
    forever should be opt-in protection, not a surprise ceiling nobody
    asked for.

    `CIBMP_<PORT>_<TARGET>_TIMEOUT` (the exact same per-container
    key shape `image_for()` uses for its own env override) wins first,
    then the blanket `CIBMP_TIMEOUT` applies to every container that has
    no more specific value of its own, then `None`. Found for real, the
    reason this exists at all: a container from an earlier, unrelated
    manual test outlived the process that started it (a killed/timed-out
    shell does not reliably kill a `docker run` several process hops
    down -- bash -> uv -> python -> docker CLI -> dockerd's own container
    process -- since a shell-level kill only reaches the immediate
    child), and burned CPU at 100% for over an hour before anyone
    noticed. `run()`'s own on-timeout handling does a real `docker kill`,
    not just letting `subprocess.run`'s own timeout kill the `docker run`
    CLI and leave the container itself running -- confirmed that gap
    specifically, not assumed away, since it is the exact failure mode
    this feature exists to close.
    """
    parts = _key_parts(port, target)
    specific = os.environ.get(_env_name(parts, "TIMEOUT"))
    if specific:
        return float(specific)
    blanket = os.environ.get("CIBMP_TIMEOUT")
    if blanket:
        return float(blanket)
    return None


def ensure_image(port: str, target: str | None = None) -> str | None:
    """The image this (port, target)'s own build command should run in.

    A thin alias for `image_for()` -- kept as its own name only because
    every real call site already reads `dockerrun.ensure_image(...)`,
    not because there is anything left to "ensure" here. Checked against
    cibuildwheel's own source directly: its container runtime
    (`oci_container.py`) holds nothing but the resolved reference string
    itself, no separate preload/cache-warming step -- `docker run
    --pull=...` is what actually fetches an image, lazily, the first
    time it is used. `run()` below does the equivalent (`--pull
    missing`), so there is nothing for this function to do beyond
    resolving which reference that command should use.
    """
    return image_for(port, target)


# (image, oci_platform) -> the `uname -m` that pair reports, for pairs
# `_probe_platform()` has already cleared this process. A build can be two
# containers against the same image (`manylinux_2_41_mipsel`'s `deplibs` pre-step,
# then the main build) and the 32-bit check asks the same question again,
# so the answer is cached rather than re-run. `""` means "the probe could
# not attribute its own failure and `run()` was left to report it".
_PROBED: dict[tuple[str, str], str] = {}


def _probe_platform(image: str, oci_platform: str) -> str:
    """Fail early, and by name, when `image` cannot actually be run at
    `oci_platform` on this host.

    0043's own open question, and the one place this design deliberately
    goes *beyond* parity: cibuildwheel pushes emulation setup onto the
    user (`docker/setup-qemu-action` on CI, a working binfmt locally) and
    does not probe for it at all. Doing the same here would mean a
    non-native target surfaces as a bare `exec format error` raised from
    somewhere inside `make`, several process hops down -- a message that
    names nothing about architecture, emulation, or which of the two
    platforms involved was the problem. That is precisely the failure
    0043 was written to stop happening, so it is worth one throwaway
    container to turn it into a sentence.

    Only runs when `oci_platform` differs from this host's own native one
    -- a native run has nothing to emulate and pays nothing for this. The
    probe is `uname -m`, the same trivial command cibuildwheel's own
    `OCIContainer` already runs inside a freshly-started container for
    its 32-bit `linux32` detection, cached per (image, platform) so a
    port whose build is two containers (unix/armhf's own `deplibs`
    pre-step plus the main build) probes once, not twice.

    Anything the probe cannot attribute to emulation or to a
    platform/image mismatch is left alone entirely -- a missing image, a
    dead daemon, a registry auth failure all have their own perfectly
    clear errors already, and `run()` below is about to surface them
    itself. This function only ever converts the two failures that
    otherwise arrive unreadable.

    **It reports what it measured, on both sides of the call.** Two lines
    per (image, platform), which is at most two per build: one before, so
    the silent `--pull` inside a `capture_output=True` subprocess is not
    an unexplained pause, and one after carrying the `uname -m` value
    itself. Both are additions made once record 0044's addendum showed
    that a probe whose whole purpose is legibility had been quietly
    costing it elsewhere -- the pull looked like a hang, and the machine
    string, the sole input to `_kernel_is_64bit()`, never reached a log at
    all. They are only useful because `cli.main()` sets line buffering;
    see the comment there.
    """
    if (image, oci_platform) in _PROBED:
        return _PROBED[(image, oci_platform)]
    # Announced before it runs, because this is the one place a build
    # legitimately stops for a long time with nothing to show: `--pull
    # missing` here is `capture_output=True`, so the *first* fetch of any
    # non-native image happens inside this call and is completely silent.
    # Measured on run 32958683512's `armv7l` leg: nineteen seconds between
    # `LINK build/mpy-cross` and the target build starting, with no line in
    # the log mentioning a pull, a digest or even the registry -- the image
    # was fetched here, and `run()`'s own `--pull missing` then found it
    # cached and printed nothing. A silent pull is indistinguishable from a
    # hang, and the probe added to make one failure legible should not
    # create another.
    print(f"  {oci_platform}: probing (pulls {image} if not cached)")
    probe = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--pull",
            "missing",
            f"--platform={oci_platform}",
            image,
            "uname",
            "-m",
        ],
        # A failing probe is the whole point of running it -- the two
        # failures worth naming are read out of `stderr` below, and
        # anything else is deliberately left for the real `run()` to
        # report unmangled.
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode == 0:
        machine = (probe.stdout or "").strip()
        _PROBED[(image, oci_platform)] = machine
        # The probed value itself, not just "the probe passed". It is the
        # sole input to `_kernel_is_64bit()`, and therefore decides whether
        # a 32-bit target's command gets the `linux32` wrap -- so keeping
        # it captured meant the `linux32` branch could not be told apart
        # from its opposite even after a successful build. Record 0044's
        # addendum hit exactly that: `i686` and `armv7l` both went green on
        # CI while "no `linux32` build has run" stayed just as unverified
        # as before, because an `arm/v7` container on an arm64 kernel
        # reports `armv8l` (no wrap) or `aarch64` (wrap) and the logs could
        # not say which. One word of output settles it per run.
        kernel = "64-bit kernel" if machine in _64BIT_MACHINES else "32-bit kernel"
        print(f"  {oci_platform}: uname -m = {machine} ({kernel})")
        return machine
    stderr = probe.stderr or ""
    if "exec format error" in stderr:
        raise UsermodBuildError(
            f"{image} cannot run as {oci_platform} on this host "
            f"({platform.machine()}): the kernel has no binfmt handler "
            f"registered for that architecture. Non-native targets are "
            f"emulated, and cibuildmp does not install emulation itself "
            f"-- add `docker/setup-qemu-action` to the job on CI, or "
            f"register binfmt locally (e.g. `docker run --privileged "
            f"--rm tonistiigi/binfmt --install all`)."
        )
    if "does not match the specified platform" in stderr or (
        "no matching manifest" in stderr
    ):
        raise UsermodBuildError(
            f"{image} is not published for {oci_platform} -- the pinned "
            f"reference resolves to a different platform. Each image is "
            f"published for exactly one platform (see dockerrun's own "
            f"ARCH_OCI_PLATFORM and record 0043); either the pin or that "
            f"table is stale, or a CIBMP_*_DOCKER_IMAGE override is "
            f"pointing at an image built for another architecture."
        )
    # Not an emulation or platform problem -- let `run()`'s own real
    # invocation report whatever this actually is, unmangled.
    _PROBED[(image, oci_platform)] = ""
    return ""


# `uname -m` values that mean "this kernel is 64-bit", which is the only
# thing the `linux32` decision turns on. Listed rather than inferred: a
# 32-bit container on a 64-bit kernel reports the *kernel's* machine, so
# these are exactly the strings a correctly-selected `i686`/`armv7l`
# image can still report.
_64BIT_MACHINES = frozenset(
    {"x86_64", "amd64", "aarch64", "arm64", "ppc64le", "s390x", "riscv64"}
)


def _kernel_is_64bit(image: str, oci_platform: str) -> bool:
    return _probe_platform(image, oci_platform) in _64BIT_MACHINES


def run(
    command: list[str],
    *,
    mounts: list[Path],
    workdir: Path,
    image: str,
    timeout: float | None = None,
    oci_platform: str | None = None,
    linux32: bool = False,
    env: dict[str, str] | None = None,
    capture_output: bool = False,
) -> str | None:
    """Run `command` inside `image`, as a sibling container -- not nested
    inside one `cibuildmp` itself is already running in (D26's own "why
    sibling containers, not Docker-in-Docker" reasoning).

    `capture_output` (default `False`, matching every existing caller's
    own fire-and-forget use): when `True`, returns the container's own
    stdout as text instead of letting it stream straight to this
    process's own -- `build_common.probe_supported_cflags()`'s own
    caller, which needs the *answer* back on the host, not just the exit
    code `check=True` already turns into `UsermodBuildError`.

    Each of `mounts` is bind-mounted at its own identical host path, so
    `command` (already built for a bare-host invocation) needs no
    rewriting: every path it references already lives under one of them.

    `--pull missing` -- correct here specifically because `image` is
    always a digest-pinned reference (`resources/pinned_docker_images.toml`'s own comment, or a
    caller's own override): an already-cached `image` (Docker's own
    local store, the only cache involved -- `ensure_image()` above does
    not pre-fetch anything itself, see its own docstring) runs
    immediately with no network access at all, and one not seen before
    pulls exactly once, with no risk of ever running a stale build
    against a name that used to mean something else.

    `timeout` (seconds, `None` for no limit -- see `timeout_for()`'s own
    docstring for why unlimited is the default): a bare
    `subprocess.run(..., timeout=...)` is not enough on its own. Its
    `TimeoutExpired` only kills the `docker run` CLI process this
    function spawned -- the *container* itself keeps running under
    `dockerd`, several process hops away, with `--rm` never getting the
    chance to clean it up because the container's own main process never
    exits. Found for real: a container from an earlier, unrelated manual
    test outlived a killed/timed-out shell exactly this way and burned
    CPU at 100% for over an hour before anyone noticed. `--name` gives
    this run's own container a reference this function can `docker kill`
    by, explicitly, the moment the timeout fires -- that kill is what
    actually stops it (and, via `--rm`, removes it); `subprocess.run`'s
    own `TimeoutExpired` is only the signal to go do that.

    `oci_platform` (`platform_for()`'s own resolved value, `None` to let
    Docker resolve by itself) becomes `--platform=<value>`, exactly what
    cibuildwheel's own `OCIContainer` passes alongside its `--pull=` --
    **0043**. Passing it explicitly, rather than letting the daemon pick
    whatever matches the host, is what makes a pinned image mean the same
    thing on an x86_64 and an arm64 host: the platform comes from the
    image's own registration, never from where the build happens to be
    running. For `unix` that platform *is* the build target (a native
    toolchain in a native container); for the cross-compiling ports it is
    just "this image is an amd64 Linux host", which on an arm64 machine
    now runs emulated instead of failing. `_probe_platform()` above is
    what turns a missing emulation into a sentence rather than an `exec
    format error` from inside `make`.

    `linux32` (`dockerrun.needs_linux32()`'s own answer -- `i686` and
    `armv7l`) asks for cibuildwheel's own 32-bit handling, copied from
    `OCIContainer` rather than reinvented: probe `uname -m` inside the
    container first, and only if the kernel still reports a 64-bit
    machine wrap the command in `linux32`. The probe matters -- a 32-bit
    image on a 64-bit kernel is the normal case, emulated or not, and the
    kernel reports its own word size regardless of the image, so
    `configure`-style logic and MicroPython's own `uname`-derived
    defaults would otherwise build for the wrong word size inside a
    correctly-selected 32-bit container. Wrapping unconditionally would
    be wrong on a genuinely 32-bit kernel, where `linux32` may not exist
    at all, which is exactly why upstream probes instead of assuming.

    `env` becomes `-e KEY=VALUE` per entry. natmod's own `PYTHONPATH`
    (mounting cibuildmp's own installed `elftools`/`ar` into the
    container rather than baking them into every toolchain image --
    `natmod/build.py`'s `_deps_mount()`) is the first caller, but nothing
    here is natmod-specific.
    """
    if oci_platform is not None and oci_platform != host_oci_platform():
        _probe_platform(image, oci_platform)
    if linux32 and oci_platform is not None and _kernel_is_64bit(image, oci_platform):
        command = ["linux32", *command]

    container_name = f"cibuildmp-{uuid.uuid4().hex[:12]}"
    docker_command = [
        "docker",
        "run",
        "--rm",
        "--pull",
        "missing",
        "--name",
        container_name,
    ]
    if oci_platform is not None:
        docker_command += [f"--platform={oci_platform}"]
    # Without this, every image here (all Ubuntu-based, no USER directive)
    # runs as root, and every file the build writes under a bind-mounted
    # path -- mpy_dir's own ports/<port>/build-<identifier>/ included --
    # comes out root-owned on the host. Found for real: a plain, non-root
    # `rm -rf` on a leftover build-<identifier>/ from an earlier run failed
    # with "Permission denied" on every file inside, which is exactly what
    # blocks cleaning stale build state the same way natmod's own
    # examples/template/natmod/Makefile now does (see that Makefile's own
    # `dist` comment) -- host-owned output is the precondition for that
    # fix, not an unrelated nicety. `os.getuid`/`getgid` do not exist on
    # native Windows Python; Docker itself is Linux-container-only for
    # every port here regardless of host OS (D30), so this only needs to
    # be skipped, not ported, where they are absent.
    if hasattr(os, "getuid"):
        docker_command += ["--user", f"{os.getuid()}:{os.getgid()}"]
    for mount in mounts:
        docker_command += ["-v", f"{mount.as_posix()}:{mount.as_posix()}"]
    for key, value in (env or {}).items():
        docker_command += ["-e", f"{key}={value}"]
    docker_command += ["-w", workdir.as_posix(), image, *command]
    try:
        result = subprocess.run(
            docker_command,
            check=True,
            timeout=timeout,
            capture_output=capture_output,
            text=capture_output,
        )
        return result.stdout if capture_output else None
    except subprocess.TimeoutExpired as exc:
        # See this function's own docstring for why a plain kill of the
        # `docker run` CLI (subprocess's own default TimeoutExpired
        # behaviour) is not enough -- this is the real stop.
        subprocess.run(["docker", "kill", container_name], check=False)
        raise UsermodBuildError(
            f"docker run --rm ... {image} `{' '.join(command)}` timed out "
            f"after {timeout}s and was killed"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise UsermodBuildError(
            f"docker run --rm ... {image} `{' '.join(command)}` failed "
            f"with exit code {exc.returncode}"
        ) from exc
    except FileNotFoundError as exc:
        raise UsermodBuildError(
            f"docker run against image {image!r} was requested but the "
            "docker CLI itself is not on PATH"
        ) from exc


# ── The container session (record 0095, addendum 2) ──────────────────────
#
# `run()` above is one `docker run --rm` per command: the container is born
# and dies around a single `make`, so anything it produced has to already be
# on a host bind mount by the time it exits. That is the whole reason build
# state used to live inside `mpy_dir` -- not a design choice, a consequence
# of the container lifetime.
#
# `Container` below inverts it. The container outlives the commands, so the
# build tree can live *inside* it and the finished artifact is fetched with
# `docker cp` before it is torn down. That is cibuildwheel's own shape
# (`OCIContainer`: `create` -> `exec`/`copy_out` -> `rm --force`,
# `oci_container.py:320-360,478`), arrived at here for the same reason.
#
# Two deliberate differences from upstream, both narrower rather than
# cleverer:
#
# * **Commands go through `docker exec`, not a bash kept open on stdin.**
#   Upstream writes each command into one attached `/bin/bash` and finds the
#   end of the output by a UUID sentinel it prints after `$?`
#   (`oci_container.py:499-575`). That earns its complexity there -- a
#   cibuildwheel build issues many small commands per Python version -- and
#   costs a real exit code, separated stderr, and a working `timeout=`.
#   cibuildmp issues a handful of commands per build, so `docker exec` is
#   both simpler and strictly better-behaved here.
# * **The keep-alive is `sh -c 'while :; do sleep 3600; done'`, not an
#   attached bash.** No supervising `Popen` to leak, and it works on every
#   image this project uses -- `sleep infinity` deliberately avoided, since
#   busybox's own `sleep` (the musllinux/Alpine images) does not take it.

# `mount -t overlay` inside a container needs more than the default
# `docker run` sandbox allows, and exactly how much more was measured
# rather than guessed -- `.github/workflows/probe-overlay.yml`, run
# 33866525827, five privilege levels on both `ubuntu-latest` and
# `ubuntu-24.04-arm`:
#
#   bare `docker run`            mount: /mp: permission denied
#   + --cap-add SYS_ADMIN        mount: /mp: cannot mount overlay read-only
#   + apparmor=unconfined        ok, on both runners
#   + seccomp=unconfined         ok (unnecessary)
#   --privileged                 ok (unnecessary)
#
# So this is the minimum, not a conservative over-grant: `seccomp` stays at
# Docker's own default profile and the container is never `--privileged`.
OVERLAY_CREATE_ARGS = (
    "--cap-add",
    "SYS_ADMIN",
    "--security-opt",
    "apparmor=unconfined",
)

# Where a `Container` puts an overlay's own `upperdir`/`workdir`. An
# anonymous volume, declared at create time, for one reason that is not
# about tidiness: `upperdir` may not sit on an overlayfs, and the
# container's own root filesystem *is* one -- the mount fails outright
# otherwise. A volume also keeps the write path on real disk rather than in
# the page cache of a tmpfs, which matters when the upper layer holds a
# whole port's object tree (measured: 72 MB for `unix`, 101 MB for `rp2`).
OVERLAY_SCRATCH = "/cibuildmp-overlay"


class Container:
    """A container that outlives the commands run in it.

    Used as a context manager::

        with Container(image=..., oci_platform=...) as c:
            c.overlay(host_checkout, at=PurePosixPath("/mp"))
            c.call(["make", "-C", "/mp/ports/unix"], workdir=...)
            c.copy_out(PurePosixPath("/mp/ports/unix/build/micropython"), dest)

    `mounts` are bind-mounted at their own identical host paths, the same
    convention `run()` already uses, so a path built for the host resolves
    unchanged inside. Under the overlay model most callers need none: the
    checkout arrives through `overlay()` and the artifact leaves through
    `copy_out()`.

    **No `--user`.** `run()` passes one, and has to: everything it produced
    landed on a host bind mount, and root-owned build output there could not
    be cleaned by an ordinary `rm -rf` (found for real, see that function's
    own comment). Here nothing is written to the host at all -- `docker cp`
    creates its output owned by whoever invoked it -- and the overlay mount
    needs `CAP_SYS_ADMIN`, which a non-root user does not keep. The reason
    for the flag and the flag itself disappear together.
    """

    def __init__(
        self,
        *,
        image: str,
        oci_platform: str | None = None,
        mounts: list[Path] | None = None,
        ro_mounts: list[Path] | None = None,
        env: dict[str, str] | None = None,
        overlay: bool = True,
        linux32: bool = False,
    ) -> None:
        self.image = image
        self.oci_platform = oci_platform
        self.linux32 = linux32
        self._linux32_prefix: list[str] = []
        self.mounts = list(mounts or [])
        # Separate from `mounts` rather than a `(path, mode)` tuple list:
        # every read-only mount here is a *lowerdir* for `overlay()`, which
        # is the only reason this class mounts anything read-only at all.
        # Docker enforces it at the bind, so nothing inside the container
        # can write through to the host even if a build tries.
        self.ro_mounts = list(ro_mounts or [])
        self.env = dict(env or {})
        self.overlay_enabled = overlay
        self.name = f"cibuildmp-{uuid.uuid4().hex[:12]}"
        self._started = False
        self._lowers = 0

    def __enter__(self) -> Self:
        if self.oci_platform is not None and self.oci_platform != host_oci_platform():
            _probe_platform(self.image, self.oci_platform)
        command = ["docker", "create", "--name", self.name, "--pull", "missing"]
        if self.oci_platform is not None:
            command += [f"--platform={self.oci_platform}"]
        if self.overlay_enabled:
            command += [*OVERLAY_CREATE_ARGS, "-v", OVERLAY_SCRATCH]
        for mount in self.mounts:
            command += ["-v", f"{mount.as_posix()}:{mount.as_posix()}"]
        # Read-only binds are *not* at their own host path, unlike every
        # other mount here: `overlay()` puts the writable view there, and a
        # lowerdir shadowed by the overlay mounted on top of it is not a
        # lowerdir at all.
        for index, mount in enumerate(self.ro_mounts, start=1):
            command += ["-v", f"{mount.as_posix()}:{_lower_path(index)}:ro"]
        for key, value in self.env.items():
            command += ["-e", f"{key}={value}"]
        # See this module's own section comment for why the keep-alive is a
        # `sleep` loop rather than `sleep infinity` or an attached bash.
        command += [self.image, "sh", "-c", "while :; do sleep 3600; done"]
        # `quiet` purely to swallow the container id/name both commands
        # echo -- neither is useful to a caller watching a build, and
        # `run()`'s own output has never carried it. Not `capture_output`,
        # which would mean claiming to want the output back.
        self._docker(command, what="create", quiet=True)
        self._docker(["docker", "start", self.name], what="start", quiet=True)
        self._started = True
        # `linux32`, resolved once for the container rather than per command
        # -- `run()` does the same probe per invocation, which is the only
        # difference a long-lived container makes here.
        #
        # **Not optional, and not cosmetic.** Live CI failure on an
        # `ubuntu-24.04-arm` runner building `manylinux_2_31_armv7l`: with
        # no `linux32`, `uname -m` inside a correctly-selected 32-bit
        # container still reports the *kernel's* `aarch64`, libffi's own
        # `configure` picks the wrong machine-dependent sources, and the
        # port links against a `libffi.a` with no `ffi_call` in it at all
        # (`undefined reference to 'ffi_call'`, `ffi_prep_cif_machdep`, …).
        # Omitting it here is what that failure was -- the first version of
        # this class simply did not carry the flag `run()` already had.
        if (
            self.linux32
            and self.oci_platform is not None
            and _kernel_is_64bit(self.image, self.oci_platform)
        ):
            self._linux32_prefix = ["linux32"]
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        # `--force`, and never `check=True`: teardown runs on the failure
        # path too, and a container that already died (a timeout kill, an
        # OOM) must not turn into a second, misleading exception on top of
        # the real one.
        subprocess.run(
            ["docker", "rm", "--force", "--volumes", self.name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._started = False

    def overlay(self, lower: Path) -> None:
        """Present host directory `lower` **at its own host path**, writable,
        without the container being able to change it.

        `lower` is bind-mounted read-only somewhere out of the way and an
        overlayfs is then mounted over its real path, so every write the
        build makes -- a `BUILD=` tree, libffi's own in-tree `autogen.sh`
        output, `mpy-cross/build/`, rp2's CMake directory -- lands in the
        container's upper layer and dies with the container. The host copy
        is shared by every container that mounts it and is never
        duplicated: this is what lets one cached checkout serve a whole run.

        **The mount point is `lower` itself, not a tidy `/mp`.** That keeps
        the convention `run()` already established and this module's own
        header states -- everything is visible inside at its own identical
        host path -- so a `make` command line built from host paths needs no
        rewriting to run in here. The alternative, mounting at a fixed
        container path, would mean every driver translating `mpy_dir`,
        `BUILD=`, `USER_C_MODULES`, `FROZEN_MANIFEST` and
        `MICROPY_MPYCROSS` on the way in, and a single missed one would
        produce a build that works by reading the wrong tree.

        Called after `__enter__`, because the mount is itself a command run
        inside the container -- `docker create` has no equivalent, and
        `--mount type=bind` cannot express "writable view of a read-only
        tree" at all.
        """
        if not self.overlay_enabled:
            msg = "overlay() on a Container created with overlay=False"
            raise UsermodBuildError(msg)
        # A distinct upper/work pair per call, so a caller may overlay more
        # than one tree into one container without them colliding.
        if lower not in self.ro_mounts:
            msg = (
                f"overlay() needs {lower} declared as a read-only bind at "
                "create time; use overlay_container() rather than "
                "constructing Container directly"
            )
            raise UsermodBuildError(msg)
        index = self.ro_mounts.index(lower) + 1
        lower_at = _lower_path(index)
        upper = f"{OVERLAY_SCRATCH}/up-{index}"
        work = f"{OVERLAY_SCRATCH}/work-{index}"
        self.call(
            [
                "sh",
                "-c",
                (
                    f"mkdir -p {upper} {work} {lower.as_posix()} && "
                    f"mount -t overlay overlay "
                    f"-o lowerdir={lower_at},upperdir={upper},"
                    f"workdir={work} {lower.as_posix()}"
                ),
            ],
            workdir=PurePosixPath("/"),
            as_root=True,
        )

    def call(
        self,
        command: list[str],
        *,
        workdir: PurePosixPath | Path,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
        capture_output: bool = False,
        as_root: bool = False,
    ) -> str | None:
        """Run one command inside the container and wait for it.

        `docker exec` rather than a shell kept open on stdin, so the exit
        code, the timeout and stderr are all the real ones -- see this
        module's own section comment.

        **Runs as the invoking host user unless `as_root`.** The container
        is *created* as root because `mount -t overlay` needs
        `CAP_SYS_ADMIN`, which a non-root user does not keep -- but that is
        needed for exactly one command, `overlay()`'s own mount, and
        `docker exec --user` lets everything after it drop back down.

        That matters as soon as anything the build produces is written to a
        read-write mount: a root-built artifact lands root-owned on the
        host, and the user who ran `cibuildmp` cannot delete their own
        `mpyhouse/` without `sudo`. `run()` solved the same problem with a
        container-wide `--user`, which is not available here. Verified
        live, not assumed: mount as root, `make` under `--user
        <uid>:<gid>` into the same overlay, copy the result into a
        read-write mount -- the file arrives on the host owned by the
        invoking user, mode 755, with no `chown` step anywhere.
        """
        if not self._started:
            msg = "Container.call() outside the `with` block"
            raise UsermodBuildError(msg)
        exec_command = ["docker", "exec", "--workdir", str(workdir)]
        if not as_root and _host_user() is not None:
            exec_command += ["--user", str(_host_user())]
        for key, value in (env or {}).items():
            exec_command += ["-e", f"{key}={value}"]
        exec_command += [self.name, *self._linux32_prefix, *command]
        return self._docker(
            exec_command,
            what=" ".join(command),
            timeout=timeout,
            capture_output=capture_output,
        )

    def copy_out(self, source: PurePosixPath, dest: Path) -> None:
        """Copy `source` (a file or a directory) out of the container to host
        path `dest`.

        The only way anything leaves a container under this model, and the
        reason the container has to outlive the build at all: a
        `docker run --rm` has already destroyed its filesystem by the time
        the host regains control.

        **`docker exec ... tar`, not `docker cp`** -- found the hard way, on
        the first real build driven through this class. `docker cp` is
        served by the daemon reading the container's filesystem through its
        own graph driver, and a mount the *container itself* made is not
        part of that view: copying the freshly built binary out of an
        overlay failed with

            Error response from daemon: Could not find the file
            /mp/ports/unix/build-standard/micropython in container ...

        while `docker cp` of an ordinary container path in the same
        container worked. `docker exec` enters the container's own mount
        namespace, so it sees exactly what the build saw. This is
        cibuildwheel's own `copy_into()` mechanism (`oci_container.py:442`,
        a `tar` piped through `exec -i`) run in the other direction, for a
        reason upstream never has to state because it never mounts anything
        from inside.

        `--no-same-owner` on the host side: everything in the container is
        built as root (see the class docstring on why there is no `--user`
        here any more), and without it a privileged host extraction would
        reproduce that ownership on files the invoking user has to be able
        to delete.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=dest.parent) as staging:
            producer = subprocess.Popen(
                [
                    "docker",
                    "exec",
                    self.name,
                    "tar",
                    "-cf",
                    "-",
                    "-C",
                    str(source.parent),
                    source.name,
                ],
                stdout=subprocess.PIPE,
            )
            assert producer.stdout is not None
            with producer.stdout:
                extracted = subprocess.run(
                    ["tar", "-xf", "-", "--no-same-owner", "-C", staging],
                    stdin=producer.stdout,
                    check=False,
                )
            if producer.wait() != 0 or extracted.returncode != 0:
                msg = f"{self.image}: copying {source} out of the container failed"
                raise UsermodBuildError(msg)
            # Atomic-ish rename rather than extracting straight to `dest`:
            # the archive member is named after `source`, which need not
            # match `dest`'s own basename, and a half-extracted tree must
            # never be mistaken for a finished artifact.
            produced = Path(staging) / source.name
            if dest.exists():
                shutil.rmtree(dest) if dest.is_dir() else dest.unlink()
            shutil.move(str(produced), str(dest))

    def _docker(
        self,
        command: list[str],
        *,
        what: str,
        timeout: float | None = None,
        capture_output: bool = False,
        quiet: bool = False,
    ) -> str | None:
        try:
            result = subprocess.run(
                command,
                check=True,
                timeout=timeout,
                capture_output=capture_output,
                text=capture_output,
                stdout=subprocess.DEVNULL if quiet else None,
            )
            return result.stdout if capture_output else None
        except subprocess.TimeoutExpired as exc:
            # The same reasoning `run()` documents: killing the CLI process
            # leaves the container itself running under `dockerd`. Here it
            # is `kill`, not `rm`, so `__exit__` still does the teardown and
            # a caller inspecting the failure sees one path, not two.
            subprocess.run(["docker", "kill", self.name], check=False)
            msg = f"{self.image}: `{what}` timed out after {timeout}s and was killed"
            raise UsermodBuildError(msg) from exc
        except subprocess.CalledProcessError as exc:
            msg = f"{self.image}: `{what}` failed with exit code {exc.returncode}"
            raise UsermodBuildError(msg) from exc
        except FileNotFoundError as exc:
            msg = (
                f"a container against image {self.image!r} was requested but "
                "the docker CLI itself is not on PATH"
            )
            raise UsermodBuildError(msg) from exc


def _host_user() -> str | None:
    """`uid:gid` for `docker exec --user`, or `None` where the host has no
    such notion. `os.getuid`/`getgid` do not exist on native Windows Python;
    Docker itself is Linux-container-only for every port here regardless of
    host OS (D30), so this only needs to be skipped, not ported."""
    if not hasattr(os, "getuid"):
        return None
    return f"{os.getuid()}:{os.getgid()}"


def _lower_path(index: int) -> str:
    """Where the `index`-th read-only bind lands inside the container -- out
    of the way, since `overlay()` needs the tree's own path free to mount
    the writable view on."""
    return f"/cibuildmp-lower-{index}"


def overlay_container(
    lower: Path,
    *,
    image: str,
    oci_platform: str | None = None,
    mounts: list[Path] | None = None,
    env: dict[str, str] | None = None,
    linux32: bool = False,
) -> Container:
    """A `Container` with `lower` already declared as a read-only bind, ready
    for `overlay(lower)` once entered.

    The two halves have to agree and are easy to get wrong apart: the bind
    can only be declared at `docker create` time, while the overlay can only
    be mounted once the container is running. This is the entry point every
    caller should use.
    """
    return Container(
        image=image,
        oci_platform=oci_platform,
        mounts=list(mounts or []),
        ro_mounts=[lower],
        env=env,
        overlay=True,
        linux32=linux32,
    )

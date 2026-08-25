"""Sibling-container execution for usermod port builds -- D26's own
design, Docker-only for every port (D30). `unix` and `webassembly` are
wired to `ensure_image()` today, reachable through the real CLI/
action.yml (`build_unix()`/`build_webassembly()`); `windows`/`qemu`/
`esp32` still need their own real example project proven live first
(D26's own "one port, proven live, before the next" precedent) before
their own `build_<port>()` calls this too.

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
but the resolved image reference itself -- no separate preload/cache
step of its own -- and only ever does a plain `docker pull` of an
already-published, digest-pinned image
(`resources/pinned_docker_images.cfg`) the first time it is actually
used; building one is a rare, out-of-band maintainer task
(`bin/update_docker.py`), never part of a consumer's own build. This
module now follows that exactly: the per-port Dockerfiles live at the
repo root (`docker/*.Dockerfile`, not shipped in the installed wheel any
more -- see pyproject.toml's own comment), published by
`.github/workflows/publish-docker-images.yml` to GHCR, digest-pinned in
`PORT_IMAGES` below the same way `pinned_docker_images.cfg` pins
quay.io's own manylinux/musllinux images. `ensure_image()` just resolves
which reference to use; `run()`'s own `--pull missing` is what actually
fetches it, lazily, the same division of labour cibuildwheel's own code
already has. Docker's own local image store is the only cache involved
-- no `CIBMP_CACHE_PATH`-backed save/load of image content was added on top
of that: checked directly, cibuildwheel does not do this either
(`docker save`/`docker load` do not appear anywhere in its repo), so
there was no real precedent for it, only extra machinery. No build
fallback at all any more: `PORT_IMAGES` having nothing registered for a
(port, arch[, libc]) is now a clear, immediate error, not a slow last
resort.

D28 step 2: adding a new port's Docker support is "write the Dockerfile
at docker/<name>.Dockerfile, let publish-docker-images.yml publish it,
register the resulting digest in PORT_IMAGES below" -- a maintainer edits
*this file*, not something an end user configures via cibuildmp.toml.
There is no config-file knob here and there deliberately never will be: a
Docker image per port is cibuildmp's own build infrastructure, the same
way `action.Dockerfile`'s package list isn't a user-facing setting
either. `CIBMP_<PORT>_<ARCH>_<LIBC>_DOCKER_IMAGE` stays purely as a
local-testing/override knob (point it at a `:local` tag you just built
yourself, or swap in a fork's image without editing source) -- it always
wins over `PORT_IMAGES`'s own default when set. See docs/BACKLOG.md's own
D26/D28.

Keyed by (port, arch), with an optional trailing libc segment -- not
port alone. Corrected mid-session, on review: `unix`'s own five
architectures do not share one image (D31), cibuildwheel's own
manylinux_x86_64/musllinux_aarch64 shape, not one combined "linux"
image. `libc6-dev-arm64-cross` etc. only apply to their own arch
anyway, so a per-arch split loses nothing a combined image had and
gains real isolation: an armhf toolchain bump can no longer touch an
x64 build's own image the way one shared apt-get install line did
before D26 at all. `libc` is `None` by default, not `"manylinux"`:
most ports (`windows`, `qemu`, `webassembly`, `esp32`) have no such
axis at all -- Windows has no second libc a binary could be built
against -- so forcing every port through a fake "manylinux" label
would leak `unix`-specific vocabulary onto ports it means nothing for.
Only `build_unix()` passes one, explicitly, since that port is the one
place this distinction is real (D31's own musllinux images don't exist
yet -- no real musl toolchain built or verified -- so `"manylinux"` is
`unix`'s own only real value today, not a stand-in default here).
"""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

from .build import UsermodBuildError

# Maintainer-declared default image per (port, arch[, libc]), keyed
# "{port}-{arch}" or "{port}-{arch}-{libc}" -- the same port/arch
# vocabulary `cibuildmp` already uses everywhere else (targets.py's
# Target.port/Target.arch), plus D31's own manylinux/musllinux libc
# axis where a port actually has one.
#
# Digest-pinned (`@sha256:...`), never a mutable tag like `:latest` --
# the same shape cibuildwheel's own `pinned_docker_images.cfg` uses for
# exactly the same reason: an immutable reference is what makes "already
# cached" and "still correct" the same fact, so `run()`'s own `--pull
# missing` never has to guess whether a locally-cached image is stale.
# `publish-docker-images.yml` is what keeps this table current -- update
# the digest here (a maintainer, real PR) whenever that workflow
# publishes a new one, the same manual-but-deliberate cadence
# `bin/update_docker.py` gives cibuildwheel's own pins.
#
# publish-docker-images.yml ran for real on 2026-08-25 (run 32895072172,
# triggered by the user) and pushed all eight -- digests below are copied
# from that run's own "Record the pinned digest" step, not guessed.
#
# **These GHCR packages are private as of that run** -- confirmed live,
# not assumed: an unauthenticated `docker pull` of the qemu image above
# returned `401 unauthorized`. A real consumer with no GHCR credentials
# at all (the entire point of this table) cannot pull any of these until
# a repo admin flips each `cibuildmp-*` package to Public under
# ballistics-lab's own package settings. Registered here anyway, since
# the digests themselves are correct and this is the one place they
# belong -- but until that visibility change happens, every usermod
# build that reaches this table (including this repo's own
# build-usermod, which no longer logs in to GHCR at all -- see D33)
# fails to pull, the same as before this table had anything in it.
PORT_IMAGES: dict[str, str] = {
    "unix-x64-manylinux": (
        "ghcr.io/ballistics-lab/cibuildmp-unix-manylinux-x64"
        "@sha256:1eb0c762936634c9a38adad5713fe02956ef1ac15af257157d26b77d6fc19cd4"
    ),
    "unix-x86-manylinux": (
        "ghcr.io/ballistics-lab/cibuildmp-unix-manylinux-x86"
        "@sha256:ea312535ea59f78e72e5294920a794ec5fc8acfc1b4733a142a24a53ab317fd0"
    ),
    "unix-aarch64-manylinux": (
        "ghcr.io/ballistics-lab/cibuildmp-unix-manylinux-aarch64"
        "@sha256:72979c6af3311b312101f37c9a5a28d1476d4b1883a3c7b98b8f6325a915726f"
    ),
    "unix-armhf-manylinux": (
        "ghcr.io/ballistics-lab/cibuildmp-unix-manylinux-armhf"
        "@sha256:773a9b0220b8be8e6d76ba6878a596e85bd360c2e18538398c78908af8c8d27c"
    ),
    "unix-mipsel-manylinux": (
        "ghcr.io/ballistics-lab/cibuildmp-unix-manylinux-mipsel"
        "@sha256:c4055efd0ccbd9a4d4d341d6969ee7577d009be190ac174f71e11fe6dfcba14b"
    ),
    # windows-x64/windows-x86 share one combined image (D28 step 3 --
    # this port has no manylinux/musllinux-shaped axis to split on).
    "windows-x64": (
        "ghcr.io/ballistics-lab/cibuildmp-windows"
        "@sha256:af86047e93e3f7cdf9460674d30c475ab6916277d8684643d63af80258bf350a"
    ),
    "windows-x86": (
        "ghcr.io/ballistics-lab/cibuildmp-windows"
        "@sha256:af86047e93e3f7cdf9460674d30c475ab6916277d8684643d63af80258bf350a"
    ),
    "qemu": (
        "ghcr.io/ballistics-lab/cibuildmp-qemu"
        "@sha256:3f204e274f36f15cdd478c9f2a55af3833359568c196955057cf5a2cc31cc336"
    ),
    "webassembly": (
        "ghcr.io/ballistics-lab/cibuildmp-webassembly"
        "@sha256:d9f9dec65136b4bb015d9b49d6741730303bbe7232958ec409af54d02d4d1004"
    ),
}


def image_for(
    port: str, arch: str | None = None, libc: str | None = None
) -> str | None:
    """An explicitly *named* image for `port`/`arch` (optionally qualified
    by `libc`) -- an env-var override or a `PORT_IMAGES`-registered
    default -- or None if neither is set. `arch` is optional for a port
    with no per-build axis at all (`qemu`, `webassembly`): omit it rather
    than passing `""`, so the key/env name don't carry a trailing
    separator that means nothing.

    Pure and side-effect-free (no `docker` invocation, no filesystem
    access) -- what lets `tests/test_usermod_dockerrun.py` cover its
    precedence rules without a Docker daemon at all. `run()` below is
    what actually fetches the resolved reference, lazily, the first time
    it is used.

    `CIBMP_<PORT>_<ARCH>_DOCKER_IMAGE` (e.g.
    `CIBMP_WINDOWS_X64_DOCKER_IMAGE=cibuildmp-windows:local`), or
    `CIBMP_<PORT>_<ARCH>_<LIBC>_DOCKER_IMAGE` when `libc` is given
    (e.g. `CIBMP_UNIX_X64_MANYLINUX_DOCKER_IMAGE=...`), overrides
    PORT_IMAGES's own registered default when set -- local testing
    against a freshly-built image, or swapping in a different image
    entirely, without touching source.
    """
    parts = _key_parts(port, arch, libc)
    override = os.environ.get(_env_name(parts, "DOCKER_IMAGE"))
    if override:
        return override
    return PORT_IMAGES.get("-".join(parts))


def _key_parts(port: str, arch: str | None, libc: str | None) -> list[str]:
    return [port, *([arch] if arch else []), *([libc] if libc else [])]


def _env_name(parts: list[str], suffix: str) -> str:
    return "CIBMP_" + "_".join(p.upper() for p in parts) + f"_{suffix}"


def timeout_for(
    port: str, arch: str | None = None, libc: str | None = None
) -> float | None:
    """Seconds `run()` should let this (port, arch[, libc])'s own
    container run before killing it, or `None` for no limit at all --
    the default the user's own call insisted on: a container hanging
    forever should be opt-in protection, not a surprise ceiling nobody
    asked for.

    `CIBMP_<PORT>_<ARCH>_<LIBC>_TIMEOUT` (the exact same per-container
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
    parts = _key_parts(port, arch, libc)
    specific = os.environ.get(_env_name(parts, "TIMEOUT"))
    if specific:
        return float(specific)
    blanket = os.environ.get("CIBMP_TIMEOUT")
    if blanket:
        return float(blanket)
    return None


def ensure_image(
    port: str, arch: str | None = None, libc: str | None = None
) -> str | None:
    """The image `port`/`arch`'s own build command should run in.

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
    return image_for(port, arch, libc)


def run(
    command: list[str],
    *,
    mounts: list[Path],
    workdir: Path,
    image: str,
    timeout: float | None = None,
) -> None:
    """Run `command` inside `image`, as a sibling container -- not nested
    inside one `cibuildmp` itself is already running in (D26's own "why
    sibling containers, not Docker-in-Docker" reasoning).

    Each of `mounts` is bind-mounted at its own identical host path, so
    `command` (already built for a bare-host invocation) needs no
    rewriting: every path it references already lives under one of them.

    `--pull missing` -- correct here specifically because `image` is
    always a digest-pinned reference (`PORT_IMAGES`'s own comment, or a
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
    """
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
    docker_command += ["-w", workdir.as_posix(), image, *command]
    try:
        subprocess.run(docker_command, check=True, timeout=timeout)
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

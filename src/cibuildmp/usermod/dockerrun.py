"""Sibling-container execution for usermod port builds -- D26's own
design, `unix` only so far, opt-in, not wired into the CLI or action.yml
yet.

The design this exists to prove out: `cibuildmp` itself stays on the bare
host (no Docker-in-Docker) and launches an ordinary sibling `docker run`
for a port's own build command, instead of that command running directly
on the host. Volume mounts land at identical absolute paths inside the
container, so the existing make/deplibs command lists (built for the bare
host) need no path translation at all -- every path they reference already
lives under `mpy_dir` or the caller's own module directory, both passed
here as `mounts`.

D28 step 2: adding a new port's Docker support is "write the Dockerfile,
declare it in PORT_IMAGES below" -- a maintainer edits *this file*, not
something an end user configures via cibuildmp.toml. There is no
config-file knob here and there deliberately never will be: a Docker
image per port is cibuildmp's own build infrastructure, the same way
`action.Dockerfile`'s package list isn't a user-facing setting either.
`CIBMP_<PORT>_<ARCH>_<LIBC>_DOCKER_IMAGE` stays purely as a
local-testing/override knob (point it at a `:local` tag you just built,
or swap in a fork's image without editing source) -- it always wins
over PORT_IMAGES's own default when set. See docs/BACKLOG.md's own
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
from pathlib import Path

from .build import UsermodBuildError

# Maintainer-declared default image per (port, arch[, libc]), keyed
# "{port}-{arch}" or "{port}-{arch}-{libc}" -- the same port/arch
# vocabulary `cibuildmp` already uses everywhere else (targets.py's
# Target.port/Target.arch), plus D31's own manylinux/musllinux libc
# axis where a port actually has one. Empty today:
# resources/docker/unix-manylinux-*.Dockerfile all exist and build
# correctly (D20, D24, D25, D26) but none are published anywhere yet
# (that's D28 step 5) -- an entry here takes effect for every caller
# that doesn't set the env var override, so registering
# "unix-x64-manylinux" before a real, pullable image exists would make
# ordinary unopted-in unix/x64 usermod builds start trying (and
# failing) to pull it. Add
# `"unix-x64-manylinux": "ghcr.io/ballistics-lab/cibuildmp-unix-manylinux-x64:latest"`
# here once publish.yml actually pushes that tag, and the same one line
# per (port, arch, libc) thereafter.
PORT_IMAGES: dict[str, str] = {}


def image_for(port: str, arch: str, libc: str | None = None) -> str | None:
    """The image to run `port`/`arch`'s own build command in (optionally
    qualified by `libc`, for ports where that's a real axis -- `unix`
    only, today), or None to build directly on the host (today's
    default for every port/arch, since PORT_IMAGES is still empty and
    no caller sets the env var).

    `CIBMP_<PORT>_<ARCH>_DOCKER_IMAGE` (e.g.
    `CIBMP_WINDOWS_X64_DOCKER_IMAGE=cibuildmp-windows:local`), or
    `CIBMP_<PORT>_<ARCH>_<LIBC>_DOCKER_IMAGE` when `libc` is given
    (e.g. `CIBMP_UNIX_X64_MANYLINUX_DOCKER_IMAGE=...`), overrides
    PORT_IMAGES's own registered default when set -- local testing
    against a freshly-built image, or swapping in a different image
    entirely, without touching source.
    """
    parts = [port, arch, *([libc] if libc else [])]
    env_key = "CIBMP_" + "_".join(p.upper() for p in parts) + "_DOCKER_IMAGE"
    override = os.environ.get(env_key)
    if override:
        return override
    return PORT_IMAGES.get("-".join(parts))


def run(command: list[str], *, mounts: list[Path], workdir: Path, image: str) -> None:
    """Run `command` inside `image`, as a sibling container -- not nested
    inside one `cibuildmp` itself is already running in (D26's own "why
    sibling containers, not Docker-in-Docker" reasoning).

    Each of `mounts` is bind-mounted at its own identical host path, so
    `command` (already built for a bare-host invocation) needs no
    rewriting: every path it references already lives under one of them.

    `--pull missing` (Docker's own default, confirmed live via `docker
    run --help` -- pinned explicitly here rather than relied on, in
    case that default ever changes) is the whole answer to "how does
    cibuildmp decide build-vs-cache": it never decides anything itself.
    An already-cached `image` (matched by full reference, tag and all)
    runs immediately with no network access at all; a `image` not seen
    before pulls exactly once. This only stays correct because every
    image `cibuildmp` itself resolves to is tagged `:sha-<gitsha>`
    (D28 step 5's own `verify-docker-images` job) -- an immutable
    reference by construction, so "already cached" and "still correct"
    are the same fact. `--pull always` would be needed instead the
    moment anything here ever resolved to a mutable tag like `:latest`,
    which is exactly why PORT_IMAGES/CIBMP_<PORT>_<ARCH>_DOCKER_IMAGE
    are documented as sha-tagged references, not `:latest` ones.
    """
    docker_command = ["docker", "run", "--rm", "--pull", "missing"]
    for mount in mounts:
        docker_command += ["-v", f"{mount.as_posix()}:{mount.as_posix()}"]
    docker_command += ["-w", workdir.as_posix(), image, *command]
    try:
        subprocess.run(docker_command, check=True)
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

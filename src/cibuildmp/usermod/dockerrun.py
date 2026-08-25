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
# Empty today: docker/unix-manylinux-*.Dockerfile (etc.) all exist and
# build correctly (D20, D24, D25, D26) but publish-docker-images.yml has
# not run for real yet (needs a real push to this repo's own main, which
# this sandbox cannot do) -- registering a digest that does not exist
# yet would make ordinary unopted-in usermod builds start failing to
# pull it. Add
# `"unix-x64-manylinux": "ghcr.io/o-murphy/cibuildmp-unix-manylinux-x64@sha256:<real digest>"`
# here once that workflow has actually published one, and the same one
# line per (port, arch, libc) thereafter.
PORT_IMAGES: dict[str, str] = {}


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
    parts = [port, *([arch] if arch else []), *([libc] if libc else [])]
    env_key = "CIBMP_" + "_".join(p.upper() for p in parts) + "_DOCKER_IMAGE"
    override = os.environ.get(env_key)
    if override:
        return override
    return PORT_IMAGES.get("-".join(parts))


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


def run(command: list[str], *, mounts: list[Path], workdir: Path, image: str) -> None:
    """Run `command` inside `image`, as a sibling container -- not nested
    inside one `cibuildmp` itself is already running in (D26's own "why
    sibling containers, not Docker-in-Docker" reasoning).

    Each of `mounts` is bind-mounted at its own identical host path, so
    `command` (already built for a bare-host invocation) needs no
    rewriting: every path it references already lives under one of them.

    `--pull missing` -- correct here specifically because `image` is
    always a digest-pinned reference (`PORT_IMAGES`'s own comment, or a
    caller's own override): an already-cached `image` runs immediately
    with no network access at all, and one not seen before pulls exactly
    once, with no risk of ever running a stale build against a name that
    used to mean something else. `ensure_image()` above already
    populated the cache (from `CIBMP_CACHE_PATH` or a real pull) before this
    ever runs, so in practice this `--pull` rarely does anything at all --
    kept anyway as the correct fallback for a caller that built `image`
    by hand and calls `run()` directly, skipping `ensure_image()`.
    """
    docker_command = ["docker", "run", "--rm", "--pull", "missing"]
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

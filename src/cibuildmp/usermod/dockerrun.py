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
`CIBMP_<PORT>_DOCKER_IMAGE` stays purely as a local-testing/override knob
(point it at a `:local` tag you just built, or swap in a fork's image
without editing source) -- it always wins over PORT_IMAGES's own default
when set. See docs/BACKLOG.md's own D26/D28.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .build import UsermodBuildError

# Maintainer-declared default image per port, keyed by the same port name
# `cibuildmp` already uses everywhere else (targets.py's Target.port).
# Empty today: resources/docker/unix.Dockerfile exists and builds
# correctly (D20, D24, D25) but is not yet published anywhere (that's
# D28 step 5) -- an entry here takes effect for every caller that
# doesn't set the env var override, so registering "unix" before a
# real, pullable image exists would make ordinary unopted-in unix
# usermod builds start trying (and failing) to pull it. Add
# `"unix": "ghcr.io/ballistics-lab/cibuildmp-unix:latest"` here once
# publish.yml actually pushes that tag, and the same one line per port
# thereafter.
PORT_IMAGES: dict[str, str] = {}


def image_for_port(port: str) -> str | None:
    """The image to run `port`'s own build command in, or None to build
    directly on the host (today's default for every port, since
    PORT_IMAGES is still empty and no caller sets the env var).

    `CIBMP_<PORT>_DOCKER_IMAGE` (e.g. `CIBMP_UNIX_DOCKER_IMAGE=cibuildmp-unix:local`)
    overrides PORT_IMAGES's own registered default when set -- local
    testing against a freshly-built image, or swapping in a different
    image entirely, without touching source.
    """
    override = os.environ.get(f"CIBMP_{port.upper()}_DOCKER_IMAGE")
    if override:
        return override
    return PORT_IMAGES.get(port)


def run(command: list[str], *, mounts: list[Path], workdir: Path, image: str) -> None:
    """Run `command` inside `image`, as a sibling container -- not nested
    inside one `cibuildmp` itself is already running in (D26's own "why
    sibling containers, not Docker-in-Docker" reasoning).

    Each of `mounts` is bind-mounted at its own identical host path, so
    `command` (already built for a bare-host invocation) needs no
    rewriting: every path it references already lives under one of them.
    """
    docker_command = ["docker", "run", "--rm"]
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

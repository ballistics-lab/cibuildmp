"""Sibling-container execution for usermod port builds -- D26's own
proof-of-concept, `unix` only, opt-in, not wired into the CLI or
action.yml yet.

The design this exists to prove out: `cibuildmp` itself stays on the bare
host (no Docker-in-Docker) and launches an ordinary sibling `docker run`
for a port's own build command, instead of that command running directly
on the host. Volume mounts land at identical absolute paths inside the
container, so the existing make/deplibs command lists (built for the bare
host) need no path translation at all -- every path they reference already
lives under `mpy_dir` or the caller's own module directory, both passed
here as `mounts`.

Selected today only via `CIBMP_<PORT>_DOCKER_IMAGE` (e.g.
`CIBMP_UNIX_DOCKER_IMAGE=cibuildmp-unix:local`) -- no config-file knob,
deliberately: this proves the mechanism works before it becomes a real,
documented option. See docs/BACKLOG.md's own D26.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .build import UsermodBuildError


def image_for_port(port: str) -> str | None:
    """The image to run `port`'s own build command in, or None to build
    directly on the host (today's default, unchanged for every existing
    caller)."""
    return os.environ.get(f"CIBMP_{port.upper()}_DOCKER_IMAGE") or None


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

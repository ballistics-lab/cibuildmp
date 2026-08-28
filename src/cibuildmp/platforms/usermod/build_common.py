"""What every `build_<port>()` driver shares: the one exception type they
all raise, and the one container-mpy-cross helper they all call.

Split out of a single `build.py` (2026-08-29) once that file reached seven
ports and 1600+ lines -- the same one-file-per-platform shape cibuildwheel
itself uses (`linux.py`/`macos.py`/`windows.py`/`pyodide.py` plus a shared
`util.py`), read directly before choosing this layout, not recalled (see
this repo's own CLAUDE.md on that discipline). See
docs/records/0061-usermod-build-drivers-split-per-port.md for the record.

Every `Path` embedded into a `make` command line, across every port module
below, goes through `.as_posix()`, never a bare `str()`: a real
`usermod-dev.yml` run on `windows-latest`, back when that port still ran
under MSYS2, caught this -- `str(WindowsPath(...))` produces backslashes,
and GNU Make wants forward slashes regardless of host OS. Kept as the rule
for every port, not just the one that surfaced it.
"""

from __future__ import annotations

import os
from pathlib import Path


class UsermodBuildError(Exception):
    pass


def container_mpy_cross(
    mpy_dir: Path,
    *,
    slug: str,
    image: str,
    oci_platform: str | None = None,
    linux32: bool = False,
    timeout: float | None = None,
) -> Path:
    """Build `mpy-cross` **inside `image`** and return the binary, for the
    port build to pass as `MICROPY_MPYCROSS=`.

    Found the hard way, on the first real build under record 0043's native
    images -- not anticipated by that record, and the reason it needed a
    live run rather than a review:

        mpy-cross: /lib64/libc.so.6: version `GLIBC_2.34' not found
        make: *** [py/mkrules.mk:231: .../frozen_content.c] Error 1

    `sources.build_mpy_cross()` builds mpy-cross on the **host**, and
    `py/mkrules.mk` then executes it *inside the container* to compile the
    frozen manifest. That worked only for as long as every image was
    `ubuntu:24.04` -- the same glibc as a typical host, by coincidence
    rather than by design. It breaks two different ways now, and both are
    structural rather than incidental:

    * **A real libc floor is a floor.** `manylinux_2_28` is AlmaLinux 8,
      glibc 2.28; a host-built binary needing 2.34 cannot run there. The
      lower and more useful the floor, the more certainly this fails --
      so the failure gets *worse* as the manylinux claim gets *better*.
      For musllinux there is no version to argue about: a glibc binary
      does not run under musl at all.
    * **Native images have a native architecture.** An x86_64 host's
      mpy-cross cannot execute inside a `linux/arm64` container under any
      libc. This alone makes the in-container build mandatory, not merely
      safer, for every non-native target -- which under 0043 is most of
      the matrix.

    The same reasoning reaches the cross-compiling ports (`windows`,
    `webassembly`, `qemu`) from the other direction: their images are
    amd64, so on an **arm64 host** the host-built mpy-cross is an arm64
    binary that cannot run inside them. That is exactly the "one config,
    either host architecture" property 0043 exists to provide, so they
    use this too.

    `slug` scopes the build directory (`mpy-cross/build-<slug>/`) so each
    image gets its own binary and none of them collide with the host
    build at `mpy-cross/build/` that natmod still uses -- natmod is
    unaffected by all of this, since it never runs mpy-cross anywhere but
    the host.

    Cached by existence, like `sources.build_mpy_cross()`: a rebuilt
    container binary is only needed when the image itself changes, and the
    image is digest-pinned.
    """
    from ... import dockerrun

    build_dir = mpy_dir / "mpy-cross" / f"build-{slug}"
    binary = build_dir / "mpy-cross"
    if binary.exists():
        return binary

    dockerrun.run(
        [
            "make",
            "-C",
            (mpy_dir / "mpy-cross").as_posix(),
            f"BUILD={build_dir.as_posix()}",
            f"-j{os.cpu_count() or 1}",
        ],
        mounts=[mpy_dir],
        workdir=mpy_dir / "mpy-cross",
        image=image,
        timeout=timeout,
        oci_platform=oci_platform,
        linux32=linux32,
    )
    if not binary.exists():
        raise UsermodBuildError(
            f"mpy-cross build inside {image} reported success but {binary} is missing"
        )
    return binary

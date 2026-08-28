"""usermod build driver: `rp2` -- record [0022]'s own last unstarted item
("no Pico SDK resolver, no live verification"), closed 2026-08-29. See
docs/records/0060-rp2-build-driver.md.

Docker, mirroring `build_esp32()`'s own container-per-port shape ([0028])
-- but simpler: the Pico SDK, and every `lib/` it in turn needs, are plain
git submodules of the MicroPython checkout itself, not a separate
host-side environment like ESP-IDF -- so there is no
`usermod/espidf.py`-equivalent resolver here. See
docs/records/0061-usermod-build-drivers-split-per-port.md for context on
this file's own split from a single `build.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import build_common
from .build_common import UsermodBuildError

# `sources.fetch_micropython()`'s own `submodules=` -- only ever consulted
# on its clone path (a preview tag with no published release tarball); the
# tarball path already vendors every lib/ submodule, which is the whole
# reason it is preferred (see that function's own docstring). Live-caught:
# `make ... submodules` run unconditionally inside the container failed
# with "fatal: not a git repository" against a real tarball checkout --
# `ports/rp2/py/mkrules.mk`'s `submodules` target is a bare `git submodule
# update`, which cannot run at all outside a real git checkout. Five, not
# just `lib/pico-sdk` itself: the old host-based
# `.github/actions/build-usermod-rp2040/action.yml` (this driver's own
# reference) notes `ports/rp2/CMakeLists.txt` redirects
# `PICO_TINYUSB_PATH`/`PICO_LWIP_PATH`/`PICO_BTSTACK_PATH`/
# `PICO_CYW43_DRIVER_PATH` at MicroPython's own top-level `lib/<name>`
# rather than at pico-sdk's own nested (and, on the clone path, never
# initialised) copies -- confirmed present as real top-level `lib/`
# directories in a genuine v1.29.0 tarball checkout.
RP2_SUBMODULES: tuple[str, ...] = (
    "lib/pico-sdk",
    "lib/tinyusb",
    "lib/lwip",
    "lib/btstack",
    "lib/cyw43-driver",
)


@dataclass(frozen=True)
class Rp2BuildOptions:
    user_c_modules: str
    frozen_manifest: str
    board: str = "PICO"
    extra_make_args: tuple[str, ...] = ()


def rp2_make_command(
    opts: Rp2BuildOptions, mpy_dir: Path, *, mpy_cross: Path | None = None
) -> list[str]:
    # No BUILD= override, same reason `esp32_make_command()`'s own comment
    # gives: `ports/rp2` is CMake-driven too, and a mismatched BUILD=
    # risks the identical FROZEN_MANIFEST-via-MAKEFLAGS leak into the
    # port's own internal mpy-cross sub-build. Simplest to just not pass
    # one, matching the esp32 driver this one is modeled on.
    return [
        "make",
        "-C",
        (mpy_dir / "ports" / "rp2").as_posix(),
        f"BOARD={opts.board}",
        f"USER_C_MODULES={opts.user_c_modules}",
        f"FROZEN_MANIFEST={opts.frozen_manifest}",
        *([f"MICROPY_MPYCROSS={mpy_cross.as_posix()}"] if mpy_cross else []),
        *opts.extra_make_args,
    ]


def build_rp2(
    opts: Rp2BuildOptions,
    mpy_dir: Path,
    *,
    toolchain_root: Path | None = None,
    quiet: bool = False,
) -> Path:
    """Build ports/rp2 for `opts.board`, returning the produced
    `firmware.uf2`.

    No provisioning step runs inside the container at all:
    `sources.fetch_micropython()` already resolved every submodule this
    port needs before `mpy_dir` ever reaches here -- vendored for free on
    its normal tarball path, `git submodule update --init`'d explicitly
    on its clone path (`orchestrate.build()` threads `RP2_SUBMODULES`
    into `submodules=` for exactly this). Running `ports/rp2`'s own
    `make ... submodules` target here instead was the first thing tried
    and failed live: it is a bare `git submodule update`, which cannot
    run at all against a tarball checkout ("fatal: not a git repository").

    Live-verified 2026-08-29: a real `examples/template` build against
    `v1.29.0-rp2-RPI_PICO` producing a genuine, correctly-sized
    `firmware.uf2` with the fixture's own C module linked in.

    The output path is `mpy_dir / "ports" / "rp2" / "build-<BOARD>" /
    "firmware.uf2"` -- the port's own unmodified default build directory,
    since nothing here overrides `BUILD=`.

    `toolchain_root`/`quiet` are accepted only for the same call shape
    every `build_<port>()` shares (`orchestrate.py`'s `build_one()`
    passes them uniformly); neither is used on this Docker-only path.
    """
    from ... import dockerrun

    docker_image = dockerrun.ensure_image("rp2")
    if docker_image is None:
        raise UsermodBuildError(
            "rp2: no Docker image registered -- see "
            "`resources/pinned_docker_images.toml`, or point "
            "CIBMP_RP2_DOCKER_IMAGE at a local tag"
        )
    oci_platform = dockerrun.platform_for("rp2")
    timeout = dockerrun.timeout_for("rp2")
    rp2_dir = mpy_dir / "ports" / "rp2"

    mpy_cross = build_common.container_mpy_cross(
        mpy_dir,
        slug="rp2",
        image=docker_image,
        oci_platform=oci_platform,
        timeout=timeout,
    )

    command = rp2_make_command(opts, mpy_dir, mpy_cross=mpy_cross)
    dockerrun.run(
        command,
        # Same directory-level mount `build_esp32()` uses (`.parent`, not
        # the bare `.cmake` file) -- see that function's own comment for
        # the sibling-manifest bug this avoids.
        mounts=[mpy_dir, Path(opts.user_c_modules).parent],
        workdir=rp2_dir,
        image=docker_image,
        timeout=timeout,
        oci_platform=oci_platform,
    )

    firmware = rp2_dir / f"build-{opts.board}" / "firmware.uf2"
    if not firmware.exists():
        raise UsermodBuildError(
            f"rp2/{opts.board}: build reported success but {firmware} is missing"
        )
    return firmware

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

import shlex
from dataclasses import dataclass
from pathlib import Path

from ... import toolchain_fetch
from . import build_common, targets
from .build_common import UsermodBuildError


@dataclass(frozen=True)
class Rp2BuildOptions:
    user_c_modules: str
    frozen_manifest: str
    board: str = "PICO"
    tag: str = ""
    extra_make_args: tuple[str, ...] = ()
    extra_cmake_args: tuple[str, ...] = ()


def rp2_make_command(
    opts: Rp2BuildOptions, mpy_dir: Path, *, mpy_cross: Path | None = None
) -> list[str]:
    # No BUILD= override, same reason `esp32_make_command()`'s own comment
    # gives: `ports/rp2` is CMake-driven too, and a mismatched BUILD=
    # risks the identical FROZEN_MANIFEST-via-MAKEFLAGS leak into the
    # port's own internal mpy-cross sub-build. Simplest to just not pass
    # one, matching the esp32 driver this one is modeled on.
    #
    # `CFLAGS_EXTRA` here too, not just on `container_mpy_cross()` below:
    # `ports/rp2` recompiles `py/` into the firmware itself, live-confirmed
    # to hit the identical gcc-15 diagnostic on `arm_embedded`'s own native
    # compiler ([0091], run 33697330722).
    cflags = build_common.tag_cflags(opts.tag)
    return [
        "make",
        "-C",
        (mpy_dir / "ports" / "rp2").as_posix(),
        f"BOARD={opts.board}",
        f"USER_C_MODULES={opts.user_c_modules}",
        f"FROZEN_MANIFEST={opts.frozen_manifest}",
        *([f"CFLAGS_EXTRA={' '.join(cflags)}"] if cflags else []),
        *([f"MICROPY_MPYCROSS={mpy_cross.as_posix()}"] if mpy_cross else []),
        *opts.extra_make_args,
    ]


def _rp2_project_mounts(opts: Rp2BuildOptions, package_dir: Path | None) -> list[Path]:
    """The user's own project, mounted so a module whose sources reach
    outside `USER_C_MODULES` still resolves -- `build_unix.py`'s own
    `_project_mounts()`, for a CMake port: `USER_C_MODULES` resolves to a
    *file* here (`portinfo.resolve_user_c_modules()`'s own
    `/micropython.cmake`), so the mount is that file's `.parent`, same as
    the pre-[0095] `usermod_mounts()` call this replaces. No entry at all
    when it is empty (record 0056) -- see `build_unix.py`'s own
    `_project_mounts()` comment for why `Path("")`/`Path("").parent` must
    never reach `docker run -v`."""
    mounts = [Path(opts.user_c_modules).parent] if opts.user_c_modules else []
    if package_dir is not None:
        mounts.append(package_dir.resolve())
    return mounts


def build_rp2(
    opts: Rp2BuildOptions,
    mpy_dir: Path,
    *,
    toolchain_root: Path | None = None,
    quiet: bool = False,
    package_dir: Path | None = None,
    staging: Path | None = None,
) -> Path:
    """Build ports/rp2 for `opts.board`, returning the produced
    `firmware.uf2`.

    No provisioning step runs inside the container at all:
    `sources.fetch_micropython()` already resolved every submodule this
    port needs before `mpy_dir` ever reaches here -- vendored for free on
    its normal tarball path, or (on its clone path -- a tag with no
    published release tarball) by running `ports/rp2`'s own `make
    submodules` target itself right after the clone (`orchestrate.build()`
    passes `ports=` for exactly this), the same command
    `ports/rp2/README.md` documents. That target is `git submodule
    update --init` for `lib/pico-sdk` followed by a `cmake
    -DUPDATE_SUBMODULES=1` step covering pico-sdk's own nested
    tinyusb/lwip/btstack/cyw43-driver -- both host-runnable (git and
    cmake only), unlike `esp32`'s own `submodules` target (`idf.py`,
    container-only), which is why `orchestrate.py` excludes that one port
    from the same call.

    Live-verified 2026-08-29: a real `examples/template` build against
    `v1.29.0-rp2-RPI_PICO` producing a genuine, correctly-sized
    `firmware.uf2` with the fixture's own C module linked in.

    **`Container`/overlay, not `dockerrun.run()`** ([0095]'s addendum 2):
    the checkout arrives read-only, `container.overlay(mpy_dir)` gives the
    build a writable view of it that dies with the container, and
    `ports/rp2`'s own `build-<BOARD>/` (CMake, no `BUILD=` override --
    see `rp2_make_command()`'s own comment) lands in that ephemeral upper
    layer rather than on the host. `staging` is the one thing that
    survives: the finished `firmware.uf2` is `cp`'d there before the
    container exits, which is why this needs a real staging directory
    (`orchestrate.build_one()` provides one) rather than reading the
    build tree back off a host mount that no longer exists. Modeled
    directly on `build_unix()`'s own shape -- see its comments for the
    reasoning this file does not repeat.

    The toolchain cache (`toolchain_root`, or `sources.cache_root()` when
    omitted) is **not** part of the overlay: unlike the build tree, it is
    fetched input meant to persist across runs ([0095]'s own category A),
    so it stays a plain, real read-write host mount the way it always
    was -- only the mechanism carrying it into the container changed.

    `toolchain_root`/`quiet`: `toolchain_root` is no longer a no-op --
    since [0087], `arm_embedded.Dockerfile` no longer bakes a cross
    compiler, so `rp2`'s own real one ([0086]/`targets.rp2_toolchain()`)
    is fetched at container time into `toolchain_root` (or
    `sources.cache_root()` when omitted), the same cache directory
    `espidf.fetch_esp_idf()` already keys off for `esp32`. `quiet` is
    still accepted only for the shared `build_<port>()` call shape and
    still unused here. `package_dir`, when given, is bind-mounted
    alongside `USER_C_MODULES` itself -- see `_rp2_project_mounts()`.
    """
    from ... import dockerrun

    if not opts.tag:
        raise UsermodBuildError(
            "rp2: a real MicroPython tag is required to resolve which "
            "cross toolchain to fetch (targets.rp2_toolchain()) -- got none"
        )

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

    if staging is None:
        msg = (
            "rp2 builds need a staging directory to hand the artifact back "
            "through ([0095]); orchestrate.build_one() provides one"
        )
        raise UsermodBuildError(msg)

    cross, version = targets.rp2_toolchain(opts.tag)
    toolchain_dir, fetch = toolchain_fetch.resolve_toolchain(
        cross, version, root=toolchain_root
    )

    with dockerrun.overlay_container(
        mpy_dir,
        image=docker_image,
        oci_platform=oci_platform,
        # `toolchain_dir.parent`, not `toolchain_dir` itself -- found live,
        # not assumed: `toolchain_dir` (the fetched cache's own version
        # directory) does not exist on the host until the fetch script
        # below creates it, so mounting it directly leaves Docker to
        # synthesize every missing path component up to it *inside the
        # container's own filesystem*, root-owned, since only the exact
        # bind-mounted leaf inode is backed by the host at all -- the very
        # first `mkdir -p` the fetch script runs then fails with a bare
        # "mkdir: Permission denied", before curl is ever reached. Mounting
        # the parent (`resolve_toolchain()` already creates it host-side,
        # host-owned) gives the container a real, already-owned directory
        # to stage and `mv` into instead.
        mounts=[staging, toolchain_dir.parent, *_rp2_project_mounts(opts, package_dir)],
    ) as container:
        container.overlay(mpy_dir)

        mpy_cross = build_common.container_mpy_cross(
            mpy_dir,
            timeout=timeout,
            extra_cflags=build_common.tag_cflags(opts.tag),
            container=container,
        )

        make_command = rp2_make_command(opts, mpy_dir, mpy_cross=mpy_cross)
        # One `bash -c` script, not a separate `call()` for the fetch:
        # there is nothing to hand back to a second one, and the point is
        # that the toolchain's own `bin/` is on `PATH` before `make` runs,
        # in the same container invocation ([0086]'s own `fetch_script()`
        # docstring). `export PATH=` here, not `env=`, because `call()`'s
        # own `env=` only ever sets `-e KEY=VALUE` (replace, not append)
        # -- it has no way to prepend onto the image's own existing
        # `$PATH`.
        script = (
            f"{fetch}"
            f'export PATH="{(toolchain_dir / "bin").as_posix()}:$PATH"\n'
            f"{shlex.join(make_command)}\n"
        )
        container.call(
            ["bash", "-c", script],
            workdir=rp2_dir,
            timeout=timeout,
            env=build_common.cmake_extra_args_env(
                opts.extra_cmake_args, var="CMAKE_ARGS"
            ),
        )

        # The firmware exists only inside the container's own overlay
        # until this copy -- see `build_unix()`'s identical reasoning.
        firmware = staging / "firmware.uf2"
        container.call(
            [
                "cp",
                (rp2_dir / f"build-{opts.board}" / "firmware.uf2").as_posix(),
                firmware.as_posix(),
            ],
            workdir=rp2_dir,
            timeout=timeout,
        )

    if not firmware.exists():
        raise UsermodBuildError(
            f"rp2/{opts.board}: build reported success but {firmware} is missing"
        )
    return firmware

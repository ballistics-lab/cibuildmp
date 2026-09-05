"""usermod build driver: `samd` -- record [0100], picked over the other
eight [0053] lists (`mimxrt`, `stm32`, `psoc-edge`, `alif`, `esp8266`,
`cc3200`, `renesas-ra`, `nrf`).

Toolchain provisioning mirrors `build_rp2()` exactly: `embedded_base`
image, `toolchain_fetch.resolve_toolchain()` fetches `arm-none-eabi-` at
container time, same PATH-prepend script. The make invocation does not,
though -- verified directly against `ports/samd/Makefile` at `v1.29.0`
(record 0100): plain GNU Make (`py/mkenv.mk`/`py.mk`/`extmod.mk`/
`mkrules.mk`, no `cmake`/`idf.py` anywhere), unlike `rp2`/`esp32`, whose
own Makefiles wrap `cmake`/`idf.py` and therefore cannot take an explicit
`BUILD=` without leaking `FROZEN_MANIFEST` into an internal sub-build via
`MAKEFLAGS` (`rp2_make_command()`'s own comment). `samd` has no such
internal sub-build, so `samd_make_command()` passes `BUILD=` the same
unconditional way `unix_make_command()` does, and needs no
`extra-cmake-args`/`cmake_extra_args_env()` handling at all.
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

from ... import toolchain_fetch
from . import build_common, targets
from .build_common import UsermodBuildError


@dataclass(frozen=True)
class SamdBuildOptions:
    user_c_modules: str
    frozen_manifest: str
    board: str = "SEEED_XIAO_SAMD21"
    tag: str = ""
    extra_make_args: tuple[str, ...] = ()


def samd_make_command(
    opts: SamdBuildOptions,
    mpy_dir: Path,
    build_dir: Path,
    *,
    mpy_cross: Path | None = None,
    extra_cflags: tuple[str, ...] | None = None,
) -> list[str]:
    # `BUILD=` passed unconditionally, unlike `rp2_make_command()`/
    # `esp32_make_command()` -- see this module's own docstring for why
    # that is safe here: `ports/samd/Makefile`'s own `ifneq
    # ($(BOARD_VARIANT),) BUILD ?= build-$(BOARD)-$(BOARD_VARIANT) else
    # BUILD ?= build-$(BOARD)` is a `?=`, which only ever fires when the
    # variable is still unset by the time that line runs -- an explicit
    # `BUILD=` on the invoking command line always wins regardless of
    # which branch the `ifneq` would otherwise have taken, the same
    # precedence `unix_make_command()`'s own comment relies on.
    #
    # `-j{os.cpu_count()}`, unlike `rp2_make_command()`/`esp32_make_command()`
    # (neither passes one -- `idf.py`/rp2's own cmake-driven build apparently
    # parallelize some other way, not investigated here): a plain `make`
    # port with no such wrapper compiles ports/samd's ~150-file tree fully
    # serially without it, live-measured at ~80s/board on this session's
    # 4-core sandbox -- `unix_make_command()`'s own precedent for a plain
    # Make port.
    #
    # `extra_cflags`, when given, overrides `tag_cflags()`'s own raw
    # candidate list -- the same override `unix_make_command()`'s own
    # `extra_cflags` parameter provides, and for the identical reason
    # (`probe_supported_cflags()`'s own docstring): live-caught building
    # this driver, `v1.20.0-samd-ADAFRUIT_FEATHER_M0_EXPRESS` against the
    # `14.2.1-1.1` cross toolchain `targets.samd_toolchain()` resolves for
    # that tag failed hard --
    # `cc1: error: '-Wno-error=unterminated-string-initialization': no
    # option '-Wunterminated-string-initialization'` -- because
    # `tag_cflags()` names a real gcc-15 diagnostic for every pre-`v1.26.0`
    # tag with no regard for which toolchain that row's own `gcc` field
    # actually resolves to. `build_samd()` probes against the real fetched
    # `arm-none-eabi-gcc` before calling this, the same way
    # `build_unix()`'s own cross-compile branch already does; this stays
    # the raw candidates only for a caller (a test, a hand invocation)
    # that has not done that filtering itself.
    cflags = extra_cflags if extra_cflags is not None else build_common.tag_cflags(opts.tag)
    return [
        "make",
        "-C",
        (mpy_dir / "ports" / "samd").as_posix(),
        f"-j{os.cpu_count() or 1}",
        f"BOARD={opts.board}",
        f"BUILD={build_dir.as_posix()}",
        f"USER_C_MODULES={opts.user_c_modules}",
        f"FROZEN_MANIFEST={opts.frozen_manifest}",
        *([f"CFLAGS_EXTRA={' '.join(cflags)}"] if cflags else []),
        *([f"MICROPY_MPYCROSS={mpy_cross.as_posix()}"] if mpy_cross else []),
        *opts.extra_make_args,
    ]


def _samd_project_mounts(
    opts: SamdBuildOptions, package_dir: Path | None
) -> list[Path]:
    """Same shape as `build_unix.py`'s own `_project_mounts()` -- `samd` is
    a Make port (`portinfo.resolve_user_c_modules()`'s make branch leaves
    `USER_C_MODULES` unchanged, no `/micropython.cmake` appended), so the
    mount is the module directory itself, not its parent the way the two
    cmake ports (`build_esp32.py`/`build_rp2.py`) need. No entry at all
    when `opts.user_c_modules` is empty (record 0056's no-module build) --
    see `build_unix.py`'s own `_project_mounts()` for why a relative
    `Path("")` must never reach `docker run -v`.
    """
    mounts = [Path(opts.user_c_modules)] if opts.user_c_modules else []
    if package_dir is not None:
        mounts.append(package_dir.resolve())
    return mounts


def build_samd(
    opts: SamdBuildOptions,
    mpy_dir: Path,
    *,
    toolchain_root: Path | None = None,
    quiet: bool = False,
    package_dir: Path | None = None,
    staging: Path | None = None,
) -> Path:
    """Build ports/samd for `opts.board`, returning the produced firmware.

    Docker/overlay, mirroring `build_rp2()`'s own shape exactly ([0095]):
    the checkout arrives read-only, `container.overlay(mpy_dir)` gives the
    build a writable view of it that dies with the container, and
    `ports/samd`'s own `build-<BOARD>/` lands in that ephemeral upper
    layer. `staging` is the one thing that survives -- the finished
    firmware is `cp`'d there before the container exits.

    The toolchain cache (`toolchain_root`, or `sources.cache_root()` when
    omitted) is fetched input meant to persist across runs ([0095]'s own
    category A), mounted the same way `build_rp2()` already does --
    `toolchain_dir.parent`, not `toolchain_dir` itself, since the latter
    does not exist on the host until the fetch script inside the
    container creates it (see `targets.rp2_toolchain()`'s own sibling
    comment in `build_rp2.py` for the live-found reasoning).

    The real output artifact name/extension is not assumed here beyond
    upstream's own default (`firmware.uf2` -- `ports/samd`'s boards are,
    like `rp2`'s, predominantly UF2-bootloader boards); [0100] leaves this
    for the first live build to confirm rather than guessing across all
    eighteen boards' own bootloader conventions.
    """
    from ... import dockerrun

    if not opts.tag:
        raise UsermodBuildError(
            "samd: a real MicroPython tag is required to resolve which "
            "cross toolchain to fetch (targets.samd_toolchain()) -- got none"
        )

    docker_image = dockerrun.ensure_image("samd")
    if docker_image is None:
        raise UsermodBuildError(
            "samd: no Docker image registered -- see "
            "`resources/pinned_docker_images.toml`, or point "
            "CIBMP_SAMD_DOCKER_IMAGE at a local tag"
        )
    oci_platform = dockerrun.platform_for("samd")
    timeout = dockerrun.timeout_for("samd")
    samd_dir = mpy_dir / "ports" / "samd"

    if staging is None:
        msg = (
            "samd builds need a staging directory to hand the artifact "
            "back through ([0095]); orchestrate.build_one() provides one"
        )
        raise UsermodBuildError(msg)

    cross, version = targets.samd_toolchain(opts.tag)
    toolchain_dir, fetch = toolchain_fetch.resolve_toolchain(
        cross, version, root=toolchain_root
    )

    build_dir = samd_dir / f"build-{opts.board}"

    with dockerrun.overlay_container(
        mpy_dir,
        image=docker_image,
        oci_platform=oci_platform,
        mounts=[staging, toolchain_dir.parent, *_samd_project_mounts(opts, package_dir)],
    ) as container:
        container.overlay(mpy_dir)

        # Fetched first, on its own -- not folded into the same script as
        # `make` the way `build_rp2()` does it -- because
        # `probe_supported_cflags()` below needs the real cross compiler
        # to already exist on disk to probe against it by full path.
        # Idempotent either way (`fetch_script()`'s own marker check), so
        # running it as a standalone step costs nothing on a warm cache.
        container.call(["bash", "-c", fetch], workdir=samd_dir, timeout=timeout)

        # Probed against the *cross* compiler this row's own toolchain
        # resolves to, not mpy-cross's native one -- see
        # `samd_make_command()`'s own docstring for the live-caught reason
        # this cannot just reuse the raw `tag_cflags()` list the way
        # `build_rp2()`/`build_esp32()` currently still do.
        cross_gcc = (toolchain_dir / "bin" / f"{cross}gcc").as_posix()
        probed_cflags = build_common.probe_supported_cflags(
            build_common.tag_cflags(opts.tag),
            compiler=cross_gcc,
            timeout=timeout,
            container=container,
        )

        mpy_cross = build_common.container_mpy_cross(
            mpy_dir,
            timeout=timeout,
            extra_cflags=build_common.tag_cflags(opts.tag),
            container=container,
        )

        make_command = samd_make_command(
            opts, mpy_dir, build_dir, mpy_cross=mpy_cross, extra_cflags=probed_cflags
        )
        script = (
            f'export PATH="{(toolchain_dir / "bin").as_posix()}:$PATH"\n'
            f"{shlex.join(make_command)}\n"
        )
        container.call(
            ["bash", "-c", script],
            workdir=samd_dir,
            timeout=timeout,
        )

        firmware = staging / "firmware.uf2"
        container.call(
            [
                "cp",
                (build_dir / "firmware.uf2").as_posix(),
                firmware.as_posix(),
            ],
            workdir=samd_dir,
            timeout=timeout,
        )

    if not firmware.exists():
        raise UsermodBuildError(
            f"samd/{opts.board}: build reported success but {firmware} is missing"
        )
    return firmware

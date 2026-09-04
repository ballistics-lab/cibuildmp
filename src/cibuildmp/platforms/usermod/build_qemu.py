"""usermod build driver: `qemu` (nine real boards across three toolchains).

`ports/qemu/Makefile`'s own default-board `CROSS_COMPILE ?=
arm-none-eabi-` (`MPS2_AN385`, Cortex-M3) is the exact toolchain natmod's
own `armv7m` arch already resolves -- reused rather than pinning it a
second time. `ports/qemu` also has RISC-V boards, `VIRT_RV32`/`VIRT_RV64`
(`CROSS_COMPILE ?= riscv64-unknown-elf-`, natmod's own `rv32imc`/
`rv64imc` toolchain), and one PowerPC board, `POWERNV9`
(`CROSS_COMPILE ?= powerpc64le-linux-gnu-`) -- `QEMU_BOARD_CROSS` below
resolves whichever one `opts.board` names. No board-level default
narrowing any more (record 0052 retracted the whole `boards = [...]`
axis-config concept along with every other one): every real identifier a
`build`/`skip` glob names is reachable the same way, uniformly.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

from ... import toolchain_fetch
from . import targets
from .build_common import UsermodBuildError, usermod_mounts

# board -> `ports/qemu/Makefile`'s own `CROSS_COMPILE ?=` for it, keyed by
# `QEMU_ARCH`, not by board directly. Every value here is copied straight
# from `resources/build-platforms.toml`'s own per-row `cross` field for
# `[usermod.qemu]` -- verified stable across v1.24.0..v1.29.0 for every
# board present in both, not re-derived or guessed here. Six boards added
# 2026-08-28 (MICROBIT/MPS2_AN500/MPS3_AN547/NETDUINO2/SABRELITE/POWERNV9)
# -- `dockerrun.ensure_image("qemu", board)` already resolved an image for
# all nine via that same table's own `images.<board>` map ([0058]), this
# dict was the only thing still gating them to "not supported yet".
# POWERNV9 needs its own real proof before this is trusted: no qemu board
# has ever built through `ppc64le_linux` before (only a bare `gcc`/
# `#include` smoke test in [0058]'s own verification table).
QEMU_BOARD_CROSS: dict[str, str] = {
    "MICROBIT": "arm-none-eabi-",
    "MPS2_AN385": "arm-none-eabi-",
    "MPS2_AN500": "arm-none-eabi-",
    "MPS3_AN547": "arm-none-eabi-",
    "NETDUINO2": "arm-none-eabi-",
    "SABRELITE": "arm-none-eabi-",
    "VIRT_RV32": "riscv64-unknown-elf-",
    "VIRT_RV64": "riscv64-unknown-elf-",
    "POWERNV9": "powerpc64le-linux-gnu-",
}


@dataclass(frozen=True)
class QemuBuildOptions:
    user_c_modules: str
    frozen_manifest: str
    build_dir: Path
    board: str = "MPS2_AN385"
    tag: str = ""
    extra_make_args: tuple[str, ...] = ()


# `ports/qemu/Makefile`'s own `CROSS_COMPILE ?= arm-none-eabi-` default,
# stated rather than relied upon. It used to come from
# `toolchains.resolve("armv7m")`, whose whole job was answering "which
# prefix actually works on this machine" -- a question record 0049
# deleted along with the resolver: the image supplies `arm-none-eabi-`
# and nothing else can be in play.
QEMU_CROSS_COMPILE = "arm-none-eabi-"


def qemu_make_command(
    opts: QemuBuildOptions, mpy_dir: Path, cross_compile: str = QEMU_CROSS_COMPILE
) -> list[str]:
    # ports/qemu/Makefile uses CROSS_COMPILE=, not natmod's own CROSS=.
    # Passed explicitly rather than left to the Makefile's own default,
    # so the prefix in play is visible in the command that ran.
    return [
        "make",
        "-C",
        (mpy_dir / "ports" / "qemu").as_posix(),
        f"BOARD={opts.board}",
        f"BUILD={opts.build_dir.as_posix()}",
        f"CROSS_COMPILE={cross_compile}",
        f"USER_C_MODULES={opts.user_c_modules}",
        f"FROZEN_MANIFEST={opts.frozen_manifest}",
        *opts.extra_make_args,
    ]


def build_qemu(
    opts: QemuBuildOptions,
    mpy_dir: Path,
    *,
    toolchain_root: Path | None = None,
    quiet: bool = False,
    package_dir: Path | None = None,
    staging: Path | None = None,
) -> Path:
    """Build ports/qemu for `opts.board`, returning the produced firmware.

    The toolchain is always one natmod already resolves -- `armv7m`
    (`arm-none-eabi-`) for the six ARM boards, `rv32imc`/`rv64imc`
    (`riscv-none-elf`) for `VIRT_RV32`/`VIRT_RV64` -- via
    `QEMU_BOARD_CROSS` above, rather than pinning a second copy of
    any of them. `POWERNV9` (`powerpc64le-linux-gnu-`) is the one
    exception: no natmod arch cross-compiles to PowerPC, so
    `ppc64le_linux` ([0058]) is a `qemu`-only image.

    The output path is `opts.build_dir / "firmware.elf"` --
    ports/qemu/Makefile's own `all: $(BUILD)/firmware.elf` target, again
    no globbing needed. `package_dir`, when given, is bind-mounted
    alongside `USER_C_MODULES` itself -- see
    `build_common.usermod_mounts()`.
    """
    from ... import dockerrun

    cross = QEMU_BOARD_CROSS.get(opts.board)
    if cross is None:
        raise UsermodBuildError(
            f"qemu board {opts.board!r} not supported yet. Known: "
            f"{', '.join(QEMU_BOARD_CROSS)}"
        )
    if not opts.tag and cross in toolchain_fetch.TOOLCHAIN_CROSS_PREFIX.values():
        raise UsermodBuildError(
            f"qemu/{opts.board}: a real MicroPython tag is required to "
            "resolve which cross toolchain to fetch (targets.qemu_toolchain()) "
            "-- got none"
        )

    # **Wired to `ensure_image()` at last** -- record 0032's own gap, and
    # the last bare-host build path in usermod. It survived this long
    # because it worked: `toolchains.resolve()` found an `arm-none-eabi-`
    # on the runner and `subprocess.run` used it. Record 0049 deleted
    # that resolver along with natmod's dependence on it, so what kept
    # this port off Docker is gone and the wiring is what D30 has
    # required of every port since it was written.
    docker_image = dockerrun.ensure_image("qemu", opts.board)
    if docker_image is None:
        raise UsermodBuildError(
            f"no image registered for qemu board {opts.board!r} -- see "
            "`resources/pinned_docker_images.toml`, or point "
            f"CIBMP_QEMU_{opts.board.upper()}_DOCKER_IMAGE at a local tag"
        )

    make_command = qemu_make_command(opts, mpy_dir, cross)
    mounts = usermod_mounts(mpy_dir, Path(opts.user_c_modules), package_dir=package_dir)

    # [0086]/[0087]: `embedded_base` (`arm_embedded`/`riscv_embedded`
    # before [0096] merged them) no longer bakes a cross compiler --
    # fetch it at container time, same as `rp2`/`natmod`.
    # `qemu_toolchain()` returns `None` for `POWERNV9`
    # (`powerpc64le-linux-gnu-`), whose own `ppc64le_linux` image still
    # bakes its toolchain (record 0025, untouched) -- run exactly as
    # before for that one.
    resolved = targets.qemu_toolchain(opts.tag, cross)
    if resolved is None:
        command = make_command
    else:
        _, version = resolved
        toolchain_dir, fetch = toolchain_fetch.resolve_toolchain(
            cross, version, root=toolchain_root
        )
        script = (
            f"{fetch}"
            f'export PATH="{(toolchain_dir / "bin").as_posix()}:$PATH"\n'
            f"{shlex.join(make_command)}\n"
        )
        command = ["bash", "-c", script]
        mounts = [*mounts, toolchain_dir.parent]

    dockerrun.run(
        command,
        mounts=mounts,
        workdir=mpy_dir / "ports" / "qemu",
        image=docker_image,
        timeout=dockerrun.timeout_for("qemu", opts.board),
        # `linux/amd64`: a statement about the image, not about the build
        # target. qemu cross-compiles to bare metal, which no Linux
        # container is native to (0043) -- so on an arm64 host this runs
        # emulated, like `windows` and `webassembly` do.
        oci_platform=dockerrun.platform_for("qemu", opts.board),
    )

    firmware = opts.build_dir / "firmware.elf"
    if not firmware.exists():
        raise UsermodBuildError(
            f"qemu/{opts.board}: build reported success but {firmware} is missing"
        )
    return firmware

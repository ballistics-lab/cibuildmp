"""usermod build driver: `unix`, the first port covered under M8's own
scope ("ports that need no exotic provisioning first" -- docs/BACKLOG.md).
`ports/unix/Makefile` owns the actual compile (D2's "delegate the compile,
own the environment"), the same shape build.py already uses for natmod --
this module resolves per-arch settings and runs it, nothing more.

Only x64, x86 and aarch64 are runnable here: all three build with the
host's own gcc (x86 reusing toolchains.resolve()'s own -m32 multilib
probe, already built for natmod's identical "x86" arch), so nothing new
needs provisioning. armhf and mipsel need a genuinely new cross-toolchain
story -- arm-linux-gnueabihf-/mipsel-linux-gnu-, glibc-hosted, not
natmod's bare-metal arm-none-eabi-/riscv64-unknown-elf- pins -- plus a
static-link `deplibs` pre-step; their UnixArchSettings are pinned below
(transcribed from .github/actions/build-usermod-unix/action.yml's own
case statement and cross-checked against a real v1.28.0
ports/unix/Makefile directly, not just that action's comments) so the
data is ready when a toolchain resolver for them exists, but build_unix()
raises rather than pretending to build them today.

`qemu` (armv7m) is the second port here: `ports/qemu/Makefile`'s own
`CROSS_COMPILE ?= arm-none-eabi-` for its default board (`MPS2_AN385`,
Cortex-M3) is the exact toolchain natmod's own `armv7m` arch already
resolves (`toolchains.resolve("armv7m")`) -- reused rather than pinning it
a second time. Only `MPS2_AN385` is supported: `ports/qemu` also has
RISC-V boards (`CROSS_COMPILE ?= riscv64-unknown-elf-`, natmod's own
`rv32imc`/`rv64imc` toolchain), a real, cheap-to-add extension later, not
attempted now since nothing here exercises it yet.

`windows`/`webassembly` are M8's own remaining scope, not started.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .. import toolchains
from ..toolchains import ResolvedToolchain


class UsermodBuildError(Exception):
    pass


@dataclass(frozen=True)
class UnixArchSettings:
    cross_compile: str = ""
    link_opts: tuple[str, ...] = ()
    standalone: bool = False


# CROSS_COMPILE, MICROPY_FORCE_32BIT and MICROPY_STANDALONE are
# ports/unix/Makefile's own variables, verified directly against a real
# v1.28.0 checkout -- not this project's or the composite action's
# invention.
UNIX_ARCH_SETTINGS: dict[str, UnixArchSettings] = {
    "x64": UnixArchSettings(),
    "aarch64": UnixArchSettings(),
    "x86": UnixArchSettings(link_opts=("MICROPY_FORCE_32BIT=1",)),
    "armhf": UnixArchSettings(
        cross_compile="arm-linux-gnueabihf-",
        link_opts=("MICROPY_STANDALONE=1", "LDFLAGS_EXTRA=-static"),
        standalone=True,
    ),
    "mipsel": UnixArchSettings(
        cross_compile="mipsel-linux-gnu-",
        link_opts=("MICROPY_STANDALONE=1", "LDFLAGS_EXTRA=-static"),
        standalone=True,
    ),
}

_RUNNABLE_ARCHS = ("x64", "x86", "aarch64")


@dataclass(frozen=True)
class UnixBuildOptions:
    arch: str
    user_c_modules: str
    frozen_manifest: str
    build_dir: Path
    variant: str = "standard"
    extra_make_args: tuple[str, ...] = ()


def _unix_dir(mpy_dir: Path) -> Path:
    return mpy_dir / "ports" / "unix"


def unix_make_command(opts: UnixBuildOptions, mpy_dir: Path) -> list[str]:
    settings = UNIX_ARCH_SETTINGS[opts.arch]
    return [
        "make",
        "-C",
        str(_unix_dir(mpy_dir)),
        f"VARIANT={opts.variant}",
        f"BUILD={opts.build_dir}",
        f"CROSS_COMPILE={settings.cross_compile}",
        *settings.link_opts,
        f"USER_C_MODULES={opts.user_c_modules}",
        f"FROZEN_MANIFEST={opts.frozen_manifest}",
        *opts.extra_make_args,
    ]


def run_unix_deplibs(opts: UnixBuildOptions, mpy_dir: Path) -> None:
    """MICROPY_STANDALONE=1 only makes libffi a DEPLIBS entry, not a
    prerequisite of the default build target -- must run as its own step
    first, same as build-usermod-unix's own "Build libffi (deplibs)" step.
    BUILD must match the main build's BUILD=: deplibs writes libffi.a
    under $(BUILD)/lib/libffi/out/lib/ and the main build looks for it
    there.
    """
    settings = UNIX_ARCH_SETTINGS[opts.arch]
    command = [
        "make",
        "-C",
        str(_unix_dir(mpy_dir)),
        f"VARIANT={opts.variant}",
        f"BUILD={opts.build_dir}",
        f"CROSS_COMPILE={settings.cross_compile}",
        "MICROPY_STANDALONE=1",
        "deplibs",
    ]
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        raise UsermodBuildError(f"unix/{opts.arch}: deplibs failed: {exc}") from exc


def build_unix(
    opts: UnixBuildOptions,
    mpy_dir: Path,
    *,
    toolchain_root: Path | None = None,
    quiet: bool = False,
) -> Path:
    """Build ports/unix for `opts.arch`, returning the produced binary.

    mpy-cross itself is not built here -- sources.build_mpy_cross() already
    does that, shared with natmod (both need the same mpy-cross for the
    same mpy_dir); call it first.

    The output path is `opts.build_dir / "micropython"` --
    ports/unix/Makefile's own `PROG ?= micropython` default, unambiguous
    with no globbing needed, unlike natmod's build.collect_output().
    """
    if opts.arch not in UNIX_ARCH_SETTINGS:
        raise UsermodBuildError(
            f"unknown unix arch {opts.arch!r}. Known: "
            f"{', '.join(sorted(UNIX_ARCH_SETTINGS))}"
        )
    if opts.arch not in _RUNNABLE_ARCHS:
        settings = UNIX_ARCH_SETTINGS[opts.arch]
        raise UsermodBuildError(
            f"unix/{opts.arch}: not buildable yet -- needs a "
            f"{settings.cross_compile!r} cross-toolchain this project does "
            f"not resolve yet (M8 covers x64/x86/aarch64 only so far; see "
            f"docs/BACKLOG.md M8)"
        )
    if opts.arch == "x86":
        # "x86" means exactly the same thing here as it does for natmod --
        # the host gcc's own -m32 multilib runtime, not a separate cross
        # toolchain -- so this reuses natmod's own probe rather than
        # re-implementing it. Raises ToolchainError, left unwrapped: the
        # caller already handles that alongside BuildError/SourceError the
        # same way natmod's own cli.main() does.
        toolchains.resolve("x86", root=toolchain_root, quiet=quiet)

    if UNIX_ARCH_SETTINGS[opts.arch].standalone:
        run_unix_deplibs(opts, mpy_dir)

    command = unix_make_command(opts, mpy_dir)
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        raise UsermodBuildError(
            f"unix/{opts.arch}: `{' '.join(command)}` failed with exit code "
            f"{exc.returncode}"
        ) from exc

    binary = opts.build_dir / "micropython"
    if not binary.exists():
        raise UsermodBuildError(
            f"unix/{opts.arch}: build reported success but {binary} is missing"
        )
    return binary


# ── qemu (armv7m) ────────────────────────────────────────────────────────

_QEMU_SUPPORTED_BOARDS = ("MPS2_AN385",)


@dataclass(frozen=True)
class QemuBuildOptions:
    user_c_modules: str
    frozen_manifest: str
    build_dir: Path
    board: str = "MPS2_AN385"
    extra_make_args: tuple[str, ...] = ()


def qemu_make_command(
    opts: QemuBuildOptions, mpy_dir: Path, chain: ResolvedToolchain
) -> list[str]:
    # ports/qemu/Makefile uses CROSS_COMPILE=, not natmod's own CROSS= --
    # ResolvedToolchain.make_overrides is dynruntime.mk-specific (that
    # variable name), so this builds its own override from chain.prefix
    # instead of reusing it. Always passed explicitly rather than relying
    # on the Makefile's own `CROSS_COMPILE ?= arm-none-eabi-` default
    # coinciding with it -- harmless when they already match, and correct
    # when resolve() ever returns a different working prefix.
    return [
        "make",
        "-C",
        str(mpy_dir / "ports" / "qemu"),
        f"BOARD={opts.board}",
        f"BUILD={opts.build_dir}",
        f"CROSS_COMPILE={chain.prefix}",
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
) -> Path:
    """Build ports/qemu for `opts.board`, returning the produced firmware.

    The toolchain is natmod's own `armv7m` (`arm-none-eabi-`) --
    `ports/qemu/Makefile`'s default-board `CROSS_COMPILE` is exactly that
    prefix, so this resolves it via `toolchains.resolve("armv7m")` rather
    than pinning a second copy. Only `MPS2_AN385` is supported today; see
    this module's own docstring for why the RISC-V boards are not.

    The output path is `opts.build_dir / "firmware.elf"` --
    ports/qemu/Makefile's own `all: $(BUILD)/firmware.elf` target, again
    no globbing needed.
    """
    if opts.board not in _QEMU_SUPPORTED_BOARDS:
        raise UsermodBuildError(
            f"qemu board {opts.board!r} not supported yet. Known: "
            f"{', '.join(_QEMU_SUPPORTED_BOARDS)} (see this module's own "
            f"docstring for why the RISC-V boards are not)"
        )

    chain = toolchains.resolve("armv7m", root=toolchain_root, quiet=quiet)

    command = qemu_make_command(opts, mpy_dir, chain)
    try:
        subprocess.run(command, env=chain.env(), check=True)
    except subprocess.CalledProcessError as exc:
        raise UsermodBuildError(
            f"qemu/{opts.board}: `{' '.join(command)}` failed with exit "
            f"code {exc.returncode}"
        ) from exc

    firmware = opts.build_dir / "firmware.elf"
    if not firmware.exists():
        raise UsermodBuildError(
            f"qemu/{opts.board}: build reported success but {firmware} is missing"
        )
    return firmware

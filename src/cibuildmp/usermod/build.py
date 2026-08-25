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

`webassembly` is the third port here: its toolchain (`emsdk`) needs its
own resolver, `usermod/emsdk.py` -- not `toolchains.py`'s shape, see that
module's own docstring for why.

`esp32` (**D19**) is the fourth port: its toolchain (ESP-IDF) is a whole
environment, not one `<prefix>gcc` -- `usermod/espidf.py` is its own
resolver, the same split `emsdk.py` already uses for `webassembly`. Not
part of **M8**'s original port list (`unix`/`webassembly`/`qemu`/
`windows`) -- added alongside **M9**'s own ESP-IDF provisioning work,
since a resolver with nothing driving a build through it proves less than
one that does.

`windows` is **M8**'s own remaining scope, not started (waits on **M9**'s
MSYS2 orchestration, **D18**).

Every `Path` embedded into a `make` command line here goes through
`.as_posix()`, never a bare `str()`: a real `usermod-dev.yml` run on
`windows-latest` caught this -- `str(WindowsPath(...))` produces
backslashes, and GNU Make (native or MSYS2) wants forward slashes
regardless of host OS. The exact class of bug **D18** already documented
for `a7p`'s own hand-written workflow (`$GITHUB_WORKSPACE`'s own native
Windows form, mangled by MSYS2 bash's own backslash-escaping), just
caught here before it shipped instead of after.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .. import toolchains
from ..toolchains import ResolvedToolchain
from . import emsdk, espidf


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
        _unix_dir(mpy_dir).as_posix(),
        f"VARIANT={opts.variant}",
        f"BUILD={opts.build_dir.as_posix()}",
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
        _unix_dir(mpy_dir).as_posix(),
        f"VARIANT={opts.variant}",
        f"BUILD={opts.build_dir.as_posix()}",
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
        (mpy_dir / "ports" / "qemu").as_posix(),
        f"BOARD={opts.board}",
        f"BUILD={opts.build_dir.as_posix()}",
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


# ── webassembly ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WebassemblyBuildOptions:
    user_c_modules: str
    frozen_manifest: str
    build_dir: Path
    variant: str = "pyscript"
    extra_make_args: tuple[str, ...] = ()


def webassembly_make_command(opts: WebassemblyBuildOptions, mpy_dir: Path) -> list[str]:
    return [
        "make",
        "-C",
        (mpy_dir / "ports" / "webassembly").as_posix(),
        f"VARIANT={opts.variant}",
        f"BUILD={opts.build_dir.as_posix()}",
        f"USER_C_MODULES={opts.user_c_modules}",
        f"FROZEN_MANIFEST={opts.frozen_manifest}",
        *opts.extra_make_args,
    ]


def build_webassembly(
    opts: WebassemblyBuildOptions,
    mpy_dir: Path,
    *,
    toolchain_root: Path | None = None,
    quiet: bool = False,
) -> Path:
    """Build ports/webassembly for `opts.variant`, returning the produced
    `micropython.mjs`.

    emsdk is resolved via `emsdk.resolve_emsdk()` -- a pinned download,
    not a `git clone emsdk` + installer run; see `usermod/emsdk.py`'s own
    docstring and `resources/usermod.toml`'s `[emsdk]` table for why this
    needs its own resolver rather than `toolchains.resolve()`.

    The output path is `opts.build_dir / "micropython.mjs"` --
    `ports/webassembly/Makefile`'s own `all:` target.
    """
    sdk = emsdk.resolve_emsdk(root=toolchain_root, quiet=quiet)

    command = webassembly_make_command(opts, mpy_dir)
    try:
        subprocess.run(command, env=sdk.env(), check=True)
    except subprocess.CalledProcessError as exc:
        raise UsermodBuildError(
            f"webassembly/{opts.variant}: `{' '.join(command)}` failed "
            f"with exit code {exc.returncode}"
        ) from exc

    produced = opts.build_dir / "micropython.mjs"
    if not produced.exists():
        raise UsermodBuildError(
            f"webassembly/{opts.variant}: build reported success but "
            f"{produced} is missing"
        )
    return produced


# ── esp32 ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Esp32BuildOptions:
    user_c_modules: str
    frozen_manifest: str
    board: str = "ESP32_GENERIC"
    idf_target: str = "esp32"
    idf_version: str = "v5.5.1"
    extra_make_args: tuple[str, ...] = ()


def esp32_make_command(opts: Esp32BuildOptions, mpy_dir: Path) -> list[str]:
    # No BUILD= override, even resolving to the exact value the port
    # already defaults to: build-usermod-esp32's own comment documents a
    # real CI failure this causes -- passing BUILD= at all (not what it's
    # set to) makes the port's own internal CMake-driven mpy-cross
    # sub-build pick up FROZEN_MANIFEST through MAKEFLAGS and fail with
    # "undefined reference to mp_qstr_frozen_const_pool", a separate copy
    # of the same symptom build_mpy_cross() being called explicitly,
    # first, already prevents for the main mpy-cross build.
    return [
        "make",
        "-C",
        (mpy_dir / "ports" / "esp32").as_posix(),
        f"BOARD={opts.board}",
        f"USER_C_MODULES={opts.user_c_modules}",
        f"FROZEN_MANIFEST={opts.frozen_manifest}",
        *opts.extra_make_args,
    ]


def build_esp32(
    opts: Esp32BuildOptions,
    mpy_dir: Path,
    *,
    toolchain_root: Path | None = None,
    quiet: bool = False,
) -> Path:
    """Build ports/esp32 for `opts.board`, returning the produced
    `micropython.bin`.

    ESP-IDF is resolved via `espidf.resolve_esp_idf()` -- clone + tool
    install, both cached (D19's own real gap; the composite action this
    is modelled on has none) -- not Docker; see `usermod/espidf.py`'s own
    docstring for why.

    mpy-cross is not built here either: `sources.build_mpy_cross()`
    already does that, and must run *before* any ESP-IDF env is on
    PATH -- mpy-cross is a host tool, and has no business being built
    inside IDF's own Python/toolchain environment (same reasoning
    `build_unix`'s own module docstring gives for natmod's build.py).

    The output path is `mpy_dir / "ports" / "esp32" / "build-<BOARD>" /
    "micropython.bin"` -- the port's own unmodified default build
    directory, since nothing here overrides `BUILD=`.
    """
    idf = espidf.resolve_esp_idf(
        opts.idf_version, opts.idf_target, root=toolchain_root, quiet=quiet
    )

    command = esp32_make_command(opts, mpy_dir)
    try:
        subprocess.run(command, env=idf.env(), check=True)
    except subprocess.CalledProcessError as exc:
        raise UsermodBuildError(
            f"esp32/{opts.board}: `{' '.join(command)}` failed with exit "
            f"code {exc.returncode}"
        ) from exc

    firmware = mpy_dir / "ports" / "esp32" / f"build-{opts.board}" / "micropython.bin"
    if not firmware.exists():
        raise UsermodBuildError(
            f"esp32/{opts.board}: build reported success but {firmware} is missing"
        )
    return firmware

"""usermod build driver: `unix`, the first port covered under M8's own
scope ("ports that need no exotic provisioning first" -- docs/BACKLOG.md).
`ports/unix/Makefile` owns the actual compile (D2's "delegate the compile,
own the environment"), the same shape build.py already uses for natmod --
this module resolves per-arch settings and runs it, nothing more.

All five arches are runnable here now. x64/x86 build with the host's
own gcc (x86 reusing toolchains.resolve()'s own -m32 multilib probe,
already built for natmod's identical "x86" arch), so nothing new needs
provisioning. aarch64 cross-compiles from an x86_64 host via apt's own
gcc-aarch64-linux-gnu + libffi-dev:arm64 -- *not* "needs a native
ARM64 host" as first assumed: verified live on a real ubuntu-latest
runner (usermod-dev.yml's own now-removed unix-aarch64-cross-check
job) that a plain dynamically-linked libffi resolves via multiarch
once apt's own arm64 sources are pointed at ports.ubuntu.com (see the
CROSS_COMPILE assignment below for why that mirror step is needed at
all -- Ubuntu's default archive/security mirrors only carry
amd64/i386), producing a genuine linked ARM-aarch64 ELF with a real
custom C module built in. `action.Dockerfile` does not yet bake that
same mirror step or aarch64's toolchain into the image, so that one
target still fails inside the Docker action specifically -- a real,
separate, still-open gap (README's own usermod table footnote).

armhf and mipsel needed a genuinely new cross-toolchain story --
arm-linux-gnueabihf-/mipsel-linux-gnu-, glibc-hosted, not natmod's
bare-metal arm-none-eabi-/riscv64-unknown-elf- pins -- plus a
static-link `deplibs` pre-step (MICROPY_STANDALONE=1, a real, separate
libffi build under $(BUILD)/lib/libffi, not the dynamically-linked
apt package aarch64 uses). Both apt-provisioned, both verified live end
to end (a real custom C module, both `deplibs` and the main build run
for real, a genuine linked ARM/EABI5 and MIPS32 ELF each): apt install
gcc-arm-linux-gnueabihf/gcc-mipsel-linux-gnu is enough for the
cross-compiler itself, but deplibs' own `./autogen.sh` (regenerating
libffi's vendored `configure` via autoreconf) failed on a real
ubuntu-latest-equivalent host with "possibly undefined macro:
LT_SYS_SYMBOL_USCORE" until `libltdl-dev` was installed too --
autoconf/automake/libtool alone do not ship `ltdl.m4` at all; only
`libltdl-dev` does. Not obvious, not documented anywhere upstream this
was checked against, found only by actually running deplibs for real
rather than assuming the pinned settings alone were enough.

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

`windows` (**D18**) is the fifth and last port here: a plain Linux-hosted
cross-compile for all three arches this project covers (`x64`/`x86` via
an apt-installed mingw-w64 GCC, `arm64` via a downloaded `llvm-mingw`
toolchain -- `usermod/llvmmingw.py`, since no Linux distro packages a GCC
targeting `aarch64-w64-mingw32` at all), no Windows host or MSYS2 needed
for any of them. This is **not** what `a7p`'s own `mp-usermod.yml` does
(it runs MSYS2 on `windows-latest` for all three arches, and two earlier
versions of this port matched that -- first for all three, then just for
`arm64` once `x64`/`x86` were confirmed to cross-compile more simply)
-- both superseded after live-verifying real alternatives: upstream
MicroPython's own CI cross-compiles `x64`/`x86` from Linux too
(`.github/workflows/ports_windows.yml`'s own `cross-build-on-linux` job),
and mingw-w64's own documentation names `llvm-mingw` as the one toolchain
that both targets ARM64 Windows and runs as a Linux-hosted cross
compiler. It is the exact same `ports/windows/Makefile` MSYS2 runs either
way -- `USER_C_MODULES`/`FROZEN_MANIFEST` work identically, confirmed
live with a real custom C module linked into a genuine `micropython.exe`
for all three arches (x64, x86, arm64/PE32+ Aarch64). See
docs/BACKLOG.md's D18 for the full MSVC-then-MSYS2-then-cross-compile
history, including the three Clang-specific `CFLAGS_EXTRA` suppressions
`arm64` alone needs and why each earlier conclusion was corrected rather
than silently replaced.

Every `Path` embedded into a `make` command line here goes through
`.as_posix()`, never a bare `str()`: a real `usermod-dev.yml` run on
`windows-latest`, back when this port still ran under MSYS2, caught this
-- `str(WindowsPath(...))` produces backslashes, and GNU Make wants
forward slashes regardless of host OS. Kept as the rule for every port
here, not just the one that surfaced it.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .. import toolchains
from ..toolchains import ResolvedToolchain
from . import emsdk, espidf, llvmmingw


class UsermodBuildError(Exception):
    pass


@dataclass(frozen=True)
class UnixArchSettings:
    cross_compile: str = ""
    link_opts: tuple[str, ...] = ()
    standalone: bool = False
    apt_package: str = ""


# CROSS_COMPILE, MICROPY_FORCE_32BIT and MICROPY_STANDALONE are
# ports/unix/Makefile's own variables, verified directly against a real
# v1.28.0 checkout -- not this project's or the composite action's
# invention.
#
# aarch64's cross_compile/apt_package: verified live end-to-end on a real
# ubuntu-latest runner -- gcc-aarch64-linux-gnu + libffi-dev:arm64 (once
# apt's own arm64 sources point at ports.ubuntu.com, not the default
# amd64-only mirror) cross-compile ports/unix from x86_64 straight to a
# dynamically-linked ARM aarch64 ELF, no deplibs/static-link step needed
# the way armhf/mipsel below require. No toolchain resolver checks this
# one in build_unix() (unlike x86's toolchains.resolve() call) because
# apt, not a downloaded tarball, is what provisions it -- the same
# shutil.which()-plus-named-package pattern build_windows() already uses
# for its own apt-provisioned x64/x86 arches covers it instead.
UNIX_ARCH_SETTINGS: dict[str, UnixArchSettings] = {
    "x64": UnixArchSettings(),
    "aarch64": UnixArchSettings(
        cross_compile="aarch64-linux-gnu-",
        apt_package="gcc-aarch64-linux-gnu libffi-dev:arm64",
    ),
    "x86": UnixArchSettings(link_opts=("MICROPY_FORCE_32BIT=1",)),
    "armhf": UnixArchSettings(
        cross_compile="arm-linux-gnueabihf-",
        link_opts=("MICROPY_STANDALONE=1", "LDFLAGS_EXTRA=-static"),
        standalone=True,
        # libltdl-dev: not the cross-compiler itself -- deplibs' own
        # ./autogen.sh (regenerating vendored libffi's configure via
        # autoreconf) fails on a real host with "possibly undefined
        # macro: LT_SYS_SYMBOL_USCORE" without it. autoconf/automake/
        # libtool alone do not ship ltdl.m4; verified live, the hard way.
        apt_package="gcc-arm-linux-gnueabihf libltdl-dev",
    ),
    "mipsel": UnixArchSettings(
        cross_compile="mipsel-linux-gnu-",
        link_opts=("MICROPY_STANDALONE=1", "LDFLAGS_EXTRA=-static"),
        standalone=True,
        apt_package="gcc-mipsel-linux-gnu libltdl-dev",
    ),
}

UNIX_RUNNABLE_ARCHS = ("x64", "x86", "aarch64", "armhf", "mipsel")


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


def run_unix_deplibs(
    opts: UnixBuildOptions, mpy_dir: Path, *, docker_image: str | None = None
) -> None:
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
    if docker_image is not None:
        from . import dockerrun

        dockerrun.run(
            command,
            mounts=[mpy_dir, Path(opts.user_c_modules)],
            workdir=_unix_dir(mpy_dir),
            image=docker_image,
        )
        return
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

    D26's own proof-of-concept: if CIBMP_UNIX_DOCKER_IMAGE is set, the
    actual make/deplibs commands run inside that image as a sibling
    container instead of directly on this host -- see
    usermod/dockerrun.py's own docstring. The host-side toolchain probe
    below is skipped in that case: the toolchain lives inside the image,
    not on this host's PATH, so shutil.which() would reject a perfectly
    good docker-based build. Opt-in only, not reachable from the CLI or
    action.yml yet.
    """
    if opts.arch not in UNIX_ARCH_SETTINGS:
        raise UsermodBuildError(
            f"unknown unix arch {opts.arch!r}. Known: "
            f"{', '.join(sorted(UNIX_ARCH_SETTINGS))}"
        )

    from . import dockerrun

    docker_image = dockerrun.image_for_port("unix")

    if docker_image is None:
        if opts.arch == "x86":
            # "x86" means exactly the same thing here as it does for
            # natmod -- the host gcc's own -m32 multilib runtime, not a
            # separate cross toolchain -- so this reuses natmod's own
            # probe rather than re-implementing it. Raises ToolchainError,
            # left unwrapped: the caller already handles that alongside
            # BuildError/SourceError the same way natmod's own cli.main()
            # does.
            toolchains.resolve("x86", root=toolchain_root, quiet=quiet)
        elif opts.arch != "x64":
            # Every other arch (aarch64/armhf/mipsel) is apt-provisioned,
            # not a downloaded tarball -- toolchains.resolve() doesn't fit
            # (nothing to download or cache), so this is the same
            # shutil.which()-plus-named-package probe build_windows()
            # already uses for its own apt-provisioned x64/x86 arches.
            # Only checks the cross-compiler itself: armhf/mipsel's own
            # extra host dependency (libltdl-dev, for deplibs' autoreconf
            # step -- this module's own docstring has the story) has no
            # equivalent shutil.which() check, the same way
            # windows/arm64's llvm-mingw download isn't pre-validated
            # piece by piece either.
            settings = UNIX_ARCH_SETTINGS[opts.arch]
            gcc = shutil.which(f"{settings.cross_compile}gcc")
            if gcc is None:
                raise UsermodBuildError(
                    f"unix/{opts.arch}: {settings.cross_compile}gcc is not "
                    f"on PATH. Install it with: apt install "
                    f"{settings.apt_package}"
                )

    if UNIX_ARCH_SETTINGS[opts.arch].standalone:
        run_unix_deplibs(opts, mpy_dir, docker_image=docker_image)

    command = unix_make_command(opts, mpy_dir)
    if docker_image is not None:
        dockerrun.run(
            command,
            mounts=[mpy_dir, Path(opts.user_c_modules)],
            workdir=_unix_dir(mpy_dir),
            image=docker_image,
        )
    else:
        try:
            subprocess.run(command, check=True)
        except subprocess.CalledProcessError as exc:
            raise UsermodBuildError(
                f"unix/{opts.arch}: `{' '.join(command)}` failed with exit "
                f"code {exc.returncode}"
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


# ── windows ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WindowsArchSettings:
    cross_compile: str
    # Empty means "no apt package -- resolved via llvm-mingw instead",
    # arm64's own case (see resolve_windows_toolchain()).
    apt_package: str = ""
    # Clang-specific diagnostics MicroPython's own C wasn't written to
    # satisfy under -Werror -- empty for the GCC-based x64/x86 arches,
    # which need none. See resources/usermod.toml's own [llvm-mingw]
    # table for exactly which and why, verified live rather than guessed.
    extra_cflags: str = ""
    # COMPILER_TARGET=/STRIP=/SIZE= -- the same overrides MSYS2's own
    # CLANGARM64 environment already needed (D18's own history): this
    # clang's -dumpmachine doesn't contain "mingw" either, which
    # ports/windows/Makefile's own .exe-suffix and post-link strip logic
    # both grep for. Empty for x64/x86 -- a plain GNU cross-gcc needs none.
    extra_make_args: tuple[str, ...] = ()


# CROSS_COMPILE prefixes for each Windows arch this project builds, and how
# each toolchain is resolved. x64/x86: the same apt packages upstream's own
# tools/ci.sh (ci_windows_setup/ci_windows_build) and
# .github/workflows/ports_windows.yml's own cross-build-on-linux job use --
# like unix's own x86 (toolchains.py's own "cannot provision itself" case),
# ordinary Debian/Ubuntu packages, not something with a standalone tarball
# worth pinning separately. arm64: Debian/Ubuntu ship no
# aarch64-w64-mingw32 GCC target at all -- llvm-mingw (usermod/llvmmingw.py)
# is the one Linux-hosted alternative mingw-w64's own docs point at by
# name, verified live with a real custom C module producing a genuine
# PE32+ Aarch64 micropython.exe.
WINDOWS_ARCH_SETTINGS: dict[str, WindowsArchSettings] = {
    "x64": WindowsArchSettings(
        "x86_64-w64-mingw32-", apt_package="gcc-mingw-w64-x86-64"
    ),
    "x86": WindowsArchSettings("i686-w64-mingw32-", apt_package="gcc-mingw-w64-i686"),
    "arm64": WindowsArchSettings(
        "aarch64-w64-mingw32-",
        extra_cflags=(
            "-Wno-double-promotion -Wno-uninitialized "
            "-Wno-default-const-init-var-unsafe"
        ),
        extra_make_args=("COMPILER_TARGET=mingw-forced", "STRIP=", "SIZE=true"),
    ),
}


@dataclass(frozen=True)
class WindowsBuildOptions:
    arch: str
    user_c_modules: str
    frozen_manifest: str
    build_dir: Path
    variant: str = "standard"
    extra_make_args: tuple[str, ...] = ()


def _windows_dir(mpy_dir: Path) -> Path:
    return mpy_dir / "ports" / "windows"


def windows_make_command(opts: WindowsBuildOptions, mpy_dir: Path) -> list[str]:
    settings = WINDOWS_ARCH_SETTINGS[opts.arch]
    command = [
        "make",
        "-C",
        _windows_dir(mpy_dir).as_posix(),
        f"VARIANT={opts.variant}",
        f"BUILD={opts.build_dir.as_posix()}",
        f"CROSS_COMPILE={settings.cross_compile}",
        *settings.extra_make_args,
    ]
    if settings.extra_cflags:
        command.append(f"CFLAGS_EXTRA={settings.extra_cflags}")
    command += [
        f"USER_C_MODULES={opts.user_c_modules}",
        f"FROZEN_MANIFEST={opts.frozen_manifest}",
        *opts.extra_make_args,
    ]
    return command


def build_windows(
    opts: WindowsBuildOptions,
    mpy_dir: Path,
    *,
    toolchain_root: Path | None = None,
    quiet: bool = False,
) -> Path:
    """Build ports/windows for `opts.arch`, returning the produced `.exe`.

    A plain Linux-hosted cross-compile for all three arches this project
    covers, not MSYS2: verified live against a real v1.28.0 checkout --
    x64/x86 with an apt-installed GCC (matching upstream's own
    cross-build-on-linux CI job exactly, tools/ci.sh's ci_windows_build),
    arm64 with a downloaded llvm-mingw toolchain (usermod/llvmmingw.py --
    no Linux distro packages a GCC targeting aarch64-w64-mingw32 at all).
    Each produced a genuine micropython.exe with a real USER_C_MODULES's
    own symbols confirmed present via `strings`. It is the exact same
    ports/windows/Makefile MSYS2 runs either way, just invoked with
    CROSS_COMPILE=<prefix>- like every other cross-compiled port here
    (unix's x86/armhf, qemu) instead of running inside an MSYS2 shell --
    superseded MSYS2 for all three arches this project builds (D18's own
    backlog entry has the full three-stage history: MSVC ruled out first,
    then MSYS2 for all arches, then this). MSYS2 stays a real option for
    an arch this project doesn't cover yet outside these three.

    mpy-cross is not built here either, same as every other port:
    it is a host tool (freezes the manifest at build time, is not part of
    the target binary), so it needs no cross-compiling at all --
    sources.build_mpy_cross() already builds a native one, shared with
    every other port.

    The output path is `opts.build_dir / "micropython.exe"` --
    ports/windows/Makefile's own `PROG ?= micropython` plus the `.exe`
    suffix `py/mkrules.mk` appends for this port specifically.
    """
    if opts.arch not in WINDOWS_ARCH_SETTINGS:
        raise UsermodBuildError(
            f"unknown windows arch {opts.arch!r}. Known: "
            f"{', '.join(sorted(WINDOWS_ARCH_SETTINGS))}"
        )
    settings = WINDOWS_ARCH_SETTINGS[opts.arch]

    env = None
    if opts.arch == "arm64":
        toolchain = llvmmingw.resolve_llvm_mingw(root=toolchain_root, quiet=quiet)
        env = toolchain.env()
    else:
        gcc = shutil.which(f"{settings.cross_compile}gcc")
        if gcc is None:
            raise UsermodBuildError(
                f"windows/{opts.arch}: {settings.cross_compile}gcc is not on "
                f"PATH. Install it with: apt install {settings.apt_package}"
            )

    command = windows_make_command(opts, mpy_dir)
    try:
        subprocess.run(command, env=env, check=True)
    except subprocess.CalledProcessError as exc:
        raise UsermodBuildError(
            f"windows/{opts.arch}: `{' '.join(command)}` failed with exit "
            f"code {exc.returncode}"
        ) from exc

    binary = opts.build_dir / "micropython.exe"
    if not binary.exists():
        raise UsermodBuildError(
            f"windows/{opts.arch}: build reported success but {binary} is missing"
        )
    return binary

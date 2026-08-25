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

`qemu` (armv7m, riscv32, riscv64) is the second port here:
`ports/qemu/Makefile`'s own default-board `CROSS_COMPILE ?=
arm-none-eabi-` (`MPS2_AN385`, Cortex-M3) is the exact toolchain natmod's
own `armv7m` arch already resolves -- reused rather than pinning it a
second time. `ports/qemu` also has RISC-V boards, `VIRT_RV32`/`VIRT_RV64`
(`CROSS_COMPILE ?= riscv64-unknown-elf-`, natmod's own `rv32imc`/
`rv64imc` toolchain) -- `QEMU_BOARD_TOOLCHAIN` below resolves whichever
one `opts.board` names. `MPS2_AN385` stays the only board `qemu`'s own
axis defaults to (targets.py's own `_PORT_AXES`); the RISC-V boards are
selectable via `[usermod.qemu] boards = [...]`, not defaulted to, the
same "default = everything actually proven at the time it became the
default" rule `unix`/`esp32` already follow for their own axes.

`webassembly` is the third port here: its toolchain (`emsdk`) needs its
own resolver, `usermod/emsdk.py` -- not `toolchains.py`'s shape, see that
module's own docstring for why. `build_webassembly()` itself is
Docker-only (docs/BACKLOG.md's D30): `emsdk.py`'s resolver now only pins
what the packaged `webassembly.Dockerfile` bakes in at image-build time,
not something a build invokes directly.

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
from . import espidf, llvmmingw


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
#
# No apt_package field any more (D30: usermod is Docker-only,
# build_unix() never probes a host toolchain, so nothing ever reads it
# programmatically) -- what each arch's own image installs is
# documented in docker/unix-manylinux-<arch>.Dockerfile and, where the
# reasoning is non-obvious, in this dict's own per-arch comments
# (armhf/mipsel's own libltdl-dev note below) instead of a second,
# code-adjacent copy.
#
# aarch64's cross_compile: verified live end-to-end on a real
# ubuntu-latest runner -- gcc-aarch64-linux-gnu + libffi-dev:arm64 (once
# apt's own arm64 sources point at ports.ubuntu.com, not the default
# amd64-only mirror) cross-compile ports/unix from x86_64 straight to a
# dynamically-linked ARM aarch64 ELF, no deplibs/static-link step needed
# the way armhf/mipsel below require.
# Order is significant, not just alphabetical/historical -- targets.py's
# own _PORT_AXES derives UNIX_RUNNABLE_ARCHS's build/display order from
# these keys (dict order is insertion order in Python), so reordering
# this literal reorders every --dry-run plan and default build sequence
# for unix too.
UNIX_ARCH_SETTINGS: dict[str, UnixArchSettings] = {
    "x64": UnixArchSettings(),
    "x86": UnixArchSettings(link_opts=("MICROPY_FORCE_32BIT=1",)),
    "aarch64": UnixArchSettings(cross_compile="aarch64-linux-gnu-"),
    "armhf": UnixArchSettings(
        cross_compile="arm-linux-gnueabihf-",
        link_opts=("MICROPY_STANDALONE=1", "LDFLAGS_EXTRA=-static"),
        standalone=True,
        # libltdl-dev (docker/unix-manylinux-armhf.Dockerfile's own apt
        # list): not the cross-compiler itself -- deplibs' own
        # ./autogen.sh (regenerating vendored libffi's configure via
        # autoreconf) fails with "possibly undefined macro:
        # LT_SYS_SYMBOL_USCORE" without it. autoconf/automake/libtool
        # alone do not ship ltdl.m4; verified live, the hard way.
    ),
    "mipsel": UnixArchSettings(
        cross_compile="mipsel-linux-gnu-",
        link_opts=("MICROPY_STANDALONE=1", "LDFLAGS_EXTRA=-static"),
        standalone=True,
    ),
}

# Derived, not hand-maintained separately -- every runnable unix arch is
# already a key of UNIX_ARCH_SETTINGS above, and the two silently drifting
# apart (an arch added to one but not the other) is a real failure mode a
# second, independently-typed tuple invites for no benefit.
UNIX_RUNNABLE_ARCHS = tuple(UNIX_ARCH_SETTINGS)


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


def run_unix_deplibs(opts: UnixBuildOptions, mpy_dir: Path, *, docker_image: str) -> None:
    """MICROPY_STANDALONE=1 only makes libffi a DEPLIBS entry, not a
    prerequisite of the default build target -- must run as its own step
    first, same as build-usermod-unix's own "Build libffi (deplibs)" step.
    BUILD must match the main build's BUILD=: deplibs writes libffi.a
    under $(BUILD)/lib/libffi/out/lib/ and the main build looks for it
    there.

    Docker-only (D30): `docker_image` is always real by the time this is
    called -- `build_unix()` itself raises before ever reaching here if
    `ensure_image()` returned `None`.
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
    from . import dockerrun

    dockerrun.run(
        command,
        mounts=[mpy_dir, Path(opts.user_c_modules)],
        workdir=_unix_dir(mpy_dir),
        image=docker_image,
        timeout=dockerrun.timeout_for("unix", opts.arch, "manylinux"),
    )


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

    Docker-only (D30's own later, superseding call: no non-Docker path
    for any usermod port, `unix`'s own long-grandfathered host
    cross-compile included -- a bare-host build means `apt-get
    install`ing arch-specific cross-toolchains onto whatever host runs
    it, a real, persistent mutation; a container is the actually
    non-mutating, deterministic, isolated choice, built once from a
    pinned Dockerfile and discarded per run). `dockerrun.ensure_image()`
    resolves an explicit `CIBMP_UNIX_<ARCH>_MANYLINUX_DOCKER_IMAGE`
    override or a `dockerrun.PORT_IMAGES`-registered, digest-pinned
    default published by `publish-docker-images.yml` -- cibuildmp itself
    never builds `docker/unix-manylinux-<arch>.Dockerfile` (see
    usermod/dockerrun.py's own docstring for why). Keyed by
    (port, arch, libc), not port alone (D31: unix's own five
    architectures do not share one image, and glibc/musl are a real
    runtime-compatibility axis a shared image would hide). "manylinux"
    is passed explicitly here, not a resolver-side default: it is
    `unix`'s only real libc option today (musllinux needs a real musl
    toolchain, D31, not built yet) -- once UnixBuildOptions grows a
    `libc` field for musllinux, that field replaces this literal, the
    resolver itself needs no change.

    `toolchain_root`/`quiet` are accepted only for the same call shape
    every `build_<port>()` shares (`orchestrate.py`'s `build_one()`
    passes them uniformly); neither is used on this Docker-only path.
    """
    if opts.arch not in UNIX_ARCH_SETTINGS:
        raise UsermodBuildError(
            f"unknown unix arch {opts.arch!r}. Known: "
            f"{', '.join(sorted(UNIX_ARCH_SETTINGS))}"
        )

    from . import dockerrun

    docker_image = dockerrun.ensure_image("unix", opts.arch, "manylinux")
    if docker_image is None:
        raise UsermodBuildError(
            f"unix/{opts.arch}: no Docker image registered for this "
            f"arch and usermod builds are Docker-only -- set "
            f"CIBMP_UNIX_{opts.arch.upper()}_MANYLINUX_DOCKER_IMAGE, or "
            f"wait for publish-docker-images.yml to publish one and "
            f"register it in dockerrun.PORT_IMAGES"
        )

    if UNIX_ARCH_SETTINGS[opts.arch].standalone:
        run_unix_deplibs(opts, mpy_dir, docker_image=docker_image)

    command = unix_make_command(opts, mpy_dir)
    dockerrun.run(
        command,
        mounts=[mpy_dir, Path(opts.user_c_modules)],
        workdir=_unix_dir(mpy_dir),
        image=docker_image,
        timeout=dockerrun.timeout_for("unix", opts.arch, "manylinux"),
    )

    binary = opts.build_dir / "micropython"
    if not binary.exists():
        raise UsermodBuildError(
            f"unix/{opts.arch}: build reported success but {binary} is missing"
        )
    return binary


# ── qemu (armv7m, riscv32, riscv64) ─────────────────────────────────────

# board -> the natmod arch whose toolchain (`toolchains.resolve()`) links
# it. VIRT_RV32/VIRT_RV64 both resolve to `riscv-none-elf` under the hood
# (natmod.toml pins the identical `cross = "riscv64-unknown-elf-"` for
# both rv32imc/rv64imc -- one multilib toolchain covers both -march/-mabi
# combinations), same as `ports/qemu/Makefile` itself: both boards'
# `CROSS_COMPILE ?= riscv64-unknown-elf-` defaults are the exact same
# string, verified directly against a real v1.28.0 checkout's own
# `boards/VIRT_RV32/mpconfigboard.mk`/`VIRT_RV64/mpconfigboard.mk`.
# Passing the arch-appropriate key to resolve() anyway (rv32imc for
# VIRT_RV32, rv64imc for VIRT_RV64) keeps this call's own intent legible
# and its error messages honest, even though either would work today.
QEMU_BOARD_TOOLCHAIN: dict[str, str] = {
    "MPS2_AN385": "armv7m",
    "VIRT_RV32": "rv32imc",
    "VIRT_RV64": "rv64imc",
}


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

    The toolchain is always one natmod already resolves -- `armv7m`
    (`arm-none-eabi-`) for `MPS2_AN385`, `rv32imc`/`rv64imc`
    (`riscv-none-elf`) for `VIRT_RV32`/`VIRT_RV64` -- via
    `QEMU_BOARD_TOOLCHAIN` above, rather than pinning a second copy of
    any of them.

    The output path is `opts.build_dir / "firmware.elf"` --
    ports/qemu/Makefile's own `all: $(BUILD)/firmware.elf` target, again
    no globbing needed.
    """
    toolchain_arch = QEMU_BOARD_TOOLCHAIN.get(opts.board)
    if toolchain_arch is None:
        raise UsermodBuildError(
            f"qemu board {opts.board!r} not supported yet. Known: "
            f"{', '.join(QEMU_BOARD_TOOLCHAIN)}"
        )

    chain = toolchains.resolve(toolchain_arch, root=toolchain_root, quiet=quiet)

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

    Docker-only (D30's own later call: no bare-host path for any usermod
    port, `unix` included). `dockerrun.ensure_image("webassembly")`
    resolves an explicit `CIBMP_WEBASSEMBLY_DOCKER_IMAGE` override or a
    `dockerrun.PORT_IMAGES`-registered, digest-pinned default published
    by `publish-docker-images.yml` -- cibuildmp itself never builds
    `docker/webassembly.Dockerfile` (see usermod/dockerrun.py's own
    docstring for why). emsdk itself is baked into that image
    (`usermod/emsdk.py`'s own resolver stays what pins/verifies the same
    download for the Dockerfile's own `RUN` step to match, not something
    a build invokes directly any more -- no `sdk.env()` to inject, the
    image's own `ENV PATH` already covers it). `toolchain_root`/`quiet`
    are accepted only for the same call shape every `build_<port>()`
    shares (`orchestrate.py`'s `build_one()` passes them uniformly);
    neither is used on this Docker-only path.

    The output path is `opts.build_dir / "micropython.mjs"` --
    `ports/webassembly/Makefile`'s own `all:` target.
    """
    from . import dockerrun

    docker_image = dockerrun.ensure_image("webassembly")
    if docker_image is None:
        raise UsermodBuildError(
            "webassembly: no Docker image registered for this port "
            "and usermod builds are Docker-only -- set "
            "CIBMP_WEBASSEMBLY_DOCKER_IMAGE, or wait for "
            "publish-docker-images.yml to publish one and register it in "
            "dockerrun.PORT_IMAGES"
        )

    command = webassembly_make_command(opts, mpy_dir)
    dockerrun.run(
        command,
        mounts=[mpy_dir, Path(opts.user_c_modules)],
        workdir=mpy_dir / "ports" / "webassembly",
        image=docker_image,
        timeout=dockerrun.timeout_for("webassembly"),
    )

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

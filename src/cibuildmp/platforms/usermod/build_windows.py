"""usermod build driver: `windows` (**D18**).

A plain Linux-hosted cross-compile for all three arches this project
covers (`x64`/`x86` via an apt-installed mingw-w64 GCC, `arm64` via a
pinned `llvm-mingw` toolchain, since no Linux distro packages a GCC
targeting `aarch64-w64-mingw32` at all), no Windows host or MSYS2 needed
for any of them -- all three baked into `docker/windows.Dockerfile` and
run there, never on the host (**D30**/**D32**). This is **not** what
`a7p`'s own `mp-usermod.yml` does (it runs MSYS2 on `windows-latest` for
all three arches, and two earlier versions of this port matched that --
first for all three, then just for `arm64` once `x64`/`x86` were
confirmed to cross-compile more simply) -- both superseded after
live-verifying real alternatives: upstream MicroPython's own CI
cross-compiles `x64`/`x86` from Linux too
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
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from . import build_common
from .build_common import UsermodBuildError, usermod_mounts


@dataclass(frozen=True)
class WindowsArchSettings:
    cross_compile: str
    # The COFF `Machine` value this arch's `micropython.exe` must carry,
    # checked by `verify_windows_output()`. `unix`'s own `elf` field is
    # the same idea for ELF, and exists for the same reason: point a
    # build at another architecture's toolchain and `make` succeeds,
    # `ld` succeeds, and the output is a working binary of the wrong
    # architecture filed under the right identifier.
    machine: int = 0
    # Clang-specific diagnostics MicroPython's own C wasn't written to
    # satisfy under -Werror -- empty for the GCC-based x64/x86 arches,
    # which need none. All three are load-bearing, not cosmetic, and were
    # found live rather than guessed: llvm-mingw's clang is strict about
    # things GCC (every other cross-compiler this project uses) is not.
    #   -Wno-double-promotion  py/binary.c's _Float16<->float union trick
    #                          reads as an implicit precision-increasing
    #                          promotion under Clang specifically.
    #   -Wno-uninitialized
    #   -Wno-default-const-init-var-unsafe
    #                          shared/runtime/gchelper_generic.c's own
    #                          `const register long x19 asm("x19")` idiom
    #                          (reading a callee-saved register an asm
    #                          stub already wrote) reads as "used
    #                          uninitialized" to Clang; GCC does not
    #                          apply this diagnosis to a bare asm-tied
    #                          register declaration the way Clang does.
    # (Migrated here from resources/usermod.toml's own [llvm-mingw]
    # table, deleted along with usermod/llvmmingw.py once windows went
    # Docker-only -- these are Make-level flags and belong with the rest
    # of them, not with a toolchain download pin.)
    extra_cflags: str = ""
    # COMPILER_TARGET=/STRIP=/SIZE= -- the same overrides MSYS2's own
    # CLANGARM64 environment already needed (D18's own history): this
    # clang's -dumpmachine doesn't contain "mingw" either, which
    # ports/windows/Makefile's own .exe-suffix and post-link strip logic
    # both grep for. Empty for win32/win_amd64 -- a plain GNU cross-gcc
    # needs none.
    extra_make_args: tuple[str, ...] = ()


# CROSS_COMPILE prefixes for each Windows arch this project builds, keyed
# by the real identifier's own arch component (win32/win_amd64/win_arm64,
# matching resources/build-platforms.toml -- the Python/PEP wheel-tag
# vocabulary the rest of the identifier scheme uses, not the bare
# x64/x86/arm64 names this dict used before the identifier scheme moved
# onto that vocabulary; a stale key here was rejecting every real windows
# build with "unknown windows arch 'win32'" until this was caught by a
# real CI run). All three now come from docker/windows.Dockerfile's own
# image, not from the host: win32/win_amd64 as the same apt mingw-w64 GCC
# packages upstream's own tools/ci.sh (ci_windows_setup/ci_windows_build)
# and .github/workflows/ports_windows.yml's own cross-build-on-linux job
# use, win_arm64 as a pinned llvm-mingw tarball baked into that same image (no
# Debian/Ubuntu package targets aarch64-w64-mingw32 at all -- llvm-mingw
# is the one Linux-hosted alternative mingw-w64's own docs point at by
# name, verified live with a real custom C module producing a genuine
# PE32+ Aarch64 micropython.exe).
#
# No apt_package field any more, same as UnixArchSettings above and for
# the same reason (D30: usermod is Docker-only, build_windows() never
# probes a host toolchain, so nothing ever reads it programmatically) --
# what this port's image installs is documented in
# docker/windows.Dockerfile instead of in a second, code-adjacent copy.
# That Dockerfile's own `ENV PATH` appends rather than prepends
# llvm-mingw's bin/, deliberately: it ships x86_64-/i686- wrapper names
# of its own that would otherwise shadow the apt GCC these two arches
# are pinned to. See its own comment -- the prefixes below are what
# depend on that ordering being right.
# COFF `Machine` values, from Microsoft's own PE format specification
# (`IMAGE_FILE_MACHINE_*` in winnt.h). Listed rather than derived: there
# is no relationship between a `CROSS_COMPILE` prefix and this number
# that could be computed, and three constants are cheaper to read than a
# mapping that pretends otherwise.
_IMAGE_FILE_MACHINE_I386 = 0x014C
_IMAGE_FILE_MACHINE_AMD64 = 0x8664
_IMAGE_FILE_MACHINE_ARM64 = 0xAA64

WINDOWS_ARCH_SETTINGS: dict[str, WindowsArchSettings] = {
    "win_amd64": WindowsArchSettings(
        "x86_64-w64-mingw32-", machine=_IMAGE_FILE_MACHINE_AMD64
    ),
    "win32": WindowsArchSettings("i686-w64-mingw32-", machine=_IMAGE_FILE_MACHINE_I386),
    "win_arm64": WindowsArchSettings(
        "aarch64-w64-mingw32-",
        machine=_IMAGE_FILE_MACHINE_ARM64,
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


def windows_make_command(
    opts: WindowsBuildOptions, mpy_dir: Path, *, mpy_cross: Path | None = None
) -> list[str]:
    settings = WINDOWS_ARCH_SETTINGS[opts.arch]
    command = [
        "make",
        "-C",
        _windows_dir(mpy_dir).as_posix(),
        f"VARIANT={opts.variant}",
        f"BUILD={opts.build_dir.as_posix()}",
        f"CROSS_COMPILE={settings.cross_compile}",
        # py/mkenv.mk's own `MICROPY_MPYCROSS` override. Passed for the
        # same reason `build_unix()` passes it, arrived at from the other
        # direction (record 0044): this image is amd64, so on an **arm64
        # host** the host-built mpy-cross is an arm64 binary that cannot
        # run inside it, and `py/mkrules.mk` runs mpy-cross *inside* the
        # container to compile FROZEN_MANIFEST. Without this, this port
        # works on an amd64 runner and nowhere else -- which is exactly
        # the host-dependence record 0043 exists to remove.
        *([f"MICROPY_MPYCROSS={mpy_cross.as_posix()}"] if mpy_cross else []),
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


def verify_windows_output(arch: str, binary: Path) -> None:
    """The PE header `ld` actually wrote must name the architecture this
    identifier claims -- `verify_unix_output()`'s counterpart for the
    `windows` port, and for the identical reason: point a build at
    another arch's toolchain and `make` succeeds, `ld` succeeds, and the
    output is a working binary of the wrong architecture filed under the
    right identifier. Until this existed `build_windows()` checked
    `binary.exists()` and nothing else, so a `CROSS_COMPILE=` that
    resolved to the host's own gcc would have produced a Linux ELF named
    `micropython.exe` and passed.

    PE puts the field three hops in, all of them little-endian
    regardless of target (unlike ELF, which encodes its own byte order):
    the DOS stub's `e_lfanew` at `0x3C` points at the `PE\0\0`
    signature, and the COFF header's 16-bit `Machine` follows it
    immediately. Read with `struct` rather than a PE library -- six bytes
    at two offsets, against `pefile` as a new dependency for a project
    that already declined to shell out to `auditwheel` for the ELF half.
    """
    expected = WINDOWS_ARCH_SETTINGS[arch].machine
    data = binary.read_bytes()
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise UsermodBuildError(
            f"windows/{arch}: {binary} has no DOS header -- it is not a PE "
            f"executable at all, whatever its name says"
        )
    (pe_offset,) = struct.unpack_from("<I", data, 0x3C)
    if len(data) < pe_offset + 6 or data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise UsermodBuildError(
            f"windows/{arch}: {binary} has a DOS header but no PE signature at "
            f"the offset it points to ({pe_offset:#x})"
        )
    (actual,) = struct.unpack_from("<H", data, pe_offset + 4)
    if actual != expected:
        raise UsermodBuildError(
            f"windows/{arch}: build reported success but {binary.name}'s COFF "
            f"header encodes machine {actual:#06x}, expected {expected:#06x} "
            f"-- the binary is not the architecture this identifier names"
        )


def build_windows(
    opts: WindowsBuildOptions,
    mpy_dir: Path,
    *,
    toolchain_root: Path | None = None,
    quiet: bool = False,
    package_dir: Path | None = None,
) -> Path:
    """Build ports/windows for `opts.arch`, returning the produced `.exe`.

    A plain Linux-hosted cross-compile for all three arches this project
    covers, not MSYS2: verified live against a real v1.28.0 checkout --
    x64/x86 with an apt-installed GCC (matching upstream's own
    cross-build-on-linux CI job exactly, tools/ci.sh's ci_windows_build),
    arm64 with an llvm-mingw toolchain (no Linux distro packages a GCC
    targeting aarch64-w64-mingw32 at all). Each produced a genuine
    micropython.exe with a real USER_C_MODULES's own symbols confirmed
    present via `strings`. It is the exact same ports/windows/Makefile
    MSYS2 runs either way, just invoked with CROSS_COMPILE=<prefix>- like
    every other cross-compiled port here (unix's x86/armhf, qemu) instead
    of running inside an MSYS2 shell -- superseded MSYS2 for all three
    arches this project builds (D18's own backlog entry has the full
    three-stage history: MSVC ruled out first, then MSYS2 for all arches,
    then this). MSYS2 stays a real option for an arch this project
    doesn't cover yet outside these three.

    Docker-only (D30), closing D32's own last named gap: `windows` was
    the port whose `PORT_IMAGES` entries were registered but dead code,
    since nothing here ever called `ensure_image()`. All three arches now
    run inside docker/windows.Dockerfile's own image, resolved through an
    explicit `CIBMP_WINDOWS_<ARCH>_DOCKER_IMAGE` override or a
    `dockerrun.PORT_IMAGES`-registered, digest-pinned default published by
    publish-docker-images.yml -- cibuildmp itself never builds that image
    (see usermod/dockerrun.py's own docstring for why). No `libc`
    argument, unlike build_unix(): D31's manylinux/musllinux axis is real
    for `unix` alone -- there is no second Windows libc a binary could be
    built against -- so all three arches key on (port, arch) only.

    The bare-host path this used to have is gone, both halves of it: the
    `shutil.which("<prefix>gcc")` probe with its "apt install ..." hint
    for x64/x86, and `llvmmingw.resolve_llvm_mingw()`'s own download-and-
    cache for arm64. That download was this port's last real reason to
    touch the host at all, and D30's mandate leaves no room for it --
    docker/windows.Dockerfile bakes the same pinned tarball in instead,
    exactly the way webassembly.Dockerfile already bakes emsdk, and is
    now the pin of record for it. `usermod/llvmmingw.py` and the
    `[llvm-mingw]` table it read were both deleted rather than left as
    uncalled scaffolding, along with `usermod/emsdk.py` and its own
    table for the identical reason.

    mpy-cross is not built here either, same as every other port:
    it is a host tool (freezes the manifest at build time, is not part of
    the target binary), so it needs no cross-compiling at all --
    sources.build_mpy_cross() already builds a native one, shared with
    every other port.

    `toolchain_root`/`quiet` are accepted only for the same call shape
    every `build_<port>()` shares (`orchestrate.py`'s `build_one()`
    passes them uniformly); neither is used on this Docker-only path --
    the same vestigial-but-uniform pair build_unix()/build_webassembly()
    already carry. `package_dir`, when given, is bind-mounted alongside
    `USER_C_MODULES` itself -- see `build_common.usermod_mounts()`.

    The output path is `opts.build_dir / "micropython.exe"` --
    ports/windows/Makefile's own `PROG ?= micropython` plus the `.exe`
    suffix `py/mkrules.mk` appends for this port specifically.
    """
    if opts.arch not in WINDOWS_ARCH_SETTINGS:
        raise UsermodBuildError(
            f"unknown windows arch {opts.arch!r}. Known: "
            f"{', '.join(sorted(WINDOWS_ARCH_SETTINGS))}"
        )

    from ... import dockerrun

    docker_image = dockerrun.ensure_image("windows", opts.arch)
    if docker_image is None:
        raise UsermodBuildError(
            f"windows/{opts.arch}: no Docker image registered for this "
            f"arch and usermod builds are Docker-only -- set "
            f"CIBMP_WINDOWS_{opts.arch.upper()}_DOCKER_IMAGE, or "
            f"wait for publish-docker-images.yml to publish one and "
            f"register it in dockerrun.PORT_IMAGES"
        )

    command = windows_make_command(
        opts,
        mpy_dir,
        mpy_cross=build_common.container_mpy_cross(
            mpy_dir,
            slug="windows",
            image=docker_image,
            oci_platform=dockerrun.platform_for("windows", opts.arch),
            timeout=dockerrun.timeout_for("windows", opts.arch),
        ),
    )
    dockerrun.run(
        command,
        mounts=usermod_mounts(mpy_dir, Path(opts.user_c_modules), package_dir=package_dir),
        workdir=_windows_dir(mpy_dir),
        image=docker_image,
        timeout=dockerrun.timeout_for("windows", opts.arch),
        # Same as webassembly's above (**0043**): an amd64 Linux
        # cross-compile host targeting Windows. All three arches share
        # one image (D42/D28 step 3), so all three share its platform.
        oci_platform=dockerrun.platform_for("windows", opts.arch),
    )

    binary = opts.build_dir / "micropython.exe"
    if not binary.exists():
        raise UsermodBuildError(
            f"windows/{opts.arch}: build reported success but {binary} is missing"
        )
    verify_windows_output(opts.arch, binary)
    return binary

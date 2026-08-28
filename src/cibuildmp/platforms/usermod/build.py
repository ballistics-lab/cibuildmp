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

`qemu` (nine real boards across three toolchains) is the second port
here: `ports/qemu/Makefile`'s own default-board `CROSS_COMPILE ?=
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

`webassembly` is the third port here: Docker-only (**D30**), with its
toolchain (`emsdk`) baked into `docker/webassembly.Dockerfile` at
image-build time. It used to have a host-side resolver of its own
(`usermod/emsdk.py`, not `toolchains.py`'s `<prefix>gcc` shape); that
went away with the bare-host path itself, and that Dockerfile is now the
pin of record.

`esp32` (**D19**) is the fourth port: its toolchain (ESP-IDF) is a whole
environment, not one `<prefix>gcc` -- `usermod/espidf.py` is its own
resolver, and the last host-side one left here (`esp32` has no Docker
image yet, D28). Not
part of **M8**'s original port list (`unix`/`webassembly`/`qemu`/
`windows`) -- added alongside **M9**'s own ESP-IDF provisioning work,
since a resolver with nothing driving a build through it proves less than
one that does.

`windows` (**D18**) is the fifth and last port here: a plain Linux-hosted
cross-compile for all three arches this project covers (`x64`/`x86` via
an apt-installed mingw-w64 GCC, `arm64` via a pinned `llvm-mingw`
toolchain, since no Linux distro packages a GCC targeting
`aarch64-w64-mingw32` at all), no Windows host or MSYS2 needed for any of
them -- all three baked into `docker/windows.Dockerfile` and run there,
never on the host (**D30**/**D32**). This is **not** what `a7p`'s own `mp-usermod.yml` does
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

import os
import shlex
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from . import espidf


class UsermodBuildError(Exception):
    pass


@dataclass(frozen=True)
class UnixArchSettings:
    """Everything about a `unix` build that depends on the *architecture*
    rather than on the libc floor.

    Keyed by architecture, not by platform tag, on purpose: nothing here
    differs between `manylinux_2_28_x86_64` and `musllinux_1_2_x86_64`
    except the container they run in, which is the pin file's business.
    Duplicating fifteen near-identical rows so each tag could own one
    would only create fifteen places for a drift to hide -- the same
    argument `UNIX_RUNNABLE_ARCHS` was derived rather than hand-written
    under.

    `elf` is `(e_machine, EI_CLASS, EI_DATA)` -- what `verify_unix_output()`
    checks the finished binary's own header against. Values are read from
    this machine's `/usr/include/elf.h` (`EM_386` 3, `EM_MIPS` 8,
    `EM_PPC64` 21, `EM_S390` 22, `EM_ARM` 40, `EM_X86_64` 62,
    `EM_AARCH64` 183, `EM_RISCV` 243), not recalled.
    """

    elf: tuple[int, int, int]
    cross_compile: str = ""
    link_opts: tuple[str, ...] = ()
    standalone: bool = False


_ELFCLASS32, _ELFCLASS64 = 1, 2
_ELFDATA2LSB, _ELFDATA2MSB = 1, 2

# **Record 0043 rewrote this table end to end**, and it is worth reading
# what it stopped saying as much as what it now says.
#
# It used to be five architectures under this project's own private
# spelling (`x64`, `x86`, `aarch64`, `armhf`, `mipsel`), four of them
# carrying a `CROSS_COMPILE` prefix naming an apt cross-toolchain
# installed into an amd64 image. Now it is eight architectures under
# **pypa's spelling** (`x86_64`, `i686`, `armv7l`, plus `ppc64le`,
# `s390x`, `riscv64`, which cibuildmp simply did not cover), and only
# one of them cross-compiles at all.
#
# The reason is structural rather than cosmetic. A `CROSS_COMPILE`
# prefix here encoded *"the host is x86_64"* as a constant, which is
# false the moment a build runs on an `ubuntu-24.04-arm` runner --
# 0043's own triggering question. Under the native-image model each
# `unix` image is built for its own target arch and holds a plain native
# gcc, so the target arch and the container platform are one fact, and
# host architecture is recorded nowhere at all. Much of what D24/D25
# built -- and the six real apt/gcc bugs D25 paid for -- was
# cross-compile machinery this deletes rather than fixes, which is the
# honest description of it: those bugs were real, and so is the fact
# that the code they fixed is gone.
#
# Two arch-specific complications the old table carried are also gone,
# both because the native base images already solve them -- verified
# against the real images, not assumed:
#
#   * `MICROPY_FORCE_32BIT=1` (the old `x86` row) added `-m32` to a
#     64-bit host gcc plus a multilib probe. `manylinux_2_28_i686`'s gcc
#     targets i686 natively; there is nothing to force. The 32-bit case
#     it was standing in for is handled the way cibuildwheel handles it,
#     with a `linux32` personality wrapper on the container
#     (`dockerrun.needs_linux32()`), not with a compiler flag.
#   * `MICROPY_STANDALONE=1 LDFLAGS_EXTRA=-static` plus a separate
#     `deplibs` pre-step (the old `armhf`/`mipsel` rows) existed because
#     no cross-usable libffi was available, so `ports/unix` had to build
#     the vendored one -- which in turn is why `libltdl-dev` had to be
#     installed for `autogen.sh` (D25's sixth bug). `pkg-config --libs
#     libffi` resolves to `-lffi` inside `manylinux_2_31_armv7l`,
#     checked directly by running it in the real image, so armv7l joins
#     every other native arch on the plain dynamic path. Only `mipsel`
#     still needs it.
#
# Order is significant, not alphabetical: `targets.py`'s `_PORT_AXES`
# derives its display/build order from the pin file and this table, so
# reordering this literal reorders every `--dry-run` plan.
UNIX_ARCH_SETTINGS: dict[str, UnixArchSettings] = {
    "x86_64": UnixArchSettings(elf=(62, _ELFCLASS64, _ELFDATA2LSB)),
    "i686": UnixArchSettings(elf=(3, _ELFCLASS32, _ELFDATA2LSB)),
    "aarch64": UnixArchSettings(elf=(183, _ELFCLASS64, _ELFDATA2LSB)),
    "armv7l": UnixArchSettings(elf=(40, _ELFCLASS32, _ELFDATA2LSB)),
    "ppc64le": UnixArchSettings(elf=(21, _ELFCLASS64, _ELFDATA2LSB)),
    # The one big-endian target in the matrix, and the reason
    # `verify_unix_output()` checks `EI_DATA` at all rather than
    # `e_machine` alone: a big-endian s390x ELF and a hypothetical
    # little-endian one share `EM_S390`.
    "s390x": UnixArchSettings(elf=(22, _ELFCLASS64, _ELFDATA2MSB)),
    "riscv64": UnixArchSettings(elf=(243, _ELFCLASS64, _ELFDATA2LSB)),
    # The documented exception to 0043 (its own open question, answered
    # as "keep it, and say plainly that it is different"): pypa publishes
    # no mipsel image, PEP 600 defines no `manylinux_*_mipsel` tag, and
    # there is no Docker official image for 32-bit mipsel either -- there
    # is nothing to be native to. So this arch alone keeps the old
    # model unchanged: an amd64 container, an apt cross-toolchain, the
    # `MICROPY_STANDALONE` static libffi path, and the `libltdl-dev`
    # that D25 found `deplibs`' own `autogen.sh` needs. Its tag is
    # `manylinux_2_39_mipsel`, PEP 425's plain unqualified platform tag, because
    # a binary making no libc-floor claim is exactly what that tag names.
    # `EM_MIPS` is spelled "MIPS R3000 big-endian" in elf.h, but the
    # value is shared with little-endian MIPS -- `EI_DATA` is what
    # separates them, which is why it is checked.
    "mipsel": UnixArchSettings(
        elf=(8, _ELFCLASS32, _ELFDATA2LSB),
        cross_compile="mipsel-linux-gnu-",
        link_opts=("MICROPY_STANDALONE=1", "LDFLAGS_EXTRA=-static"),
        standalone=True,
    ),
}

# Every runnable `unix` architecture, in table order. Kept as a derived
# name rather than a second literal for the reason it always was: the two
# drifting apart is a real failure mode and a hand-maintained copy buys
# nothing.
UNIX_RUNNABLE_ARCHS = tuple(UNIX_ARCH_SETTINGS)


@dataclass(frozen=True)
class UnixBuildOptions:
    """`target` is the **platform tag** -- `manylinux_2_28_x86_64`,
    `musllinux_1_2_aarch64`, `manylinux_2_39_mipsel` -- not a bare architecture.

    It was `arch: str` (`"x64"`, `"armhf"`) until record 0043. The rename
    is not cosmetic: a bare arch cannot name a cell of the matrix any
    more, because glibc and musl builds of the same architecture are
    different artifacts that run on different hosts (record 0031), and
    because the floor is now part of what the identifier claims
    (`unix-manylinux_2_28_x86_64` is a real PEP 600 tag, where
    `unix-x64` was a name for "whatever glibc the base image happened to
    ship"). `dockerrun.split_tag()` recovers the architecture where
    something genuinely depends on it alone.
    """

    target: str
    user_c_modules: str
    frozen_manifest: str
    build_dir: Path
    variant: str = "standard"
    extra_make_args: tuple[str, ...] = ()


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


def _unix_dir(mpy_dir: Path) -> Path:
    return mpy_dir / "ports" / "unix"


# Per-cell `CFLAGS_EXTRA` (`ports/unix/Makefile`'s own variable, appended
# to `CFLAGS`). Every entry here suppresses **-Werror on third-party
# vendored code**, never on MicroPython's own, and every one was found by
# running a real build rather than predicted -- the same way D25's six
# apt/gcc bugs were, and the same shape D18's own three Clang-specific
# `arm64` suppressions already take for `windows`.
#
# This is the cost of a real libc floor and a real native toolchain that
# record 0043 did not price in: leaving `ubuntu:24.04` for AlmaLinux 8 and
# Alpine means new compilers and new libcs meeting `lib/mbedtls` and
# `lib/berkeley-db-1.xx` for the first time, and `ports/unix` builds those
# with `-Werror`.
#
# `musllinux` -- `-Wno-error=cpp`. Confirmed on a real
# `musllinux_1_2_x86_64` build: `extmod/modbtree.c` includes
# `lib/berkeley-db-1.xx/include/berkeley-db/db.h`, which includes
# `<sys/cdefs.h>`, and musl's own copy of that header is nothing but
# `#warning usage of non-standard #include <sys/cdefs.h> is deprecated`.
# glibc has no such warning, so this is a property of the libc rather
# than of the architecture, and it applies to the whole musllinux column.
# The alternative was turning `MICROPY_PY_BTREE` off for musl, which
# would silently give that column a different feature set from the glibc
# one -- a worse trade than one narrow suppression in a vendored header.
_MUSL_CFLAGS: tuple[str, ...] = ("-Wno-error=cpp",)

# Per-architecture rules, for cells where the *compiler backend* rather
# than the libc is what objects.
#
# `aarch64` -- `-Wno-error=array-bounds`. `lib/mbedtls/library/ctr_drbg.c`
# trips `-Werror=array-bounds=` inside `common.h`'s own `mbedtls_xor`
# ("array subscript 48 is outside array bounds of `unsigned char[48]`",
# `common.h:235`), a gcc 14 false positive on a loop bounded by exactly
# that size: `ctr_drbg_update_internal` XORs two
# `MBEDTLS_CTR_DRBG_SEEDLEN` buffers and gcc reports the one-past-the-end
# index it proved unreachable.
#
# **This started life as a per-tag entry for `manylinux_2_28_aarch64`
# alone, and the second aarch64 cell ever built moved it here.** The
# original note reasoned that "gcc's own bounds analysis differs by
# target, so this cannot be a column-wide rule and has to stay per cell",
# which was the right conclusion from one data point and the wrong axis.
# `musllinux_1_2_aarch64`'s first CI run (32960761641) failed with the
# byte-identical diagnostic from an Alpine base and a different libc
# entirely, while `x86_64`, `i686` and `armv7l` build clean on *both*
# columns. Two aarch64 cells, two failures; seven non-aarch64 cells, none.
# The varying thing is the backend, so the key is the architecture --
# which also means `musllinux_1_2_aarch64` needed no new entry at all,
# and neither will any future aarch64 floor.
_ARCH_CFLAGS: dict[str, tuple[str, ...]] = {
    "aarch64": ("-Wno-error=array-bounds",),
}

# Genuine per-tag one-offs: a cell whose problem is neither its libc nor
# its architecture. Empty today, and that is the honest state rather than
# a gap -- every suppression found so far has generalised to one of the
# two axes above. Kept because the `windows` port's own `arm64` needs
# three Clang-specific flags that no other target does (D18), so the
# shape is known to be reachable.
#
# A cell missing from all three tables has not been proven clean; it has
# usually not been built at all (record 0044 is explicit about which
# were), so expect these to grow as the remaining cells get a first run.
UNIX_TARGET_CFLAGS: dict[str, tuple[str, ...]] = {}


def unix_extra_cflags(target: str) -> tuple[str, ...]:
    """Every `CFLAGS_EXTRA` flag this cell needs: the libc-wide rule, the
    per-architecture one, and any per-tag one-off. Empty for a cell that
    needs none."""
    from ... import dockerrun

    floor, arch = dockerrun.split_tag(target)
    libc_flags = _MUSL_CFLAGS if floor.startswith("musllinux") else ()
    return (
        *libc_flags,
        *_ARCH_CFLAGS.get(arch, ()),
        *UNIX_TARGET_CFLAGS.get(target, ()),
    )


def unix_arch_settings(target: str) -> UnixArchSettings:
    """This platform tag's architecture settings, or a clear error.

    The lookup that turns a matrix cell back into the one thing that
    genuinely varies by architecture rather than by libc floor. Raises
    rather than returning `None`: a tag that reaches here unknown is a
    config or resolver bug, and the two error messages it can produce
    (`split_tag()`'s "not a known architecture" and this one) say which.
    """
    from ... import dockerrun

    return UNIX_ARCH_SETTINGS[dockerrun.split_tag(target)[1]]


def unix_make_command(
    opts: UnixBuildOptions, mpy_dir: Path, *, mpy_cross: Path | None = None
) -> list[str]:
    settings = unix_arch_settings(opts.target)
    return [
        "make",
        "-C",
        _unix_dir(mpy_dir).as_posix(),
        f"VARIANT={opts.variant}",
        f"BUILD={opts.build_dir.as_posix()}",
        f"CROSS_COMPILE={settings.cross_compile}",
        *(
            [f"CFLAGS_EXTRA={' '.join(cflags)}"]
            if (cflags := unix_extra_cflags(opts.target))
            else []
        ),
        # py/mkenv.mk's own override (`MICROPY_MPYCROSS`, defaulting to
        # `$(TOP)/mpy-cross/build/mpy-cross`) -- passed only when the
        # caller built one inside this container, which `build_unix()`
        # always does. See `container_mpy_cross()` for why the host's
        # own binary cannot be used here any more.
        *([f"MICROPY_MPYCROSS={mpy_cross.as_posix()}"] if mpy_cross else []),
        *settings.link_opts,
        f"USER_C_MODULES={opts.user_c_modules}",
        f"FROZEN_MANIFEST={opts.frozen_manifest}",
        *opts.extra_make_args,
    ]


def run_unix_deplibs(
    opts: UnixBuildOptions, mpy_dir: Path, *, docker_image: str
) -> None:
    """MICROPY_STANDALONE=1 only makes libffi a DEPLIBS entry, not a
    prerequisite of the default build target -- must run as its own step
    first, same as build-usermod-unix's own "Build libffi (deplibs)" step.
    BUILD must match the main build's BUILD=: deplibs writes libffi.a
    under $(BUILD)/lib/libffi/out/lib/ and the main build looks for it
    there.

    Docker-only (D30): `docker_image` is always real by the time this is
    called -- `build_unix()` itself raises before ever reaching here if
    `ensure_image()` returned `None`.

    Only `manylinux_2_39_mipsel` still reaches this at all. Every other
    architecture builds natively in an image whose own `pkg-config`
    resolves `-lffi` (verified by running it inside the real
    `manylinux_2_28_x86_64` / `manylinux_2_31_armv7l` / `musllinux_1_2_*`
    images), so record 0043 dropped the whole `MICROPY_STANDALONE`
    static-libffi path for them along with the cross toolchains it
    existed to work around.
    """
    settings = unix_arch_settings(opts.target)
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
    from ... import dockerrun

    dockerrun.run(
        command,
        mounts=[mpy_dir, Path(opts.user_c_modules)],
        workdir=_unix_dir(mpy_dir),
        image=docker_image,
        timeout=dockerrun.timeout_for("unix", opts.target),
        oci_platform=dockerrun.platform_for("unix", opts.target),
        linux32=dockerrun.needs_linux32("unix", opts.target),
    )


# Why both checks below exist at all, in one place: **under the
# native-image model a wrong result no longer looks like a failure**.
# The target architecture and the container platform are the same fact
# (record 0043), so getting that fact wrong does not produce an error --
# point a `unix-manylinux_2_28_x86_64` build at an arm64 image and `make`
# succeeds, gcc succeeds, and the output is a working aarch64 binary
# filed under an x86_64 identifier that nothing downstream will question.
# The same goes for the libc floor: nothing about a successful build
# says the binary can run on a host meeting the floor its own name
# advertises.
#
# `verify_unix_output()` is `natmod/build.py`'s own `verify_output()` for
# this port -- that module's "cibuildmp's equivalent of auditwheel",
# decoded by hand the same way, because an ELF header's first 20 bytes
# are a fixed layout and reading three fields out of them needs no
# library. `verify_unix_floor()` is the part that genuinely does need
# one, and uses `pyelftools` (already a dependency, D12) to read the
# version-requirement table `auditwheel` reads for wheels.
#
# `EM_*`/`ELFCLASS*`/`ELFDATA*` values are in `UnixArchSettings` above,
# read from this machine's own `/usr/include/elf.h` rather than recalled.
def _required_glibc(binary: Path) -> tuple[int, int] | None:
    """The highest `GLIBC_x.y` symbol version this ELF actually requires,
    or `None` if it requires none at all.

    This is the computed half of PEP 600, and the part record 0031 was
    explicit could not be faked: a curated table decides which base image
    a build runs in, but only the finished binary's own symbol versions
    say which glibc it really needs. `auditwheel` does exactly this for
    wheels (`elfutils.elf_find_versioned_symbols`); `unix` produces a bare
    executable rather than a wheel, so the inspection is reimplemented on
    the same data instead of shelling out to a tool that only accepts
    `.whl` files.

    `pyelftools` is already a cibuildmp dependency (D12), so this needs
    nothing new -- 0031 checked that specifically before recommending it.

    `None` covers two real cases, both legitimate: a fully static build
    (`manylinux_2_39_mipsel`, whose `-static` link leaves no version
    requirements to read) and a musl binary (musl does not use symbol
    versioning at all, which is why PEP 656 is a separate spec rather
    than manylinux with a different number).
    """
    from elftools.common.exceptions import ELFError
    from elftools.elf.elffile import ELFFile
    from elftools.elf.gnuversions import GNUVerNeedSection

    versions: list[tuple[int, int]] = []
    try:
        with binary.open("rb") as handle:
            elf = ELFFile(handle)
            for section in elf.iter_sections():
                if not isinstance(section, GNUVerNeedSection):
                    continue
                for _verneed, auxes in section.iter_versions():
                    for aux in auxes:
                        name = aux.name
                        if not name.startswith("GLIBC_"):
                            continue
                        parts = name[len("GLIBC_") :].split(".")
                        if len(parts) >= 2 and all(q.isdigit() for q in parts[:2]):
                            versions.append((int(parts[0]), int(parts[1])))
    except ELFError:
        # "This file has no readable version-requirement table" and "this
        # file is not a floor violation" are the same answer here, and
        # this check is not the one that decides whether the output is a
        # sound binary at all -- `verify_unix_output()` runs first and
        # has already read a valid ELF header of the expected
        # architecture out of it. Turning a parse quirk into a build
        # failure would make the *additional* check the strictest one,
        # which is backwards.
        return None
    return max(versions) if versions else None


def verify_unix_floor(target: str, binary: Path) -> None:
    """The binary must not require a newer glibc than its own tag claims
    -- **record 0043**'s PEP 600 half, and what stops `manylinux_2_28`
    from being decorative.

    Record 0031's finding, stated plainly: `unix-manylinux-<arch>` used to
    mean "whatever glibc `ubuntu:24.04` happens to ship", changing
    silently underneath every image with no floor recorded anywhere. The
    floor is now in the name, so it has to be true, and the only way to
    know it is true is to read the finished binary.

    Checked live while implementing this, not asserted: a real
    `manylinux_2_28_x86_64` build of `ports/unix` requires at most
    `GLIBC_2.28` -- the claim and the binary agree exactly, which is also
    what makes this check meaningful rather than permanently slack.

    Only glibc floors are checked. musllinux is PEP 656 and a separate
    shape: musl has no symbol versioning, so a musl build's version
    cannot be recovered from the binary at all, and the guarantee there
    comes from the pinned `musllinux_1_2_<arch>` base rather than from
    inspection. `verify_unix_output()`'s architecture check still applies
    to every target either way.
    """
    floor, _arch = _split_target(target)
    if not floor.startswith("manylinux_"):
        return
    parts = floor.split("_")
    claimed = (int(parts[1]), int(parts[2]))
    required = _required_glibc(binary)
    if required is None:
        return
    if required > claimed:
        raise UsermodBuildError(
            f"unix/{target}: {binary.name} requires GLIBC_"
            f"{required[0]}.{required[1]}, but this target claims a floor of "
            f"manylinux_{claimed[0]}_{claimed[1]} -- the binary would not run "
            f"on a host meeting the floor its own identifier advertises"
        )


def _split_target(target: str) -> tuple[str, str]:
    from ... import dockerrun

    return dockerrun.split_tag(target)


def verify_unix_output(target: str, binary: Path) -> None:
    """The ELF header `ld` actually wrote must name the architecture this
    identifier claims -- `natmod/build.py`'s own `verify_output()` for
    the `unix` port, required by **0043**.

    Reads `EI_CLASS`/`EI_DATA` (`e_ident[4]`/`e_ident[5]`) and
    `e_machine` (a 16-bit little-endian field at offset `0x12`) straight
    out of the first 20 bytes. `EI_DATA` is checked, not just
    `e_machine`, because `mipsel` and a big-endian `mips` share one
    `e_machine` value and differ only there -- and because a header whose
    endianness does not match is also the case where reading `e_machine`
    as little-endian would be meaningless.

    Deliberately silent about *why* a mismatch happened: an unregistered
    or mis-registered `PORT_PLATFORMS` entry, a `CIBMP_*_DOCKER_IMAGE`
    override pointing at another architecture's image, and a genuinely
    mis-set `CROSS_COMPILE` all land here identically, and guessing
    between them in the message would be worse than reporting the fact.
    """
    expected = unix_arch_settings(target).elf
    header = binary.read_bytes()[:20]
    if len(header) < 20 or header[:4] != b"\x7fELF":
        raise UsermodBuildError(f"unix/{target}: {binary} is not an ELF file at all")
    # e_machine is a 16-bit field at 0x12 whose own byte order is the one
    # EI_DATA (e_ident[5]) declares -- decoding it little-endian
    # unconditionally would misread every big-endian target, which for
    # this matrix means s390x.
    byteorder: Literal["big", "little"] = (
        "big" if header[5] == _ELFDATA2MSB else "little"
    )
    actual = (int.from_bytes(header[18:20], byteorder), header[4], header[5])
    if actual != expected:
        raise UsermodBuildError(
            f"unix/{target}: build reported success but {binary.name}'s ELF "
            f"header encodes (e_machine, class, data) "
            f"{actual[0]:#x}/{actual[1]}/{actual[2]}, expected "
            f"{expected[0]:#x}/{expected[1]}/{expected[2]} -- the binary "
            f"is not the architecture this identifier names"
        )


def build_unix(
    opts: UnixBuildOptions,
    mpy_dir: Path,
    *,
    toolchain_root: Path | None = None,
    quiet: bool = False,
) -> Path:
    """Build ports/unix for `opts.target`, returning the produced binary.

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
    pinned Dockerfile and discarded per run).

    Under **record 0043** the container is also what decides the
    *architecture*. `dockerrun.ensure_image("unix", target)` resolves a
    `CIBMP_UNIX_<TARGET>_DOCKER_IMAGE` override or the digest pinned in
    `resources/pinned_docker_images.toml`, and
    `dockerrun.platform_for()` names the OCI platform that image is
    published for -- which, for `unix`, *is* the build target, because
    each image is native to its own architecture and holds a plain
    native gcc. Nothing here records what the host is. That is what lets
    one config produce the same identifiers on an x86_64 runner and on an
    `ubuntu-24.04-arm` one, with the non-native side emulated; before
    0043 an ARM host got `exec format error` from inside `make`.

    Two consequences worth stating because they are easy to misread as
    bugs. `CROSS_COMPILE=` is passed empty for every target except
    `manylinux_2_39_mipsel` -- correct, not missing: the compiler in the container
    already targets the right architecture. And a mismatch cannot be
    caught by the build succeeding, so `verify_unix_output()` below
    checks the finished ELF's own machine type against the identifier;
    an image resolved for the wrong platform otherwise yields a working
    binary of the wrong architecture, which is the specific trap 0043 was
    written about.

    `toolchain_root`/`quiet` are accepted only for the same call shape
    every `build_<port>()` shares (`orchestrate.py`'s `build_one()`
    passes them uniformly); neither is used on this Docker-only path.
    """
    from ... import dockerrun

    if opts.target not in dockerrun.unix_targets():
        raise UsermodBuildError(
            f"unknown unix target {opts.target!r}. Known: "
            f"{', '.join(dockerrun.unix_targets())}"
        )

    docker_image = dockerrun.ensure_image("unix", opts.target)
    if docker_image is None:
        raise UsermodBuildError(
            f"unix/{opts.target}: no Docker image registered for this "
            f"target and usermod builds are Docker-only -- set "
            f"CIBMP_UNIX_{opts.target.upper()}_DOCKER_IMAGE, or wait for "
            f"publish-docker-images.yml to publish one and fill its digest "
            f"into resources/pinned_docker_images.toml"
        )

    oci_platform = dockerrun.platform_for("unix", opts.target)
    linux32 = dockerrun.needs_linux32("unix", opts.target)
    timeout = dockerrun.timeout_for("unix", opts.target)

    if unix_arch_settings(opts.target).standalone:
        run_unix_deplibs(opts, mpy_dir, docker_image=docker_image)

    mpy_cross = container_mpy_cross(
        mpy_dir,
        slug=f"unix-{opts.target}",
        image=docker_image,
        oci_platform=oci_platform,
        linux32=linux32,
        timeout=timeout,
    )
    command = unix_make_command(opts, mpy_dir, mpy_cross=mpy_cross)
    dockerrun.run(
        command,
        mounts=[mpy_dir, Path(opts.user_c_modules)],
        workdir=_unix_dir(mpy_dir),
        image=docker_image,
        timeout=timeout,
        oci_platform=oci_platform,
        linux32=linux32,
    )

    binary = opts.build_dir / "micropython"
    if not binary.exists():
        raise UsermodBuildError(
            f"unix/{opts.target}: build reported success but {binary} is missing"
        )
    verify_unix_output(opts.target, binary)
    verify_unix_floor(opts.target, binary)
    return binary


# ── qemu (armv7m, riscv32, riscv64) ─────────────────────────────────────

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
    no globbing needed.
    """
    from ... import dockerrun

    cross = QEMU_BOARD_CROSS.get(opts.board)
    if cross is None:
        raise UsermodBuildError(
            f"qemu board {opts.board!r} not supported yet. Known: "
            f"{', '.join(QEMU_BOARD_CROSS)}"
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

    command = qemu_make_command(opts, mpy_dir, cross)
    dockerrun.run(
        command,
        mounts=[mpy_dir, Path(opts.user_c_modules)],
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


# ── webassembly ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WebassemblyBuildOptions:
    user_c_modules: str
    frozen_manifest: str
    build_dir: Path
    variant: str = "pyscript"
    extra_make_args: tuple[str, ...] = ()


def webassembly_make_command(
    opts: WebassemblyBuildOptions, mpy_dir: Path, *, mpy_cross: Path | None = None
) -> list[str]:
    return [
        "make",
        "-C",
        (mpy_dir / "ports" / "webassembly").as_posix(),
        f"VARIANT={opts.variant}",
        f"BUILD={opts.build_dir.as_posix()}",
        # py/mkenv.mk's own `MICROPY_MPYCROSS` override. Passed for the
        # same reason `build_unix()` passes it, arrived at from the other
        # direction (record 0044): this image is amd64, so on an **arm64
        # host** the host-built mpy-cross is an arm64 binary that cannot
        # run inside it, and `py/mkrules.mk` runs mpy-cross *inside* the
        # container to compile FROZEN_MANIFEST. Without this, this port
        # works on an amd64 runner and nowhere else -- which is exactly
        # the host-dependence record 0043 exists to remove.
        *([f"MICROPY_MPYCROSS={mpy_cross.as_posix()}"] if mpy_cross else []),
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
    docstring for why). emsdk itself is baked into that image, which is
    also the pin of record for it -- there is no `sdk.env()` to inject,
    the image's own `ENV PATH` already covers it. `toolchain_root`/`quiet`
    are accepted only for the same call shape every `build_<port>()`
    shares (`orchestrate.py`'s `build_one()` passes them uniformly);
    neither is used on this Docker-only path.

    The output path is `opts.build_dir / "micropython.mjs"` --
    `ports/webassembly/Makefile`'s own `all:` target.
    """
    from ... import dockerrun

    docker_image = dockerrun.ensure_image("webassembly")
    if docker_image is None:
        raise UsermodBuildError(
            "webassembly: no Docker image registered for this port "
            "and usermod builds are Docker-only -- set "
            "CIBMP_WEBASSEMBLY_DOCKER_IMAGE, or wait for "
            "publish-docker-images.yml to publish one and register it in "
            "dockerrun.PORT_IMAGES"
        )

    command = webassembly_make_command(
        opts,
        mpy_dir,
        mpy_cross=container_mpy_cross(
            mpy_dir,
            slug="webassembly",
            image=docker_image,
            oci_platform=dockerrun.platform_for("webassembly"),
            timeout=dockerrun.timeout_for("webassembly"),
        ),
    )
    dockerrun.run(
        command,
        mounts=[mpy_dir, Path(opts.user_c_modules)],
        workdir=mpy_dir / "ports" / "webassembly",
        image=docker_image,
        timeout=dockerrun.timeout_for("webassembly"),
        # `linux/amd64` -- a statement about this *image* (an emsdk cross
        # host), not about the build target, which is wasm and which no
        # container is ever native to. Passing it is what lets this port
        # run on an arm64 host at all (**0043**): emulated, explicitly,
        # instead of resolving by accident-of-host and failing with a
        # bare `exec format error` from inside `make`.
        oci_platform=dockerrun.platform_for("webassembly"),
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


def esp32_make_command(
    opts: Esp32BuildOptions, mpy_dir: Path, *, mpy_cross: Path | None = None
) -> list[str]:
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
        # py/mkenv.mk's own `MICROPY_MPYCROSS` override -- the container's
        # own copy (container_mpy_cross()), never the host's. See that
        # function's own docstring for why a host-built mpy-cross cannot
        # run inside this port's container either, now that it does.
        *([f"MICROPY_MPYCROSS={mpy_cross.as_posix()}"] if mpy_cross else []),
        *opts.extra_make_args,
    ]


def _esp32_container_script(
    opts: Esp32BuildOptions,
    mpy_dir: Path,
    idf_dir: Path,
    tools_dir: Path,
    mpy_cross: Path,
) -> str:
    """The one shell invocation `build_esp32()` runs inside the container:
    install ESP-IDF's own tools (only once -- `.installed` marks a cache
    hit, the same "cached by existence" rule `container_mpy_cross()` and
    `sources.build_mpy_cross()` both already use), export the environment
    `idf_tools.py export` computes, then `make`. One invocation, not
    several `dockerrun.run()` calls, because `dockerrun.run()` has no
    stdout-capturing mode to hand `export`'s own key=value lines back to a
    second call -- letting bash itself `eval` them, in the same shell that
    then runs `make`, needs no such plumbing at all, and gets `$PATH`-style
    substitutions in exported values (`ResolvedEspIdf.env()`'s own old
    special case) for free from the shell instead of a bespoke replace.

    Every path here is `.as_posix()` and already bind-mounted at its own
    identical host path (`build_esp32()`'s own `mounts=`), the same
    convention every other port's `*_make_command()` already relies on --
    this script needs no rewriting to run the same inside the container as
    the paths already resolve to on the host.
    """
    tools_py = shlex.quote((idf_dir / "tools" / "idf_tools.py").as_posix())
    marker = shlex.quote((tools_dir / ".installed").as_posix())
    idf_tools_path = shlex.quote(tools_dir.as_posix())
    idf_path = shlex.quote(idf_dir.as_posix())
    make_command = shlex.join(esp32_make_command(opts, mpy_dir, mpy_cross=mpy_cross))
    return f"""set -eux
export IDF_TOOLS_PATH={idf_tools_path}
if [ ! -e {marker} ]; then
    python3 {tools_py} install --targets={shlex.quote(opts.idf_target)}
    python3 {tools_py} install-python-env
    touch {marker}
fi
eval "$(python3 {tools_py} export --format key-value | sed 's/^/export /')"
export IDF_PATH={idf_path}
{make_command}
"""


def build_esp32(
    opts: Esp32BuildOptions,
    mpy_dir: Path,
    *,
    toolchain_root: Path | None = None,
    quiet: bool = False,
) -> Path:
    """Build ports/esp32 for `opts.board`, returning the produced
    `micropython.bin`.

    Docker, since 2026-08-28 -- `usermod/espidf.py`'s own module docstring
    has the full reasoning (the bare-host `idf_tools.py install-python-env`
    step refused to run from inside cibuildmp's own `uv tool install`
    venv). Only the `git clone` (`espidf.fetch_esp_idf()`, source, portable)
    stays on the host; installing ESP-IDF's own tools, and `make` itself,
    both run inside `esp_idf_base` ([0058]) via `_esp32_container_script()`
    above, in one `dockerrun.run()` call.

    mpy-cross is built inside the same container too now
    (`container_mpy_cross()`, matching `unix`/`windows`/`webassembly`) --
    `esp32` moved out of `orchestrate.py`'s own `_HOST_MPY_CROSS_PORTS` in
    the same change, since a host-built mpy-cross is exactly the "wrong
    glibc" binary that function's own docstring warns about, once `make`
    itself is no longer running on the host either.

    The output path is `mpy_dir / "ports" / "esp32" / "build-<BOARD>" /
    "micropython.bin"` -- the port's own unmodified default build
    directory, since nothing here overrides `BUILD=`.
    """
    from ... import dockerrun

    docker_image = dockerrun.ensure_image("esp32")
    if docker_image is None:
        raise UsermodBuildError(
            "esp32: no Docker image registered -- see "
            "`resources/pinned_docker_images.toml`, or point "
            "CIBMP_ESP32_DOCKER_IMAGE at a local tag"
        )
    oci_platform = dockerrun.platform_for("esp32")
    timeout = dockerrun.timeout_for("esp32")

    idf_dir = espidf.fetch_esp_idf(opts.idf_version, root=toolchain_root, quiet=quiet)
    tools_dir = espidf.tools_dir(opts.idf_version, opts.idf_target, root=toolchain_root)
    tools_dir.mkdir(parents=True, exist_ok=True)

    mpy_cross = container_mpy_cross(
        mpy_dir,
        slug="esp32",
        image=docker_image,
        oci_platform=oci_platform,
        timeout=timeout,
    )

    script = _esp32_container_script(opts, mpy_dir, idf_dir, tools_dir, mpy_cross)
    dockerrun.run(
        ["bash", "-c", script],
        # The *directory* `opts.user_c_modules` resolves inside
        # (`portinfo.resolve_user_c_modules()`'s own cmake branch appends
        # `/micropython.cmake` to it), not the file itself -- a Make
        # port's own `USER_C_MODULES=` is already that directory
        # (`resolve_user_c_modules()`'s make branch returns it unchanged),
        # so mounting `Path(opts.user_c_modules)` there already covers
        # any sibling file the config's own `manifest = "..."` combined
        # into `opts.frozen_manifest` might `include()` -- live-caught
        # 2026-08-28, esp32's own bare `.cmake` file mount left exactly
        # that sibling (`usermod/manifest.py`) unreachable: `CMake Error
        # ... [Errno 2] No such file or directory`. `.parent` brings this
        # port's own mount up to the same directory-level coverage every
        # Make port already has, not a new guarantee beyond that.
        mounts=[mpy_dir, Path(opts.user_c_modules).parent, idf_dir, tools_dir],
        workdir=mpy_dir / "ports" / "esp32",
        image=docker_image,
        timeout=timeout,
        oci_platform=oci_platform,
    )

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
    already carry.

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
        mpy_cross=container_mpy_cross(
            mpy_dir,
            slug="windows",
            image=docker_image,
            oci_platform=dockerrun.platform_for("windows", opts.arch),
            timeout=dockerrun.timeout_for("windows", opts.arch),
        ),
    )
    dockerrun.run(
        command,
        mounts=[mpy_dir, Path(opts.user_c_modules)],
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

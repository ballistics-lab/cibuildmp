"""usermod build driver: `unix`, the first port covered under M8's own
scope ("ports that need no exotic provisioning first" -- docs/0000-TRACKER.md).
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
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from . import build_common
from .build_common import UsermodBuildError


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
    standalone: bool = False
    # True only for `mipsel`: the one arch with no native pypa image to
    # resolve a dynamic `libc`/`libffi` floor from at all (a Bootlin
    # cross-toolchain sysroot instead), so it has always had to link
    # fully static, tag or no tag. Every other arch's own static-or-not
    # now depends on which *tag* (`manylinux`/`musllinux`) is being
    # built, not on the arch alone -- see `unix_make_command()`'s own
    # `_use_static()`.
    force_static: bool = False


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
#     checked directly by running it in the real image, so 0043 dropped
#     `MICROPY_STANDALONE` everywhere but `mipsel`, which has no image at
#     all to resolve a system `libffi` from.
#
# **That second bullet is half-reversed below, and half stands.**
# `MICROPY_STANDALONE=1` (vendor and build `lib/libffi` from source) now
# applies to every arch, not just `mipsel` -- not because system `libffi`
# stopped resolving, but because depending on it made the submodule list
# itself arch-conditional (`lib/libffi` only on the clone path, only when
# `MICROPY_STANDALONE=1`) for one arch out of eight, and because it stops
# this project depending on every published image happening to ship
# `libffi-dev`/`libffi-devel` at all -- already a real gap once
# (`manylinux_2_28_x86_64` measured with none, record 0084's own
# baseline).
#
# `LDFLAGS_EXTRA=-static` (the whole binary, not just libffi) did **not**
# follow it everywhere, on reflection and against record 0084's own
# already-argued position ("`LDFLAGS_EXTRA=-static` is a separate flag
# and stays behind... a fully static binary is a change to what cibuildmp
# ships"): `manylinux_2_28` isn't only a floor claim, it's a live, native
# glibc userland whose whole *point* is that ordinary dynamic linking
# against its own symbol versions is exactly what makes the artifact
# portable, per PEP 600 -- the same mechanism every real manylinux wheel
# already relies on, no static anything. Reaching for `-static` there
# does not buy a cleaner artifact, it buys a linker error on any image
# missing `glibc-static` (`libc.a`/`libm.a`/`libpthread.a`/`libdl.a`, not
# shipped by pypa's own `manylinux_2_28_*` images, confirmed live) for a
# guarantee that is *already* leaky on glibc regardless: record 0031's
# own finding is that `libffi`'s `dlopen()` and `getaddrinfo()`'s own NSS
# backends still reach out to the linking host's glibc at runtime even
# from a "static" binary, so `-static` was never a complete escape from
# the floor on a glibc target in the first place. It stays for `musl`
# (musllinux, `force_static` below): musl's own static story has no such
# leak -- no dynamic NSS, everything genuinely self-contained -- which is
# exactly why Alpine/musl-based static binaries are a well-established
# pattern and glibc ones are not. See `unix_make_command()`'s own
# `_use_static()` for where this actually gets decided per build.
#
# Order is significant, not alphabetical: `targets.py`'s `_PORT_AXES`
# derives its display/build order from the pin file and this table, so
# reordering this literal reorders every `--dry-run` plan.
UNIX_ARCH_SETTINGS: dict[str, UnixArchSettings] = {
    "x86_64": UnixArchSettings(
        elf=(62, _ELFCLASS64, _ELFDATA2LSB),
        standalone=True,
    ),
    "i686": UnixArchSettings(
        elf=(3, _ELFCLASS32, _ELFDATA2LSB),
        standalone=True,
    ),
    "aarch64": UnixArchSettings(
        elf=(183, _ELFCLASS64, _ELFDATA2LSB),
        standalone=True,
    ),
    "armv7l": UnixArchSettings(
        elf=(40, _ELFCLASS32, _ELFDATA2LSB),
        standalone=True,
    ),
    "ppc64le": UnixArchSettings(
        elf=(21, _ELFCLASS64, _ELFDATA2LSB),
        standalone=True,
    ),
    # The one big-endian target in the matrix, and the reason
    # `verify_unix_output()` checks `EI_DATA` at all rather than
    # `e_machine` alone: a big-endian s390x ELF and a hypothetical
    # little-endian one share `EM_S390`.
    "s390x": UnixArchSettings(
        elf=(22, _ELFCLASS64, _ELFDATA2MSB),
        standalone=True,
    ),
    "riscv64": UnixArchSettings(
        elf=(243, _ELFCLASS64, _ELFDATA2LSB),
        standalone=True,
    ),
    # The documented exception to 0043 (its own open question, answered
    # as "keep it, and say plainly that it is different"): pypa publishes
    # no mipsel image, PEP 600 defines no `manylinux_*_mipsel` tag, and
    # there is no Docker official image for 32-bit mipsel either -- there
    # is nothing to be native to. So this arch alone keeps the old
    # shape: an amd64 container, a cross-toolchain, the
    # `MICROPY_STANDALONE` static libffi path, and the `libltdl-dev`
    # that D25 found `deplibs`' own `autogen.sh` needs. Only the
    # toolchain's *source* changed -- `docker/manylinux_2_41_mipsel.Dockerfile`
    # pins a Bootlin tarball (gcc 14.3.0, glibc 2.41) rather than apt's
    # `gcc-mipsel-linux-gnu`, which Debian 13 "Trixie" dropping the mipsel
    # port took out of Ubuntu's archive entirely (record 0068). The
    # `mipsel-linux-gnu-` prefix below is unchanged and deliberately so:
    # Bootlin's own prefix is `mipsel-linux-`, and that Dockerfile
    # generates `mipsel-linux-gnu-*` wrappers rather than this constant
    # moving. Its tag is
    # `manylinux_2_41_mipsel`, and the `2_41` moved with the toolchain: it
    # was `manylinux_2_39_mipsel` while apt's cross-glibc was 2.39, and
    # renaming rather than repointing is record 0031's own principle --
    # a real PEP 600 tag must not keep claiming a floor its image no
    # longer has.
    # `EM_MIPS` is spelled "MIPS R3000 big-endian" in elf.h, but the
    # value is shared with little-endian MIPS -- `EI_DATA` is what
    # separates them, which is why it is checked.
    "mipsel": UnixArchSettings(
        elf=(8, _ELFCLASS32, _ELFDATA2LSB),
        cross_compile="mipsel-linux-gnu-",
        standalone=True,
        force_static=True,
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
    `musllinux_1_2_aarch64`, `manylinux_2_41_mipsel` -- not a bare architecture.

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
    # The MicroPython release being built. Defaulted so every existing
    # caller and fixture keeps working; only `_row_cflags()` reads it, and
    # only to find this row's own `cflags_extra`.
    tag: str = ""


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
#
# `s390x`/`riscv64` -- `-Wno-error=clobbered`. `ports/unix/main.c`'s own
# `path_remaining` (real code, not a vendored library this time):
#
#   main.c:565:14: error: variable 'path_remaining' might be clobbered
#   by 'longjmp' or 'vfork' [-Werror=clobbered]
#
# The same diagnostic class record [0044] already found in `mpy-cross`'s
# own `main.c` (`parse_integer`, `s390x`, `v1.28.0` only, back when it
# looked narrow enough to descope by identifier rather than suppress) --
# real GCC output for how these two architectures' own register
# allocation interacts with `setjmp`/`longjmp` around a `nlr_push()` call
# site, not specific to one function or one tag. This sweep found it on
# multiple tags on *both* architectures, in the *port's* `main.c` this
# time, which is what moved it from "worth descoping two identifiers
# for" to "worth suppressing at the architecture level" -- the same
# escalation `aarch64`'s own entry above already went through once.
_ARCH_CFLAGS: dict[str, tuple[str, ...]] = {
    "aarch64": ("-Wno-error=array-bounds",),
    "s390x": ("-Wno-error=clobbered",),
    "riscv64": ("-Wno-error=clobbered",),
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


# `riscv64`'s own `lib/libffi` submodule pin, on every one of these tags,
# points to `https://github.com/atgreen/libffi` (a fork/mirror whose
# `configure.host` has no `riscv*` case at all -- verified directly by
# fetching `.gitmodules` and `configure.host` at the pinned commit for
# each), so `deplibs` hard-fails with `configure: error: "libffi has not
# been ported to riscv64-unknown-linux-gnu."` on every one of them,
# regardless of anything cibuildmp does. `v1.24.0` moves the pin to the
# canonical `libffi/libffi` (tag `v3.4.6`), whose `configure.host` has a
# real `riscv*-*)` case -- filed upstream
# (micropython/micropython, not yet numbered), but nothing to wait on:
# there is no fix to backport onto a tag that has already shipped.
# `MICROPY_PY_FFI=0` for exactly these (tag, riscv64) pairs is the only
# lever available short of patching the vendored submodule ourselves.
_RISCV64_FFI_UNPORTED_TAGS = (
    "v1.20.0",
    "v1.21.0",
    "v1.22.0",
    "v1.22.1",
    "v1.22.2",
    "v1.23.0",
)


def _riscv64_ffi_unported(target: str, tag: str) -> bool:
    """Whether this (target, tag) pair is the known-broken `riscv64` +
    pre-`v1.24.0` combination -- see `_RISCV64_FFI_UNPORTED_TAGS`'s own
    comment. Every other architecture's `lib/libffi` builds cleanly on
    every tag cibuildmp covers; this is not a stand-in for a broader
    per-tag capability check."""
    from ... import dockerrun

    return (
        dockerrun.split_tag(target)[1] == "riscv64"
        and tag in _RISCV64_FFI_UNPORTED_TAGS
    )


def unix_extra_cflags(target: str, tag: str = "") -> tuple[str, ...]:
    """Every `CFLAGS_EXTRA` flag this cell needs: the libc-wide rule, the
    per-architecture one, any per-tag one-off, and whatever this
    MicroPython release needs in every port (`build_common.tag_cflags()`). Empty for a cell that needs none.

    `tag` defaults to empty so a caller that genuinely has no MicroPython
    version in hand still resolves the other three axes rather than
    raising -- the tag axis simply contributes nothing."""
    from ... import dockerrun

    floor, arch = dockerrun.split_tag(target)
    libc_flags = _MUSL_CFLAGS if floor.startswith("musllinux") else ()
    return (
        *libc_flags,
        *_ARCH_CFLAGS.get(arch, ()),
        *UNIX_TARGET_CFLAGS.get(target, ()),
        *build_common.tag_cflags(tag),
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


def _use_static(target: str, settings: UnixArchSettings) -> bool:
    """Whether this build should link fully static (`LDFLAGS_EXTRA=-static`),
    as opposed to `MICROPY_STANDALONE=1` alone (a vendored, statically-linked
    `libffi` inside an otherwise ordinary dynamic binary).

    `musllinux` always does -- musl's own static story has no dynamic-NSS
    leak, so `-static` there is a real, complete guarantee. `mipsel`
    always does too, via `settings.force_static` -- it cross-compiles
    against a Bootlin sysroot with no dynamic libc/libffi floor to link
    against at all. Every other (`manylinux`) cell does not: see
    `UNIX_ARCH_SETTINGS`'s own header for why `-static` was pulled back
    off them.
    """
    return settings.force_static or target.startswith("musllinux_")


def unix_make_command(
    opts: UnixBuildOptions,
    mpy_dir: Path,
    *,
    mpy_cross: Path | None = None,
    extra_cflags: tuple[str, ...] | None = None,
) -> list[str]:
    """`extra_cflags`, when given, overrides `unix_extra_cflags()`'s own
    raw candidate list -- `build_unix()` passes the already
    `probe_supported_cflags()`-filtered set (a `-Wno-error=<diagnostic>`
    this cell's own gcc does not recognize is a hard `cc1: error`, not a
    no-op -- see that function's own docstring), so this stays the raw
    candidates only for a caller (a test, a hand invocation) that has not
    done that filtering itself.
    """
    settings = unix_arch_settings(opts.target)
    link_opts = (
        ("MICROPY_STANDALONE=1", "LDFLAGS_EXTRA=-static")
        if _use_static(opts.target, settings)
        else ("MICROPY_STANDALONE=1",)
    )
    cflags = (
        extra_cflags
        if extra_cflags is not None
        else unix_extra_cflags(opts.target, opts.tag)
    )
    return [
        "make",
        "-C",
        _unix_dir(mpy_dir).as_posix(),
        f"-j{os.cpu_count() or 1}",
        f"VARIANT={opts.variant}",
        f"BUILD={opts.build_dir.as_posix()}",
        f"CROSS_COMPILE={settings.cross_compile}",
        *([f"CFLAGS_EXTRA={' '.join(cflags)}"] if cflags else []),
        # py/mkenv.mk's own override (`MICROPY_MPYCROSS`, defaulting to
        # `$(TOP)/mpy-cross/build/mpy-cross`) -- passed only when the
        # caller built one inside this container, which `build_unix()`
        # always does. See `container_mpy_cross()` for why the host's
        # own binary cannot be used here any more.
        *([f"MICROPY_MPYCROSS={mpy_cross.as_posix()}"] if mpy_cross else []),
        *link_opts,
        # `ports/unix/Makefile`'s own `MICROPY_STANDALONE` branch sits
        # nested inside `ifeq ($(MICROPY_PY_FFI),1)`, so this is a no-op
        # for every other cell -- `MICROPY_STANDALONE=1` above stays
        # harmlessly unread rather than needing its own exclusion here.
        # See `_riscv64_ffi_unported()`'s own comment for why.
        *(["MICROPY_PY_FFI=0"] if _riscv64_ffi_unported(opts.target, opts.tag) else []),
        f"USER_C_MODULES={opts.user_c_modules}",
        f"FROZEN_MANIFEST={opts.frozen_manifest}",
        *opts.extra_make_args,
    ]


def run_unix_deplibs(
    opts: UnixBuildOptions,
    mpy_dir: Path,
    *,
    container: Any,
) -> None:
    """MICROPY_STANDALONE=1 only makes libffi a DEPLIBS entry, not a
    prerequisite of the default build target -- must run as its own step
    first, same as build-usermod-unix's own "Build libffi (deplibs)" step.
    BUILD must match the main build's BUILD=: deplibs writes libffi.a
    under $(BUILD)/lib/libffi/out/lib/ and the main build looks for it
    there.

    **Required `container`** -- every usermod port builds through
    `Container` now (record 0095's own addenda 8-12 landed the last of
    the six).

    Every arch reaches this now (`standalone=True` on every
    `UnixArchSettings` row) -- record 0043 dropped this step for every
    arch but `mipsel` on the strength of each native image's own
    `pkg-config` resolving `-lffi`; it comes back for all eight so the
    submodule list and the link mode stop being arch-conditional facts.
    See `UNIX_ARCH_SETTINGS`'s own header for the full argument and cost.

    Followed by a symlink fixup, not baked into upstream's own recipe:
    `lib/libffi/configure.ac` installs to `$(toolexeclibdir)`, which is
    `${libdir}/$(gcc -print-multi-os-directory)` -- a relative path
    fragment (from `out/lib`, autoconf's own `libdir` under
    `--prefix=$$PWD/out`) that names wherever *this* compiler's own
    multiarch convention actually puts things, while
    `ports/unix/Makefile`'s own `LIBFFI_LDFLAGS` unconditionally expects
    `out/lib/libffi.a`. Queried live with the same `$(CC)` deplibs
    itself just built with, not hardcoded to one value: `../lib64` on a
    RHEL-family host (`manylinux_2_28_{x86_64,aarch64,ppc64le,s390x,
    i686}`), `../lib64/lp64d` on `riscv64` (its own ABI-variant
    subdirectory -- one level deeper than the RHEL case, found live once
    a tag whose `lib/libffi` pin actually supports `riscv64` reached this
    step at all, see `_riscv64_ffi_unported()`), `../lib` on
    Debian/Alpine hosts (`musllinux_1_2_x86_64`), which normalizes right
    back to `out/lib` and needs no fixup at all. A single hardcoded
    `../lib64` check (this function's own first version) is exactly the
    kind of per-arch table this project keeps finding reasons not to
    maintain -- see `probe_supported_cflags()`'s identical reasoning for
    live-asking the compiler instead of predicting its answer.
    `deplibs` has no hook to pass `--libdir=`/`--disable-multi-os-directory`
    through to libffi's own `configure` (`$(TOP)/lib/libffi/configure
    ... --prefix=$$PWD/out`, no other args, hardcoded in
    `ports/unix/Makefile`), so this is the only lever available short of
    patching that submodule.
    """
    settings = unix_arch_settings(opts.target)
    build_dir = opts.build_dir.as_posix()
    compiler = f"{settings.cross_compile}gcc"
    make_command = [
        "make",
        "-C",
        _unix_dir(mpy_dir).as_posix(),
        f"-j{os.cpu_count() or 1}",
        f"VARIANT={opts.variant}",
        f"BUILD={build_dir}",
        f"CROSS_COMPILE={settings.cross_compile}",
        "MICROPY_STANDALONE=1",
        "deplibs",
    ]
    libffi_out = f"{build_dir}/lib/libffi/out"
    fixup = (
        f"multi_os_dir=$({shlex.quote(compiler)} -print-multi-os-directory) && "
        f"[ -e {shlex.quote(libffi_out)}/lib/libffi.a ] || "
        f'[ ! -e {shlex.quote(libffi_out)}/lib/"$multi_os_dir"/libffi.a ] || '
        f"{{ mkdir -p {shlex.quote(libffi_out)}/lib && "
        f'ln -sf "$multi_os_dir/libffi.a" {shlex.quote(libffi_out)}/lib/libffi.a; }}'
    )
    command = [
        "sh",
        "-c",
        shlex.join(make_command) + " && " + fixup,
    ]
    from ... import dockerrun

    container.call(
        command,
        workdir=_unix_dir(mpy_dir),
        timeout=dockerrun.timeout_for("unix", opts.target),
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
    (`mipsel`, and every `musllinux` cell -- see `UNIX_ARCH_SETTINGS`'s
    own header for why `-static` stayed on those and only those) and a
    musl binary (musl does not use symbol versioning at all, which is why
    PEP 656 is a separate spec rather than manylinux with a different
    number -- true for every `musllinux` cell regardless of `-static`).
    Every `manylinux` cell links ordinary dynamic glibc now, so this
    check reads a real `GLIBC_x.y` requirement for it again, the same way
    it always did before `MICROPY_STANDALONE=1` went universal.
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


def _split_target(target: str) -> tuple[str, str]:
    from ... import dockerrun

    return dockerrun.split_tag(target)


# The one dynamic-linking guarantee `manylinux_2_28`/`manylinux_2_31` make
# about the *host* (every dynamic `unix` target that is not `mipsel`
# builds under one of these two) -- verified against `auditwheel`'s own
# `policy/manylinux-policy.json` (2026-08-29, `auditwheel==6.8.1`), not
# recalled: the two floors carry byte-identical `lib_whitelist`s, so one
# table covers both. This is what `auditwheel repair` bundles a wheel's
# own copy of anything *not* in it for -- `libffi.so.6` included, the
# specific gap a real `unix` build hit (a `manylinux_2_28_x86_64` binary,
# run on a plain `ubuntu-latest` runner: "error while loading shared
# libraries: libffi.so.6: cannot open shared object file"). `unix`
# produces a bare executable rather than a wheel, so there is nothing for
# `auditwheel` itself to operate on; `repair_unix_binary()` below
# reimplements the same vendor-and-patch-rpath idea directly, the same
# "decoded by hand" choice `_required_glibc()` already makes for the
# floor check.
_MANYLINUX_BASELINE_LIBS = frozenset(
    {
        "libGL.so.1",
        "libICE.so.6",
        "libSM.so.6",
        "libX11.so.6",
        "libXext.so.6",
        "libXrender.so.1",
        "libanl.so.1",
        "libatomic.so.1",
        "libc.so.6",
        "libdl.so.2",
        "libexpat.so.1",
        "libgcc_s.so.1",
        "libglib-2.0.so.0",
        "libgobject-2.0.so.0",
        "libgthread-2.0.so.0",
        "libm.so.6",
        "libmvec.so.1",
        "libnsl.so.1",
        "libpthread.so.0",
        "libresolv.so.2",
        "librt.so.1",
        "libstdc++.so.6",
        "libutil.so.1",
        "libz.so.1",
    }
)

# musl's own guarantee is far narrower -- verified the same way, against
# `musllinux-policy.json`: `musllinux_1_2` whitelists only `libc.so` and
# `libz.so.1`. `libffi` is absent from both tables; nothing here special-
# cases it by name, since the point is to catch whatever is missing, not
# just the one gap that happened to be found first.
_MUSLLINUX_BASELINE_LIBS = frozenset({"libc.so", "libz.so.1"})


def _baseline_libs(floor: str) -> frozenset[str]:
    return (
        _MUSLLINUX_BASELINE_LIBS
        if floor.startswith("musllinux")
        else _MANYLINUX_BASELINE_LIBS
    )


def _dynamic_needed_libs(binary: Path) -> list[str]:
    """The `DT_NEEDED` entries in `binary`'s own `.dynamic` section, in
    file order -- the same table `auditwheel` reads off a wheel's `.so`
    files to decide what needs vendoring, read here with `pyelftools`
    (already a dependency, D12) instead of shelling out to a tool that
    only accepts `.whl` files.

    `[]` for a statically-linked binary (`mipsel`'s `-static` link, or any
    future one): a static binary carries no `.dynamic` section at all,
    which is a legitimate, fully-portable case rather than a read
    failure -- nothing to repair. `ELFError` is swallowed for the same
    reason `_required_glibc()` swallows it: this check runs after
    `verify_unix_output()` has already read a valid ELF header, so a
    parse failure here would only ever be this function's own bug, not a
    build outcome worth surfacing as one.
    """
    from elftools.common.exceptions import ELFError
    from elftools.elf.dynamic import DynamicSection
    from elftools.elf.elffile import ELFFile

    try:
        with binary.open("rb") as handle:
            elf = ELFFile(handle)
            dynamic = elf.get_section_by_name(".dynamic")
            if not isinstance(dynamic, DynamicSection):
                return []
            return [
                # DynamicTag.__init__ sets .needed via a runtime setattr()
                # for DT_NEEDED specifically (pyelftools' own "_HANDLED_TAGS"
                # convenience-attribute mechanism) -- real at runtime, just
                # invisible to pyright's static analysis.
                tag.needed  # pyright: ignore[reportAttributeAccessIssue]
                for tag in dynamic.iter_tags()
                if tag.entry.d_tag == "DT_NEEDED"
            ]
    except ELFError:
        return []


def _elf_interpreter_name(binary: Path) -> str | None:
    """The basename of `binary`'s own `PT_INTERP` segment -- the dynamic
    linker the kernel invokes to start it at all (`/lib/ld-linux-
    armhf.so.3`, `/lib64/ld-linux-x86-64.so.2`, musl's `/lib/ld-musl-
    <arch>.so.1`) -- or `None` for a static binary, which has no such
    segment.

    Live-caught on a real `manylinux_2_31_armv7l` build (2026-08-29):
    32-bit ARM glibc's own `ld.so` also lists itself as a `DT_NEEDED`
    entry, not just the usual `PT_INTERP` -- `_dynamic_needed_libs()`
    picked up `ld-linux-armhf.so.3` alongside `libffi.so.7`, and `ldd`'s
    own output for it carries no `name => path` arrow at all (it maps
    itself rather than being resolved through the search path the way
    every other entry is), so the repair script's `awk` pattern found
    nothing and failed loudly rather than silently mis-copying anything.
    Excluded here rather than added to either baseline table: the loader
    is guaranteed present on any host that can execute an ELF at all
    (the kernel itself won't start the process without it, before any
    `RPATH` this repair step sets is ever consulted), so it is not a
    library `_MANYLINUX_BASELINE_LIBS`/`_MUSLLINUX_BASELINE_LIBS` need to
    know the name of -- that guarantee holds architecture-wide, not just
    for the one cell that happened to surface it.
    """
    from elftools.common.exceptions import ELFError
    from elftools.elf.elffile import ELFFile
    from elftools.elf.segments import InterpSegment

    try:
        with binary.open("rb") as handle:
            elf = ELFFile(handle)
            for segment in elf.iter_segments():
                if isinstance(segment, InterpSegment):
                    return PurePosixPath(segment.get_interp_name()).name
    except ELFError:
        return None
    return None


def _non_baseline_needed_libs(target: str, binary: Path) -> list[str]:
    floor, _arch = _split_target(target)
    baseline = _baseline_libs(floor)
    interpreter = _elf_interpreter_name(binary)
    return [
        name
        for name in _dynamic_needed_libs(binary)
        if name not in baseline and name != interpreter
    ]


def repair_unix_binary(
    target: str,
    binary: Path,
    *,
    timeout: float | None,
    container: Any,
) -> None:
    """`cibuildmp`'s own `auditwheel repair`, for the one artifact type
    `auditwheel` cannot touch at all: a bare executable rather than a
    wheel.

    A no-op whenever `_non_baseline_needed_libs()` finds nothing -- every
    target today, for two different reasons (`UNIX_ARCH_SETTINGS`'s own
    header): `mipsel`/every `musllinux` cell link fully static and have
    no `.dynamic` section to find anything in, and every `manylinux`
    cell links `libffi.a` (`MICROPY_STANDALONE=1`) rather than a shared
    `libffi.so`, so it was never a `DT_NEEDED` entry regardless of
    `-static`. Neither case reaches a `docker run` here at all.

    Otherwise runs `ldd`/`patchelf` **inside `docker_image`**, the same
    image `binary` was just built in -- not on the host, which is the
    reason this exists: only the container's own dynamic linker can
    resolve where `libffi.so.6` (or whatever else shows up here in the
    future) actually lives, and only that container is guaranteed to
    carry `patchelf` at all. Both tools are already present in every
    `pypa/manylinux*`/`pypa/musllinux*` base image without cibuildmp (or
    cibuildwheel, whose own default `repair-wheel-command` is bare
    `auditwheel repair -w {dest_dir} {wheel}`, installing neither tool
    itself anywhere in its own source) ever installing either -- verified
    by that absence, not assumed.

    For each non-baseline `DT_NEEDED` name: resolve it with `ldd` (the
    same resolution the dynamic linker itself would do at container run
    time, so this cannot disagree with what the binary actually loads),
    copy the real file it points at into a `lib/` directory next to
    `binary`, then `patchelf --set-rpath '$ORIGIN/lib'` the binary once,
    after every copy. `$ORIGIN` is `patchelf`'s/the ELF loader's own
    runtime token (resolved relative to the *binary's* own location at
    load time), not a shell variable -- single-quoted here so bash never
    touches it.

    **Required `container`** -- every usermod port builds through
    `Container` now (record 0095's own addenda 8-12 landed the last of the
    six). `binary` is always the `staging` copy (`build_unix()`'s own
    call), the one read-write mount the container gets, so the `lib/`
    directory this writes lands on the host for free, the same way the
    binary itself already does -- no separate copy-out step, no new mount.
    """
    needed = _non_baseline_needed_libs(target, binary)
    if not needed:
        return

    lib_dir = binary.parent / "lib"
    bin_q = shlex.quote(binary.as_posix())
    lib_dir_q = shlex.quote(lib_dir.as_posix())
    libs_q = " ".join(shlex.quote(name) for name in needed)
    script = f"""set -eux
mkdir -p {lib_dir_q}
for lib in {libs_q}; do
    src=$(ldd {bin_q} | awk -v want="$lib" '$1 == want {{ print $3; exit }}')
    if [ -z "$src" ] || [ ! -e "$src" ]; then
        echo "repair: ldd could not resolve $lib for {bin_q}" >&2
        exit 1
    fi
    cp -L "$src" {lib_dir_q}/"$lib"
done
patchelf --set-rpath '$ORIGIN/lib' {bin_q}
"""
    container.call(["bash", "-c", script], workdir=binary.parent, timeout=timeout)


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

    **A no-op only for `mipsel` and every `musllinux` target now**
    (`UNIX_ARCH_SETTINGS`'s own header) -- their `-static` link leaves
    `_required_glibc()` nothing to read (`required is None`, below).
    Every `manylinux` target links ordinary dynamic glibc again, so the
    live `GLIBC_2.28`-style check this docstring describes is real once
    more, not merely "still correct if it ever comes back" -- it did.
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
    or mis-registered `ARCH_OCI_PLATFORM` entry, a `CIBMP_*_DOCKER_IMAGE`
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
    package_dir: Path | None = None,
    staging: Path | None = None,
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
    `manylinux_2_41_mipsel` -- correct, not missing: the compiler in the container
    already targets the right architecture. And a mismatch cannot be
    caught by the build succeeding, so `verify_unix_output()` below
    checks the finished ELF's own machine type against the identifier;
    an image resolved for the wrong platform otherwise yields a working
    binary of the wrong architecture, which is the specific trap 0043 was
    written about.

    `toolchain_root`/`quiet` are accepted only for the same call shape
    every `build_<port>()` shares (`orchestrate.py`'s `build_one()`
    passes them uniformly); neither is used on this Docker-only path.
    `package_dir`, when given, is bind-mounted alongside `USER_C_MODULES`
    itself -- see `_project_mounts()`'s own docstring for why.

    One more step runs after both verifications pass:
    `repair_unix_binary()` vendors any shared library the binary needs
    that is not part of its own floor's baseline (`libffi` being the one
    found so far) into a `lib/` directory beside it and points the binary
    at that directory with `patchelf --set-rpath` -- this project's own
    `auditwheel repair`, for the one artifact type `auditwheel` itself
    cannot touch. See that function's own docstring for the full
    reasoning; a no-op for every target that needs nothing repaired --
    every arch today, but for two different reasons now that `-static`
    is not universal (`UNIX_ARCH_SETTINGS`'s own header): `mipsel` and
    every `musllinux` cell have no `.dynamic` section at all for
    `_dynamic_needed_libs()` to find anything in, and every `manylinux`
    cell links `libffi.a` (`MICROPY_STANDALONE=1`, unconditional) rather
    than a shared `libffi.so`, so `libffi` was never a `DT_NEEDED` entry
    to begin with, static binary or not. Left wired in rather than
    removed: still correct for whatever a genuinely dynamically-linked
    `libffi` would look like, and still the right step if that ever
    happens again.
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

    settings = unix_arch_settings(opts.target)
    oci_platform = dockerrun.platform_for("unix", opts.target)
    linux32 = dockerrun.needs_linux32("unix", opts.target)
    timeout = dockerrun.timeout_for("unix", opts.target)

    if staging is None:
        msg = (
            "unix builds need a staging directory to hand the artifact back "
            "through ([0095]); orchestrate.build_one() provides one"
        )
        raise UsermodBuildError(msg)

    # One container for the whole build ([0095]), where there used to be a
    # separate `docker run --rm` per step -- deplibs, two `cflags` probes,
    # `mpy-cross`, the port's own `make`, and `repair_unix_binary()`, six in
    # all. Beyond the obvious saving, it is what makes the probes *mean*
    # something: they now ask the very compiler that is about to run,
    # inside the same filesystem, rather than a fresh container of the same
    # image and a hope that nothing differs.
    #
    # `mpy_dir` is the overlay's lower layer, so the checkout is visible at
    # its own host path and writable *inside*, and the host copy is never
    # touched. `staging` and the user's own project are ordinary read-write
    # and read-only mounts respectively: the build reads the module's
    # sources and writes exactly one thing outward, the finished artifact.
    with dockerrun.overlay_container(
        mpy_dir,
        image=docker_image,
        oci_platform=oci_platform,
        linux32=linux32,
        mounts=[staging, *_project_mounts(opts, package_dir)],
    ) as container:
        container.overlay(mpy_dir)
        return _build_unix_in(
            opts,
            mpy_dir,
            container=container,
            staging=staging,
            settings=settings,
            timeout=timeout,
        )


def _project_mounts(opts: UnixBuildOptions, package_dir: Path | None) -> list[Path]:
    """The user's own project, mounted so a module whose sources reach
    outside `USER_C_MODULES` still resolves -- the same reasoning the
    pre-[0095] `usermod_mounts()` helper had for the same mount, minus
    `mpy_dir`, which arrives through the overlay instead (and minus
    `scratch_root()`, no longer mounted at all once every port stopped
    needing a host-visible build tree).

    No entry for `opts.user_c_modules` at all when it is empty (record
    0056's no-module build): `Path("")` is `Path(".")`, a *relative*
    path, and `docker run -v` rejects a relative mount source outright --
    there is also nothing there worth mounting once `USER_C_MODULES=`
    goes out empty."""
    mounts = [Path(opts.user_c_modules)] if opts.user_c_modules else []
    if package_dir is not None:
        mounts.append(package_dir.resolve())
    return mounts


def _build_unix_in(
    opts: UnixBuildOptions,
    mpy_dir: Path,
    *,
    container: Any,
    staging: Path,
    settings: UnixArchSettings,
    timeout: float | None,
) -> Path:
    """`build_unix()`'s own body, once the container exists."""
    from ... import dockerrun  # noqa: F401  -- re-exported names used below

    # `_riscv64_ffi_unported()`'s own comment: `deplibs`' entire job is
    # building `lib/libffi`, which is a hard `configure: error` on these
    # (tag, riscv64) pairs regardless of anything cibuildmp does --
    # running it would just fail before `MICROPY_PY_FFI=0` below ever
    # gets a chance to make it unnecessary.
    if settings.standalone and not _riscv64_ffi_unported(opts.target, opts.tag):
        run_unix_deplibs(opts, mpy_dir, container=container)

    # `unix_extra_cflags()`'s own candidates include `-Wno-error=
    # <diagnostic>` entries a *different* image's gcc needed ([0082]'s
    # own `unterminated-string-initialization`, gcc-15-only); naming an
    # unrecognized diagnostic is a hard `cc1: error`, not a no-op, so
    # what actually reaches `make` here has to be what the compiler that
    # runs it accepts, not the raw candidate list. See
    # `probe_supported_cflags()`'s own docstring.
    #
    # Two separate probes, not one shared between them: `mpy_cross`
    # below always builds with this image's own native `gcc` (a host
    # tool -- mpy-cross emits target-independent bytecode, so it is
    # never cross-compiled), while the main build below uses whatever
    # `settings.cross_compile` names. Identical for every arch but
    # `mipsel` (empty prefix, so both probe the same bare `gcc`), but
    # `mipsel`'s own image is a Bootlin cross-toolchain where those two
    # are genuinely different, and older, gcc's -- found live, sharing
    # one probe's result silently carried the native image gcc's
    # (>=15) verdict on `-Wno-error=unterminated-string-initialization`
    # into `mipsel-linux-gnu-gcc` (14.3.0), which does not accept it,
    # and the build failed exactly the way an unprobed flag would have.
    candidates = unix_extra_cflags(opts.target, opts.tag)
    mpy_cross_cflags = build_common.probe_supported_cflags(
        candidates,
        timeout=timeout,
        container=container,
    )
    build_cflags = (
        mpy_cross_cflags
        if not settings.cross_compile
        else build_common.probe_supported_cflags(
            candidates,
            compiler=f"{settings.cross_compile}gcc",
            timeout=timeout,
            container=container,
        )
    )

    mpy_cross = build_common.container_mpy_cross(
        mpy_dir,
        extra_cflags=mpy_cross_cflags,
        timeout=timeout,
        container=container,
    )
    container.call(
        unix_make_command(
            opts, mpy_dir, mpy_cross=mpy_cross, extra_cflags=build_cflags
        ),
        workdir=_unix_dir(mpy_dir),
        timeout=timeout,
    )

    # The binary exists only inside the container until this copy. `staging`
    # is the one read-write mount, so a plain `cp` inside is all it takes --
    # no `docker cp`, which cannot see a mount the container made itself
    # (see `Container.copy_out()`), and no host-side temporary directory.
    #
    # Copied *before* the checks below rather than after, because every one
    # of them reads the ELF with Python on the host, and there is no host
    # path to read until now.
    binary = staging / "micropython"
    container.call(
        ["cp", (opts.build_dir / "micropython").as_posix(), binary.as_posix()],
        workdir=_unix_dir(mpy_dir),
        timeout=timeout,
    )
    if not binary.exists():
        raise UsermodBuildError(
            f"unix/{opts.target}: build reported success but {binary} is missing"
        )
    verify_unix_output(opts.target, binary)
    verify_unix_floor(opts.target, binary)
    # Repair operates on the staged copy, not on the build tree: `staging`
    # is visible at the same path on both sides, so `ldd` resolves against
    # the container's own libraries (which is the whole point -- they are
    # the ones the binary was linked against) while the `lib/` it vendors
    # lands straight on the host beside the artifact, where
    # `unix_companions()` looks for it.
    repair_unix_binary(
        opts.target,
        binary,
        timeout=timeout,
        container=container,
    )
    return binary


def unix_companions(produced: Path) -> list[Path]:
    """The shared objects `repair_unix_binary()` vendored, and only those.

    `ports/unix/build-<identifier>/lib/` is **the port's own object
    directory** -- `mbedtls/`, `berkeley-db-1.xx/`, `littlefs/`,
    `oofatfs/`, each full of `.o`/`.P` intermediates -- and
    `repair_unix_binary()` drops its `cp -L "$src" lib/"$lib"` output
    straight into it. So "the `lib/` beside the binary" is two unrelated
    things sharing a name, and record 0070's fix (copy the whole
    directory) shipped both: a real collected `manylinux_2_28_x86_64`
    artifact carried 2.0M of `lib/`, of which 40K was the `libffi.so.6`
    the binary actually needs and 94 `.o` + 94 `.P` files were not.
    Measured on a downloaded CI artifact, not estimated.

    The two are cleanly separable, from `repair_unix_binary()`'s own
    shell: what it vendors is always a plain *file* directly in `lib/`,
    named after a `DT_NEEDED` entry, while every port intermediate lives
    one directory deeper. Returning the files preserves the
    `$ORIGIN/lib` layout the rpath needs -- `build_one()` copies each
    companion to its own path relative to the binary -- without carrying
    the object tree along with it. Record 0079.
    """
    lib_dir = produced.parent / "lib"
    if not lib_dir.is_dir():
        return []
    return sorted(p for p in lib_dir.iterdir() if p.is_file() and ".so" in p.name)

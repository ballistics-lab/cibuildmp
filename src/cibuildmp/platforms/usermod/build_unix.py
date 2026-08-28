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
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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


def _split_target(target: str) -> tuple[str, str]:
    from ... import dockerrun

    return dockerrun.split_tag(target)


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

    mpy_cross = build_common.container_mpy_cross(
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

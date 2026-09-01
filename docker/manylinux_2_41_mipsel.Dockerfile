# `unix` build image for the **manylinux_2_41_mipsel** cell -- the one documented
# exception to record 0043's native-image model, and the only `unix`
# image that still cross-compiles.
#
# There is nothing to be native to. pypa publishes no mipsel image, PEP
# 600 defines no `manylinux_*_mipsel` tag, and Docker has no official
# image for 32-bit mipsel either. So this cell keeps an amd64 host with
# a cross-toolchain, and says so plainly instead of pretending to a
# floor it cannot claim.
#
# **This file was `docker/manylinux_2_39_mipsel.Dockerfile` until the
# toolchain change below.** `2_39` was the version of apt's own
# `libc6-dev-mipsel-cross` (`2.39-0ubuntu8cross2`); the Bootlin tarball
# pinned below bundles glibc `2.41-70`, so the name moved with it rather
# than the toolchain being frozen to preserve a name -- record 0031's own
# principle, that a real PEP 600 tag must not keep claiming a floor its
# image no longer has. Record 0068 has the whole decision.
#
# The rename is a **breaking change to the identifier**: every
# `*-manylinux_2_39_mipsel` becomes `*-manylinux_2_41_mipsel`, in this
# repo and in any caller naming it (`micropython-bclibc` and
# `micropython-wasm3` both do).
#
# It has no `resources/pinned_pypa_images.toml` entry because that file
# mirrors upstream's own pins, and this base is not one of them.
#
# Content is the former docker/unix-manylinux-mipsel.Dockerfile, with
# its apt cross-toolchain replaced (see below) -- including
# `libltdl-dev`, which is not the cross-compiler but the fix for
# `deplibs`' own `./autogen.sh` failing with "possibly undefined macro:
# LT_SYS_SYMBOL_USCORE" (D25's sixth real bug; autoconf/automake/libtool
# alone do not ship `ltdl.m4`). This arch still needs
# `MICROPY_STANDALONE=1` and its static vendored libffi, since unlike
# every native cell it has no system libffi for its target.
#
# Build: docker buildx build --platform=linux/amd64 \
#          -t manylinux_2_41_mipsel \
#          -f docker/manylinux_2_41_mipsel.Dockerfile .
# Use:   CIBMP_UNIX_MANYLINUX_2_41_MIPSEL_DOCKER_IMAGE=manylinux_2_41_mipsel cibuildmp ...
FROM ubuntu:24.04

# Host-side build tooling only. The cross-toolchain no longer comes from
# apt at all: `gcc-mipsel-linux-gnu` and `libc6-dev-mipsel-cross` are
# **gone from Ubuntu's archive**, not merely bumped -- Debian 13
# "Trixie" is the first Debian release with no `mipsel` port
# (https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=1043114: the 2GB
# user-space limit, the unresolved Y2038 problem, and no porter
# manpower), and Ubuntu's own `gcc-*-cross-mipsen` packages are built
# from that same Debian source. The `ubuntu:24.04` -> `26.04` bump that
# exposed this failed with "Package 'gcc-mipsel-linux-gnu' has no
# installation candidate"; record 0068 has the whole incident.
#
# `curl`/`xz-utils`/`ca-certificates` exist only to fetch the toolchain
# tarball below.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3 \
    libltdl-dev \
    libtool \
    ca-certificates \
    curl \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

# The cross-toolchain, pinned by version + URL + sha256 -- the same
# model `arm_embedded`/`riscv_embedded`/`xtensa_esp`/`xtensa_lx106`
# (record 0025) already use, and the whole point of the change: this
# image no longer depends on an apt archive for an architecture its
# upstream has abandoned. A pruned mirror or the next base-OS bump
# cannot take the compiler away again.
#
# Bootlin's releases are versioned by build date, not by glibc version.
# `2025.08-1` is the newest `mips32el` release and bundles gcc 14.3.0 /
# binutils 2.43.1 / glibc 2.41-70 (read from the tarball's own
# `README.txt`, not inferred from the release name). Record 0068's
# addendum chose the newest maintained release over
# `stable-2024.05-1`, which bundles glibc 2.39-74 and would have matched
# today's tag exactly -- freezing the toolchain to preserve a name is
# the wrong way round, so the name moves instead (see the ⚠️ above).
ARG BOOTLIN_RELEASE=mips32el--glibc--stable-2025.08-1
ARG BOOTLIN_SHA256=1085fe6b13d74205ef6e92d1d40fb3960bf6e4bad50555c723fa07416cb53c1c

# `relocate-sdk.sh` is Buildroot's own: the SDK is built against an
# absolute path and its wrapper resolves the sysroot relative to that,
# so extracting it anywhere else without running this leaves a compiler
# that cannot find its own headers.
#
# The `mipsel-linux-gnu-` wrappers are what keep this a Dockerfile-only
# change. Bootlin ships the `mipsel-linux-` and
# `mipsel-buildroot-linux-gnu-` prefixes;
# `UNIX_ARCH_SETTINGS["mipsel"].cross_compile` in
# `src/cibuildmp/platforms/usermod/build_unix.py` is `mipsel-linux-gnu-`,
# apt's own spelling. A generated wrapper per tool here beats editing a
# source constant, a fixture and every test that names it (record 0050's
# own "a FROM line and four symlinks" shape).
#
# Two-line `exec` scripts rather than symlinks, and that is not a style
# choice -- it is what a symlink actually did here. Every Bootlin
# frontend is Buildroot's `toolchain-wrapper`, which locates the real
# binary as *its own directory* (from `/proc/self/exe`, so it follows a
# symlink) plus *`argv[0]`'s basename* (so it does not) plus `.br_real`.
# A `mipsel-linux-gnu-gcc` symlink therefore sends it looking for
# `/opt/.../bin/mipsel-linux-gnu-gcc.br_real`, which does not exist:
# "No such file or directory", exit 2, caught by the `--version` check
# at the end of this very step. `exec`ing the real name instead leaves
# `argv[0]` as something the wrapper can resolve.
#
# `.br_real` files are skipped: they are the wrapper's own targets, not
# tools to be called directly.
RUN curl -fsSL -o /tmp/toolchain.tar.xz \
      "https://toolchains.bootlin.com/downloads/releases/toolchains/mips32el/tarballs/${BOOTLIN_RELEASE}.tar.xz" \
 && echo "${BOOTLIN_SHA256}  /tmp/toolchain.tar.xz" | sha256sum -c - \
 && tar -xJf /tmp/toolchain.tar.xz -C /opt \
 && rm /tmp/toolchain.tar.xz \
 && "/opt/${BOOTLIN_RELEASE}/relocate-sdk.sh" \
 && for tool in "/opt/${BOOTLIN_RELEASE}"/bin/mipsel-linux-*; do \
      case "$tool" in *.br_real) continue ;; esac ; \
      wrapper="/usr/local/bin/mipsel-linux-gnu-${tool##*/mipsel-linux-}" ; \
      printf '#!/bin/sh\nexec "%s" "$@"\n' "$tool" > "$wrapper" ; \
      chmod +x "$wrapper" ; \
    done \
 && mipsel-linux-gnu-gcc --version \
 && mipsel-linux-gnu-ld --version \
 && echo 'int main(void){return 0;}' > /tmp/probe.c \
 && mipsel-linux-gnu-gcc -static -o /tmp/probe /tmp/probe.c \
 && rm /tmp/probe.c /tmp/probe

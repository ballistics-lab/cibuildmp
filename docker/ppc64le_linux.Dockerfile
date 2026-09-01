# powerpc64le-linux-gnu -- `qemu`'s POWERNV9 board
#
# One of the six toolchain-group images record 0058 splits
# `natmod.Dockerfile` into. Keyed by the group, not the port: usermod `qemu` board `POWERNV9` only.
#
# `ubuntu:26.04`, not a pypa image -- `unix` builds on pypa's own
# ([0043]/[0044]) because those targets are native and need manylinux's
# glibc floor. Nothing here is.
#
# **The apt cross-toolchain (`gcc-powerpc64le-linux-gnu` +
# `libc6-dev-ppc64el-cross`) is gone, replaced by a pinned Bootlin
# tarball -- the same model `arm_embedded`/`riscv_embedded`/
# `xtensa_esp`/`xtensa_lx106` (record 0025) and `manylinux_2_41_mipsel`
# (record 0068) already use.** Not because the apt packages disappeared
# the way mipsel's did -- both are still in Ubuntu's `26.04` archive --
# but because the same `ubuntu:24.04` -> `26.04` bump that broke
# `natmod_host`'s multilib pairing (record 0068) broke this image too,
# differently: a real `POWERNV9` build (`ports/qemu`'s own `readline.c`,
# which every board links) fails at the final link with `undefined
# reference to '__snprintfieee128'`. That symbol is glibc's own
# powerpc64le long-double transition (IBM double-double -> IEEE
# binary128): the *native* `libc6-dev-ppc64el` on this base carries the
# compat symbol, the *cross* `libc6-dev-ppc64el-cross` built alongside
# `gcc-15-powerpc64le-linux-gnu` does not export it the same way, so a
# cross link asking for it fails where a native build on real
# `ppc64le` hardware would not. Nothing here was miscounted the way
# `natmod_host`'s multilib was: `docker build` never exercised a real
# link (`gcc --version` was the only proof this image's own `RUN` ever
# asked for, per 0058's own verification table -- see its own
# now-corrected claim that "nothing about the 32-bit path is fragile or
# distribution-specific" did not survive contact with real builds
# either), so this was found the same way -- downstream, by a real
# build, not by this repo's own CI.
#
# Bootlin's own `powerpc64le-power8` toolchain sidesteps the whole
# problem rather than patching around it: it is gcc 14.3.0 built
# against its own matched glibc `2.41-70` sysroot (read from the
# tarball's own `README.txt`, not inferred from the release name) --
# one Buildroot build, not Debian's split "native gcc + separately
# packaged -cross libc" pairing that let the two drift apart in the
# first place. `stable-2025.08-1` is the newest maintained release,
# same build wave as the mipsel tarball 0068 already pinned.
#
# `POWERNV9` needs its own real proof before this is trusted (see
# `build_qemu.py`'s own note that no board had ever built through this
# image for real before this incident) -- this `RUN` compiles and
# statically links the exact call shape that broke
# (`snprintf`/`%Lf` on a `long double`, `readline.c`'s own usage) through
# the Bootlin toolchain before the layer finishes, so a future toolchain
# bump that reintroduces this ABI mismatch fails `docker build` itself
# instead of staying green while a real firmware link quietly breaks.
#
# Build: docker build -t cibuildmp-ppc64le_linux -f docker/ppc64le_linux.Dockerfile .
FROM ubuntu:26.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Host-side build tooling only. `ca-certificates`/`curl`/`xz-utils` exist
# only to fetch the toolchain tarball below.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    python3 \
    python3-pyelftools \
    ca-certificates \
    curl \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

# The cross-toolchain, pinned by version + URL + sha256.
ARG BOOTLIN_RELEASE=powerpc64le-power8--glibc--stable-2025.08-1
ARG BOOTLIN_SHA256=819c8dee94b1baff33943f3b01d669ea794a825e7b4cbead340ad5de8cff6baa

# `relocate-sdk.sh` is Buildroot's own: the SDK is built against an
# absolute path and its wrapper resolves the sysroot relative to that,
# so extracting it anywhere else without running this leaves a compiler
# that cannot find its own headers.
#
# The `powerpc64le-linux-gnu-` wrappers are what keep this a
# Dockerfile-only change. Bootlin ships the `powerpc64le-linux-` and
# `powerpc64le-buildroot-linux-gnu-` prefixes; `ports/qemu/Makefile`'s
# own `CROSS_COMPILE ?= powerpc64le-linux-gnu-` for `POWERNV9`
# (`QEMU_BOARD_CROSS["POWERNV9"]` in
# `src/cibuildmp/platforms/usermod/build_qemu.py`) is apt's own
# spelling. A generated wrapper per tool here beats editing a source
# constant, a fixture and every test that names it (record 0050's own
# "a FROM line and four symlinks" shape) -- exactly mipsel's own
# reasoning in record 0068.
#
# Two-line `exec` scripts rather than symlinks, and that is not a style
# choice -- it is what a symlink actually did for mipsel. Every Bootlin
# frontend is Buildroot's `toolchain-wrapper`, which locates the real
# binary as *its own directory* (from `/proc/self/exe`, so it follows a
# symlink) plus *`argv[0]`'s basename* (so it does not) plus `.br_real`.
# A `powerpc64le-linux-gnu-gcc` symlink therefore sends it looking for
# `/opt/.../bin/powerpc64le-linux-gnu-gcc.br_real`, which does not
# exist: "No such file or directory", exit 2, caught by the `--version`
# check at the end of this very step. `exec`ing the real name instead
# leaves `argv[0]` as something the wrapper can resolve.
#
# `.br_real` files and the versioned `powerpc64le-linux-gcc-14.3.0`
# alias are skipped: the former are the wrapper's own targets, the
# latter is a duplicate of the plain `-gcc` name, neither is a tool to
# wrap a second time.
RUN curl -fsSL -o /tmp/toolchain.tar.xz \
      "https://toolchains.bootlin.com/downloads/releases/toolchains/powerpc64le-power8/tarballs/${BOOTLIN_RELEASE}.tar.xz" \
 && echo "${BOOTLIN_SHA256}  /tmp/toolchain.tar.xz" | sha256sum -c - \
 && tar -xJf /tmp/toolchain.tar.xz -C /opt \
 && rm /tmp/toolchain.tar.xz \
 && "/opt/${BOOTLIN_RELEASE}/relocate-sdk.sh" \
 && for tool in "/opt/${BOOTLIN_RELEASE}"/bin/powerpc64le-linux-*; do \
      case "$tool" in *.br_real|*-gcc-14.3.0) continue ;; esac ; \
      wrapper="/usr/local/bin/powerpc64le-linux-gnu-${tool##*/powerpc64le-linux-}" ; \
      printf '#!/bin/sh\nexec "%s" "$@"\n' "$tool" > "$wrapper" ; \
      chmod +x "$wrapper" ; \
    done \
 && powerpc64le-linux-gnu-gcc --version \
 && powerpc64le-linux-gnu-ld --version \
 && echo '#include <stdio.h>' > /tmp/probe.c \
 && echo 'int main(void){char b[32];long double v=1.5L;snprintf(b,sizeof b,"%Lf",v);return (int)b[0]-(int)b[0];}' >> /tmp/probe.c \
 && powerpc64le-linux-gnu-gcc -static -o /tmp/probe /tmp/probe.c \
 && rm /tmp/probe.c /tmp/probe

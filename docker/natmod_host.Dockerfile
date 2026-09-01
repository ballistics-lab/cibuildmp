# natmod's own host arches -- `x86` and `x64`
#
# One of the six toolchain-group images record 0058 splits
# `natmod.Dockerfile` into. Keyed by the group, not the port: natmod `x86`/`x64` only.
#
# `ubuntu:26.04`, not a pypa image -- `unix` builds on pypa's own
# ([0043]/[0044]) because those targets are native and need manylinux's
# glibc floor. Nothing here is.
#
# Build: docker build -t cibuildmp-natmod_host -f docker/natmod_host.Dockerfile .
FROM ubuntu:26.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# The one image here that cross-compiles nothing. natmod's `x86`/`x64`
# targets link a `.mpy` for the machine the build runs on, so what they
# need is a host gcc plus the 32-bit half of it -- which is why these two
# arches were the reason `natmod.Dockerfile` carried multilib and an i386
# architecture at all, and why they are their own group rather than
# riding along in one of the cross images.
#
# `gcc-multilib` + `linux-libc-dev:i386` is the `-m32` path; `gcc-i686-
# linux-gnu` is the prefixed one. Both are kept, and genuinely both are
# live -- record 0058 already counted exactly this split while choosing
# this image's own package list (`x86 {'': 22, 'i686-linux-gnu-': 2}`,
# its own verification table calling both proven): upstream's own
# `py/dynruntime.mk` switches `x86`'s `CROSS` from empty (`-m32`, plain
# host gcc) to `i686-linux-gnu-` starting at v1.29.0 -- "depending on
# tag" means depending on *which MicroPython version*, not this
# project's own natmod ABI tag.
#
# It was `gcc-13-multilib` -- correct on `ubuntu:24.04`, whose
# `build-essential` also pulls gcc 13 -- until the `ubuntu:26.04` bump
# moved `build-essential`'s own gcc to 15 without this pin following it:
# every `x86` build still on the `-m32` path (every supported tag through
# v1.28.0) that needs anything from libgcc (soft-float, 64-bit-arithmetic
# helpers) links against gcc 15's 64-bit-only `libgcc.a` (no matching
# `gcc-15-multilib` installed) and fails with "LinkError: incompatible
# arch". `docker build`, `verify-docker-images`, and even a *real* `x86`
# natmod build all stayed green throughout -- but every one of them
# (`test-upstream-natmod.yml`, `build-examples.yml`) pins `v1.29.0` or
# newer, so every `x86` build this repo's own CI ever ran used the
# *other*, cross-prefixed path, which never touches this image's
# multilib at all (`gcc-i686-linux-gnu` is a self-contained cross
# toolchain, its own `libgcc` always matches its own version). A
# trivial module (`examples/template`) would not have caught this even
# on the right tag -- it never references anything from libgcc, so
# `mpy_ld.py` never loads the archive at all. Found only downstream, by
# `micropython-wasm3`'s own CI, pinned to `v1.28.0`.
#
# Repinned to the unversioned `gcc-multilib` metapackage -- matching what
# this Dockerfile's own comment already pointed at, upstream's own
# `tools/ci.sh` installing plain `gcc-multilib` for the identical job
# (`ci_unix_32bit_setup`) -- so it tracks whatever gcc `build-essential`
# resolves to on this base image and the next one, instead of a version
# that has to be bumped by hand in lockstep.
#
# `ca-certificates`/`curl` are not needed to build this image's own
# toolchain (nothing here is downloaded, unlike the other five toolchain
# groups) -- they are here because a project's own `pre-build-command`
# runs inside whichever image its arch resolves to, and one that fetches
# something over HTTPS (`examples/wasm2mpy`'s own wabt install) needs
# both. The monolithic `natmod.Dockerfile` this group was split out of
# carried them for its own toolchain downloads and every arch got them
# for free; splitting the image means this arch has to ask for them on
# its own merits. Found live: `wasm2mpy` failed with "curl: command not
# found" on `x86` the first time this group's own image ran it for real.
RUN set -eux; \
    dpkg --add-architecture i386; \
    sed -i '/^Types: deb$/a Architectures: amd64 i386' \
        /etc/apt/sources.list.d/ubuntu.sources; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential \
        git \
        ca-certificates \
        curl \
        gcc-multilib \
        gcc-i686-linux-gnu \
        linux-libc-dev:i386 \
        python3 \
        python3-pyelftools; \
    rm -rf /var/lib/apt/lists/*; \
    python3 -c "from elftools.elf.elffile import ELFFile"

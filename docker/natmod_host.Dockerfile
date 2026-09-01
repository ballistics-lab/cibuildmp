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
# A real, version-specific `gcc-<N>-multilib` + `linux-libc-dev:i386` is
# the `-m32` path; `gcc-i686-linux-gnu` is the prefixed one. Both are
# kept, and genuinely both are live -- record 0058 already counted
# exactly this split while choosing this image's own package list
# (`x86 {'': 22, 'i686-linux-gnu-': 2}`, its own verification table
# calling both proven): upstream's own `py/dynruntime.mk` switches
# `x86`'s `CROSS` from empty (`-m32`, plain host gcc) to
# `i686-linux-gnu-` starting at v1.29.0 -- "depending on tag" means
# depending on *which MicroPython version*, not this project's own
# natmod ABI tag.
#
# It was hardcoded to `gcc-13-multilib` -- correct on `ubuntu:24.04`,
# whose `build-essential` also pulls gcc 13 -- until the `ubuntu:26.04`
# bump moved `build-essential`'s own gcc to 15 without this pin
# following it: every `x86` build still on the `-m32` path (every
# supported tag through v1.28.0) that needs anything from libgcc
# (soft-float, 64-bit-arithmetic helpers) links against gcc 15's
# 64-bit-only `libgcc.a` (no matching `gcc-15-multilib` installed) and
# fails with "LinkError: incompatible arch". `docker build`,
# `verify-docker-images`, and even a *real* `x86` natmod build all
# stayed green throughout -- but every one of them
# (`test-upstream-natmod.yml`, `build-examples.yml`) pins `v1.29.0` or
# newer, so every `x86` build this repo's own CI ever ran used the
# *other*, cross-prefixed path, which never touches this image's
# multilib at all (`gcc-i686-linux-gnu` is a self-contained cross
# toolchain, its own `libgcc` always matches its own version). A
# trivial module (`examples/template`, or even upstream's own
# `examples/natmod/features0`) would not have caught this on the right
# tag either -- neither references anything from libgcc, so
# `mpy_ld.py` never loads the archive at all. Found only downstream, by
# `micropython-wasm3`'s own CI, pinned to `v1.28.0`.
#
# **First attempt at a fix, reverted here: the unversioned `gcc-multilib`
# metapackage.** It matched what this Dockerfile's own comment already
# said upstream's `tools/ci.sh` installs for the identical job, and
# looked like it would track whatever gcc `build-essential` resolves to
# without needing a version bumped by hand. It does not build: apt
# reports `gcc-multilib:amd64=4:15.2.0-5ubuntu1` (the metapackage)
# **Conflicts** `gcc-15-i686-linux-gnu` -- which `gcc-i686-linux-gnu`
# (unversioned, also resolving to the `15` build) already pulls in --
# so the two packages this image has always installed side by side
# cannot both be satisfied through the metapackage on this base.
# Upstream's own `tools/ci.sh` never combines the two in one image, so
# it never meets this conflict; this image always has.
#
# Fixed instead by computing the real, version-specific package name at
# build time -- `gcc-$(gcc -dumpversion | cut -d. -f1)-multilib` --
# which is exactly the shape that already worked (`gcc-13-multilib`),
# just no longer typed by hand: whatever `build-essential` resolves to
# on this base image or the next one is what gets asked for, and the
# real per-version package (unlike the metapackage) declares no such
# conflict with `gcc-i686-linux-gnu`.
#
# This `RUN` now proves both toolchains actually link, not just that apt
# considered them installed: an explicit 64-bit multiply (no native i386
# instruction for it, so it unconditionally needs `__muldi3` from libgcc)
# is compiled and linked through `gcc -m32` and through
# `i686-linux-gnu-gcc` before this layer finishes.
#
# `-nostartfiles -nostdlib -Wl,-e,mul64 ... -lgcc`, not a plain
# `-shared`/executable link -- found live, the first version of this
# check (`gcc -shared -fPIC`) failed `i686-linux-gnu-gcc` on a missing
# `crti.o`, a real gap (this image never installs a full i686 cross
# sysroot, only `gcc-i686-linux-gnu` itself) but the wrong one to chase:
# `mpy_ld.py` never asks the system linker for a runnable ELF, shared or
# not, only for `libgcc.a`'s own member objects to resolve a natmod's
# undefined symbols, so this image never needed a full sysroot for real
# natmod builds either. `-nostartfiles -nostdlib` skips every crt object
# a real link would need, `-Wl,-e,mul64` gives the linker an entry point
# so it does not go looking for the also-absent `_start`, and `-lgcc`
# is the one library still on the command line -- so this fails exactly
# when `__muldi3` cannot be resolved from it, and nothing else. Verified
# against this exact failure mode locally first, on a host with no
# 32-bit multilib either: `ld: skipping incompatible .../libgcc.a when
# searching for -lgcc` -- the same error class the real incident hit.
#
# A future base bump that breaks either toolchain's own libgcc match
# fails `docker build` itself -- wherever it runs, not just a job that
# happens to run the image afterward -- instead of staying green while
# the real link quietly breaks the way this incident did the first time.
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
        gcc-i686-linux-gnu \
        linux-libc-dev:i386 \
        python3 \
        python3-pyelftools; \
    apt-get install -y --no-install-recommends \
        "gcc-$(gcc -dumpversion | cut -d. -f1)-multilib"; \
    rm -rf /var/lib/apt/lists/*; \
    python3 -c "from elftools.elf.elffile import ELFFile"; \
    echo 'long long mul64(long long a, long long b) { return a * b; }' > /tmp/probe.c; \
    gcc -m32 -nostartfiles -nostdlib -Wl,-e,mul64 /tmp/probe.c -lgcc -o /tmp/probe-m32; \
    i686-linux-gnu-gcc -nostartfiles -nostdlib -Wl,-e,mul64 /tmp/probe.c -lgcc -o /tmp/probe-cross; \
    rm -f /tmp/probe.c /tmp/probe-m32 /tmp/probe-cross

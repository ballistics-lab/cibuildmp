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
# linux-gnu` is the prefixed one. Both are kept because `dynruntime.mk`'s
# `x86` row reaches for either depending on tag -- upstream's own
# `tools/ci.sh` installs plain `gcc-multilib` for the same job
# (`ci_unix_32bit_setup`), which this now matches exactly rather than
# pinning a version by hand. It was `gcc-13-multilib` -- correct on
# `ubuntu:24.04`, whose `build-essential` also pulls gcc 13 -- until the
# `ubuntu:26.04` bump moved `build-essential`'s own gcc to 15 without
# this pin following it: `-m32` then linked against gcc 15's 64-bit-only
# `libgcc.a` (no matching `gcc-15-multilib` installed), failing every
# `x86` build with "LinkError: incompatible arch". `docker build` and
# `verify-docker-images` both stayed green throughout -- `apt install
# gcc-13-multilib` succeeds regardless of which gcc is default, and
# neither this image nor `test-upstream-natmod.yml` (x64 and armv7emsp
# only) ever actually links an `x86` binary -- so this was only caught
# downstream, by `micropython-wasm3`'s own CI (which builds every arch,
# `x86` included). The unversioned metapackage is what upstream's own
# comparison already pointed at: it tracks whatever gcc `build-essential`
# resolves to on the base image, on this Ubuntu bump and the next one.
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

# arm-none-eabi -- every Cortex-M/A target this project builds
#
# One of the six toolchain-group images record 0058 splits
# `natmod.Dockerfile` into. The group, not the port, is what an image is
# keyed by: natmod `armv6m`/`armv7m`/`armv7emsp`/`armv7emdp`, usermod `rp2`,
# `stm32`, `samd`, `mimxrt`, `nrf`, `renesas-ra`, `cc3200`, `alif`,
# `psoc-edge`, and `qemu`'s six ARM boards --
# all resolve here, so this file exists once instead of once per port.
#
# `ubuntu:26.04`, not a pypa image. `unix` builds on pypa's own
# ([0043]/[0044]) because those targets are genuinely native and need
# manylinux's glibc floor; nothing here is. A cross toolchain is a
# tarball either way, and `manylinux_2_28_x86_64` is 589 MB compressed
# before one is added -- its CPython set, auditwheel and glibc floor buy
# a bare-metal `.elf` nothing at all.
#
# Build: docker build -t cibuildmp-arm_embedded -f docker/arm_embedded.Dockerfile .
# Use:   CIBMP_..._DOCKER_IMAGE=cibuildmp-arm_embedded cibuildmp ...
FROM ubuntu:26.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# The pin, as named build args rather than buried in the RUN below:
# `bin/update_docker.py` can rewrite an ARG line, and record 0058 leaves
# moving these into `resources/` open -- a `--build-arg` is the seam that
# makes that a data change rather than a Dockerfile edit.
ARG TOOLCHAIN_URL="https://github.com/xpack-dev-tools/arm-none-eabi-gcc-xpack/releases/download/v15.2.1-1.1/xpack-arm-none-eabi-gcc-15.2.1-1.1-linux-x64.tar.gz"
ARG TOOLCHAIN_SHA256="da6a49ad4003944b823c6c93702a8787c922ab34bd7e918ec0eaf6933a9b1ff6"

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl xz-utils; \
    rm -rf /var/lib/apt/lists/*; \
    mkdir -p /opt/toolchains/arm-none-eabi; \
    curl -fsSL -o /tmp/tc.tar "$TOOLCHAIN_URL"; \
    # Verified, not merely fetched: a third-party tarball every build then
    # runs a compiler out of. "It downloaded" and "it is the artifact that
    # was pinned" are different claims.
    echo "$TOOLCHAIN_SHA256  /tmp/tc.tar" | sha256sum -c -; \
    # --strip-components=1: each tarball has one versioned top-level
    # directory, and flattening it keeps PATH free of version numbers, so
    # a bump is one ARG and no other edit.
    tar -xf /tmp/tc.tar --strip-components=1 -C /opt/toolchains/arm-none-eabi; \
    rm -f /tmp/tc.tar

# The build environment MicroPython's own makefiles need, and nothing
# else. `python3-pyelftools` is `mpy_ld.py`'s only third-party import
# (record 0012's addendum -- the `ar` it used to name alongside is not
# imported by anything, at any tag). Its own layer, last, so adding to it
# never invalidates the toolchain above.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential \
        git \
        python3 \
        python3-pyelftools \
        cmake; \
    rm -rf /var/lib/apt/lists/*; \
    python3 -c "from elftools.elf.elffile import ELFFile"

# cmake is here and not in the other three because `rp2` is the only ARM
# port that needs it -- `ports/rp2/Makefile` shells out to cmake, which
# then pulls pico-sdk from MicroPython's own `lib/`, not from a vendored
# copy of its own (verified live by `build-usermod-rp2040`, whose header
# records the same finding). Every other ARM port here is plain make.
#
# What is deliberately NOT installed: `gcc-arm-none-eabi`,
# `libnewlib-arm-none-eabi` and `libstdc++-arm-none-eabi-newlib`, which
# the `build-usermod-rp2040` composite action apt-installs. Checked
# inside a real image rather than assumed: the xpack toolchain above
# already ships `arm-none-eabi/lib/libstdc++.a`, the full C++ header set
# under `include/c++/15.2.1/`, and newlib's own `libc.a`. Installing the
# apt ones would put a second, older arm-none-eabi on PATH.

ENV PATH="${PATH}:/opt/toolchains/arm-none-eabi/bin"

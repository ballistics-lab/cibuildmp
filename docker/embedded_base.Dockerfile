# arm-none-eabi + riscv-none-elf -- every bare-metal Cortex-M/A and RISC-V
# target this project builds
#
# One image group (record 0058's own "the group, not the port, is what an
# image is keyed by"): natmod `armv6m`/`armv7m`/`armv7emsp`/`armv7emdp`/
# `rv32imc`/`rv64imc`, usermod `rp2`/`stm32`/`samd`/`mimxrt`/`nrf`/
# `renesas-ra`/`cc3200`/`alif`/`psoc-edge`, and `qemu`'s eight ARM/RISC-V
# boards -- all resolve here.
#
# **Was two images, `arm_embedded.Dockerfile` and `riscv_embedded.Dockerfile`
# (record 0096).** [0087]/[0089] already deleted the one thing that gave
# either of them a distinct build-time recipe -- neither bakes a cross
# compiler any more, both fetch one into a host-mounted cache at container
# run time instead (`toolchain_fetch.py`, record 0086), keyed by the row's
# own `cross` prefix, not by which image it runs in. Once that landed, the
# two Dockerfiles' own `RUN apt-get install` layers were identical but for
# one package (`cmake`, `rp2`-only) -- [0044]'s own addendum had already
# named this exact consolidation as a real, open resolver-shape question
# ("sketched but not built this session... stays open"); [0096] is that
# question, answered directly once the two files had nothing left to
# distinguish them. `toolchain_fetch.py`'s own per-row `cross` resolution
# is what still tells the two toolchain families apart inside this one
# image -- the image no longer does.
#
# `ubuntu:26.04`, not a pypa image. `unix` builds on pypa's own
# ([0043]/[0044]) because those targets are genuinely native and need
# manylinux's glibc floor; nothing here is. A cross toolchain is a
# tarball either way, and `manylinux_2_28_x86_64` is 589 MB compressed
# before one is added -- its CPython set, auditwheel and glibc floor buy
# a bare-metal `.elf` nothing at all.
#
# Build: docker build -t cibuildmp-embedded_base -f docker/embedded_base.Dockerfile .
# Use:   CIBMP_..._DOCKER_IMAGE=cibuildmp-embedded_base cibuildmp ...
FROM ubuntu:26.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# The build environment MicroPython's own makefiles need, plus
# `curl`/`ca-certificates`/`xz-utils` for the runtime toolchain fetch
# above (record 0086's own `fetch_script()` needs `curl` and `tar`;
# `xz-utils` covers a future `.tar.xz` pin the same way it already did
# when this layer still extracted one at build time). One layer, not two:
# unlike the old baked-toolchain split (toolchain first so adding a dev
# package never invalidated the expensive download), nothing here is
# expensive enough any more to protect from cache invalidation by staying
# in its own `RUN`. `python3-pyelftools` is `mpy_ld.py`'s only
# third-party import (record 0012's addendum -- the `ar` it used to name
# alongside is not imported by anything, at any tag).
#
# `cmake` is here for `rp2` alone -- `ports/rp2/Makefile` shells out to
# cmake, which then pulls pico-sdk from MicroPython's own `lib/`, not
# from a vendored copy of its own (verified live by `build-usermod-rp2040`,
# whose header records the same finding). No other port sharing this image
# is CMake-driven; carrying the package into the RISC-V-only builds too
# costs one apt package, and a second image existing only to withhold it
# is exactly the distinction record 0096 removed.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        xz-utils \
        build-essential \
        git \
        python3 \
        python3-pyelftools \
        cmake; \
    rm -rf /var/lib/apt/lists/*; \
    python3 -c "from elftools.elf.elffile import ELFFile"

# What is deliberately NOT installed: `gcc-arm-none-eabi`,
# `libnewlib-arm-none-eabi` and `libstdc++-arm-none-eabi-newlib`, which
# the `build-usermod-rp2040` composite action apt-installs. Checked
# inside a real image rather than assumed: the xpack toolchain this image
# fetches at run time already ships `arm-none-eabi/lib/libstdc++.a`, a
# full C++ header set, and newlib's own `libc.a`. Installing the apt ones
# would put a second, older arm-none-eabi on PATH. The same holds for
# RISC-V: nothing here installs a `riscv64-*` apt cross compiler either,
# for the identical reason.

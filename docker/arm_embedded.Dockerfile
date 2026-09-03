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
# **No cross compiler baked in any more (record 0087).** [0085] found a
# single shared pin cannot satisfy every tag's own floor/ceiling window
# ("seventy rows are one fact", and that one fact is wrong for most of
# them) -- `rp2`'s own `toolchain_version` (`build-platforms.toml`'s own
# per-row `gcc` field, resolved through `targets.rp2_toolchain()`) is
# fetched into a host-mounted cache at container-run time instead
# (`toolchain_fetch.py`, record 0086), verified there against
# `resources/pinned_toolchains.toml`'s own sha256, the same "populate the
# cache from inside the container" rule `esp_idf_base.Dockerfile` already
# states. `PATH` is therefore no longer a baked `ENV` line -- each build
# passes it per-run, once the fetch has landed.
#
# Build: docker build -t cibuildmp-arm_embedded -f docker/arm_embedded.Dockerfile .
# Use:   CIBMP_..._DOCKER_IMAGE=cibuildmp-arm_embedded cibuildmp ...
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

# cmake is here and not in the other three because `rp2` is the only ARM
# port that needs it -- `ports/rp2/Makefile` shells out to cmake, which
# then pulls pico-sdk from MicroPython's own `lib/`, not from a vendored
# copy of its own (verified live by `build-usermod-rp2040`, whose header
# records the same finding). Every other ARM port here is plain make.
#
# What is deliberately NOT installed: `gcc-arm-none-eabi`,
# `libnewlib-arm-none-eabi` and `libstdc++-arm-none-eabi-newlib`, which
# the `build-usermod-rp2040` composite action apt-installs. Checked
# inside a real image rather than assumed: the xpack toolchain this image
# fetches at run time already ships `arm-none-eabi/lib/libstdc++.a`, a
# full C++ header set, and newlib's own `libc.a`. Installing the apt ones
# would put a second, older arm-none-eabi on PATH.

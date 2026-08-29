# the base ESP-IDF is installed *into* at build time
#
# One of the six toolchain-group images record 0058 splits
# `natmod.Dockerfile` into. Keyed by the group, not the port: usermod `esp32`, every board and MCU.
#
# `ubuntu:24.04`, not a pypa image -- `unix` builds on pypa's own
# ([0043]/[0044]) because those targets are native and need manylinux's
# glibc floor. Nothing here is.
#
# Build: docker build -t cibuildmp-esp_idf_base -f docker/esp_idf_base.Dockerfile .
FROM ubuntu:26.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Deliberately holds no toolchain. `build-platforms.toml` carries eight
# distinct `idf_version` values across its `esp32` rows (v4.0.2, v4.4,
# v5.0.2, v5.0.4, v5.2.2, v5.4.2, v5.5.1, v5.5.2), and v1.20.0 varies it
# per MCU rather than per tag -- so baking a toolchain means baking the
# wrong one seven times out of eight, or publishing eight images.
#
# Instead the driver installs IDF at build time (record 0058): a
# `git clone -b <idf_version> --recursive` plus `./install.sh <target>`,
# which is what `usermod/espidf.py` already does and already caches by
# `(version, target)` under `cache_root()`. `dockerrun.run()` bind-mounts
# each of its `mounts` at its own identical host path, so that cache
# reaches the container where `IDF_PATH` already expects it.
#
# **The cache must be populated from inside this image, not on the host.**
# `install.sh` fetches binaries built against a particular glibc; a cache
# filled by whatever the runner happens to be and then consumed here is
# the same class of mismatch `container_mpy_cross()` was written to fix.
#
# The package list starts from ESP-IDF's own documented Linux
# prerequisites -- git to clone, python3-venv because `install.sh` builds
# its own virtualenv, cmake/ninja/ccache for the build itself, and the
# flex/bison/gperf/libffi/libssl set the IDF tools build against.
#
# `build-essential` is **not** on that list and is required anyway, which
# a first build of this image without it found: upstream's prerequisites
# assume a developer machine that already has a compiler. `cc`, `gcc` and
# `make` were all absent, and this port needs all three -- `ports/esp32`
# is driven by a Makefile, `mpy-cross` is a host C program built before
# the firmware, and IDF's own cmake runs host compiler checks. Verified
# by running the built image, not by reading the list again.
#
# System `pip3` is deliberately still absent: `install.sh` creates its own
# virtualenv and installs into that, which was checked to work here.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        bison \
        build-essential \
        ca-certificates \
        ccache \
        cmake \
        dfu-util \
        flex \
        git \
        gperf \
        libffi-dev \
        libssl-dev \
        libusb-1.0-0 \
        ninja-build \
        python3 \
        python3-venv \
        wget; \
    rm -rf /var/lib/apt/lists/*

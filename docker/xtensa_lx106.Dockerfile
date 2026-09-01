# xtensa-lx106-elf -- ESP8266
#
# One of the six toolchain-group images record 0058 splits
# `natmod.Dockerfile` into. The group, not the port, is what an image is
# keyed by: natmod `xtensa` and usermod `esp8266` --
# all resolve here, so this file exists once instead of once per port.
#
# `ubuntu:26.04`, not a pypa image. `unix` builds on pypa's own
# ([0043]/[0044]) because those targets are genuinely native and need
# manylinux's glibc floor; nothing here is. A cross toolchain is a
# tarball either way, and `manylinux_2_28_x86_64` is 589 MB compressed
# before one is added -- its CPython set, auditwheel and glibc floor buy
# a bare-metal `.elf` nothing at all.
#
# Build: docker build -t cibuildmp-xtensa_lx106 -f docker/xtensa_lx106.Dockerfile .
# Use:   CIBMP_..._DOCKER_IMAGE=cibuildmp-xtensa_lx106 cibuildmp ...
FROM ubuntu:26.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# The pin, as named build args rather than buried in the RUN below:
# `bin/update_docker.py` can rewrite an ARG line, and record 0058 leaves
# moving these into `resources/` open -- a `--build-arg` is the seam that
# makes that a data change rather than a Dockerfile edit.
ARG TOOLCHAIN_URL="https://micropython.org/resources/xtensa-lx106-elf-standalone.tar.gz"
ARG TOOLCHAIN_SHA256="f45f755ea8021c24c9b36cc3d363973927857fe4e6279f32e6968abfac38d1ba"

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl xz-utils; \
    rm -rf /var/lib/apt/lists/*; \
    mkdir -p /opt/toolchains/xtensa-lx106-elf; \
    curl -fsSL -o /tmp/tc.tar "$TOOLCHAIN_URL"; \
    # Verified, not merely fetched: a third-party tarball every build then
    # runs a compiler out of. "It downloaded" and "it is the artifact that
    # was pinned" are different claims.
    echo "$TOOLCHAIN_SHA256  /tmp/tc.tar" | sha256sum -c -; \
    # --strip-components=1: each tarball has one versioned top-level
    # directory, and flattening it keeps PATH free of version numbers, so
    # a bump is one ARG and no other edit.
    tar -xf /tmp/tc.tar --strip-components=1 -C /opt/toolchains/xtensa-lx106-elf; \
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
        python3-pyelftools; \
    rm -rf /var/lib/apt/lists/*; \
    python3 -c "from elftools.elf.elffile import ELFFile"

# Kept separate from `xtensa_esp` despite the shared architecture name.
# They are two different compilers -- this one a standalone tarball
# micropython.org publishes, that one Espressif's crosstool-NG build --
# and measured in a real image this one is 106 MB against that one's
# 565 MB. Merging them would make every `esp8266` build pull 6.3x what it
# needs to save a single pin.

ENV PATH="${PATH}:/opt/toolchains/xtensa-lx106-elf/bin"

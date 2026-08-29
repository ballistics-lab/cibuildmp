# xtensa-esp-elf -- the `xtensawin` natmod arch
#
# One of the six toolchain-group images record 0058 splits
# `natmod.Dockerfile` into. The group, not the port, is what an image is
# keyed by: natmod `xtensawin` only --
# all resolve here, so this file exists once instead of once per port.
#
# `ubuntu:24.04`, not a pypa image. `unix` builds on pypa's own
# ([0043]/[0044]) because those targets are genuinely native and need
# manylinux's glibc floor; nothing here is. A cross toolchain is a
# tarball either way, and `manylinux_2_28_x86_64` is 589 MB compressed
# before one is added -- its CPython set, auditwheel and glibc floor buy
# a bare-metal `.elf` nothing at all.
#
# Build: docker build -t cibuildmp-xtensa_esp -f docker/xtensa_esp.Dockerfile .
# Use:   CIBMP_..._DOCKER_IMAGE=cibuildmp-xtensa_esp cibuildmp ...
FROM ubuntu:26.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# The pin, as named build args rather than buried in the RUN below:
# `bin/update_docker.py` can rewrite an ARG line, and record 0058 leaves
# moving these into `resources/` open -- a `--build-arg` is the seam that
# makes that a data change rather than a Dockerfile edit.
ARG TOOLCHAIN_URL="https://github.com/espressif/crosstool-NG/releases/download/esp-16.1.0_20260609/xtensa-esp-elf-16.1.0_20260609-x86_64-linux-gnu.tar.xz"
ARG TOOLCHAIN_SHA256="f708752ebb35cab21f184b2574114ed1187619db0edb8a4ba913c06ca2fa675e"

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl xz-utils; \
    rm -rf /var/lib/apt/lists/*; \
    mkdir -p /opt/toolchains/xtensa-esp-elf; \
    curl -fsSL -o /tmp/tc.tar "$TOOLCHAIN_URL"; \
    # Verified, not merely fetched: a third-party tarball every build then
    # runs a compiler out of. "It downloaded" and "it is the artifact that
    # was pinned" are different claims.
    echo "$TOOLCHAIN_SHA256  /tmp/tc.tar" | sha256sum -c -; \
    # --strip-components=1: each tarball has one versioned top-level
    # directory, and flattening it keeps PATH free of version numbers, so
    # a bump is one ARG and no other edit.
    tar -xf /tmp/tc.tar --strip-components=1 -C /opt/toolchains/xtensa-esp-elf; \
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

# Not usermod `esp32`. That port's compiler comes from ESP-IDF's own
# `install.sh <target>`, run at build time against the row's own
# `idf_version` (record 0058) -- eight distinct versions appear in
# `build-platforms.toml`, so baking one would be baking the wrong one
# seven times out of eight. `esp_idf_base.Dockerfile` is that port's
# image; this one exists purely for the natmod arch, which links a
# `.mpy` with a fixed compiler and no framework at all.
#
# `dynruntime.mk` spells the prefix `xtensa-esp32-elf-`; the tarball
# ships `xtensa-esp-elf-`.
RUN set -eux; \
    # Every tool in the toolchain's own bin/, not a hand-written list.
    # The list this replaced was copied from `natmod.Dockerfile`, where
    # ten names sufficed because `dynruntime.mk` never assembles -- a full
    # port build does, and `make -C ports/qemu BOARD=VIRT_RV32` died on a
    # missing `xtensa-esp32-elf-as` at `shared/runtime/gchelper_rv32i.s`.
    # A glob cannot be short by one the way a list can.
    for src in /opt/toolchains/xtensa-esp-elf/bin/xtensa-esp-elf-*; do \
        tool="${src##*/xtensa-esp-elf-}"; \
        ln -sf "$src" "/usr/local/bin/xtensa-esp32-elf-${tool}"; \
    done; \
    xtensa-esp32-elf-as --version | head -1

ENV PATH="${PATH}:/opt/toolchains/xtensa-esp-elf/bin"

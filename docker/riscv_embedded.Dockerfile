# riscv-none-elf -- RISC-V bare metal
#
# One of the six toolchain-group images record 0058 splits
# `natmod.Dockerfile` into. The group, not the port, is what an image is
# keyed by: natmod `rv32imc`/`rv64imc` and `qemu`'s `VIRT_RV32`/`VIRT_RV64` --
# all resolve here, so this file exists once instead of once per port.
#
# `ubuntu:26.04`, not a pypa image. `unix` builds on pypa's own
# ([0043]/[0044]) because those targets are genuinely native and need
# manylinux's glibc floor; nothing here is. A cross toolchain is a
# tarball either way, and `manylinux_2_28_x86_64` is 589 MB compressed
# before one is added -- its CPython set, auditwheel and glibc floor buy
# a bare-metal `.elf` nothing at all.
#
# **No cross compiler baked in any more (record 0087/0089), and no
# build-time symlink either.** The tarball (xpack's real
# `riscv-none-elf-*` binaries) is fetched into a host-mounted cache at
# container-run time instead (`toolchain_fetch.py`, record 0086),
# verified there against `resources/pinned_toolchains.toml`'s own
# sha256. The `riscv-none-elf-*` -> `riscv64-unknown-elf-*` rename
# `py/dynruntime.mk`/`ports/qemu` need moves with it --
# `toolchain_fetch.rename_prefix_script()` now symlinks them inside the
# fetched cache directory itself at run time, because `dockerrun.run()`
# always runs as the host's own non-root uid: the old build-time loop
# wrote into `/usr/local/bin`, which a root-less runtime fetch cannot do.
#
# Build: docker build -t cibuildmp-riscv_embedded -f docker/riscv_embedded.Dockerfile .
# Use:   CIBMP_..._DOCKER_IMAGE=cibuildmp-riscv_embedded cibuildmp ...
FROM ubuntu:26.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# The build environment MicroPython's own makefiles need, plus
# `curl`/`ca-certificates`/`xz-utils` for the runtime toolchain fetch
# above -- one layer, not two: unlike the old baked-toolchain split
# (toolchain first so adding a dev package never invalidated the
# expensive download), nothing here is expensive enough any more to
# protect from cache invalidation by staying in its own `RUN`.
# `python3-pyelftools` is `mpy_ld.py`'s only third-party import (record
# 0012's addendum -- the `ar` it used to name alongside is not imported
# by anything, at any tag).
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        xz-utils \
        build-essential \
        git \
        python3 \
        python3-pyelftools; \
    rm -rf /var/lib/apt/lists/*; \
    python3 -c "from elftools.elf.elffile import ELFFile"

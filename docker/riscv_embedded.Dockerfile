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
# Build: docker build -t cibuildmp-riscv_embedded -f docker/riscv_embedded.Dockerfile .
# Use:   CIBMP_..._DOCKER_IMAGE=cibuildmp-riscv_embedded cibuildmp ...
FROM ubuntu:26.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# The pin, as named build args rather than buried in the RUN below:
# `bin/update_docker.py` can rewrite an ARG line, and record 0058 leaves
# moving these into `resources/` open -- a `--build-arg` is the seam that
# makes that a data change rather than a Dockerfile edit.
ARG TOOLCHAIN_URL="https://github.com/xpack-dev-tools/riscv-none-elf-gcc-xpack/releases/download/v15.2.0-1/xpack-riscv-none-elf-gcc-15.2.0-1-linux-x64.tar.gz"
ARG TOOLCHAIN_SHA256="aaaa8060c914851a3e5ee1ba82cc3d6f80972f90638a05c6e823a37557a33758"

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl xz-utils; \
    rm -rf /var/lib/apt/lists/*; \
    mkdir -p /opt/toolchains/riscv-none-elf; \
    curl -fsSL -o /tmp/tc.tar "$TOOLCHAIN_URL"; \
    # Verified, not merely fetched: a third-party tarball every build then
    # runs a compiler out of. "It downloaded" and "it is the artifact that
    # was pinned" are different claims.
    echo "$TOOLCHAIN_SHA256  /tmp/tc.tar" | sha256sum -c -; \
    # --strip-components=1: each tarball has one versioned top-level
    # directory, and flattening it keeps PATH free of version numbers, so
    # a bump is one ARG and no other edit.
    tar -xf /tmp/tc.tar --strip-components=1 -C /opt/toolchains/riscv-none-elf; \
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

# `py/dynruntime.mk` and `ports/qemu` both spell the prefix
# `riscv64-unknown-elf-`; xpack ships `riscv-none-elf-`. Symlinks rather
# than a PATH trick, so `CROSS_COMPILE=riscv64-unknown-elf-` resolves
# every tool and not just the ones a wrapper happened to cover.
RUN set -eux; \
    # Every tool in the toolchain's own bin/, not a hand-written list.
    # The list this replaced was copied from `natmod.Dockerfile`, where
    # ten names sufficed because `dynruntime.mk` never assembles -- a full
    # port build does, and `make -C ports/qemu BOARD=VIRT_RV32` died on a
    # missing `riscv64-unknown-elf-as` at `shared/runtime/gchelper_rv32i.s`.
    # A glob cannot be short by one the way a list can.
    for src in /opt/toolchains/riscv-none-elf/bin/riscv-none-elf-*; do \
        tool="${src##*/riscv-none-elf-}"; \
        ln -sf "$src" "/usr/local/bin/riscv64-unknown-elf-${tool}"; \
    done; \
    riscv64-unknown-elf-as --version | head -1

ENV PATH="${PATH}:/opt/toolchains/riscv-none-elf/bin"

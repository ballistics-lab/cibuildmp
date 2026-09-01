# powerpc64le-linux-gnu -- `qemu`'s POWERNV9 board
#
# One of the six toolchain-group images record 0058 splits
# `natmod.Dockerfile` into. Keyed by the group, not the port: usermod `qemu` board `POWERNV9` only.
#
# `ubuntu:26.04`, not a pypa image -- `unix` builds on pypa's own
# ([0043]/[0044]) because those targets are native and need manylinux's
# glibc floor. Nothing here is.
#
# Build: docker build -t cibuildmp-ppc64le_linux -f docker/ppc64le_linux.Dockerfile .
FROM ubuntu:26.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# One board, and only from v1.29.0 onwards -- `POWERNV9` does not exist
# in `ports/qemu/boards/` at v1.28.0 or earlier (checked against real
# checkouts at v1.24.0, v1.26.0, v1.27.0, v1.28.0). It is upstream's own
# former `ports/powerpc` folded into `ports/qemu` as a board, which is
# why this group has exactly one member and no prospect of more.
#
# The package list is upstream's, not a guess: `tools/ci.sh`'s
# `ci_powerpc_setup` installs precisely
# `gcc-powerpc64le-linux-gnu libc6-dev-ppc64el-cross`. The second is the
# part worth naming -- a cross gcc with no target libc headers fails at
# the first `#include`, and it is the half that is easy to leave out.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential \
        git \
        gcc-powerpc64le-linux-gnu \
        libc6-dev-ppc64el-cross \
        python3 \
        python3-pyelftools; \
    rm -rf /var/lib/apt/lists/*; \
    powerpc64le-linux-gnu-gcc --version

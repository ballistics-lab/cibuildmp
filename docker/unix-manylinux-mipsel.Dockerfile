# One of five per-(arch, libc) `unix` images -- see
# unix-manylinux-x64.Dockerfile's own header for the full split
# rationale (D26/D31), and unix-manylinux-armhf.Dockerfile's own header
# for why this arch needs neither `dpkg --add-architecture` nor
# libffi-dev/pkg-config (identical MICROPY_STANDALONE=1 shape, just
# `mipsel-linux-gnu-` instead of `arm-linux-gnueabihf-`).
#
# Build: docker build -t cibuildmp-unix-manylinux-mipsel -f src/cibuildmp/resources/docker/unix-manylinux-mipsel.Dockerfile .
# Use:   CIBMP_UNIX_MIPSEL_MANYLINUX_DOCKER_IMAGE=cibuildmp-unix-manylinux-mipsel cibuildmp ...
#
# Not yet built for real via `docker build` -- see
# unix-manylinux-x64.Dockerfile's own header for the same open
# verification gap.
FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3 \
    gcc-mipsel-linux-gnu \
    libc6-dev-mipsel-cross \
    libltdl-dev \
    libtool \
    && rm -rf /var/lib/apt/lists/*

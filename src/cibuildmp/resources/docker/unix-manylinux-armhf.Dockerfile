# One of five per-(arch, libc) `unix` images -- see
# unix-manylinux-x64.Dockerfile's own header for the full split
# rationale (D26/D31).
#
# armhf: no `dpkg --add-architecture`/ports.ubuntu.com mirror needed at
# all, unlike aarch64/x86 -- `gcc-arm-linux-gnueabihf`/
# `libc6-dev-armhf-cross` are "-cross" packages, ordinary amd64-native
# .debs that happen to contain ARM headers/libs for cross-compiling,
# not real foreign-arch binaries the way `libffi-dev:arm64` is. This
# arch also never touches libffi-dev/pkg-config at all: MICROPY_STANDALONE=1
# (build.py's own UnixArchSettings) makes ports/unix/Makefile build
# libffi from the vendored lib/libffi submodule instead of the system
# one (verified directly against a real v1.28.0 checkout's own
# Makefile) -- which is exactly why deplibs' own ./autogen.sh needs
# libtoolize (libltdl-dev alone only Recommends: libtool, which
# --no-install-recommends skips -- D25's own sixth real bug,
# transcribed here unchanged).
#
# Build: docker build -t cibuildmp-unix-manylinux-armhf -f src/cibuildmp/resources/docker/unix-manylinux-armhf.Dockerfile .
# Use:   CIBMP_UNIX_ARMHF_MANYLINUX_DOCKER_IMAGE=cibuildmp-unix-manylinux-armhf cibuildmp ...
#
# Not yet built for real via `docker build` -- see
# unix-manylinux-x64.Dockerfile's own header for the same open
# verification gap.
FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3 \
    gcc-arm-linux-gnueabihf \
    libc6-dev-armhf-cross \
    libltdl-dev \
    libtool \
    && rm -rf /var/lib/apt/lists/*

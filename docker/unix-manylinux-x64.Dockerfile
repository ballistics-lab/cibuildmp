# One image per (arch, libc) for the `unix` port -- cibuildwheel's own
# manylinux_x86_64/musllinux_aarch64 shape, not one image combining every
# arch (that was this file's own earlier, wrong shape: a single
# unix.Dockerfile for all five arches at once, corrected on review --
# glibc-vs-musl is a real runtime-compatibility axis a combined image
# hides, and packages `libc6-dev-arm64-cross` etc. only apply to their
# own arch anyway, so splitting loses nothing and gains real isolation:
# an armhf toolchain bump can no longer touch an x64 build's own image).
# See docs/BACKLOG.md's own D26/D31.
#
# "manylinux" here names the libc, not a specific glibc version pin the
# way cibuildwheel's own manylinux_2_28 etc. do -- ubuntu:24.04's system
# glibc, whatever that is. `musllinux` variants do not exist yet (D31):
# they need a real musl toolchain (an Alpine base, not this file), not
# yet built.
#
# x64: no cross-compiler at all -- the host gcc IS the target compiler
# (ubuntu:24.04 is x86_64), the same toolchain used to build this image
# itself. `libffi-dev`/`pkg-config`: ports/unix/Makefile's own
# non-standalone branch resolves libffi via `pkg-config --cflags/libs
# libffi` (verified directly against a real v1.28.0 checkout's own
# Makefile, not assumed) -- x64 is not one of the MICROPY_STANDALONE
# arches (those build libffi from the vendored submodule instead, no
# pkg-config/libffi-dev involved at all; see
# unix-manylinux-armhf.Dockerfile for that path).
#
# Build: docker build -t cibuildmp-unix-manylinux-x64 -f src/cibuildmp/resources/docker/unix-manylinux-x64.Dockerfile .
# Use:   CIBMP_UNIX_X64_MANYLINUX_DOCKER_IMAGE=cibuildmp-unix-manylinux-x64 cibuildmp ...
#
# Not yet built for real via `docker build` (no reachable Docker daemon
# in the sandbox this was written in) -- correctness inferred from
# action.Dockerfile's own already-proven package list for this exact
# arch, not yet confirmed independently. Confirm with a real `docker
# build` plus a real usermod-unix-x64 run through it before registering
# "unix-x64" in usermod/dockerrun.py's own PORT_IMAGES.
FROM ubuntu:24.04

# python3: ports/unix/Makefile's own build shells out to it directly
# (makeversionhdr.py, mpy-tool.py, qstr generation). No git/
# ca-certificates/curl: the MicroPython checkout and manifest generation
# both happen on the host, before this image is ever invoked -- only
# `make` itself runs inside.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3 \
    libffi-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

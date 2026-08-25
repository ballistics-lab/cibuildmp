# One of five per-(arch, libc) `unix` images -- see
# unix-manylinux-x64.Dockerfile's own header for the full split
# rationale (D26/D31) and why "manylinux" here just means "this base
# image's own glibc," not a cibuildwheel-style pinned glibc version.
#
# x86: not a separate cross-compiler either -- `usermod/build.py`'s own
# UnixArchSettings for "x86" carries no `cross_compile` prefix at all,
# just `MICROPY_FORCE_32BIT=1` -- it is the *same* host gcc as x64,
# built with `-m32` multilib support (`gcc-13-multilib`, matching
# `toolchains.resolve("x86")`'s own probe, natmod's identical arch).
# libffi-dev:i386/linux-libc-dev:i386 are the real i386 headers/libs
# `-m32` needs that `--no-install-recommends` alone does not provision
# (D25's own second real bug, transcribed here unchanged). i386 needs no
# ports.ubuntu.com mirror rewrite the way arm64 does -- it is on
# Ubuntu's own default archive mirror already.
#
# Build: docker build -t cibuildmp-unix-manylinux-x86 -f src/cibuildmp/resources/docker/unix-manylinux-x86.Dockerfile .
# Use:   CIBMP_UNIX_X86_DOCKER_IMAGE=cibuildmp-unix-manylinux-x86 cibuildmp ...
#
# Not yet built for real via `docker build` -- see
# unix-manylinux-x64.Dockerfile's own header for the same open
# verification gap.
FROM ubuntu:24.04

RUN dpkg --add-architecture i386

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3 \
    gcc-13-multilib \
    libffi-dev \
    libffi-dev:i386 \
    linux-libc-dev:i386 \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

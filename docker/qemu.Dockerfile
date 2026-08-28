# D28 step 3's own third per-port image -- see
# unix-manylinux-x64.Dockerfile's own header for the general split
# rationale (cibuildmp stays on the bare host, this image holds nothing
# but the toolchain a real `make -C ports/qemu` invocation needs, no
# `cibuildmp` installed inside it) and for why this lives under
# src/cibuildmp/resources/docker/ rather than a top-level docker/
# directory (a real package resource, shipped with the installed tool).
#
# One combined image, not split per (arch, libc) like `unix` -- `qemu`
# only ever targets the one bare-metal Cortex-M3 board this project
# supports (MPS2_AN385, `build.py`'s own `_QEMU_SUPPORTED_BOARDS`), and
# a bare-metal ELF has no libc/musl-vs-glibc axis at all (D26/D31's own
# reasoning for splitting `unix` doesn't apply here either).
#
# Package list verified against two independent real sources, not
# derived from memory (D28 step 3's own explicit instruction): (1)
# o-murphy/a7p's own real .github/workflows/mp-usermod.yml, whose
# usermod-qemu-armv7m job installs the toolchain via
# cibuildmp/.github/actions/build-usermod-armv7m -- `apt-get install
# gcc-arm-none-eabi libnewlib-arm-none-eabi`, with qemu-system-arm
# installed separately in the *caller's* own job, deliberately not a
# build dependency (that action's own description: "QEMU itself is
# deliberately NOT installed here: it is a runtime emulator for testing
# the resulting firmware.elf, not a build dependency"). (2) This
# project's own resources/natmod.toml `[[toolchain]] name =
# "arm-none-eabi"` entry, which cibuildmp's own build_qemu()
# (usermod/build.py) resolves via `toolchains.resolve("armv7m")` for
# the exact same CROSS_COMPILE prefix -- its own `apt-packages` field
# is the identical `"gcc-arm-none-eabi libnewlib-arm-none-eabi"`. Since
# `resolve()`'s own "auto" strategy checks PATH before ever downloading
# the pinned xpack tarball (toolchains.py's own `_find_on_path()`),
# apt-installing this package here means build_qemu() finds it on PATH
# immediately inside this image -- no code change needed there for
# this Dockerfile to be usable, once dockerrun wiring like
# build_unix()'s own is added to build_qemu() too (not done yet).
# qemu-system-arm (the *execution* axis, D21) stays out of this image
# entirely, matching a7p's own split exactly -- this image only ever
# builds firmware.elf, it never runs it.
#
# Build: docker build -t cibuildmp-qemu -f src/cibuildmp/resources/docker/qemu.Dockerfile .
# Use:   CIBMP_QEMU_ARMV7M_DOCKER_IMAGE=cibuildmp-qemu cibuildmp ...
#
# Not yet built for real via `docker build` locally (no reachable
# Docker daemon in the sandbox this was written in) -- but see
# build-examples.yml's own `verify-docker-images` job, which now
# builds (and, on a real push, publishes) every Dockerfile here for
# real on every push, closing this gap live rather than leaving it
# open as a comment.
FROM ubuntu:24.04

# python3: ports/qemu/Makefile includes py/mkenv.mk, whose own
# `PYTHON = python3` default every port's build shells out to directly
# (makeversionhdr.py, mpy-tool.py, qstr generation) -- confirmed
# directly against a real v1.28.0 checkout, not assumed just because
# every other port here needs it too.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3 \
    gcc-arm-none-eabi \
    libnewlib-arm-none-eabi \
    && rm -rf /var/lib/apt/lists/*

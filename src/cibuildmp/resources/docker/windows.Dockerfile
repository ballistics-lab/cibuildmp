# D28 step 3's own second per-port image -- see
# unix-manylinux-x64.Dockerfile's own header for the general split
# rationale (cibuildmp stays on the bare host, this image holds nothing
# but the toolchain a real `make -C ports/windows` invocation needs, no
# `cibuildmp` installed inside it) and for why this lives under
# src/cibuildmp/resources/docker/ rather than a top-level docker/
# directory (a real package resource, shipped with the installed tool).
#
# One combined x64+x86 image, NOT split per arch like `unix`'s own five
# images (D26/D31): windows has no manylinux/musllinux-shaped
# runtime-compatibility axis at all (there is no second Windows libc a
# binary could be built against), so the isolation argument that drove
# splitting `unix` doesn't carry over here, and both arches already
# share one small, stable apt package pair with no history of
# conflicting bumps. Registered as both "windows-x64" and "windows-x86"
# in PORT_IMAGES once published -- same image, two keys, matching
# usermod/dockerrun.py's own (port, arch) resolver shape uniformly
# across every port even where a port doesn't need the split.
#
# Both are plain apt-installed mingw-w64 GCC cross-compilers
# (usermod/build.py's own WINDOWS_ARCH_SETTINGS), the same packages
# action.Dockerfile already proves work for this exact port
# (build_windows()'s own x64/x86 path, live-verified with a real custom
# C module linked into a genuine micropython.exe, D18). arm64 is
# deliberately NOT baked in: no Debian/Ubuntu package targets
# aarch64-w64-mingw32 at all, so that arch downloads llvm-mingw at build
# time instead (usermod/llvmmingw.py) -- this stays a bare-host-only
# arch until D28 step 4 gives usermod/dockerrun.py real mount coverage
# for sources.cache_root(), the same way windows/arm64, webassembly, and
# esp32 all will.
#
# Build: docker build -t cibuildmp-windows -f src/cibuildmp/resources/docker/windows.Dockerfile .
# Use:   CIBMP_WINDOWS_X64_DOCKER_IMAGE=cibuildmp-windows cibuildmp ...
#        CIBMP_WINDOWS_X86_DOCKER_IMAGE=cibuildmp-windows cibuildmp ...
#
# Not yet built for real via `docker build` (no reachable Docker daemon
# in the sandbox this was written in, the same gap D28's own
# "Docker-daemon-reachability" question hit) -- correctness here is
# inferred from matching action.Dockerfile's own already-proven package
# list for this exact port/arch pair, same as the unix-manylinux-*
# images' own still-open verification gap. Confirm with a real `docker
# build` plus a real usermod-windows-x64/x86 run through it before
# registering "windows-x64"/"windows-x86" in usermod/dockerrun.py's own
# PORT_IMAGES.
FROM ubuntu:24.04

# python3: ports/windows/Makefile's own build shells out to it directly
# (makeversionhdr.py, mpy-tool.py, qstr generation), same as unix. No
# git/ca-certificates/curl: the MicroPython checkout and manifest
# generation both happen on the host, before this image is ever invoked
# -- only `make` itself runs inside, same reasoning as
# unix-manylinux-x64.Dockerfile's own header comment.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3 \
    gcc-mingw-w64-x86-64 \
    gcc-mingw-w64-i686 \
    && rm -rf /var/lib/apt/lists/*

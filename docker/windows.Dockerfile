# D28 step 3's own second per-port image -- see
# unix-manylinux-x64.Dockerfile's own header for the general split
# rationale (cibuildmp stays on the bare host, this image holds nothing
# but the toolchain a real `make -C ports/windows` invocation needs, no
# `cibuildmp` installed inside it) and for why this lives under a
# top-level docker/ directory rather than src/cibuildmp/resources/ (D33:
# cibuildmp never builds one of these itself, so they no longer ship
# inside the installed wheel at all).
#
# One combined x64+x86+arm64 image, NOT split per arch like `unix`'s own
# five images (D26/D31): windows has no manylinux/musllinux-shaped
# runtime-compatibility axis at all (there is no second Windows libc a
# binary could be built against), so the isolation argument that drove
# splitting `unix` doesn't carry over here, and the three arches have no
# history of conflicting toolchain bumps. Registered as "windows-x64",
# "windows-x86" and "windows-arm64" in PORT_IMAGES -- same image, three
# keys, matching usermod/dockerrun.py's own (port, arch) resolver shape
# uniformly across every port even where a port doesn't need the split.
#
# x64/x86 are plain apt-installed mingw-w64 GCC cross-compilers
# (usermod/build.py's own WINDOWS_ARCH_SETTINGS), the same packages
# action.Dockerfile already proves work for this exact port
# (build_windows()'s own x64/x86 path, live-verified with a real custom
# C module linked into a genuine micropython.exe, D18).
#
# arm64 is baked in as a pinned llvm-mingw tarball, not apt: no
# Debian/Ubuntu package targets aarch64-w64-mingw32 at all (D18), so
# there is nothing to `apt-get install` for that arch. It used to
# download at build time on the bare host instead (usermod/llvmmingw.py's
# own `resolve_llvm_mingw()`, cached under `~/.cache/cibuildmp/`) -- that
# was this port's own last remaining bare-host path, and D30's
# Docker-only mandate leaves no room for it. Baked here exactly the way
# webassembly.Dockerfile already bakes emsdk, for the same reason.
#
# **This file is the llvm-mingw pin of record.** The resolver above and
# the `[llvm-mingw]` table in `resources/usermod.toml` it read are both
# gone -- with every usermod port Docker-only there was no caller left
# for the one, and no reader left for the other. The version/URL/sha256
# in the second `RUN` step below are now the single source of truth;
# what follows is the provenance that table carried, migrated here
# rather than deleted with it.
#
# Debian/Ubuntu package no aarch64-w64-mingw32 GCC target at all, and
# GCC's own upstream ARM64 Windows support is not what any Linux distro
# ships pre-built. mingw-w64's own docs (https://www.mingw-w64.org,
# "Pre-built Toolchains") name llvm-mingw as the one toolchain that
# targets ARM64 Windows *and* runs as a Linux-hosted cross compiler
# (mstorsjo/llvm-mingw's own README: releases named
# `llvm-mingw-<version>-<crt>-ubuntu-<distro>-<arch>.tar.xz` are "cross
# compilers, that can be run on Linux, compiling binaries for any of the
# 4 target Windows architectures"). Verified live, not assumed: a real
# v1.28.0 ports/windows build, CROSS_COMPILE=aarch64-w64-mingw32- from
# this tarball, with a real custom C module, produced a genuine PE32+
# Aarch64 micropython.exe with that module's own symbols linked in --
# re-confirmed through this image itself, see below.
#
# The three `-Wno-*` suppressions and the
# COMPILER_TARGET/STRIP/SIZE overrides this toolchain needs are not
# here -- they are Make-level flags, and live with the rest of them in
# usermod/build.py's own WINDOWS_ARCH_SETTINGS, which explains each.
#
# Live-verified through this exact image, not inferred from the older
# bare-host result: a real v1.28.0 ports/windows build of
# examples/template for all three arches, run through
# `dockerrun.run()` itself, produced a PE32+ x86-64, a PE32 i386 and a
# PE32+ ARM64 micropython.exe, each with the example usermod's own
# translation unit compiled into it and its `template` qstr present in
# both genhdr/qstrdefs.generated.h and the linked binary.
#
# Build: docker build -t cibuildmp-windows:local -f docker/windows.Dockerfile .
# Use:   CIBMP_WINDOWS_X64_DOCKER_IMAGE=cibuildmp-windows:local cibuildmp ...
#        CIBMP_WINDOWS_X86_DOCKER_IMAGE=cibuildmp-windows:local cibuildmp ...
#        CIBMP_WINDOWS_ARM64_DOCKER_IMAGE=cibuildmp-windows:local cibuildmp ...
FROM ubuntu:24.04

# python3: ports/windows/Makefile's own build shells out to it directly
# (makeversionhdr.py, mpy-tool.py, qstr generation), same as unix.
# curl/ca-certificates/xz-utils exist only for the llvm-mingw fetch in the
# next layer -- the MicroPython checkout and manifest generation both
# still happen on the host, before this image is ever invoked, so no
# `git` is needed here, same reasoning as
# unix-manylinux-x64.Dockerfile's own header comment.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3 \
    curl \
    ca-certificates \
    xz-utils \
    gcc-mingw-w64-x86-64 \
    gcc-mingw-w64-i686 \
    && rm -rf /var/lib/apt/lists/*

# Pinned to resources/usermod.toml's own [llvm-mingw] table (version
# 20260616, linux-x64) -- keep the URL and sha256 in step with it. The
# tarball unpacks to a single `llvm-mingw-20260616-ucrt-ubuntu-22.04-x86_64/`
# directory (`sole_directory()`'s own assumption in llvmmingw.py);
# --strip-components=1 flattens that away so the install prefix is a
# stable /opt/llvm-mingw regardless of the version in the name.
RUN curl -fsSL -o /tmp/llvm-mingw.tar.xz \
      https://github.com/mstorsjo/llvm-mingw/releases/download/20260616/llvm-mingw-20260616-ucrt-ubuntu-22.04-x86_64.tar.xz && \
    echo "534b92e067b22a6b4441f48ae9240a3341b17825d04d577eab0cf85c44b4deda  /tmp/llvm-mingw.tar.xz" | sha256sum -c - && \
    mkdir -p /opt/llvm-mingw && \
    tar -xJf /tmp/llvm-mingw.tar.xz -C /opt/llvm-mingw --strip-components=1 && \
    rm /tmp/llvm-mingw.tar.xz

# **Appended, not prepended** -- load-bearing, and found live rather than
# reasoned about: llvm-mingw's own bin/ also ships
# `x86_64-w64-mingw32-gcc` and `i686-w64-mingw32-gcc` wrapper names (both
# really Clang 22). Putting this directory first therefore silently
# shadows the apt mingw-w64 GCC for x64/x86 as well -- those two arches
# would quietly stop being "the exact toolchain upstream MicroPython's
# own CI uses" (D18) and start being Clang, without any of the three
# `-Wno-*` suppressions or `COMPILER_TARGET=mingw-forced` that
# WINDOWS_ARCH_SETTINGS only gives arm64. Appending keeps /usr/bin ahead
# for the two prefixes apt provides, while `aarch64-w64-mingw32-*`
# (which exists nowhere but here) still resolves. Verified per-prefix
# with `command -v` inside a real container, not assumed from the order.
ENV PATH="${PATH}:/opt/llvm-mingw/bin"

# The image action.yml itself builds (runs.image below), not the root
# Dockerfile -- deliberately a separate file, not a shared one. GitHub
# Actions builds this from the exact checkout it already pinned (the
# tag/ref a caller's own `uses:` names), so it installs from that local
# checkout (COPY .) rather than a second git+https fetch of the same ref.
# The root Dockerfile pins the opposite way on purpose (an explicit
# --build-arg ref, for a human running it standalone) -- reusing that one
# here would be a real correctness risk: action.yml's own Docker-action
# syntax has no way to pass --build-arg, so a shared file's ref pin would
# have to be a hardcoded default that silently drifts out of sync with
# whatever tag actually triggered this build.
#
# Lives at the repo root, not .github/docker/ alongside entrypoint.sh --
# a real build failure showed why: GitHub's own Docker-action build uses
# *this file's own directory* as the build context, not action.yml's
# directory (`docker build -f <path> <dirname of that path>`, confirmed
# directly from a real failing run's own command line). Filed in
# .github/docker/ instead, `COPY .` here would only ever see that one
# subdirectory's own two files -- silently missing the wheel install and
# failing to find entrypoint.sh at all, both undetectable without an
# actual build (YAML syntax and local shell testing both passed first).
FROM ubuntu:24.04

# unix/aarch64's own libffi-dev:arm64 is a target-arch package -- Ubuntu's
# default archive.ubuntu.com/security.ubuntu.com mirrors only carry
# amd64/i386; every other architecture lives on a separate mirror,
# ports.ubuntu.com, that the default sources never reference (confirmed
# live, twice: once on a real GitHub-hosted runner -- docs/BACKLOG.md's
# D20 addendum -- and again directly in this image's own base, ubuntu:24.04,
# before writing this). i386 is NOT one of those -- it stays on the main
# archive.ubuntu.com/security.ubuntu.com mirrors alongside amd64 (confirmed
# live the same way, D25's addendum), so it only needs adding to the
# existing stanzas' own Architectures: line, no ports.ubuntu.com stanza of
# its own. 24.04 moved to the deb822 sources format, so this restricts the
# existing stanzas to amd64,i386 and appends arm64-only ones pointing at
# ports.ubuntu.com, rather than editing the now-unused plain
# /etc/apt/sources.list.
RUN dpkg --add-architecture arm64 && \
    dpkg --add-architecture i386 && \
    sed -i '/^Types: deb$/a Architectures: amd64,i386' /etc/apt/sources.list.d/ubuntu.sources && \
    { \
        echo; \
        echo 'Types: deb'; \
        echo 'URIs: http://ports.ubuntu.com/ubuntu-ports'; \
        echo 'Suites: noble noble-updates noble-backports'; \
        echo 'Components: main universe restricted multiverse'; \
        echo 'Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg'; \
        echo 'Architectures: arm64'; \
        echo; \
        echo 'Types: deb'; \
        echo 'URIs: http://ports.ubuntu.com/ubuntu-ports'; \
        echo 'Suites: noble-security'; \
        echo 'Components: main universe restricted multiverse'; \
        echo 'Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg'; \
        echo 'Architectures: arm64'; \
    } >> /etc/apt/sources.list.d/ubuntu.sources

# Same apt-only prerequisites as the root Dockerfile -- see that file's
# own comment for the full per-package reasoning (D3/M2/D18/D20/D24).
# Kept in sync by hand today; a real drift risk if one changes without
# the other, not automated away here.
#
# gcc-13-multilib, not gcc-multilib: a real, documented package
# conflict, found only by an actual `docker build` failing (this
# sandbox never had gcc-multilib installed at all, so it never
# surfaced locally) -- gcc-multilib (the transitional/meta package)
# unconditionally Conflicts: every gcc-N-<target>-linux-gnu cross
# package, every GCC version, apt-cache show's own field says so
# outright. gcc-13-multilib (the real, versioned package it depends on)
# carries no such Conflicts at all -- same libc6-dev-i386/lib32gcc-13-dev
# multilib support, verified live (a real `gcc -m32` build and run)
# alongside gcc-aarch64-linux-gnu/gcc-arm-linux-gnueabihf/
# gcc-mipsel-linux-gnu installed in the very same transaction.
#
# pkg-config: ports/unix/Makefile's own LIBFFI_CFLAGS/LIBFFI_LDFLAGS
# (`pkg-config --cflags/--libs libffi`) -- without it those stay empty
# and modffi.c fails to find ffi.h even with libffi-dev installed. A
# real build failure caught this too, one layer past the -m32 fix
# above: apt succeeded, gcc -m32 worked, then unix/x64 (no
# cross-compile at all) still failed the same way for a third,
# independent reason.
#
# libffi-dev:i386/linux-libc-dev:i386: usermod unix/x86's own modffi.c
# build, under gcc -m32. NOT the same fix as plain libffi-dev above --
# libffi's own ffitarget.h is word-size-specific (it encodes the target
# ABI), so a 32-bit compile needs the real i386 package, not the amd64
# one under a borrowed path. An earlier attempt symlinked
# i386-linux-gnu -> x86_64-linux-gnu instead, which happened to fix
# asm/errno.h but fed modffi.c the wrong-arch ffitarget.h -- a fourth
# real build failure (`#warning ... X86 IS DEFINED [-Werror=cpp]`,
# `-Werror` turning it fatal) this replaced it after. linux-libc-dev:i386
# is what actually ships asm/errno.h under a real i386-linux-gnu/
# directory (the symlink's only genuine job) -- no apt package installs
# one at all otherwise.
#
# libc6-dev-arm64-cross/libc6-dev-armhf-cross/libc6-dev-mipsel-cross: a
# fifth real build failure, on unix/aarch64 -- the first arch past the
# two x86 fixes above to actually reach its own compiler for the first
# time in either image. Each cross gcc package only Recommends: its own
# libc6-dev-<arch>-cross (confirmed via apt-cache depends), which
# --no-install-recommends below skips -- the cross-compiler itself still
# runs, but the target's own kernel/libc headers are missing, so any
# source touching <asm/errno.h> (most of ports/unix) fails to even
# preprocess. Reproduced and fixed live (purge, reinstall with
# --no-install-recommends to reproduce, then install these three to
# fix) before either armhf or mipsel had ever been tried for real in
# either image -- both share the identical gap. Each package pulls its
# own linux-libc-dev-<arch>-cross as a hard Depends, so naming these
# three is enough.
#
# libtool: a sixth real build failure, past the fifth above --
# unix/armhf's own deplibs step got past ltdl.m4 (libltdl-dev) only to
# fail differently: `libtoolize: No such file or directory`, then
# `Makefile.am:39: error: Libtool library used but 'LIBTOOL' is
# undefined`. Same shape as the libc6-dev-<arch>-cross gap:
# libltdl-dev only Recommends: libtool (confirmed via apt-cache
# depends), which --no-install-recommends skips. This project's own
# dev sandbox already had libtool installed from unrelated earlier
# work, which is exactly why the ltdl.m4 fix looked complete when
# first verified there -- only a real image without it ever exposed
# the gap.
#
# wabt: examples/wasm2mpy's own toolchain (wasm2c), pinned by nothing more
# than "whatever Ubuntu 24.04 carries" -- deliberately, since that is the
# same version build-examples.yml's own runner-level apt-get used to
# install before the build itself moved into this container (confirmed
# live: 1.0.41 fails to compile that example's vendored runtime.c, the
# 1.0.36 Ubuntu ships works). Keep this image's own Ubuntu base in sync
# with whatever build-examples.yml expects if that ever changes.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    ca-certificates \
    curl \
    python3 \
    gcc-13-multilib \
    gcc-mingw-w64-x86-64 \
    gcc-mingw-w64-i686 \
    gcc-aarch64-linux-gnu \
    libffi-dev \
    libffi-dev:i386 \
    linux-libc-dev:i386 \
    libffi-dev:arm64 \
    libc6-dev-arm64-cross \
    gcc-arm-linux-gnueabihf \
    libc6-dev-armhf-cross \
    gcc-mipsel-linux-gnu \
    libc6-dev-mipsel-cross \
    libltdl-dev \
    libtool \
    pkg-config \
    libusb-1.0-0 \
    wabt \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Installed from this exact checkout, not a git fetch -- the runner
# already checked out the pinned ref before building this Dockerfile, so
# COPY . picks up precisely that ref's own source: no separate network
# round-trip, no version-drift risk. Installed here, at build time, with
# no extras -- the common case, and the whole point of converting this
# action to a Docker image at all (the install cost is paid once, at
# build/cache time, not on every job run). `inputs.extras` is the one
# thing that can't be known at build time; entrypoint.sh reinstalls with
# it, from this same already-COPY'd source, only when a caller actually
# sets that input -- everyone else pays nothing extra for it.
COPY . /opt/cibuildmp
RUN uv tool install /opt/cibuildmp

# `uv tool install` puts the binary at ~/.local/bin -- not on this base
# image's default PATH at all (verified live against the root Dockerfile's
# own identical install step: `which cibuildmp` finds nothing with a bare
# /usr/local/bin:/usr/bin:/bin PATH, the same set a plain, non-login
# container process actually gets).
ENV PATH="/root/.local/bin:${PATH}"

COPY .github/docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

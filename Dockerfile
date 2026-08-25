# Everything cibuildmp itself can self-provision (every natmod toolchain
# except x86, and usermod's emsdk/ESP-IDF/llvm-mingw) downloads its own
# pinned copy into ~/.cache/cibuildmp on first use -- D3's own design, the
# same reason this image stays lean rather than baking every toolchain in.
# Mount that directory as a volume to persist it across container runs:
#
#   docker build -t cibuildmp .                                   # default ref, below
#   docker build -t cibuildmp --build-arg CIBUILDMP_REF=v0.3.0 .   # a specific tag
#   docker run --rm -it \
#     -v cibuildmp-cache:/root/.cache/cibuildmp \
#     -v "$PWD":/work -w /work \
#     cibuildmp --dry-run
#
# On Windows, run this through WSL2 (Docker Desktop's own WSL2 backend, or
# a plain `docker` install inside a WSL2 distro) -- see README.md's own
# "Target support" tables for why no target here needs a Windows host at
# all, `windows`'s own three usermod arches included.
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

# Only what cibuildmp cannot self-provision (docs/BACKLOG.md's own D3/M2
# "why not docker for x86" reasoning, and D18/D20/D24's own addenda):
#   gcc-13-multilib        -- natmod's own x86 arch, and usermod unix/x86.
#                             No downloadable tarball exists for either;
#                             this is the one arch/target pair D3 always
#                             said would need a real Linux userland. The
#                             *versioned* package, not the gcc-multilib
#                             transitional one -- a real, documented apt
#                             Conflicts: gcc-multilib has against every
#                             gcc-N-<target>-linux-gnu cross package, every
#                             GCC version (found only by an actual `docker
#                             build` failing; this same dev sandbox never
#                             had gcc-multilib installed at all, so it
#                             never surfaced locally). gcc-13-multilib
#                             carries no such Conflicts -- same
#                             libc6-dev-i386/lib32gcc-13-dev multilib
#                             support, verified live (a real `gcc -m32`
#                             build and run) alongside every cross
#                             package below, in the same transaction.
#   gcc-mingw-w64-x86-64/  -- usermod windows/x64 and windows/x86. No
#   gcc-mingw-w64-i686        Linux distro packages an aarch64-w64-mingw32
#                             target at all -- windows/arm64 downloads its
#                             own llvm-mingw toolchain instead (see
#                             usermod/llvmmingw.py), nothing to apt-install
#                             for it here.
#   libffi-dev             -- usermod unix/x64 and unix/x86: modffi.c
#                             (MICROPY_PY_FFI) needs the host's own
#                             ffi.h, native amd64, distinct from the
#                             target-arch libffi-dev:arm64 below. Missed
#                             on the first pass -- nothing needed it
#                             until usermod's own unix arches actually
#                             built here for the first time.
#   libffi-dev:i386/       -- usermod unix/x86's own modffi.c build,
#   linux-libc-dev:i386        under gcc -m32: NOT the same headers as
#                             plain libffi-dev above. libffi's own
#                             ffitarget.h is genuinely word-size-specific
#                             (it encodes the target ABI), so a 32-bit
#                             compile needs the real i386 package here,
#                             not the amd64 one under a borrowed path --
#                             an earlier attempt symlinked
#                             i386-linux-gnu -> x86_64-linux-gnu instead,
#                             which happened to fix asm/errno.h below but
#                             fed modffi.c the wrong-arch ffitarget.h, a
#                             real build failure
#                             (`#warning ... X86 IS DEFINED
#                             [-Werror=cpp]`) this replaced it after.
#                             linux-libc-dev:i386 is what actually ships
#                             asm/errno.h under i386-linux-gnu/ (the
#                             symlink's only genuine job) -- no apt
#                             package installs a real, arch-correct
#                             i386-linux-gnu/ directory at all otherwise.
#   gcc-aarch64-linux-gnu/ -- usermod unix/aarch64, unix/armhf, unix/mipsel
#   libffi-dev:arm64/         (D20, D24). libltdl-dev is not the
#   gcc-arm-linux-gnueabihf/  cross-compiler itself -- armhf/mipsel's own
#   gcc-mipsel-linux-gnu/     deplibs step (a real, static libffi build)
#   libltdl-dev               fails its own ./autogen.sh without it
#                             ("possibly undefined macro:
#                             LT_SYS_SYMBOL_USCORE" -- ltdl.m4's, which
#                             autoconf/automake/libtool alone don't ship).
#   libc6-dev-arm64-cross/ -- each cross gcc package only Recommends:
#   libc6-dev-armhf-cross/    its own libc6-dev-<arch>-cross (confirmed via
#   libc6-dev-mipsel-cross    apt-cache depends), which --no-install-recommends
#                             below skips -- silently fine for linking (the
#                             cross-compiler itself still runs) but leaves
#                             the target's own kernel/libc headers missing,
#                             so any source touching <asm/errno.h> (most of
#                             ports/unix) fails to even preprocess. A real
#                             build failure caught this on unix/aarch64
#                             specifically, the first arch past the x86
#                             fixes above to actually reach the compiler --
#                             armhf/mipsel share the identical gap,
#                             reproduced and fixed live the same way before
#                             either was ever tried for real in either
#                             image. Each of these three packages pulls its
#                             own linux-libc-dev-<arch>-cross as a hard
#                             Depends, so naming them here is enough.
#   pkg-config             -- ports/unix/Makefile's own LIBFFI_CFLAGS/
#                             LIBFFI_LDFLAGS (`pkg-config --cflags/--libs
#                             libffi`) -- without it those stay empty and
#                             modffi.c fails to find ffi.h even with
#                             libffi-dev installed. A real build failure
#                             caught this too, one layer past the -m32
#                             fix: apt succeeded, gcc -m32 worked, then
#                             unix/x64 (no cross-compile at all) still
#                             failed the same way for a third, independent
#                             reason.
#   libusb1               -- usermod esp32: openocd-esp32 (part of
#                             ESP-IDF's own default toolset, installed
#                             regardless of what a usermod build actually
#                             needs it for) depends on this at runtime.
#   git, ca-certificates,  -- fetching MicroPython, cloning ESP-IDF,
#   curl, python3             downloading pinned toolchain tarballs, and
#                             ESP-IDF's own Python env bootstrap.
#   build-essential        -- the host gcc every natmod x64/x86 arch and
#                             usermod unix/x64/x86 already assume is there.
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
    pkg-config \
    libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Installed from a pinned git ref, not a local COPY or PyPI -- keeps this
# buildable from the bare Dockerfile alone (no repo checkout needed as
# build context) and the resulting image self-documenting about exactly
# what it shipped (`docker history` shows the real --build-arg used, not
# "whatever was in the directory"). Override at build time for a specific
# release: `docker build --build-arg CIBUILDMP_REF=v0.3.0 .` -- same "pin
# a tag, not @main" rule README.md's own Versioning section already holds
# every other consumer to.
ARG CIBUILDMP_REF=v0.3.0
RUN uv tool install "git+https://github.com/ballistics-lab/cibuildmp.git@${CIBUILDMP_REF}"

# `uv tool install` puts the binary at ~/.local/bin -- not on this base
# image's default PATH at all (verified live: `which cibuildmp` finds
# nothing with a bare /usr/local/bin:/usr/bin:/bin PATH, the same set a
# plain, non-login container process actually gets).
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /work
ENTRYPOINT ["cibuildmp"]

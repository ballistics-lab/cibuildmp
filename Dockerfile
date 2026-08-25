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
# before writing this). 24.04 moved to the deb822 sources format, so this
# restricts the existing stanzas to amd64 and appends arm64-only ones
# pointing at ports.ubuntu.com, rather than editing the now-unused plain
# /etc/apt/sources.list.
RUN dpkg --add-architecture arm64 && \
    sed -i '/^Types: deb$/a Architectures: amd64' /etc/apt/sources.list.d/ubuntu.sources && \
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
#   gcc-aarch64-linux-gnu/ -- usermod unix/aarch64, unix/armhf, unix/mipsel
#   libffi-dev:arm64/         (D20, D24). libltdl-dev is not the
#   gcc-arm-linux-gnueabihf/  cross-compiler itself -- armhf/mipsel's own
#   gcc-mipsel-linux-gnu/     deplibs step (a real, static libffi build)
#   libltdl-dev               fails its own ./autogen.sh without it
#                             ("possibly undefined macro:
#                             LT_SYS_SYMBOL_USCORE" -- ltdl.m4's, which
#                             autoconf/automake/libtool alone don't ship).
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
    libffi-dev:arm64 \
    gcc-arm-linux-gnueabihf \
    gcc-mipsel-linux-gnu \
    libltdl-dev \
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

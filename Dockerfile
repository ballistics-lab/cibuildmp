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

# Only what cibuildmp cannot self-provision (docs/BACKLOG.md's own D3/M2
# "why not docker for x86" reasoning, and D18's windows/x64/x86 addendum):
#   gcc-multilib          -- natmod's own x86 arch, and usermod unix/x86.
#                             No downloadable tarball exists for either;
#                             this is the one arch/target pair D3 always
#                             said would need a real Linux userland.
#   gcc-mingw-w64-x86-64/  -- usermod windows/x64 and windows/x86. No
#   gcc-mingw-w64-i686        Linux distro packages an aarch64-w64-mingw32
#                             target at all -- windows/arm64 downloads its
#                             own llvm-mingw toolchain instead (see
#                             usermod/llvmmingw.py), nothing to apt-install
#                             for it here.
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
    gcc-multilib \
    gcc-mingw-w64-x86-64 \
    gcc-mingw-w64-i686 \
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

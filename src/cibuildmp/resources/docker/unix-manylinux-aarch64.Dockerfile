# One of five per-(arch, libc) `unix` images -- see
# unix-manylinux-x64.Dockerfile's own header for the full split
# rationale (D26/D31).
#
# aarch64: cross-compiles from this image's own x86_64 base via apt's
# own gcc-aarch64-linux-gnu + libffi-dev:arm64 -- verified live end to
# end on a real ubuntu-latest runner (build.py's own module docstring
# has the story), a genuine dynamically-linked ARM aarch64 ELF, no
# deplibs/static-link step needed the way armhf/mipsel require.
# libffi-dev:arm64/libc6-dev-arm64-cross need arm64 packages neither
# Ubuntu's default mirrors carry -- the ports.ubuntu.com rewrite below
# is D20's own fix for that, transcribed unchanged.
#
# Build: docker build -t cibuildmp-unix-manylinux-aarch64 -f src/cibuildmp/resources/docker/unix-manylinux-aarch64.Dockerfile .
# Use:   CIBMP_UNIX_AARCH64_MANYLINUX_DOCKER_IMAGE=cibuildmp-unix-manylinux-aarch64 cibuildmp ...
#
# Not yet built for real via `docker build` -- see
# unix-manylinux-x64.Dockerfile's own header for the same open
# verification gap.
FROM ubuntu:24.04

# The default entry must explicitly EXCLUDE arm64, not include it:
# archive.ubuntu.com (this entry's own default URIs) never carries arm64
# packages at all -- only ports.ubuntu.com does (the separate block
# below). Left unrestricted, apt would try arm64 indices against
# archive.ubuntu.com too, once `dpkg --add-architecture arm64` makes it
# a known architecture, and fail outright.
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

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3 \
    gcc-aarch64-linux-gnu \
    libffi-dev:arm64 \
    libc6-dev-arm64-cross \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# D26's own proof-of-concept, `unix` port only -- one image per port
# instead of today's single Dockerfile/action.Dockerfile combining every
# port's toolchain in one filesystem. See docs/BACKLOG.md's own D26 for
# the full design, tradeoffs, and what this deliberately does not fix
# (unix's own five architectures still combine in one image here, same as
# today -- the honest limit D26 documents up front).
#
# Unlike Dockerfile/action.Dockerfile, `cibuildmp` itself is NOT installed
# in this image at all -- it stays on the bare host and runs this image's
# own toolchain via ordinary sibling `docker run` calls
# (usermod/dockerrun.py), never inside a container itself. That is the
# whole point of the split: no `uv tool install`, no ENTRYPOINT, nothing
# but the toolchain a real `make -C ports/unix` invocation needs.
#
# Build: docker build -t cibuildmp-unix -f docker/unix.Dockerfile .
# Use:   CIBMP_UNIX_DOCKER_IMAGE=cibuildmp-unix cibuildmp ...
FROM ubuntu:24.04

# Identical apt-source setup to Dockerfile/action.Dockerfile's own --
# unix/aarch64's libffi-dev:arm64 and unix/x86's modffi.c both need real
# foreign-arch packages neither Ubuntu's default mirrors carry (arm64) nor
# --no-install-recommends alone provisions (i386's own kernel/libffi
# headers) -- see that file's own comment for the full story (D20, D25).
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

# Only what ports/unix's own build (all five arches) needs -- no mingw
# (windows), no wabt (natmod's own wasm2mpy example), no libusb-1.0-0
# (esp32 only). git/ca-certificates/curl are not needed here at all: the
# MicroPython checkout and manifest generation both happen on the host,
# before this image is ever invoked -- only `make` itself runs inside.
# python3 stays: ports/unix/Makefile's own build shells out to it
# directly (makeversionhdr.py, mpy-tool.py, qstr generation).
#
# gcc-13-multilib, not gcc-multilib; libc6-dev-arm64-cross/
# libc6-dev-armhf-cross/libc6-dev-mipsel-cross named explicitly (each
# cross gcc only Recommends: its own, which --no-install-recommends
# skips); libffi-dev:i386/linux-libc-dev:i386 for unix/x86's own
# modffi.c, not a symlink; libtool (deplibs' own ./autogen.sh needs
# libtoolize, which libltdl-dev only Recommends:, not Depends:) -- all
# six real bugs D25/D26 found and fixed, transcribed here unchanged
# rather than re-discovered for this image too.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3 \
    gcc-13-multilib \
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
    && rm -rf /var/lib/apt/lists/*

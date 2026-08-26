# natmod's build environment: one amd64 image holding every toolchain the
# ten `dynruntime.mk` arches need.
#
# **One image, not one per arch** -- the shape `windows.Dockerfile` already
# has, and deliberately not the per-target-native shape record 0043 gave
# `unix`. The two ports differ in what they produce and the image follows
# that: a `unix` cell builds a *Linux executable for that architecture*, so
# an image native to it is the only honest way to get a real libc floor;
# natmod produces a `.mpy`, whose architecture lives in a header byte and
# whose toolchains are all cross-compilers regardless of host. Nothing here
# is native to anything, so there is nothing for a native image to buy --
# and one pull per run beats ten.
#
# `x86` is the one arch that looks like an exception and is not. It builds
# with the host gcc and `-m32`, so it needs 32-bit multilib -- which is
# exactly why it could not be built on an arm64 runner before this image
# existed (`action.yml` skipped the i386 setup on non-amd64 hosts, because
# a 32-bit x86 cross-build is not a thing an arm64 host does). Inside a
# `linux/amd64` image the host *is* amd64, always, whatever the machine
# underneath is doing -- so multilib is correct here by construction, and
# the arch stops depending on what the runner happens to be.
#
# Base is `ubuntu:24.04` rather than a pypa image: natmod links nothing
# against the host libc (a `.mpy` is relocatable machine code, not an ELF
# executable), so it has no libc floor to state and PEP 600 has nothing to
# say about it. `manylinux_2_39_mipsel`'s own entry in
# `pinned_docker_images.toml` makes the same call for the same kind of
# reason.
FROM ubuntu:24.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# ── apt: the host-native half ─────────────────────────────────────────
#
# `gcc-13-multilib` + `linux-libc-dev:i386` are for `x86` alone, and
# `build-essential` covers `x64` (plain host gcc, no cross prefix). Record
# 0025 paid for six real apt/gcc bugs finding this list; what is left here
# is what survived record 0033's slimming, minus everything the `unix`
# cross-toolchains needed before those moved into their own images.
RUN set -eux; \
    dpkg --add-architecture i386; \
    sed -i '/^Types: deb$/a Architectures: amd64 i386' \
        /etc/apt/sources.list.d/ubuntu.sources; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
        gcc-13-multilib \
        linux-libc-dev:i386 \
        python3 \
        xz-utils; \
    rm -rf /var/lib/apt/lists/*

# ── the four downloaded cross toolchains ──────────────────────────────
#
# **This file is the pin.** The URLs and hashes lived in
# `resources/natmod.toml`'s `[[toolchain]]` table while a host-side
# resolver read them at build time; record 0049 deleted that resolver,
# and data whose only consumer is a Dockerfile belongs in the Dockerfile
# rather than in a table nothing reads. Each entry carries its sha256 and
# is checked below, which the old host path also did and this image had
# briefly stopped doing.
#
# Every one of them ships a `linux-x64`/`x86_64` binary and has no other
# build, which is the second reason this image is amd64: there is no arm64
# toolchain to put in an arm64 image even if the shape called for one.
#
# **Prefix reconciliation happens here, once, instead of at every build.**
# xpack ships `riscv-none-elf-*` where `dynruntime.mk` expects
# `riscv64-unknown-elf-*`, and Espressif ships `xtensa-esp-elf-*` where it
# expects `xtensa-esp32-elf-*` (record 0036 found both, live). The symlinks
# below make the expected names real on PATH, so a build inside this image
# needs no prefix logic at all.
# Versions, for the record and for a reviewer diffing a bump:
# arm-none-eabi     15.2.1-1.1
# riscv-none-elf    15.2.0-1
# xtensa-lx106-elf  standalone
# xtensa-esp-elf    16.1.0_20260609
RUN set -eux; \
    mkdir -p /opt/toolchains; \
    for spec in \
        "arm-none-eabi|https://github.com/xpack-dev-tools/arm-none-eabi-gcc-xpack/releases/download/v15.2.1-1.1/xpack-arm-none-eabi-gcc-15.2.1-1.1-linux-x64.tar.gz|da6a49ad4003944b823c6c93702a8787c922ab34bd7e918ec0eaf6933a9b1ff6" \
        "riscv-none-elf|https://github.com/xpack-dev-tools/riscv-none-elf-gcc-xpack/releases/download/v15.2.0-1/xpack-riscv-none-elf-gcc-15.2.0-1-linux-x64.tar.gz|aaaa8060c914851a3e5ee1ba82cc3d6f80972f90638a05c6e823a37557a33758" \
        "xtensa-lx106-elf|https://micropython.org/resources/xtensa-lx106-elf-standalone.tar.gz|f45f755ea8021c24c9b36cc3d363973927857fe4e6279f32e6968abfac38d1ba" \
        "xtensa-esp-elf|https://github.com/espressif/crosstool-NG/releases/download/esp-16.1.0_20260609/xtensa-esp-elf-16.1.0_20260609-x86_64-linux-gnu.tar.xz|f708752ebb35cab21f184b2574114ed1187619db0edb8a4ba913c06ca2fa675e" \
    ; do \
        IFS="|" read -r name url sha <<< "$spec"; \
        dest="/opt/toolchains/${name}"; \
        mkdir -p "$dest"; \
        curl -fsSL -o /tmp/tc.tar "$url"; \
        # **Verified, not merely fetched.** These are four third-party
        # tarballs pulled over the network into an image every build then
        # runs compilers out of; "it downloaded" and "it is the artifact
        # that was pinned" are different claims and only the second is
        # worth anything. The hashes come from `resources/natmod.toml`,
        # which held them for the old host-side resolver and is where
        # they were cross-checked against a fresh sha256sum rather than
        # copied from a sidecar.
        echo "$sha  /tmp/tc.tar" | sha256sum -c -; \
        # --strip-components=1: each of these has a single versioned
        # top-level directory, and flattening it is what keeps the PATH
        # entries below free of version numbers, so a bump is one line
        # here and no other edit.
        tar -xf /tmp/tc.tar --strip-components=1 -C "$dest"; \
        rm -f /tmp/tc.tar; \
    done; \
    # The two names dynruntime.mk expects but no upstream ships.
    ln -s /opt/toolchains/riscv-none-elf/bin/riscv-none-elf-gcc \
          /usr/local/bin/riscv64-unknown-elf-gcc; \
    for tool in ld objcopy objdump size nm readelf strip ar ranlib; do \
        ln -s "/opt/toolchains/riscv-none-elf/bin/riscv-none-elf-${tool}" \
              "/usr/local/bin/riscv64-unknown-elf-${tool}"; \
        ln -s "/opt/toolchains/xtensa-esp-elf/bin/xtensa-esp-elf-${tool}" \
              "/usr/local/bin/xtensa-esp32-elf-${tool}"; \
    done; \
    ln -s /opt/toolchains/xtensa-esp-elf/bin/xtensa-esp-elf-gcc \
          /usr/local/bin/xtensa-esp32-elf-gcc

# ── the build's own Python ────────────────────────────────────────────
#
# `py/dynruntime.mk` runs `tools/mpy_ld.py`, which does a bare
# `from elftools.elf... import` with no try/except, and shells out to
# `ar`. Record 0012 made both **cibuildmp's own dependencies** rather
# than something a build installs, and `make_command()`'s
# `PYTHON=<sys.executable>` is how that reaches make: dynruntime.mk
# assigns `PYTHON` with a plain `=`, so pointing it at cibuildmp's own
# interpreter wins over the `python3` it would otherwise use.
#
# **That mechanism cannot cross into a container**, and this layer is
# what replaces it: `sys.executable` names a path in the *host's* virtual
# environment, which does not exist here. So a containerised natmod build
# passes `PYTHON=python3` and this image has to be the thing that makes
# that Python sufficient. `ar` comes from `build-essential` above.
#
# Its own RUN, deliberately, rather than folded into the apt layer at the
# top: it is a different concern -- the Python environment mpy_ld.py
# needs, not a cross toolchain -- and keeping it last means adding or
# bumping it never invalidates the 3.4GB of toolchains above.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends python3-pyelftools; \
    rm -rf /var/lib/apt/lists/*; \
    python3 -c "from elftools.elf.elffile import ELFFile"

# Appended, not prepended, for the same reason windows.Dockerfile's own
# PATH is: these directories ship generically-named helpers that would
# otherwise shadow the apt gcc `x86`/`x64` are pinned to.
ENV PATH="${PATH}:/opt/toolchains/arm-none-eabi/bin:/opt/toolchains/riscv-none-elf/bin:/opt/toolchains/xtensa-lx106-elf/bin:/opt/toolchains/xtensa-esp-elf/bin"

# `unix` build image for the **manylinux_2_39_mipsel** cell -- the one documented
# exception to record 0043's native-image model, and the only `unix`
# image that still cross-compiles.
#
# There is nothing to be native to. pypa publishes no mipsel image, PEP
# 600 defines no `manylinux_*_mipsel` tag, and Docker has no official
# image for 32-bit mipsel either. So this cell keeps exactly the model
# every `unix` arch used before 0043 -- an `ubuntu:24.04` amd64 host with
# an apt cross-toolchain -- and says so plainly instead of pretending to
# a floor it cannot claim. Its tag is `manylinux_2_39_mipsel`: PEP 425's plain,
# unqualified platform tag, which is precisely what a Linux binary making
# no libc-floor claim is.
#
# It has no `resources/pinned_pypa_images.toml` entry for the same
# reason: that file mirrors upstream's own pins, and this base is not one
# of them.
#
# Content is the former docker/unix-manylinux-mipsel.Dockerfile,
# unchanged -- including `libltdl-dev`, which is not the cross-compiler
# but the fix for `deplibs`' own `./autogen.sh` failing with "possibly
# undefined macro: LT_SYS_SYMBOL_USCORE" (D25's sixth real bug;
# autoconf/automake/libtool alone do not ship `ltdl.m4`). This arch still
# needs `MICROPY_STANDALONE=1` and its static vendored libffi, since
# unlike every native cell it has no system libffi for its target.
#
# Build: docker buildx build --platform=linux/amd64 \
#          -t manylinux_2_39_mipsel \
#          -f docker/manylinux_2_39_mipsel.Dockerfile .
# Use:   CIBMP_UNIX_MANYLINUX_2_39_MIPSEL_DOCKER_IMAGE=manylinux_2_39_mipsel cibuildmp ...
FROM ubuntu:24.04

# `libc6-dev-mipsel-cross` is version-pinned, unlike every other package
# here, because this image's *name* is a claim about it. `2_39` in the tag
# is this cross-glibc's own version (`2.39-0ubuntu8cross2`, read with
# `apt-cache policy` in the real image), so letting apt install whatever
# `ubuntu:24.04` ships next would silently make the tag false the first
# time Ubuntu bumps it -- exactly the "manylinux means whatever the base
# happens to ship" failure record 0031 wrote up and record 0043 set out
# to end. Every other cell gets that guarantee from a digest-pinned pypa
# base; this one has no pypa base, so it pins the package instead.
#
# `2.39-*` rather than the exact `2.39-0ubuntu8cross2`: apt accepts the
# version glob (verified, not assumed -- a real install inside
# `ubuntu:24.04` succeeds with it), and an Ubuntu security update to the
# same 2.39 line neither changes the floor nor should break this build,
# while a jump to 2.40 must. The exact revision is removed from the
# archive when superseded; the 2.39 line is what the tag is about.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3 \
    gcc-mipsel-linux-gnu \
    "libc6-dev-mipsel-cross=2.39-*" \
    libltdl-dev \
    libtool \
    && rm -rf /var/lib/apt/lists/*

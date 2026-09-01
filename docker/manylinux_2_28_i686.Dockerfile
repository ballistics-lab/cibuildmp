# `unix` build image for the **manylinux_2_28_i686** cell -- one native
# image per (architecture, libc floor), record 0043.
#
# `FROM` is pypa's own `manylinux_2_28_i686`, digest-pinned from
# `resources/pinned_pypa_images.toml` (which mirrors cibuildwheel's own
# pinned list). Everything this image is -- the libc floor it guarantees,
# the gcc that targets i686, the whole userland -- comes from there.
# cibuildmp adds only what `ports/unix` needs on top and nothing else,
# which is what makes "same floor as a manylinux wheel" a true statement
# rather than a label.
#
# **This is a `linux/386` image**, built and published for its own
# target architecture rather than cross-compiled from amd64. That is the
# whole of 0043: the target arch and the container platform are one fact,
# so nothing anywhere records which arch the *host* is, and the same pin
# works unchanged on an x86_64 runner and on an `ubuntu-24.04-arm` one.
# The non-native side runs under binfmt/QEMU; `dockerrun._probe_platform()`
# is what names a missing binfmt instead of letting `make` fail with
# `exec format error`.
#
# Build: docker buildx build --platform=linux/386 \
#          -t manylinux_2_28_i686 \
#          -f docker/manylinux_2_28_i686.Dockerfile .
# Use:   CIBMP_UNIX_MANYLINUX_2_28_I686_DOCKER_IMAGE=manylinux_2_28_i686 cibuildmp ...
#
# Published by .github/workflows/publish-docker-images.yml; the digest it
# prints goes into resources/pinned_docker_images.toml (record 0033 --
# cibuildmp never builds this itself, it only ever pulls it).
FROM quay.io/pypa/manylinux_2_28_i686@sha256:bce1c1f15a59f9b4aa3e8a82aab777f0dc987213dcae66609d25651c277e86c5

# `libffi-devel` is the one thing missing, and the only reason this image
# is published at all rather than pypa's being pinned directly.
# `ports/unix/Makefile` resolves libffi through `pkg-config --cflags/libs
# libffi`, and inside a stock `manylinux_2_28_i686` that command fails
# outright -- verified by running it in the real image, not assumed. gcc,
# make, python3, pkg-config, libtool and autoreconf are all already there.
#
# cibuildwheel's own answer to this same gap is `before-all`, a
# user-configured `yum install` run inside the container. cibuildmp has no
# such user-facing hook and deliberately wants none for its own build
# infrastructure (D28: a build image is infrastructure, not a
# cibuildmp.toml knob), so it goes in a layer instead.
RUN dnf install -y libffi-devel && dnf clean all

# `unix` build image for the **manylinux_2_31_armv7l** cell -- one native
# image per (architecture, libc floor), record 0043.
#
# `FROM` is pypa's own `manylinux_2_31_armv7l`, digest-pinned from
# `resources/pinned_pypa_images.toml` (which mirrors cibuildwheel's own
# pinned list). Everything this image is -- the libc floor it guarantees,
# the gcc that targets armv7l, the whole userland -- comes from there.
# cibuildmp adds only what `ports/unix` needs on top and nothing else,
# which is what makes "same floor as a manylinux wheel" a true statement
# rather than a label.
#
# **This is a `linux/arm/v7` image**, built and published for its own
# target architecture rather than cross-compiled from amd64. That is the
# whole of 0043: the target arch and the container platform are one fact,
# so nothing anywhere records which arch the *host* is, and the same pin
# works unchanged on an x86_64 runner and on an `ubuntu-24.04-arm` one.
# The non-native side runs under binfmt/QEMU; `dockerrun._probe_platform()`
# is what names a missing binfmt instead of letting `make` fail with
# `exec format error`.
#
# Build: docker buildx build --platform=linux/arm/v7 \
#          -t manylinux_2_31_armv7l \
#          -f docker/manylinux_2_31_armv7l.Dockerfile .
# Use:   CIBMP_UNIX_MANYLINUX_2_31_ARMV7L_DOCKER_IMAGE=manylinux_2_31_armv7l cibuildmp ...
#
# Published by .github/workflows/publish-docker-images.yml; the digest it
# prints goes into resources/pinned_docker_images.toml (record 0033 --
# cibuildmp never builds this itself, it only ever pulls it).
FROM quay.io/pypa/manylinux_2_31_armv7l@sha256:235c282aa532e01136e5e1db0a9403463032c9281fa56d89b39e45dfb5081484

# **No `RUN` at all, deliberately.** Verified by running the checks
# inside the real image rather than assumed: this base already resolves
# `pkg-config --libs libffi` and already ships gcc, make, python3,
# pkg-config, libtool and autoreconf. `ports/unix` needs nothing else, so
# adding a no-op package step would only invent a way for this cell to
# drift from the base it claims to be.
#
# It is still published as a cibuildmp image rather than pinning pypa's
# directly, so that all fifteen cells share one name scheme, one publish
# pipeline and one pin table -- and so that the day `ports/unix` does need
# a package here, this file is already the place it goes. The layers are
# the base's own, so a registry stores nothing new for it.

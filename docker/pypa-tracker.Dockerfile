# Not a build step. Dependabot's own docker ecosystem, pointed at this
# directory (.github/dependabot.yml), reads `FROM` lines and opens a PR
# when the digest a tag currently resolves to moves -- this file exists so
# it has something to read for the nine `unix` cells that have no
# Dockerfile of their own (record 0044/0058: `armv7l`'s `manylinux_2_31`,
# `riscv64`'s `manylinux_2_39`, and every `musllinux_1_2` cell -- each
# verified to be a bare `FROM` and nothing else, so publishing a second
# copy under a cibuildmp name would have been pure overhead). The other
# five `unix` Dockerfiles already carry a real, buildable `FROM
# quay.io/pypa/...@sha256:...` of their own and need no entry here;
# duplicating them would just be two things Dependabot has to agree with
# each other.
#
# `bin/update_docker.py --pypa` is what actually moves a pin in
# `resources/pinned_pypa_images.toml` -- a Dependabot PR against this file
# is a notification that a base moved, not a fix: bumping the real pin is
# still a maintainer's own reviewed decision (a new base can mean a new
# libc floor, not just routine hygiene -- that script's own docstring).
# `FROM` lines below are copied verbatim from that file's own cells, kept
# in the same order.

FROM quay.io/pypa/musllinux_1_2_x86_64@sha256:0092b7d1019f3110cc691e4997e9838e7c9f086655643aac442f273ce90efdd0 AS musllinux_1_2_x86_64
FROM quay.io/pypa/musllinux_1_2_i686@sha256:c29484d9ed14510c0db9509ea04a962ae8a3462962425588974bdcaef44e7130 AS musllinux_1_2_i686
FROM quay.io/pypa/musllinux_1_2_aarch64@sha256:4b8c72510cd25410a9a12535ea15028b043bfc58a886741066ed06c9c06d4d3e AS musllinux_1_2_aarch64
FROM quay.io/pypa/musllinux_1_2_ppc64le@sha256:1caa3e116d017ef619b19f11a70589f44a4db6c3ed814eeef7ed97e49c315f8e AS musllinux_1_2_ppc64le
FROM quay.io/pypa/musllinux_1_2_s390x@sha256:00e64e3687db37d5ce570f3dab3138f212f89419b1c4c8393bb506633c3f5a1c AS musllinux_1_2_s390x
FROM quay.io/pypa/musllinux_1_2_armv7l@sha256:aa9ef6eeafac4ed3d71b86451dbd602fe294c6c24f190de0bc0227c2755d4d10 AS musllinux_1_2_armv7l
FROM quay.io/pypa/musllinux_1_2_riscv64@sha256:2706c279cfee5e0ab525009f9d45ddda37d3e85b501d6deb42057f8276719e15 AS musllinux_1_2_riscv64
FROM quay.io/pypa/manylinux_2_31_armv7l@sha256:7475b7281e0bd62e85f8f63d8215505c7ca598bb2579bd50f53f234d33dc7b06 AS manylinux_2_31_armv7l
FROM quay.io/pypa/manylinux_2_39_riscv64@sha256:a77c91a4ddc3b43dcda15bcd8320b02d2bd322360485c5168e81c3c280cdf19c AS manylinux_2_39_riscv64

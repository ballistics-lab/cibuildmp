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

FROM quay.io/pypa/musllinux_1_2_x86_64@sha256:43f81b5440015302cd0b0671d3d05d1961a2a0995cb7ff3d1725ce62990498a8 AS musllinux_1_2_x86_64
FROM quay.io/pypa/musllinux_1_2_i686@sha256:0a6d0bdb934c541ce76a0469a4274f129da0e5828873460d6d803d98f952169c AS musllinux_1_2_i686
FROM quay.io/pypa/musllinux_1_2_aarch64@sha256:83734eadb0172f639c75221229f42298568e63ea74e6d827ee3f91fb3a17e5b3 AS musllinux_1_2_aarch64
FROM quay.io/pypa/musllinux_1_2_ppc64le@sha256:12b4b6350a8dd265ecc9849c8eeb0414e355838eb78c755ba70fc0a049c01407 AS musllinux_1_2_ppc64le
FROM quay.io/pypa/musllinux_1_2_s390x@sha256:9c5c555832706b53d2e0b63d134e4d7343e2bdd54b0bc86d0e02f19115f221b3 AS musllinux_1_2_s390x
FROM quay.io/pypa/musllinux_1_2_armv7l@sha256:cceca74205a4276294d0890a2ad2e3680431ab64b89a6e1f5fca82eb6a7df86c AS musllinux_1_2_armv7l
FROM quay.io/pypa/musllinux_1_2_riscv64@sha256:890e72e6f2a9956a09ecc574bce14b8d6ef2f4f66764491260effb716db1e2d9 AS musllinux_1_2_riscv64
FROM quay.io/pypa/manylinux_2_31_armv7l@sha256:ecb0b7cd6db693d46a399226fd93cfd0d01d0dfbf9c65a8d5a0f6821767178fe AS manylinux_2_31_armv7l
FROM quay.io/pypa/manylinux_2_39_riscv64@sha256:848e318264954170a7fd2b1734db60cfe5f0ea8d66fc8b9d776052777d0ede7f AS manylinux_2_39_riscv64

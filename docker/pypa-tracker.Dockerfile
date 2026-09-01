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

FROM quay.io/pypa/musllinux_1_2_x86_64@sha256:8900a53ed236d85edd6868387b3e3327c45774156519ad492fe8b1c2a434d1dc AS musllinux_1_2_x86_64
FROM quay.io/pypa/musllinux_1_2_i686@sha256:e9029eacb01a207fc991eed8abccf55f653900b4b83068e37fb0ea201176a64a AS musllinux_1_2_i686
FROM quay.io/pypa/musllinux_1_2_aarch64@sha256:ab0391c77648e2b15d37e3e5b8c3d43a0c4a1ca0fb3ab2f60d252be3474d2975 AS musllinux_1_2_aarch64
FROM quay.io/pypa/musllinux_1_2_ppc64le@sha256:e745f8e8e8c7c8e02e6379502d0b73f7cc4fd95283e011a78063292740f3cf42 AS musllinux_1_2_ppc64le
FROM quay.io/pypa/musllinux_1_2_s390x@sha256:411d3d433dde4b3a9fce85122f7080110e2ec3543ca6c22578acb4a61c38cc14 AS musllinux_1_2_s390x
FROM quay.io/pypa/musllinux_1_2_armv7l@sha256:bb213c77861583faa326b24de1c413dab0e7c51af76f8a30f5abcaf749da5265 AS musllinux_1_2_armv7l
FROM quay.io/pypa/musllinux_1_2_riscv64@sha256:3c2e2c26c10c2788046e54e816d8880011e4af9c4292cb735705a89870248082 AS musllinux_1_2_riscv64
FROM quay.io/pypa/manylinux_2_31_armv7l@sha256:bb0c6355c62cd0971f17a66969b1bce15222e67e4064667e25030923bb216bfe AS manylinux_2_31_armv7l
FROM quay.io/pypa/manylinux_2_39_riscv64@sha256:4e74e5408c307666116196383a3bbf741b171fda049c776dac731e5b6087a1d5 AS manylinux_2_39_riscv64

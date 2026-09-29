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

FROM quay.io/pypa/musllinux_1_2_x86_64@sha256:bcd644f5f08de4c286b4e8a99652d106a7e56881d8e0b3f92d471f05f5b60fd3 AS musllinux_1_2_x86_64
FROM quay.io/pypa/musllinux_1_2_i686@sha256:cf2b239c5788f6c6de291a8213e3ca0cd4d443e96ac3f275bd285ae426a0ca7f AS musllinux_1_2_i686
FROM quay.io/pypa/musllinux_1_2_aarch64@sha256:fecc36f309839b485f04e36b6fd2272d98b84936e68122f3de9bd65c253e76dc AS musllinux_1_2_aarch64
FROM quay.io/pypa/musllinux_1_2_ppc64le@sha256:bed4b2eaa5013b4a67e68307be9517246288608111665e8f0d32b457e5a307a5 AS musllinux_1_2_ppc64le
FROM quay.io/pypa/musllinux_1_2_s390x@sha256:4a1af0293993de3ba12789a38ebcd4fce21bd8c1b1c04fab06cb75cd3c8cff78 AS musllinux_1_2_s390x
FROM quay.io/pypa/musllinux_1_2_armv7l@sha256:36d3a643f82372b2e69690e1111db1583d568752ce2888f13af6f85f1c8ff1cc AS musllinux_1_2_armv7l
FROM quay.io/pypa/musllinux_1_2_riscv64@sha256:e47e6e52f302f9cbfb57a806f41c0fef25017c6070b4e9912ab6db495153109e AS musllinux_1_2_riscv64
FROM quay.io/pypa/manylinux_2_31_armv7l@sha256:222db91566088f0643a1a36fa0be0ba22b0aa426da7cbb4e3a7109a02d044133 AS manylinux_2_31_armv7l
FROM quay.io/pypa/manylinux_2_39_riscv64@sha256:0058fcf87e482872960e1d583483769886bb6e95ff9116a6a965b843419838bf AS manylinux_2_39_riscv64

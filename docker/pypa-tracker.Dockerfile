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

FROM quay.io/pypa/musllinux_1_2_x86_64@sha256:34e72b200d8938bca4d3edac681db7055285e81329beaf5e817e86c9db3d5d2f AS musllinux_1_2_x86_64
FROM quay.io/pypa/musllinux_1_2_i686@sha256:54453c5476d823270839486591771864ccb401df7fd4e5a5463a29dcfdad9d30 AS musllinux_1_2_i686
FROM quay.io/pypa/musllinux_1_2_aarch64@sha256:a4f053d721429d1d08132f112750b5ef8e794d895a380f40348bfacfccd4fe89 AS musllinux_1_2_aarch64
FROM quay.io/pypa/musllinux_1_2_ppc64le@sha256:bd56239ef43d8f2ec374e5baa28435b7d9772923adfe529f11898fc2e6442de3 AS musllinux_1_2_ppc64le
FROM quay.io/pypa/musllinux_1_2_s390x@sha256:7350f167e5ca2818a1fec3bd9c270a99c81921a3c2b1f9afd4c44f6b230eaf49 AS musllinux_1_2_s390x
FROM quay.io/pypa/musllinux_1_2_armv7l@sha256:0d9e52979fbaa113736d24e6794b73f0ba5435a4bdf0b9574f33e5ecf33aeaf1 AS musllinux_1_2_armv7l
FROM quay.io/pypa/musllinux_1_2_riscv64@sha256:203b43d3c496569c9ff23e9bb50fefdbfede41b0c23778333702bc551d7ab56a AS musllinux_1_2_riscv64
FROM quay.io/pypa/manylinux_2_31_armv7l@sha256:32948ad16f91f2590cb5bf722fbcb1c098ebaa81ca0708b26880c9e41a22756c AS manylinux_2_31_armv7l
FROM quay.io/pypa/manylinux_2_39_riscv64@sha256:452055600f0c5bdac5df069b0b6a9e7cf58658fbe1b634e6975d730324f23ea1 AS manylinux_2_39_riscv64

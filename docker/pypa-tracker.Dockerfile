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

FROM quay.io/pypa/musllinux_1_2_x86_64@sha256:8f7d1c70a5cfb088d9a9609a2671d7a1ac7cb46ccb19e7ac078ba9dbf2552068 AS musllinux_1_2_x86_64
FROM quay.io/pypa/musllinux_1_2_i686@sha256:a31d86eb287829c99eb7cdf0a0e17bafde14f313076a711ce70161d46a296520 AS musllinux_1_2_i686
FROM quay.io/pypa/musllinux_1_2_aarch64@sha256:70a81491cfd91b4ebfc4f1b0bcd8e5da04d78a104cb8dc799f0b071034343df4 AS musllinux_1_2_aarch64
FROM quay.io/pypa/musllinux_1_2_ppc64le@sha256:9780112264ac9653b404627b99f3e017ea0bf414e56d9174f3fa27ba8f69c5ac AS musllinux_1_2_ppc64le
FROM quay.io/pypa/musllinux_1_2_s390x@sha256:5b2068a8dafb5224af5b71c74057fc1f4152312345f2b1408c440ed4f31d596c AS musllinux_1_2_s390x
FROM quay.io/pypa/musllinux_1_2_armv7l@sha256:4eca90557e9070423ddfa612b155f6b0339550cffd9ae3fec3ba99524bcdd6c1 AS musllinux_1_2_armv7l
FROM quay.io/pypa/musllinux_1_2_riscv64@sha256:19e6fc73cb8bf98c595d61043b8edb25189a5d180e5f509460ed1a7df717e257 AS musllinux_1_2_riscv64
FROM quay.io/pypa/manylinux_2_31_armv7l@sha256:2af698070b6f852e0a2dcec165a1f07662d20b2e664efa0e5c1c6669829f76a0 AS manylinux_2_31_armv7l
FROM quay.io/pypa/manylinux_2_39_riscv64@sha256:5d475b18315134634549f097926231a78110159cedee78e222eb35f98567f738 AS manylinux_2_39_riscv64

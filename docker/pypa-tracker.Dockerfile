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

FROM quay.io/pypa/musllinux_1_2_x86_64@sha256:dc96c1f69b8a6241bcc8175a8d89b1caf0dccf959ff111a2272c42747af38350 AS musllinux_1_2_x86_64
FROM quay.io/pypa/musllinux_1_2_i686@sha256:131d4accbf96853ebe7508a8659520019fcedb353bb3aeba9944b48344efaa93 AS musllinux_1_2_i686
FROM quay.io/pypa/musllinux_1_2_aarch64@sha256:83a69fa8383ba5ac2d4f01597b791ebf93269c9748270b51b7a54fbba0dcdd39 AS musllinux_1_2_aarch64
FROM quay.io/pypa/musllinux_1_2_ppc64le@sha256:1c92fb30e31d6912001d2aece53af5141b81d362d30f2f7791f091d88f910555 AS musllinux_1_2_ppc64le
FROM quay.io/pypa/musllinux_1_2_s390x@sha256:a51c6abfd7686efc9c0778b5ab5357894292a6dbd0f02a58d81cf20aab9e4a4a AS musllinux_1_2_s390x
FROM quay.io/pypa/musllinux_1_2_armv7l@sha256:f54e78498818fbf3b71324af55f4bb87214baeb42a736465bdacaa112a9332ea AS musllinux_1_2_armv7l
FROM quay.io/pypa/musllinux_1_2_riscv64@sha256:2fb619d4bc948178659a93243ad6edc689c6157082678fa6d7d24ef43d924cbb AS musllinux_1_2_riscv64
FROM quay.io/pypa/manylinux_2_31_armv7l@sha256:19693b5c1aa30e568c4b1480bc8f1e1e66e7b6bb10f2ccb021f15eb34164d71a AS manylinux_2_31_armv7l
FROM quay.io/pypa/manylinux_2_39_riscv64@sha256:be5cb4698cc7c13486bd2c3aa21b0124d80d4641d34be2f6ef357903693eb9d1 AS manylinux_2_39_riscv64

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

FROM quay.io/pypa/musllinux_1_2_x86_64@sha256:ff786af69d772d7ac3e318c00a2b682428a352cc822d6175f6a0d4b431c0d44d AS musllinux_1_2_x86_64
FROM quay.io/pypa/musllinux_1_2_i686@sha256:1dd91376182cb65bd594fec2043ed7045a0482dee5b4c7685dcc743dc6259a9d AS musllinux_1_2_i686
FROM quay.io/pypa/musllinux_1_2_aarch64@sha256:09c35642d008faa6d43a45809ff068e22f37bba801f7d75faf19431aefed579d AS musllinux_1_2_aarch64
FROM quay.io/pypa/musllinux_1_2_ppc64le@sha256:37cac257191867a26d9593b45bd0b8183384657c917216929a1be4d04f0daf8f AS musllinux_1_2_ppc64le
FROM quay.io/pypa/musllinux_1_2_s390x@sha256:cdb216b2d50e775b024179862f0b413dcece273c2ee73a45fe933443fc86d74b AS musllinux_1_2_s390x
FROM quay.io/pypa/musllinux_1_2_armv7l@sha256:2a2b44f4b40cfd73133e67a872479b5f1250a20740fe4a5f1f4e433f5d2d6db8 AS musllinux_1_2_armv7l
FROM quay.io/pypa/musllinux_1_2_riscv64@sha256:33af64ac6b613797e9135a2acc35c448e03799bb6ce87c6d491661876e71103f AS musllinux_1_2_riscv64
FROM quay.io/pypa/manylinux_2_31_armv7l@sha256:5b1b07fbff38d153bb0f7c25ec5c7437ead95ffed0d29ef281162e4fa748236d AS manylinux_2_31_armv7l
FROM quay.io/pypa/manylinux_2_39_riscv64@sha256:101258e23c486e00cdfa8d83bb6da407fe99713cafb3ebd64a5abff0107a98f6 AS manylinux_2_39_riscv64

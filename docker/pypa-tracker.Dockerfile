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

FROM quay.io/pypa/musllinux_1_2_x86_64@sha256:04e877afa939007f6784f9076d2aa797d1156f31281cfe19f203945d7b624970 AS musllinux_1_2_x86_64
FROM quay.io/pypa/musllinux_1_2_i686@sha256:b2ad7d04f327b3b2e805e50b11a009a2cf2a4ce22aec3463cd89caa72f4a128c AS musllinux_1_2_i686
FROM quay.io/pypa/musllinux_1_2_aarch64@sha256:1db347533f8a7ea39aa20b0203f4e4af00630cdb621216a2b43771523c9983c5 AS musllinux_1_2_aarch64
FROM quay.io/pypa/musllinux_1_2_ppc64le@sha256:e1d66fc80892cc6275597e1179f84a3b38460cfc483fee00ebb01b362df1f5b9 AS musllinux_1_2_ppc64le
FROM quay.io/pypa/musllinux_1_2_s390x@sha256:f5cd9250de3b4c9577606d9097b91b4ad960193e38d1b4f6c5b931a6018e2e80 AS musllinux_1_2_s390x
FROM quay.io/pypa/musllinux_1_2_armv7l@sha256:22d2d1303b4e78e5d73055f50dc5d6fb0ebbc26a65c9c1256134c52d4975634e AS musllinux_1_2_armv7l
FROM quay.io/pypa/musllinux_1_2_riscv64@sha256:c1ecafb83d4442f542877a469c53e45e1bbd4c32aef4d8f81fd009a8fcd6ad97 AS musllinux_1_2_riscv64
FROM quay.io/pypa/manylinux_2_31_armv7l@sha256:ff4a72812594311c071eebce43efcaa9061bd1205649d864c1054d4e56e6bdae AS manylinux_2_31_armv7l
FROM quay.io/pypa/manylinux_2_39_riscv64@sha256:7c353f5e76199618437ec0c187cb7d6bb1777d85f2c13d95636b1a55a6b2ca72 AS manylinux_2_39_riscv64

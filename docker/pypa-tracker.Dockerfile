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

FROM quay.io/pypa/musllinux_1_2_x86_64@sha256:cf82db9d8dc8c5c2cb27f422208baf266ebc8ad70be4ab1bc79bcc8807a6432d AS musllinux_1_2_x86_64
FROM quay.io/pypa/musllinux_1_2_i686@sha256:f698cc2c2bfd1c89cbbfe35a73d7c50fe97f09fec0cce9ddd28f60f91d6f6b7d AS musllinux_1_2_i686
FROM quay.io/pypa/musllinux_1_2_aarch64@sha256:6cdf1dca55fa6fb1e689e7516e465b51eed1f822167386d61102116c49235d6f AS musllinux_1_2_aarch64
FROM quay.io/pypa/musllinux_1_2_ppc64le@sha256:5e2baf4191bbda2c6ce3b9fd9a218a207fafe13df145fc39fe774436e9a61b1b AS musllinux_1_2_ppc64le
FROM quay.io/pypa/musllinux_1_2_s390x@sha256:f1b638e7cf88450748564eb3372f74e4038453557978badc7e732726f6983414 AS musllinux_1_2_s390x
FROM quay.io/pypa/musllinux_1_2_armv7l@sha256:0bc7c8970e85443da05f2d1eb11dfd2488807b7306f15bef5fa813954383bcea AS musllinux_1_2_armv7l
FROM quay.io/pypa/musllinux_1_2_riscv64@sha256:de20b22f90df4fe2ad8b13b1cf9c61919b4dfdc25656db67be42d486485ae326 AS musllinux_1_2_riscv64
FROM quay.io/pypa/manylinux_2_31_armv7l@sha256:32bc94a2dd90364071a30de92cb025015ac3c3f0e3a46b72e9ab920fb97a87dc AS manylinux_2_31_armv7l
FROM quay.io/pypa/manylinux_2_39_riscv64@sha256:9df0bc95e32b764fdbd35d7d4053aeb239ffd932803cb33be3ba3b6fef81a6d7 AS manylinux_2_39_riscv64

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

FROM quay.io/pypa/musllinux_1_2_x86_64@sha256:c564755a06228cc28fe8383fc5fde4468f6cea91b9d35a38eaf853018bb3b320 AS musllinux_1_2_x86_64
FROM quay.io/pypa/musllinux_1_2_i686@sha256:0cb5a3c096aaca8a78766cc8591264e3d947de4626e42b8d236832bf7501588d AS musllinux_1_2_i686
FROM quay.io/pypa/musllinux_1_2_aarch64@sha256:202c3e7e9a872d4e8d712621d3f63f02e4760a9b958679506841c452ad91f959 AS musllinux_1_2_aarch64
FROM quay.io/pypa/musllinux_1_2_ppc64le@sha256:ab5a460e341cd005f91571bbb27ab5f05b5d01c4557272c243966d26a22f52e3 AS musllinux_1_2_ppc64le
FROM quay.io/pypa/musllinux_1_2_s390x@sha256:7f09a6b54da2aac67f805b22b7a87a0ede99ddb2277bfeab76d16941beb0b456 AS musllinux_1_2_s390x
FROM quay.io/pypa/musllinux_1_2_armv7l@sha256:c65bca151bb0d2265157c49e55f7a290965c24647241eaeee6b9b05dbf964b8c AS musllinux_1_2_armv7l
FROM quay.io/pypa/musllinux_1_2_riscv64@sha256:c6f3c6250f1928e36edee95dd290919f2b67c81002c32ecd076f61ce154a7236 AS musllinux_1_2_riscv64
FROM quay.io/pypa/manylinux_2_31_armv7l@sha256:66666f7c60ba3c2f36c6a03489077d4b002e0602ce54bb88fa5a2b7f52019ea0 AS manylinux_2_31_armv7l
FROM quay.io/pypa/manylinux_2_39_riscv64@sha256:9608e4053959f4cb1c1c848924bb0d0658c69412554c11c6d9aca434d5b0ef8f AS manylinux_2_39_riscv64

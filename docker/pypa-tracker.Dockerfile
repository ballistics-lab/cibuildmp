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

FROM quay.io/pypa/musllinux_1_2_x86_64@sha256:621f8004ed526a5a6bf6a866fb415ad8da54d59a991e50b3b69167c3a768a616 AS musllinux_1_2_x86_64
FROM quay.io/pypa/musllinux_1_2_i686@sha256:7ff9262769ecadb9b889d2977f2e1fd47400a161664502ecb0eda9291d9abdfb AS musllinux_1_2_i686
FROM quay.io/pypa/musllinux_1_2_aarch64@sha256:4dffcd49f0b6fc6928a49915f3cd939f973bbecbdfe96e1e7926b6049bc0bad5 AS musllinux_1_2_aarch64
FROM quay.io/pypa/musllinux_1_2_ppc64le@sha256:fbc1983eb04e9bf311bd743863472b3ac9840edc3f2ca4e9dd4085d26f24fc84 AS musllinux_1_2_ppc64le
FROM quay.io/pypa/musllinux_1_2_s390x@sha256:a7254c085d6c28ae74acb229af697133a8827535ac26b542b7be014272ba81d2 AS musllinux_1_2_s390x
FROM quay.io/pypa/musllinux_1_2_armv7l@sha256:7fa1e5ac26e79b9aa6b64aac4ca2479eadd8d00229f178eb5495edd538e9ff4b AS musllinux_1_2_armv7l
FROM quay.io/pypa/musllinux_1_2_riscv64@sha256:f8bf1ede4138d95937a98362ce482453d717c62d22207f038619262b180d4ab8 AS musllinux_1_2_riscv64
FROM quay.io/pypa/manylinux_2_31_armv7l@sha256:3503ad3cef1b2a35ee05048eaebdb93ad1b4a6e9426af7f43dbe7658243ab0db AS manylinux_2_31_armv7l
FROM quay.io/pypa/manylinux_2_39_riscv64@sha256:000de3e1037325a6cc13615c1218061a56e1ece60ecdbe1a4572933a90654d18 AS manylinux_2_39_riscv64

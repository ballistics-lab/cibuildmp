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

FROM quay.io/pypa/musllinux_1_2_x86_64@sha256:915d73c75b4551f98fd7b12de655ef2e27419a6441ea07472b6e25e0d868d18d AS musllinux_1_2_x86_64
FROM quay.io/pypa/musllinux_1_2_i686@sha256:4f48980053df66ab0707e0a61b2be7d94630a4e95912e9460ad8fe89e26520ac AS musllinux_1_2_i686
FROM quay.io/pypa/musllinux_1_2_aarch64@sha256:75a9ccd28ccc0abda65e462133f6e324943354e4e4936b51ba7c2ddc98352f86 AS musllinux_1_2_aarch64
FROM quay.io/pypa/musllinux_1_2_ppc64le@sha256:29197338e7987091eca905e2a0d2112cc6ada631ef4bfbd1e04942998f49a38f AS musllinux_1_2_ppc64le
FROM quay.io/pypa/musllinux_1_2_s390x@sha256:baab9d9494448f428046faf977f5eb5c067c1d408331affe5982aaf2a38e065c AS musllinux_1_2_s390x
FROM quay.io/pypa/musllinux_1_2_armv7l@sha256:a22b7f19bc629eb90390f2b3416d3ef07b87c229fd5d1b6ad67e94be6c782d8b AS musllinux_1_2_armv7l
FROM quay.io/pypa/musllinux_1_2_riscv64@sha256:1f6615cca693d2083b5b3754a97dd047d11d7a9b89914129b6bbac2befac756e AS musllinux_1_2_riscv64
FROM quay.io/pypa/manylinux_2_31_armv7l@sha256:0a6ba56acdd4599eb3f71d0c21bd2803de00e43117911f9009ca9d4e06f448a0 AS manylinux_2_31_armv7l
FROM quay.io/pypa/manylinux_2_39_riscv64@sha256:20117735b8a2a63349df86a8b74901a16c0f77149559d3d73ff115575732fcc1 AS manylinux_2_39_riscv64

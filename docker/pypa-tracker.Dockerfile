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

FROM quay.io/pypa/musllinux_1_2_x86_64@sha256:75327606c7666fc971bd9239c6b220fd205b4bb9563b588075164622609219ca AS musllinux_1_2_x86_64
FROM quay.io/pypa/musllinux_1_2_i686@sha256:8ca1be90979cb290909c1c945573ccdc7114505d66c563567ee6c78927fb215f AS musllinux_1_2_i686
FROM quay.io/pypa/musllinux_1_2_aarch64@sha256:cea133e28484a93e9c40fc661256e8f1ec69b2887d0b64acbfaf48f26bbab103 AS musllinux_1_2_aarch64
FROM quay.io/pypa/musllinux_1_2_ppc64le@sha256:d70f4708a377ba4a21eee38be20e35c757e911b5ca90df0fce002fd71a6df3a8 AS musllinux_1_2_ppc64le
FROM quay.io/pypa/musllinux_1_2_s390x@sha256:97af923ea31a097445fcaad1af154e1f0fd997a6d722141d55607dc3767f8782 AS musllinux_1_2_s390x
FROM quay.io/pypa/musllinux_1_2_armv7l@sha256:c7ee1ecd4967a3ea682c814b564a900d90dc81d75b0b7c2deeb8d6819752a460 AS musllinux_1_2_armv7l
FROM quay.io/pypa/musllinux_1_2_riscv64@sha256:203b43d3c496569c9ff23e9bb50fefdbfede41b0c23778333702bc551d7ab56a AS musllinux_1_2_riscv64
FROM quay.io/pypa/manylinux_2_31_armv7l@sha256:235c282aa532e01136e5e1db0a9403463032c9281fa56d89b39e45dfb5081484 AS manylinux_2_31_armv7l
FROM quay.io/pypa/manylinux_2_39_riscv64@sha256:9fa1bc388ea2494e457eec44e7c16a9e66fff892d73da8af3621009e76167949 AS manylinux_2_39_riscv64

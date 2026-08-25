# 0010. Pinned data lives in resources/, not in Python

- Status: Accepted
- Related: [0003], [0016]

<!-- migrated verbatim from docs/BACKLOG.md lines 173-188 -->

**D10 — pinned data lives in `resources/`, not in Python.**
Checked against cibuildwheel rather than invented: it keeps
`resources/build-platforms.toml` (identifiers and interpreter versions),
`resources/pinned_docker_images.cfg` (image digests, pinned by `@sha256:`
with a dated comment), `nodejs.toml` and
`python-build-standalone-releases.json` out of its source — which is why its
`--only` reads its `choices` from `read_all_configs()`. Everything in those
files goes stale on someone else's schedule, so bumping one should be a
reviewable data diff a script can make, not a patch to resolver logic.

`src/cibuildmp/resources/natmod.toml` holds all three of ours: the arch →
`CROSS` map (transcribed from `py/dynruntime.mk`), the tag → `.mpy` ABI map
(from `py/persistentcode.h`), and the toolchain download pins. A cross-check
runs at import and fails loudly if the arch table and the toolchain table
disagree about a prefix.

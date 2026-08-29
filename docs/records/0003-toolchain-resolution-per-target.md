# 0003. Toolchain resolution is per-target, chosen by the tool (variant C)

- Status: Accepted
- Related: [0002], [0010]

<!-- migrated verbatim from docs/BACKLOG.md lines 56-61 -->

**D3 — toolchain resolution is per-target, chosen by the tool (variant C).**
Download-into-cache is the default where a standalone toolchain tarball
exists; Docker and "already on PATH" are escape hatches. Selecting the
mechanism is `cibuildmp`'s job, not the user's — that self-resolution is the
part of cibuildwheel worth copying.

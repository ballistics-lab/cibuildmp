# 0008. Distribution of the tool itself is deferred

- Status: Accepted; PyPI name reservation still open
- Related: [0011]

<!-- migrated verbatim from docs/BACKLOG.md lines 140-149 -->

**D8 — distribution of the tool itself is deferred.**
The PyPI name `cibuildmp` is free (404 on the JSON API) but not reserved.
Until it is, both actions install from their own checkout —
`uv tool install ${{ github.action_path }}` — so the version that runs is
exactly the ref the caller pinned, with no package index to keep in sync
with the action tag. Under **D11** this is no longer a workaround so much as
the natural arrangement: the action root and the package root are the same
directory. Reserving the name is still worth doing, if only to stop someone
else taking it.

# 0005. One identifier namespace, one override mechanism

- Status: Accepted
- Related: [0004], [0023]

<!-- migrated verbatim from docs/BACKLOG.md lines 68-74 -->

**D5 — one identifier namespace, one override mechanism.**
Config is scoped by build mode the way cibuildwheel scopes by platform
(`[tool.cibuildwheel.android]`, `.pyodide`, …), but *selectors* — `build`,
`skip`, and `overrides[].select` — are globs over a single flat identifier
string. The current draft config's three different override shapes collapse
into one `[[overrides]]` list.

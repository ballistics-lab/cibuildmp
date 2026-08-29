# 0004. Config lives in cibuildmp.toml at the repo root

- Status: Accepted
- Related: [0005]

<!-- migrated verbatim from docs/BACKLOG.md lines 62-67 -->

**D4 — config lives in `cibuildmp.toml` at the repo root.**
MicroPython C-module repos have no `pyproject.toml` and it is not their
convention. `cibuildmp.toml` uses top-level tables. If a `pyproject.toml`
exists, the same tree is also accepted under `[tool.cibuildmp]`;
`cibuildmp.toml` wins when both are present.

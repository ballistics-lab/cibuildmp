# 0001. natmod first, and natmod is the wheel-shaped half

- Status: Accepted
- Related: shapes the whole phase-1 scope; see 0000-TRACKER.md

<!-- migrated verbatim from docs/BACKLOG.md lines 36-42 -->

**D1 — natmod first, and natmod is the wheel-shaped half.**
A natmod `.mpy` is a portable, ABI-tagged binary artifact with a real
distribution channel (GitHub release + `package.json` + `mip install`). That
maps onto cibuildwheel almost exactly. A usermod artifact is firmware — it is
not installed into a runtime, it *is* the runtime — so it gets a different
pipeline, later. Phase 1 ships natmod only.

# 0006. No test runners in phase 1

- Status: Accepted
- Related: [0021], [0040]

<!-- migrated verbatim from docs/BACKLOG.md lines 75-80 -->

**D6 — no test runners in phase 1.**
Execution substrates (qemu-user, qemu-system, rp2040py, node, real hardware
over `mpremote`) are a genuinely hard axis and are deferred. Phase 1 is
build-only. `[test]` keys are not parsed yet; do not ship a half-working
version of them.

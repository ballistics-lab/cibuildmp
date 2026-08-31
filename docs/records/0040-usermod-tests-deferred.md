# 0040. usermod's own test-runner axis, deferred

- Status: Not scheduled ([0006] holds for natmod)
- Related: [0006], [0021]

<!-- migrated verbatim from docs/BACKLOG.md lines 3553-3567 -->

### Later — tests

Not scheduled (**D6**). When it lands, the design is an explicit runner axis:
`native`, `qemu-user`, `qemu-system`, `node`, `rp2040py`, `mpremote`, `none`.
`mpremote` — tests on real hardware attached to a self-hosted runner — is the
one with no cibuildwheel analogue and the most value for embedded.

Four of these seven (`native`, `qemu-system`, `node`, `rp2040py`) are no
longer hypothetical: `mp-usermod.yml` already runs all four today, hand-driven
per job (**D21**). That doesn't move this out of "not scheduled" on its own —
D6 still holds for natmod, where a build-only artifact is the actual
deliverable — but it does mean usermod's own runner-axis design, when it
happens, has four of seven cases to transcribe from a working reference
rather than design from scratch.

# 0011. One repository: cibuildmp absorbed micropython-native-ci

- Status: Accepted
- Related: [0008], [0038]

<!-- migrated verbatim from docs/BACKLOG.md lines 189-205 -->

**D11 — one repository: `cibuildmp` absorbed `micropython-native-ci`.**
The tool and the composite actions ship together, on one version line
continuing the old repository's (`v0.3.0` follows `v0.2.0`; the actions in
it are the same actions, moved). The old repository is deprecated and gets
archived once its three consumers have repinned.

The alternative — tool in one repo, actions in the other — split a thing
that is converging, not diverging: M5 turns `build-natmod` into a wrapper
over `cibuildmp --only`, which is awkward across a repo boundary and
impossible to release atomically. Keeping both copies alive, meanwhile, was
exactly the drift this whole project exists to end.

The cost is real and falls on consumers: bclibc, a7p and micropython-wasm3
each have ~15 `uses:` paths to repin. That is a one-line-per-reference
change with no behaviour difference, and old pins keep working until they
make it.

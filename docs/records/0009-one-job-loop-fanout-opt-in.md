# 0009. One job looping over targets is the default; fan-out is opt-in

- Status: Accepted
- Related: [0020] revisits this for usermod

<!-- migrated verbatim from docs/BACKLOG.md lines 150-172 -->

**D9 — one job looping over targets is the default; fan-out is opt-in.**
Verified against cibuildwheel rather than assumed: its canonical workflow
(`examples/github-minimal.yml`) puts *runners* in `strategy.matrix` — `os:
[ubuntu-latest, ubuntu-24.04-arm, windows-latest, windows-11-arm,
macos-15-intel, macos-14]` — and loops over the Python versions inside each
job. There is no matrix over `cp311`/`cp312`/… at all, and
`--print-build-identifiers` appears in its docs exactly once, under
`build`/`skip`, as introspection; the widely copied `jq` matrix recipe is a
community pattern, not something cibuildwheel documents.

The reason is that the runner is a hard constraint there: a macOS wheel
cannot be built on Linux. **That constraint does not exist for natmod** —
all ten arches are cross-compiles on x86-64 Linux. What *does* cost is
fetching MicroPython and building `mpy-cross`, which are identical for every
arch, so a ten-leg matrix pays for them ten times.

So `cibuildmp` with no `--only` builds every selected target sequentially in
one invocation. `--only` remains for callers who want a job per target
anyway — failure isolation, wall-clock parallelism — and is what the matrix
generator feeds. Revisit for usermod, where different targets genuinely need
different runners and the fan-out becomes structural rather than a
preference.

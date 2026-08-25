# 0029. A real GitHub Actions job summary, like cibuildwheel's

- Status: Implemented
- Related: [0028]

<!-- migrated verbatim from docs/BACKLOG.md lines 2904-3004 -->

**D29 — a real GitHub Actions job summary, the way cibuildwheel's own
action already does it: a table of what got built, visible directly on
the Action run's own page, not just buried in raw log lines. Done,
implemented while D28's own composite-action CI was running.** The
user's own explicit ask, independent of **D28**'s container-per-port
migration -- landed on its own, in parallel.

- **Implemented as designed below**, in a new standalone module,
  `src/cibuildmp/stepsummary.py` -- `write_step_summary(results,
  total_duration)`, duck-typed over a `_Result` `Protocol`
  (`identifier`/`output`/`size`, read-only properties so
  `Sequence[_Result]` stays covariant and accepts both `list[BuildResult]`
  and `list[UsermodBuildResult]` without `pyright` complaining -- the
  same list-invariance snag **D26**'s own `usermod/targets.py` comment
  already hit once). A standalone module rather than living in either
  `cli.py`, specifically to dodge a circular import: `cli.py` already
  imports `usermod.cli` for dispatch, so a shared helper defined in
  either one would need the other to import it back.
- No-ops when `$GITHUB_STEP_SUMMARY` is unset (every local run, and
  any non-GitHub CI system), otherwise appends a Markdown table to
  that path -- *appends*, not overwrites, since GitHub Actions expects
  every step in a job to add to the same running file across the
  whole job, confirmed by a dedicated test.
- Wired into both call sites exactly where designed:
  `src/cibuildmp/cli.py`'s `build()` and
  `src/cibuildmp/usermod/cli.py`'s `run()`, immediately after each
  one's own existing plain-text summary loop -- runs in addition to
  it, not instead of it.
- Tested at two levels, not just written and trusted: `stepsummary.py`
  itself (`tests/test_stepsummary.py`, 5 cases -- no-op when unset,
  correct table contents, appends rather than truncates, large sizes
  get a thousands separator, an empty result list still writes a
  header) and the real wiring through the actual CLI
  (`tests/test_cli.py::test_real_build_writes_github_step_summary_when_set`,
  a genuine `main()` call with only the toolchain/fetch/build edges
  mocked, confirmed to fail without the `write_step_summary(...)` call
  in `cli.py` before being confirmed to pass with it -- not just
  written and assumed correct). 237 tests pass project-wide.
- **Not yet verified on real GitHub Actions itself** -- unlike every
  Dockerfile fix in this session's own chain, this one genuinely
  cannot be meaningfully faked locally beyond what the tests above
  already do (there is no live `$GITHUB_STEP_SUMMARY` file to inspect
  outside a real Actions run), so the real proof is whatever the next
  `build-examples.yml` run's own Summary tab shows once this lands on
  the branch.

The original design notes below are kept for the historical record of
what was planned before implementation, not because anything in this
entry supersedes them -- the implementation matches the design as
written.

- **What cibuildwheel's own action does, precisely:** after a build,
  it writes a Markdown table into `$GITHUB_STEP_SUMMARY` -- one row
  per wheel produced, filename and size -- which GitHub renders on the
  job's own summary page (the "Summary" tab of an Actions run),
  visible without opening any log at all. `$GITHUB_STEP_SUMMARY` is a
  file path GitHub Actions itself sets as an env var on every runner;
  appending Markdown to it is the whole mechanism, no special API or
  action needed.
- **`cibuildmp` already computes exactly the data this needs, in both
  CLIs, today** -- it just only ever goes to plain stdout:
  - natmod, `src/cibuildmp/cli.py:284-287`:
    ```python
    total_duration = sum(r.duration for r in results)
    print(f"\ncibuildmp: {total} target(s) built in {total_duration:.1f}s")
    for result in results:
        print(f"  {result.identifier}: {result.output.name} ({result.size} bytes)")
    ```
  - usermod, `src/cibuildmp/usermod/cli.py:115-120`: the identical
    shape, over `UsermodBuildResult` instead of `BuildResult` --
    `identifier`, `output`, `size`, `duration` all already exist on
    both result dataclasses.
- **The design this suggests:** one small shared helper (a natural
  home: `src/cibuildmp/cli.py` or a new tiny module either CLI
  imports, since both natmod's `main()` and usermod's `run()` need
  it) -- `write_step_summary(results, *, total_duration)` or similar --
  that:
  1. No-ops immediately if `os.environ.get("GITHUB_STEP_SUMMARY")` is
     unset (every local/non-CI invocation, and any CI system that
     isn't GitHub Actions -- matches cibuildwheel's own behaviour of
     never requiring GitHub Actions specifically, and keeps this from
     ever becoming a hard dependency).
  2. Otherwise appends a Markdown table (identifier, filename, size,
     build duration) to that file path -- plain `open(path,
     "a").write(...)`, no library needed.
  3. Runs *in addition to* the existing stdout prints, not instead of
     them -- the plain-text summary is still what a local run or a
     non-GitHub CI system sees.
- **Scope check:** natmod and usermod both need this (two call sites,
  not one) but the helper itself is genuinely shared -- both result
  types already expose the same three fields (`identifier`, a way to
  get a filename, `size`), so a small `Protocol` or just duck-typing
  on those three attributes avoids writing it twice. Do not gold-plate
  this into a generic "reporting" subsystem; it is one Markdown table,
  written once, called from two places.
- Genuinely independent of **D28**: this is pure CLI/output-formatting
  work, touches no Dockerfile, no toolchain resolution, no
  `action.yml` structure at all -- a good candidate to implement
  first, quickly, before or in parallel with **D28**'s much larger
  container migration, if a new session wants an early, low-risk win.

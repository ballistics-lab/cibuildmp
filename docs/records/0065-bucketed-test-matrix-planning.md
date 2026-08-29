# 0065 — bucketed test-matrix planning: ≤20 concurrent jobs, ordered by plan

- Status: Implemented
- Related: [0062], [0063], [0044], [0058]

## What this decides

[0062] split `test-platforms.yml`'s own single shared matrix into one
`workflow_call` per port, each with its own independent 256-config budget,
because landing `rp2` pushed one shared amd64 matrix to 211/256 --
real headroom, not hypothetical. That fixed the ceiling it was aimed at.
It did not fix wall-clock, and a real run of the result proved it: one job
per identifier (~238 of them) finished 30 legs in the first eight minutes,
then made no further progress for 35+ more minutes ([0044]'s own
2026-08-29 addendum records the same run). GitHub's own account-wide
concurrent-job cap is the actual bottleneck -- more, smaller matrices
sharing one concurrency budget queue exactly as badly as one big one, and
no amount of per-port splitting touches that.

This record replaces the per-port shape with a planned one:

- **`bin/plan_test_matrix.py`** resolves the real, ordered identifier list
  a `build`/`skip` selection produces (via `cibuildmp`'s own
  `cli._resolve_all()` -- not re-parsing identifier strings, see the
  script's own docstring) and bin-packs it into **at most 20 buckets**
  (configurable, `--max-buckets`), so a run never asks GitHub for more
  concurrent jobs than that regardless of how many identifiers are
  selected.
- Buckets are balanced by a **static, coarse per-image time estimate**
  (seeded from the real run [0044]'s own addendum measured, see that
  record's table) rather than left to chance -- an LPT bin-packing over
  chunks, where a chunk is every identifier sharing one `(image, tag)`,
  so batching still gets the benefit `--keep-going`'s own docstring
  argues for (one shared `fetch_micropython()`/`mpy-cross`/image pull per
  chunk, cache-backed, [0063]) instead of being scattered one identifier
  at a time.
- A chunk heavier than its own runner's fair per-bucket share is split
  into near-equal, still-contiguous sub-chunks first, so one huge port
  (esp32's 83 identifiers on `esp_idf_base`, rp2's 74 on `arm_embedded`)
  does not have to land in a single, disproportionately long bucket.
- Buckets are partitioned by **runner first** (a job has exactly one
  `runs-on`): unix's own `aarch64`/`armv7l` cells are the only ones ever
  native to `ubuntu-24.04-arm` (record 0044), everything else runs on
  `ubuntu-latest` -- the 20-bucket budget is shared proportionally
  across whichever runner classes are actually in play, never fewer than
  one bucket for a non-empty class.
- Each bucket becomes one call to `test-platforms.yml` (now a thin,
  single-job reusable/dispatchable building block, not an orchestrator in
  its own right -- see below), running with `--keep-going` and uploading
  its own JSON report ([0063]).
- **`aggregate-results` builds the summary from those JSON reports**,
  not the old `result-*.md`-per-leg-plus-`grep '❌'` convention -- and
  renders every row in `plan`'s own identifier order, the order
  `cibuildmp` itself finds them in, not upload-completion order and not
  the old step's own `sort`. An identifier with no matching report entry
  at all (its own bucket's job never got as far as `orchestrate.build()`/
  `build_all()`'s own `try`/`finally`) still gets a row, marked distinctly
  from a real build failure.

## Why bucket by estimated time, not just by port

A bucket that is mostly one slow port (esp32, ~268s/identifier) and
another that is mostly fast unix native cells (~125s/identifier) would
otherwise finish at wildly different times even at equal identifier
counts -- the whole run's own wall clock is bounded by its *slowest*
bucket, so an unbalanced split wastes exactly the concurrency this record
exists to use well. Real run 33220563659's own measured averages (record
[0044]'s addendum) are what `_WEIGHTS` seeds from; nothing yet builds a
live history from the JSON reports this same change makes available run
over run, which would let a future version replace the static table with
real, current numbers -- flagged below, not attempted here.

## Where the ordering requirement comes from, and why it is load-bearing

The user's own explicit ask: the final summary must list every identifier
in the order the tool itself finds them, not the order buckets happen to
finish or upload in (both are real timing races under `fail-fast: false`
+ parallel jobs, and neither is stable across reruns). `plan`'s own
`identifiers` output is threaded through, unmodified, all the way to
`aggregate-results`'s own render step specifically so the table's row
order is a property of the *plan*, not of runtime scheduling.

## What `test-platforms.yml` still is, and is not, after this

Still a real, standalone `workflow_dispatch` target -- a maintainer can
run it directly against one `--build` glob without going through
`plan`/`aggregate-results` at all, the same debugging use [0062]'s own
version already served. No longer an orchestrator of its own: the old
`build-matrix` (native-vs-emulated arch classification) and
`test-amd64`/`test-arm64`/`test-emulated` fan-out are gone, because
`bin/plan_test_matrix.py` already does the equivalent classification once,
for the whole run, before any job starts -- doing it again per port-call
would be the same work, done worse (per-call 256-config ceilings this
record no longer needs, since 20 buckets never approaches 256 regardless
of port count).

## `action.yml` grows a `keep-going` input

`test-platforms.yml`'s own bucket job goes through `uses: ./` (the real
composite action, the same discipline `build-examples.yml`'s own docstring
argues for -- "the only real feedback loop for `action.yml` itself"), not
a direct `cibuildmp` CLI call. `--keep-going` therefore needed a real
action input, not a workaround; added the same way `build`/`skip` already
are (`ACTION_KEEP_GOING`, `[ -n ... ]` presence check, `args+=(--keep-going)`).
Any consumer of this action, not just this project's own CI, can now ask
for it.

## What is not decided here

- **The weight table is static**, not learned. `--keep-going`'s own JSON
  reports are, from this point on, a real per-identifier duration history
  -- nothing reads them back into `bin/plan_test_matrix.py` yet. A real
  refinement, once enough runs exist to make an average meaningful.
- **20 is not derived from a real account concurrency limit read from the
  GitHub API** -- it is the number the user asked for directly. If the
  account's own real cap is higher, buckets could be fewer and longer;
  if lower, this could still queue. Nothing here discovers it
  automatically.
- **The bucket count is fixed for the whole run**, not adaptive to how
  many *other* workflows are competing for the same account-wide budget
  at the same time (`build-examples.yml`'s own concurrent jobs, any other
  running workflow). Real headroom varies; this plans against a fixed
  assumption.

## Addendum, 2026-08-29 — every bucket built green, zero reports uploaded

The first real run (33225078049, PR#7) came back exactly as designed on paper: 20
buckets, every one `success`, `aggregate-results` itself green. And the summary it
rendered showed "no report" for every single one of 228 identifiers -- the failure
mode the render step exists to make visible rather than hide, doing exactly that,
just for a reason that had nothing to do with any build actually failing.

`actions/download-artifact`'s own log said it plainly: `Found 0 artifact(s)`. Every
bucket's own "Upload report" step had already warned and moved on: `No files were
found with the provided path: .cibmp-report/*.json`. The builds themselves were
real and successful -- one esp32 bucket's own log shows "12 usermod target(s) built
in 1794.7s" with real byte sizes -- so `report.write_report()` did run, in its own
`finally`, exactly as designed. It just never wrote where `CIBMP_REPORT_PATH` said
to.

The cause: `CIBMP_REPORT_PATH` (and `CIBMP_DISABLE_GITHUB_STEP_SUMMARY`,
`CIBMP_VERSION`) were set as `env:` on `test-platforms.yml`'s own `Build this
bucket` step -- the step that calls `uses: ./`. A composite action's own inner
steps do not reliably inherit `env:` declared on the *calling* step; only
job-level (or workflow-level) `env:` is guaranteed to reach them. So the Python
process actually running `cibuildmp` never saw `CIBMP_REPORT_PATH` at all, fell
through to its own real default (`report.py`'s own `cache_root() / "reports"`,
inside this ephemeral runner's own cache -- gone the moment the job ends), and
`upload-artifact`'s `path: .cibmp-report/*.json` matched nothing, on every one of
twenty buckets, for the exact same reason each time.

Doubly silent because `if-no-files-found` was `warn`, not `error` -- the correct
default for a step whose whole point is "there might genuinely be nothing to
upload", but wrong here, where a bucket with any real identifiers at all should
*always* produce a report. Fixed both ways: the three `CIBMP_*` vars moved to the
`build` job's own top-level `env:` (guaranteed to reach every step, composite or
not), and `if-no-files-found` changed to `error` -- so the same class of bug
would now fail the step loudly instead of a report silently going missing behind
a green check.

## Addendum, 2026-08-29 (second) — moving `env:` to job level was not the fix

The very next real run (33246930962) still found zero reports -- this time loudly,
`if-no-files-found: error` doing exactly what it was changed to do, cancelled by
the user mid-run once enough buckets had gone red to look like a real regression.
But this run's own logs settle the previous addendum's own theory for real,
rather than leaving it argued from GitHub's general documented behaviour: the
`Run cibuildmp` step's own resolved `env:` block, printed in the log, lists
`CIBMP_REPORT_PATH: /home/runner/work/cibuildmp/cibuildmp/.cibmp-report` right
there next to the job-level `CIBMP_VERSION`/`CIBMP_DISABLE_GITHUB_STEP_SUMMARY` --
job-level `env:` does reach a composite action's own inner steps, confirmed
directly rather than assumed. The previous addendum's fix was real (job-level
`env:` is the correct, guaranteed-reliable place for these three vars regardless)
but it was not addressing the actual cause of the missing reports, which survived
it unchanged.

The real cause was sitting in the very same "Upload report" step's own resolved
inputs, printed in the exact same log: `include-hidden-files: false`, right next
to `path: .cibmp-report/*.json`. `actions/upload-artifact@v7` excludes every file
under a dot-prefixed path segment by default, *regardless of whether the `path:`
glob names that segment explicitly* -- `.cibmp-report` is a hidden directory by
that rule, so nothing under it was ever eligible for upload, on any of the twenty
buckets, in either run. Every build really had succeeded (both runs' own logs
show real "N target(s) built" lines with real byte sizes); the report file really
was written, at exactly the path `CIBMP_REPORT_PATH` named -- it just could never
leave the runner.

Fixed by dropping the leading dot: `CIBMP_REPORT_PATH`/`path:` both renamed
`cibmp-report` (no longer hidden), rather than reaching for
`include-hidden-files: true` -- fewer surprises from anything else in this
project's own tooling (`.gitignore`, an editor, a future `find`) that also treats
a dot-prefixed path specially.

## Addendum, 2026-08-29 (third) — the weight table's own seeding was measuring the wrong thing

Run 33225078049 (the first run whose reports were actually recoverable, once
the two addenda above landed) built green end to end, but its own real
per-bucket wall time was nowhere near uniform: 3m21s to 36m59s across twenty
buckets whose own *estimates* only spanned a 1.3x range (2455s-3216s). The
user's own read of that run -- "still 43 minutes, not even" -- was exactly
right, and the cause was not the LPT packing, it was the weight table itself.

Every real bucket's own wall time was divided evenly across its own
identifiers and cross-checked against `dockerrun.image_for()` (the same
resolution this module already uses), giving a real, batched-regime
per-identifier cost for the first time. It disagreed with `_WEIGHTS` by
1.5-4x, in one direction only -- every real number came in *lower*:
`esp_idf_base` 144s measured against 268s assumed, `arm_embedded` 55-116s
(port-dependent) against a single blended 180s, `riscv_embedded`/`windows`/
`webassembly` each 3-4x lower.

The reason is what `_WEIGHTS` was actually seeded from: run 33220563659, a
one-job-per-identifier run where each identifier's own measured duration
included its own full, unshared `fetch_micropython()`/image-pull/ESP-IDF-
install cost. Batching ([0065]'s own point) makes that cost shared per
*bucket*, paid once and amortized -- so the real marginal cost of adding one
more identifier to an already-warm bucket is substantially below what an
isolated job's own total ever measured. The table conflated "total time
alone" with "marginal cost inside a batch", which is a category error, not
a stale constant -- re-measuring from the isolated run again would have
reproduced the same wrong shape.

`arm_embedded` carried a second, independent error on top: one blended
weight (180s) across three ports whose own real costs differ by 2x (rp2
116s, qemu/natmod 54s) meant two buckets estimated identically (16
identifiers each) could be real-measured at 12 minutes and 37 minutes
depending on which port happened to dominate each one -- confirmed directly
(`amd64-04`: mostly natmod-arm, 754s real; `amd64-06`: mostly rp2, 2219s
real). `_PORT_WEIGHTS` now overrides by port before falling back to the
per-image table, `rp2` split out at its own 116s rather than folded in.

Re-seeded from the batched numbers throughout (`_WEIGHTS`/`_PORT_WEIGHTS`/
`_DEFAULT_WEIGHT` all lowered to match); the six emulated-everywhere unix
cells (`_EMULATED_UNIX_WEIGHT`) are the one deliberate exception, kept at
the original isolated-run figure (1050s) rather than re-measured the same
way -- none of them has landed in a bucket small enough yet to isolate a
trustworthy per-identifier share, and the naive even-split estimate for
them (30-40s) flatly contradicts every real isolated measurement this
project has for that class of cell. Re-planning locally against the exact
same `build`/`skip` this run used drops the worst-case (amd64) bucket
estimate from ~54 minutes to ~35 minutes -- and the 35-minute floor left is
the two emulated-unix identifiers LPT still occasionally pairs into one
bucket, a real, small, remaining packing inefficiency, not a table error.

One thing this addendum does not fix: real bucket **start** times were
staggered by up to five minutes in that same run (several buckets did not
start until well after `plan` finished), which is queueing against the
account's own real concurrent-job limit, not anything `bin/plan_test_matrix.py`
controls -- 20 was the user's own chosen cap, not a number read from the
account's real limit ([0065]'s own "what is not decided here" already flags
this). Whatever that real limit is, if it is below 20, some staggering on
every run is a residual cost this change does not remove.

## Addendum, 2026-08-29 (fourth) — the config's own default `skip` silently re-applies when `--skip` is omitted

A later run (33249014504, same commit as the third addendum's re-plan)
still came back with three buckets missing reports -- not all twenty, and
not the same failure mode as either prior addendum: this time the "Build
this bucket" step itself failed, in ~12-25 seconds, well before a real
build could even start. All three (`amd64-14`, `amd64-15`, `amd64-16`) were
buckets made entirely of pairs from the nine surviving emulated unix
identifiers -- the exact class `_EMULATED_UNIX_WEIGHT` exists for. The job
log gave the real cause directly:

```
ACTION_BUILD: v1.28.0-manylinux_2_28_ppc64le v1.29.0-musllinux_1_2_s390x
ACTION_SKIP:
ACTION_KEEP_GOING: 1
##[endgroup]
cibuildmp: error: no targets selected. Pass --allow-empty if that is expected.
##[error]Process completed with exit code 2.
```

`examples/template/cibuildmp.toml` carries its own top-level `skip =
"*_ppc64le *_s390x *_riscv64"` -- the exact suffixes these three buckets
were built from. `action.yml`'s own script only appends `--skip
"$ACTION_SKIP"` to the CLI when `[ -n "$ACTION_SKIP" ]`; for these three
buckets `inputs.skip` was the empty-string default (`bin/plan_test_
matrix.py` never emits a per-bucket `skip`, it pre-filters instead), so
`--skip` was omitted from the CLI *entirely* -- not passed as `--skip ""`.
That let the config file's own `skip` cascade layer apply unopposed
(`options.py`'s `resolve_cascade()`: an *omitted* layer is `None` and is
skipped, but this was never given the chance to be an omitted layer in the
first place, since no `--skip` flag means the config layer is the only one
present at all), filtering the exact identifiers `plan_test_matrix.py` had
already selected right back out, down to zero. `cli.main()` raises before
`orchestrate.build()`/`build_all()` is ever called, so `report.write_
report()` never runs either -- zero report files, so "Upload report"
failed too (loudly, `if-no-files-found: error`), which is why this looked
like a missing-report bug and not a skip bug at first glance.

The fix is not in `plan_test_matrix.py` or `action.yml` -- it is a real env
var, `CIBMP_SKIP: ""`, added to `test-platforms.yml`'s own job-level
`env:` block (alongside `CIBMP_VERSION`/`CIBMP_REPORT_PATH`/`CIBMP_
DISABLE_GITHUB_STEP_SUMMARY`, for the same job-level-reaches-the-composite-
action's-inner-steps reason the first addendum already established).
Unlike `action.yml`'s own `[ -n ... ]` presence check, `options.py` reads
`CIBMP_SKIP` via plain `os.environ.get()`, which does distinguish "unset"
(`None`, cascade layer skipped) from "set to empty string" (a real,
explicit value that replaces) -- confirmed directly from `resolve_
cascade()`'s own docstring and `platforms/natmod/options.py`'s env-lookup
line. Setting it unconditionally means every bucket's own explicit,
already-filtered `build` selection is what actually decides what gets
built, regardless of whether `inputs.skip` happens to be empty for that
bucket -- the config file's own default skip no longer gets a chance to
silently re-apply underneath it.

[0044]: 0044-unix-native-images-landed.md
[0058]: 0058-image-groups-are-toolchains-not-ports.md
[0062]: 0062-test-platforms-per-port-orchestrator.md
[0063]: 0063-keep-going-and-json-build-report.md

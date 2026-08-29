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

[0044]: 0044-unix-native-images-landed.md
[0058]: 0058-image-groups-are-toolchains-not-ports.md
[0062]: 0062-test-platforms-per-port-orchestrator.md
[0063]: 0063-keep-going-and-json-build-report.md

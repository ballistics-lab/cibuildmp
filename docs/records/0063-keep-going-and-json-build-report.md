# 0063 — `--keep-going` and a JSON build report, for coverage sweeps

- Status: Implemented
- Related: [0029], [0047], [0058], [0062]

## What this decides

`build_all()` (natmod) and `orchestrate.build()` (usermod) both loop over
every selected target in-process, and until this record neither one caught
anything: a single target's own `BuildError`/`UsermodBuildError`, or a
whole tag group's own `SourceError` from a bad fetch, propagated straight
out and aborted the run. Nothing after the failure was even attempted, and
nothing about it survived past `run_resolved()`'s own one-line `print(...,
file=sys.stderr)`.

That is the right default for a real build (`build-examples.yml`'s own
comment on the qemu leg makes the argument directly: "one failing target
aborts the whole invocation"). It is the wrong shape for
`test-platforms.yml`'s own coverage sweeps, which exist specifically to
find out how many of a wide `--build` glob's identifiers still build, not
to stop at the first one that doesn't. Today that workflow gets this by
brute force — one job per identifier, `continue-on-error: true` at the job
level — which is also why a ~230-identifier sweep spends most of its wall
clock queued rather than building (measured live: 30/238 jobs finished in
the first 8 minutes of a real run, then nothing progressed for 35+ more).
Fixing that queueing problem means batching many identifiers into fewer
jobs, and batching needs `cibuildmp` itself to survive a failure inside a
batch — a bash loop calling `cibuildmp --build "$id"` once per identifier
gets there without any of this, but throws away the one thing a single
process already does for free: `sources.fetch_micropython()`/
`build_mpy_cross()` both cache to disk (`cache_root()`, stamp-file guarded)
and a single invocation already groups by tag ([0051]/D13), so batching
inside cibuildmp itself, not just inside one CI job, is the version that
does not re-fetch the same checkout once per identifier.

Two things, added together:

- **`--keep-going`.** Off by default — every existing caller, in CI or
  local, keeps today's exact fail-fast behaviour with zero code changes.
  On, both `build_all()`/`orchestrate.build()` catch a target's own build
  failure (and a tag group's own setup failure) instead of letting it
  propagate, record it, and move on to the next target — the next one in
  the same tag group, and the next tag group after that.
- **A JSON build report** (`report.py`), one file per invocation, written
  unconditionally — not gated on `--keep-going` — because a plain
  fail-fast run that fails still leaves something worth reading: whatever
  built before the failure, plus the failure itself. Each entry is
  `{identifier, duration, error, output_dir, size, files}` — `error: null`
  plus the artifact's directory/size/file listing for a success, `error:
  "<message>"` and nulls for a failure. Defaults to `cache_root() /
  "reports"`, overridable with `CIBMP_REPORT_PATH` — the same
  one-env-var-per-path shape `CIBMP_CACHE_PATH` already has, not the
  `opt()`/`cibuildmp.toml` cascade (this is a runtime/CI knob about where
  output lands, the same category `CIBMP_DISABLE_GITHUB_STEP_SUMMARY`
  already lives in).

## Where this deliberately diverges from cibuildwheel

Checked live against a real `cibuildwheel==4.2.0` install before writing
any of this (this project's own standing rule — see `CLAUDE.md`).
`platforms/linux.py`'s own `get_build_steps()` already groups
`PythonConfiguration`s by `(platform_tag, container_image, before_all,
container_engine)`, one container per group — validating the batching
motivation above independently, upstream already pays fetch/pull cost
once per image group, not once per wheel. But its own `build()` is
unconditionally fail-fast: the first `subprocess.CalledProcessError` from
any build step raises `errors.FatalError` and stops the whole run, with no
keep-going flag, config key, or env var anywhere in the module. There is
no upstream shape to mirror for the "record every outcome, don't stop"
half of this record — every part of `--keep-going` and the report format
is this project's own, added because `test-platforms.yml`'s own coverage
sweep is a use case cibuildwheel's own CI does not have (it does not
attempt to build every wheel across the entire real matrix on a schedule
the way this project's own descoped-from-default-but-still-real cells
are). Everything else about how a build actually runs — the pinned
images, the pull-only rule ([0033]), one process per invocation — is
unchanged.

## Shape, and why it lives where it does

`report.py` is a new top-level module, not folded into `stepsummary.py`,
for the same reason `stepsummary.py` itself is not folded into either
family module (its own docstring): a shared helper importing from either
`natmod`/`usermod` would make the other import it back. Duck-typed against
the same `_Result` protocol shape (`identifier`/`output`/`size`/
`duration`) `stepsummary.py` already uses, so it depends on neither
`BuildResult` nor `UsermodBuildResult` directly.

`--keep-going` is spelled as the affirmative "keep going" (GNU Make's own
`-k`/`--keep-going`, "continue as much as possible after an error"), not
as a `--no-fail-fast` negation of a `--fail-fast` flag that would need to
default to true — the same "name the destination, not the inverse of the
default" the rest of this project's own CLI already follows
(`--allow-empty`, not `--no-fail-on-empty`).

`write_report()` is called from inside a `try`/`finally` wrapped around
each function's own per-tag-group, per-target loop, in both families —
not from `run_resolved()` one layer up — so a fail-fast run's own
propagating exception still passes through the `finally` and gets a
report written before it escapes. This is also why `orchestrate.build()`'s
own return type stays exactly `list[UsermodBuildResult]` (successes only,
unchanged) rather than growing a second return value for failures: the
report already carries the complete picture, and every existing caller
that does `results = build(...)`/iterates the list keeps working
unmodified. `usermod/__init__.py`'s own `run_resolved()` tells a
keep-going partial failure apart from a clean run the same way natmod's
`build_all()` does internally — by comparing how many targets were
selected against how many results came back — not by a second return
value or a raised summary exception (raising would have thrown away
`results` for whatever did succeed, and with it the GitHub step summary
table and the plain-text per-target printing a keep-going run wants most).

## What is not decided here

- **`test-platforms.yml` does not use any of this yet.** This record adds
  the CLI-level capability; wiring the CI workflow to batch identifiers
  per image group and pass `--keep-going`, parsing the JSON report instead
  of (or alongside) today's per-job `result-*.md` artifact convention, is
  real, separate follow-up work.
- **The exit code for a partial `--keep-going` failure is a bare `1`**
  (matching `--allow-empty`'s own already-established `0`/`2` split
  elsewhere in this CLI) — not a distinct code from a config-load error
  (`2`) or a clean run (`0`). Whether a CI caller needs to tell "some
  targets failed" apart from "the whole invocation could not even start"
  by exit code alone, rather than by reading the report, is not asked yet.
- **No `--report-path` CLI flag**, only `CIBMP_REPORT_PATH` — matches
  `CIBMP_CACHE_PATH`'s own env-var-only precedent exactly, but has not
  been asked for as a flag.

[0029]: 0029-github-actions-job-summary.md
[0033]: 0033-cibuildmp-never-builds-docker-image-itself.md
[0047]: 0047-run-output-parity-with-cibuildwheel.md
[0051]: 0051-usermod-identifiers-have-no-version-axis.md
[0058]: 0058-image-groups-are-toolchains-not-ports.md
[0062]: 0062-test-platforms-per-port-orchestrator.md

# 0047 — the run output works, but it is not cibuildwheel's

Status: Accepted (design; nothing implemented here)

The user's call, stated directly: the run summary works, but they want it to
look **exactly** like cibuildwheel's. This record separates what that actually
means from what cibuildmp prints today, because the gap is not cosmetic — it is
mostly a missing *mechanism* (log folding), and one deliberate divergence that
should survive the change.

## What cibuildmp prints today

`natmod/cli.py` and `usermod/cli.py` each own their own `print()` calls, plain
and uncoloured:

```
cibuildmp: resolving toolchains for 5 target(s)

cibuildmp: 1 usermod target(s) against MicroPython v1.28.0
  MicroPython v1.28.0: cached at /home/…/v1.28.0
  mpy-cross: cached at /home/…/mpy-cross/build/mpy-cross

  [ 1/1 ] unix-manylinux_2_28_x86_64   …
        done in 45.7s -> …/micropython

cibuildmp: 1 usermod target(s) built in 45.7s
  unix-manylinux_2_28_x86_64: micropython-unix-manylinux_2_28_x86_64 (696984 bytes)
```

Plus a real GitHub Actions job summary ([0029], `natmod/stepsummary.py`) — a
Markdown table on the run's Summary page, which cibuildwheel's own action also
produces. That part already has parity and is not what this record is about.

## What cibuildwheel prints

Read from `cibuildwheel/logger.py` on `main`, not recalled:

```python
FOLD_PATTERNS = {
    "azure":  ("##[group]{name}",                                "##[endgroup]"),
    "travis": ("travis_fold:start:{identifier}\n{name}",          "travis_fold:end:{identifier}"),
    "github": ("::group::{name}",                                 "::endgroup::{name}"),
}
```

```python
print(f"{c.bold}{c.blue}Building {identifier} wheel{c.end}")
print(f"{description}")
...
print(f"{c.green}{s.done} {c.end}{self.active_build_identifier} finished in {duration_str}")
...
print(f"{c.green}{s.done} {c.end}{duration:.2f}s".rjust(78))
self._start_fold_group(f"{n_wheels} wheel{s} produced in {duration_str}")
for build_info in self.summary:
    print(" ", build_info)
```

with `s.done = "✓"`, `s.error = "✕"`, and the usual ANSI constants
(`\033[32m` green, `\033[1m` bold, …), degrading to the words `done`/`failed`
when symbols are unavailable.

## The four real differences

1. **Log folding is the big one, and cibuildmp has none.** Every noisy phase
   upstream is wrapped in a collapsible group, per CI provider — `::group::` on
   GitHub Actions, `##[group]` on Azure, `travis_fold` on Travis, plain headers
   elsewhere. This is not decoration: a `unix` build emits several hundred `CC`
   lines per target, and cibuildmp emits all of them flat, so a five-target run
   buries its own summary under thousands of lines. Upstream's structure is
   "one fold per build identifier, plus a final fold for the summary".
2. **No colour, no symbols.** Upstream marks completion with a green `✓` and
   failure with `✕`, and bolds the identifier being built. cibuildmp prints
   `done in 45.7s`. Colour must be conditional the way upstream's is (a
   `no-color`/TTY/`FORCE_COLOR` decision), not unconditional escapes.
3. **The final summary is a fold with per-item lines**, opened with
   `N wheels produced in <duration>`. cibuildmp's equivalent
   (`N target(s) built in Xs` plus one line per result) is the same information
   in the same order — this part is close, and mostly needs the fold and the
   symbols.
4. **The per-build header.** Upstream prints `Building <identifier> wheel`
   followed by a description; cibuildmp prints a `[ n/m ] <identifier>` plan
   line plus a toolchain description line. Same content, different shape.

## What should *not* converge

Two things, and they should be argued rather than quietly dropped in a "make it
look like upstream" change:

- **`cibuildmp: ` prefixes on errors.** They make grep-ability and error
  attribution obvious, and upstream has no equivalent because it is the only
  thing running. Keep them on `stderr`; upstream parity is about the *build
  log*, not about how errors identify themselves.
- **The plan/`--dry-run` output.** cibuildmp prints a resolved plan before
  building (`[ n/m ] identifier`, toolchain, make command) and can stop there;
  upstream has no such mode. That is cibuildmp's own thing ([0003]'s "the tool
  chooses the toolchain, and says which"), and folding it away or restyling it
  into upstream's shape would lose the point of it.

## Shape of the work

`logger.py`-equivalent as its own module, the way `stepsummary.py` already is —
and for the same reason its own docstring gives: `cli.py` imports `usermod.cli`
for dispatch, so a shared helper in either would be a circular import. Both
result types (`BuildResult`, `UsermodBuildResult`) already expose the same
`identifier`/`output`/`size` fields, and `stepsummary.py` already duck-types
them via a `Protocol` rather than importing either dataclass; a logger should
do the same.

Fold-mode detection has a real precedent to copy exactly rather than invent:
upstream picks the pattern from CI environment variables and falls back to
plain headers. `stepsummary.py` already reads `GITHUB_STEP_SUMMARY`, so the
"am I on Actions" question is answered in this codebase once already.

## Not decided here

- Whether folding applies to natmod's per-target `make` output as well as
  usermod's. natmod's is far quieter (one `.mpy` per target), so the payoff is
  mostly on the usermod side, but a split would be its own inconsistency.
- Whether `--dry-run`'s plan output stays outside the folding entirely (this
  record's own guess is yes).
- Whether the job summary ([0029]) and the fold summary should share a
  formatter or stay separate. They already produce the same facts in two shapes.

[0003]: 0003-toolchain-resolution-per-target.md
[0029]: 0029-github-actions-job-summary.md

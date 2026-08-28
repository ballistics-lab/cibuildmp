# 0047 — the run output works, but it is not cibuildwheel's

Status: Accepted (design; nothing implemented here). **Corrected and widened by the
2026-08-28 addendum**, read against an installed cibuildwheel 4.1.0: the folds are
per *step*, not per build identifier, and `stepsummary.py` is in scope after all

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
    "azure": ("##[group]{name}", "##[endgroup]"),
    "travis": (
        "travis_fold:start:{identifier}\n{name}",
        "travis_fold:end:{identifier}",
    ),
    "github": ("::group::{name}", "::endgroup::{name}"),
}
```

```python
print(f"{c.bold}{c.blue}Building {identifier} wheel{c.end}")
print(f"{description}")
...
print(
    f"{c.green}{s.done} {c.end}{self.active_build_identifier} finished in {duration_str}"
)
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

---

## Addendum, 2026-08-28 — cibuildwheel 4.1.0 read properly: the folds are per *step*, not per identifier

Read from an installed cibuildwheel **4.1.0**
(`~/.local/share/uv/tools/cibuildwheel/lib/python3.14/site-packages/cibuildwheel/`),
`logger.py` in full plus every `log.*` call site across `platforms/*.py`, `audit.py`
and `__main__.py`. The record above quoted `logger.py` correctly but inferred the
*structure* from the quotes alone, and the inference was wrong in a way that changes
the work.

### The correction: folding granularity

The record says upstream's structure is "one fold per build identifier, plus a final
fold for the summary". It is not. `build_start()` / `build_end()` open **no fold at
all** — they print an unfolded, bold-blue `Building <identifier> wheel` header with a
description under it, and an unfolded `✓ <identifier> finished in <duration>` when the
build ends. Those lines are the *visible spine* of the log, deliberately outside every
group so they survive collapsing.

The folds are opened by `log.step(description)` and closed by `step_end()`, **inside**
a build. One build on `platforms/linux.py` produces this sequence:

```
Starting container image <image>...        ← fold   (per build step, outside build_start)
Copying project into container...          ← fold
Running before_all...                      ← fold
                                             ─── build_start(identifier): NOT folded ───
Setting up build environment...            ← fold
Running before_build...                    ← fold
Building wheel...                          ← fold
Repairing wheel...                         ← fold
Auditing wheel...                          ← fold   (audit.py)
Testing wheel...                           ← fold
                                             ─── build_end(): NOT folded ───
Copying wheels back to host...             ← fold
N wheels produced in <duration>            ← fold   (print_summary, contents inside)
```

So the unit of collapsing is a *phase of one build*, not a build. That is the opposite
of what cibuildmp would have implemented from the record above, and it is also the
better shape for cibuildmp specifically: a `unix` build's several hundred `CC` lines
all belong to one phase (`make`), and folding at identifier granularity would have
buried the per-target `✓` lines that are the actual thing a reader scans for.

Concretely, cibuildmp's equivalent step list is already latent in what it prints:
resolving MicroPython, resolving mpy-cross, pulling the image, running `make`,
collecting output, verifying the platform tag. Those are the folds. The
`[ n/m ] <identifier>` line and its `done in 45.7s` are the spine and stay unfolded.

### Folds never nest, and that is enforced, not conventional

`_start_fold_group()` calls `_end_fold_group()` as its first statement, and `step()`
calls `step_end()` as its first statement. There is exactly one active group at any
moment; a new step implicitly closes the previous one. GitHub Actions does not support
nested `::group::` at all, and this is how upstream sidesteps the question rather than
tracking a stack. Any cibuildmp logger should copy the constraint, not just the
patterns.

`step_end()` also prints the timing line **after** closing the fold, so it lands
outside the collapsed region:

```python
print(f"{c.green}{s.done} {c.end}{duration:.2f}s".rjust(78))
```

Note `.rjust(78)` is applied to the string *including* its ANSI escapes, so the visible
column is short of 78 by the escape length. Copying the number without copying the quirk
would produce a visibly different alignment.

### The colour policy in the record is wrong

The record says colour "must be conditional the way upstream's is (a
`no-color`/TTY/`FORCE_COLOR` decision)". Upstream has no such decision. `NO_COLOR` and
`FORCE_COLOR` do not appear anywhere in the cibuildwheel package. The real rule, in
`Logger.__init__`, is CI-provider-first:

| `detect_ci_provider()` | `fold_mode` | `colors_enabled` |
| --- | --- | --- |
| `azure_pipelines` | `azure` | `True` unconditionally |
| `github_actions` | `github` | `True` unconditionally |
| `travis_ci` | `travis` | `True` unconditionally |
| `appveyor` | `disabled` | `True` unconditionally |
| anything else (incl. `gitlab`, `circle_ci`, `other`, `None`) | `disabled` | `file_supports_color(sys.stdout)` — a TTY check |

On a recognised CI, colour is on whether or not stdout is a terminal — which is the
point, since CI stdout never is. TTY detection is only the *fallback*. Note also that
GitLab and CircleCI get no folding despite GitLab supporting collapsible sections;
that is an upstream gap, not a design decision to copy.

Symbols are a separate axis: `Symbols(unicode=file_supports_unicode(sys.stdout))`
degrades `✓`/`✕` to the words `done`/`failed` based on whether stdout's encoding is a
utf codec — nothing to do with colour or with CI.

And one real gotcha worth stealing outright, from `ci.py`:

```python
def fix_ansi_codes_for_github_actions(text: str) -> str:
    """Github Actions forgets the current ANSI style on every new line."""
```

Any multi-line coloured block printed on Actions needs its active codes repeated per
line. Upstream applies this to exactly one thing (the options preamble in
`__main__.py`), but the fact is general.

### `cibuildmp: ` prefixes are parity, not divergence

The record's "What should *not* converge" section argues for keeping `cibuildmp: `
prefixes on errors because "upstream has no equivalent, because it is the only thing
running". That premise is false. Upstream prefixes its own diagnostics with its own
name in **every** mode:

```python
print(f"::error::cibuildwheel: {error}\n",  file=sys.stderr)     # fold_mode == "github"
print(f"cibuildwheel: {c.bright_red}error{c.end}: {error}\n", file=sys.stderr)  # otherwise
```

Same shape for `notice` and `warning`. So the decision stands unchanged, but the
argument inverts: keeping the prefix is *converging* with upstream, and the thing
cibuildmp is actually missing is the GitHub-Actions branch — `::error::` / `::warning::`
/ `::notice::` workflow commands, which surface as annotations on the run rather than
as text buried in a log. That is now the more valuable half of this item.

`log.quiet()` is a fourth level, printed grey to stderr with no prefix.

### The summary line carries two facts cibuildmp does not print

`BuildInfo.__str__` is the per-item line inside the final fold:

```
<identifier>: <filename> <size> in <duration>, SHA256=<hex>
<identifier>: <duration> (test only)
```

Sizes go through `humanize.naturalsize` (`"696.9 kB"`, not `696984 bytes`) and every
duration through `humanize.naturaldelta` — a real runtime dependency, not a formatting
helper upstream wrote. `sha256` is a `functools.cached_property` computed with
`hashlib.file_digest` on demand, so it costs nothing when the summary is not printed.

cibuildmp prints raw byte counts and no digest. The digest is the more interesting
omission: for a `.mpy` or a firmware binary it is the same provenance claim it is for a
wheel, and [0029]'s job summary would carry it for free.

There are three duration formats in play, and they are not interchangeable:
`naturaldelta(d, minimum_unit="milliseconds")` at `build_end`, plain `naturaldelta(d)`
in the summary, and bare `f"{d:.2f}s"` at `step_end`.

### The job-summary question this record left open is answered upstream

The record asks "whether the job summary ([0029]) and the fold summary should share a
formatter or stay separate". Upstream's answer: **share the data, format twice, in one
class.** `Logger.summary` is a `list[BuildInfo]`; `print_summary()` is a context manager
wrapping the whole build that, on exit, writes `_github_step_summary()` to
`$GITHUB_STEP_SUMMARY` (through `filter_ansi_codes()`) *and* prints the terminal fold
from the same list. Two renderers, one accumulated fact set, no second bookkeeping path.

That is a direct argument for merging `stepsummary.py` into the logger module this
record proposes, rather than building the logger beside it — and it costs little, since
`stepsummary.py` already duck-types both result types through a `Protocol` instead of
importing either dataclass.

Upstream's own step-summary body is worth reading before reworking [0029]'s: an
options `<details>`/`<summary>` block containing a YAML dump of resolved options, then
an HTML table of Wheel / Size / Build identifier / Time / SHA256, then a right-aligned
`<sup>` footer line and a `---`.

### The preamble exists, which sharpens the `--dry-run` divergence

The record argues cibuildmp's resolved-plan output is its own thing because "upstream
has no such mode". Upstream has no `--dry-run`, true — but `print_preamble()` in
`__main__.py` does print, unfolded, before any build: ASCII-art banner, version,
`Build options:` with the resolved option summary indented under it, the cache folder,
then every detected warning and error. The divergence is therefore narrower and more
defensible than the record claims: not "upstream prints nothing before building" but
"upstream prints resolved *options*, cibuildmp additionally prints a resolved *plan*
with a per-target toolchain and `make` command, and can stop there". The guess that the
plan stays outside folding is confirmed by upstream's treatment of its own preamble.

### What still holds from the record above

Everything else. The four differences it names are real; the two `should not converge`
items survive (one with an inverted argument, above); the module-shape reasoning — a
`logger.py`-equivalent as its own module, `Protocol`-typed against both result types,
because `natmod/cli.py` imports `usermod.cli` and a shared helper in either would be a
circular import — is unaffected and is still the right shape.

### `write_step_summary` is explicitly in scope too, and it diverges more than the log does

Added on the user's own call, same session: the job summary is part of "look exactly
like cibuildwheel's", not a separate settled thing. The record above excluded it —
"that part already has parity and is not what this record is about" — and that is the
second thing this addendum has to withdraw. It has parity of *intent* (a real Markdown
table on the Summary page rather than raw log lines, which is all [0029] ever claimed);
it does not have parity of *content* or *shape*.

`src/cibuildmp/stepsummary.py` writes:

```markdown
### cibuildmp: 5 target(s) built in 231.4s

| Identifier | File | Size |
| --- | --- | ---: |
| `unix-manylinux_2_28_x86_64` | `micropython` | 696,984 bytes |
```

`Logger._github_step_summary` writes an options `<details>` block, then a raw HTML
table, then a right-aligned footer and a `---`. Cell by cell:

| | cibuildmp | cibuildwheel 4.1.0 |
| --- | --- | --- |
| Heading | `### cibuildmp: N target(s) built in Xs` | `### 🎡 cibuildwheel` — no counts, no duration |
| Resolved options | not shown | `<details><summary>Build options</summary>` wrapping a ```yaml dump of `options.summary(identifiers=…, skip_unset=True)` |
| Table markup | Markdown pipe table | raw `<table>` with `<th align="left">`, every cell `nowrap`, filenames and identifiers wrapped in `<samp>` |
| Columns | Identifier, File, Size | Wheel, Size, Build identifier, Time, SHA256 — note the order: artefact first, identifier third |
| Size | `f"{size:,} bytes"` → `696,984 bytes` | `humanize.naturalsize` → `696.9 kB` |
| Per-item time | none; only a total, in the heading | `humanize.naturaldelta(b.duration)` per row |
| SHA256 | none | per row, `hashlib.file_digest`, a `cached_property` so it costs nothing unless rendered |
| Rows with no artefact | cannot occur | `*Test only*` in the Wheel column |
| Footer | none | `<div align="right"><sup>N wheels created in <duration></sup></div>` |
| Trailer | none | `\n---\n` |
| Write mode | `open(path, "a")` — **append** | `Path(...).write_text(...)` — **truncate** |
| ANSI | not applicable | `filter_ansi_codes()` over the whole string before writing |
| Called from | explicitly, by each platform's own `__init__.py` (two call sites) | on exit of the `print_summary()` context manager that wraps the entire build |

Three of these are more than cosmetic:

1. **The two columns cibuildmp does not have are the two worth having.** Per-target
   `duration` is already carried by both `BuildResult` and `UsermodBuildResult` — the
   `_Result` Protocol in `stepsummary.py` simply does not expose it, while the callers
   pass a `total_duration` alongside. Adding `duration` to the Protocol is a one-line
   change and needs no new bookkeeping anywhere. SHA256 is genuinely new, and is the
   same provenance claim for a `.mpy` or a firmware binary that it is for a wheel.
2. **Append vs truncate is a real difference, not a style choice, and cibuildmp's may
   be the correct one.** `$GITHUB_STEP_SUMMARY` names one file per *step*, so upstream's
   `write_text` is safe precisely because one step runs cibuildwheel once. cibuildmp is
   invoked more than once per step in places — `build-examples.yml`'s own per-runner
   globs — and truncating would silently keep only the last table. This should be
   settled by looking at the real workflows before converging, and if append stays it
   belongs in "What should *not* converge" with that reason written down.
3. **The options block is the most valuable missing piece, and it is not free.** It is
   what makes a summary answer "what was this run *asked* to do", which no amount of
   result rows can. Upstream gets it from `Options.summary(skip_unset=True)`; cibuildmp
   has no equivalent renderer over its own resolved config, and writing one is its own
   piece of work — a `build`/`skip` glob plus the `[override]` entries that actually
   matched, at minimum. Note this is also the only reason upstream needs
   `filter_ansi_codes()` at all: the options dump is the one coloured thing that reaches
   the file.

The heading is worth one deliberate departure either way: upstream puts no counts in it
because the footer carries them, and a bare `### 🎡 cibuildwheel` reads better when
several actions each append their own section to one run's Summary page. cibuildmp's
current heading front-loads the same facts instead. Copying upstream means moving them
to a footer, and that is a choice to make on purpose rather than by transcription.

Finally, this is the strongest argument yet for the merge the previous section
proposed: every column upstream has and cibuildmp lacks is already accumulated by the
build loop, and upstream reaches all of it because the step summary and the terminal
summary read the *same* `list[BuildInfo]`. Keeping `stepsummary.py` a separate module
fed by its own `Sequence[_Result]` argument is exactly what makes each new column a
second plumbing job.

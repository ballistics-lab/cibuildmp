# 0048 — `build`/`skip` live in opposite tables in the two modes, and a misplaced one is silent

Status: Fixed 2026-08-26 -- top level is canonical in both modes, and a
misplaced or misspelt key in a mode table is now an error. See the resolution
at the end.

Found while implementing [0045], and specifically *because* of it: a test named
`test_only_overrides_skip` was passing against code that could not override
`skip`. It was passing for a reason that turned out to be a bug of its own.

## The behaviour

Verified live, four runs against a real config:

| where `skip` is written | natmod | usermod |
| --- | --- | --- |
| top level, above `[natmod]`/`[usermod]` | **applied** | **silently ignored** |
| inside the mode's own table | **silently ignored** | **applied** |

The same key means the same thing in both modes and is read from opposite
places, and putting it in the other one produces no error, no warning, and no
diagnostic of any kind — just a target you asked to skip getting built.

## Why

`natmod/options.py`'s `Options.load()` resolves global keys through a local
`opt()` that reads the **top-level** table:

```python
def opt(key, default=None):
    env_value = environ.get("CIBMP_" + key.replace("-", "_").upper())
    if env_value is not None:
        return env_value
    return raw.get(key, default)
...
build=parse_selector(opt("build", "*")),
skip=parse_selector(opt("skip", "")),
```

`usermod/options.py` reads the **mode table**:

```python
build=parse_selector(usermod.get("build", "*")),
skip=parse_selector(usermod.get("skip", "")),
```

Neither is unreasonable alone. Together they are a trap, and one line above the
natmod pair makes it worse:

```python
archs_value = opt("archs") or natmod.get("archs") or list(NATMOD_ARCHS)
```

`archs` accepts **both** placements. So a natmod user who writes
`[natmod] archs = [...]` — which works — has every reason to expect
`[natmod] skip = "..."` next to it to work too. It does not.

## What it cost already

`tests/test_cli.py::test_only_overrides_skip` built its config as
`CONFIG + '\nskip = "*-armv6m"\n'`, where `CONFIG` ends inside `[natmod]`. The
skip therefore landed in the mode table, was never read, and the test asserted
that `--only` overrode a selector that was never applied. It passed for years
of commits while testing nothing, and it was the *only* coverage of that
interaction — which is how [0045] came to describe the override as missing while
a green test claimed it worked. Both are now written with the selector where it
is actually read, and say so.

That is the real damage here: not a user hitting it, but a test that looked like
coverage and was not.

## What to do

Not fixed in this record, because "which placement is correct" is a decision
rather than a repair:

- **Accept both, everywhere.** Cheapest, matches what `archs` already does for
  natmod, breaks nothing. Also entrenches an ambiguity.
- **Pick one and diagnose the other.** cibuildwheel has no equivalent question
  — it is single-mode, so `build`/`skip` are simply top level (`CIBW_BUILD` /
  `CIBW_SKIP`, [tool.cibuildwheel]). By that argument top level wins, since
  `micropython`, `output-dir` and `build`/`skip` are all invocation-wide rather
  than mode-specific. usermod would then need a deprecation path, since its
  current placement is the working one for every existing usermod config.
- **Whichever is chosen, the wrong placement must not be silent.** An unknown
  key inside `[natmod]`/`[usermod]` is cheap to detect and is the part that
  turns a typo into a wrong build.

Worth checking at the same time: which *other* keys have this split. `archs` is
already known to be dual-read for natmod; nothing has audited the rest.

[0045]: 0045-only-is-a-filter-not-a-forced-identifier.md


---

## Resolution, 2026-08-26

Both halves, and one adjacent defect the audit turned up.

### Top level is canonical, in both modes

Of the three options above, **"pick one and diagnose the other"** was chosen,
and top level is the one. The argument the record already made stands on what
these keys *do*: `build`/`skip` filter identifiers, and an identifier names one
whole invocation's worth of work rather than anything mode-specific — the same
reason `micropython` and `output-dir` were already top-level in both.
cibuildwheel, single-mode and so never forced to choose, puts its own
equivalents in exactly that place.

The deprecation path the record worried about turned out to be nearly empty. A
sweep of every `cibuildmp.toml` in reach found **no config using `[usermod]
build`/`skip` at all** — this repo's own has both at the top level already, and
`examples/template` has neither. The old placement still works and prints a
warning naming the new one; when both are written the top level wins.

The warning goes to **stderr**, which is not a detail: `--print-build-identifiers`
and `--print-build-matrix` write machine-readable output to stdout, and
`cibuildmp-matrix`'s own action calls `json.loads()` on it. A deprecation notice
there would not be clutter, it would corrupt a CI matrix. Caught by an existing
test asserting the exact stdout of a `--print-build-identifiers` run — the same
test file the original bug had already damaged once.

### A key in the wrong table is an error

`check_table_keys()` validates `[natmod]`, `[usermod]`, `[usermod.<port>]` and
`[[overrides]]`. Two messages, because they are two different mistakes:

- a key that belongs at the top level says so and names the line to move it
  above — "unknown key `skip`" would be actively misleading about a key the
  tool knows perfectly well;
- anything else lists what the table does read.

An error rather than a warning, because the failure being replaced is a
*successful build of the wrong thing*. Three real traps it now catches, beyond
the one this record was written about: `module-dr` for `module-dir`, `arch` for
`archs` inside `[usermod.unix]` (which silently built the entire default axis
instead of the one cell asked for), and `arch-flags` inside `[[overrides]]` —
that last one already documented as impossible in `design.md`'s own schema
comment ("this cannot be set per-`[[overrides]]`, only here") and until now
enforced nowhere.

`archs`/`arch-flags` stay dual-read for natmod and are not flagged. That
predates this record and is not the trap: both placements work, so neither is
silent. There is a test asserting the new check did not quietly take it away.

### The audit's own finding: usermod ignored the environment

The record's closing line asked which *other* keys had this split. One does, and
it is the same defect one layer up rather than a variant: `usermod/options.py`'s
module docstring stated that `micropython`/`output-dir` were read "the same
env-aware way `options.py`'s own `opt()` does", and the code read `raw` directly
and consulted no environment at all. So `CIBMP_MICROPYTHON` and
`CIBMP_OUTPUT_DIR` worked in natmod mode and silently did nothing in usermod
mode, with the file's own documentation claiming otherwise. Fixed here, since
code disagreeing with its own docstring is the strongest possible signal about
which of the two was intended.

### And `UsermodConfigError` was never caught

`usermod/cli.py` caught `UnknownPortError` and `UnknownAxisError` and not this
one, so it surfaced as a raw traceback. It had gone unnoticed because until now
it had exactly one raise site — a `[usermod.<port>]` table for a port with no
axis yet — that nothing had reached from the CLI. Every misplaced or misspelt
key raises it now, and a config mistake is the most ordinary error this tool
has, so it exits 2 with one line like everything else.

Eleven tests, across `test_options.py` and `test_usermod_options.py`; every
path also run against the real CLI on real configs.

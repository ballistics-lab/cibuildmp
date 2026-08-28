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
build = (parse_selector(opt("build", "*")),)
skip = (parse_selector(opt("skip", "")),)
```

`usermod/options.py` reads the **mode table**:

```python
build = (parse_selector(usermod.get("build", "*")),)
skip = (parse_selector(usermod.get("skip", "")),)
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

---

## Addendum, 2026-08-26 — the partition doesn't generalise, a cascade does

Surfaced while designing [0051]'s points 4/6 (`--platform` becomes the port,
`natmod` alongside `unix`/`windows`/`qemu`/`webassembly`/`esp32`, six
structurally identical platform tables instead of two modes). This record's
own fix — every key has exactly one correct location, every other location is
a loud error — does not generalise cleanly to six platforms that need to
share option keys (`module-dir`, `manifest`, `extra-make-args`): either every
platform table repeats an identical value, or a bespoke "these specific keys
are shared, these are not" rule gets invented per key, which is this record's
own trap again in a different shape.

Read from `cibuildwheel/options.py` directly, not recalled: upstream never
partitions. `Options.get()` resolves every option as a **cascade** —
`default → global config → platform config → environment → CLI`,
most-specific-wins, and nothing is an error to place at any layer. There is
no "wrong location" for the cascade to protect against, because every
location is a real, meaningful layer.

**This is not a reversal of this record's own reasoning — it is a more
general way to satisfy the same constraint.** The actual guarantee this
record cared about was never "a key has one true home"; it was "a misplaced
key must never silently do nothing." A cascade satisfies that differently:
there is no placement left that silently does nothing, because every
placement is *some* layer that genuinely applies (global as every platform's
own default, platform as that one platform's override). What the cascade
does still need, and gets, is this record's other real finding — a key
**unknown to every schema at once** (a typo, `module-dr` for `module-dir`)
must still be a loud error. `cibuildmp/options.py`'s own `known_option_names()`
(the union of every platform's own keys plus the generic ones) and
`check_known_keys()` are that check, replacing `TOP_LEVEL_ONLY_KEYS`/
`NATMOD_TABLE_KEYS`/`USERMOD_TABLE_KEYS`/`check_table_keys()`'s
placement-specific error with a single "does this key exist anywhere"
check — `difflib`-suggested close matches, the same upstream already does in
`_validate_global_option()`.

`archs`/`arch-flags`'s own dual-read exception (natmod, predating this
record) stops being an exception under a cascade — it was always just the
platform layer overriding the global one, the general case, not a special
carve-out for two keys.

Not yet wired to real config loading — `cibuildmp/options.py` (the cascade
mechanism) landed standalone and unit-tested; `natmod/options.py`/
`usermod/options.py` still read config exactly as this record's own
resolution describes until [0051]'s later phases migrate them. See that
record's own addendum for the full phased plan.

**Wired, 2026-08-26 (the same day, [0051]'s own Phase F):** both modules
now resolve `module-dir`/`extra-make-args`/etc. through `Options.get()`,
bounded to the plain `default → global → platform → env` layers — not
`[[overrides]]`/`inherit`, which stay [0051]'s own "Phase G" ([0051]'s
fourth addendum has the full account). `check_table_keys()` itself is
retired in favour of `check_known_keys()` plus a small per-module
`check_keys()` wrapper that still gives the "this belongs at the top
level" message this record's own resolution introduced, now also with a
`difflib`-suggested close match for a genuine typo.

**`[[overrides]]`/`inherit` wired too, the same day ([0051]'s own Phase
G):** this record's own guarantee — a misplaced or unknown key is a loud
error, never a silent no-op — now covers the merged, shared
`[[overrides]]` list specifically, re-verified once more under the
cascade: a key valid on some platform's own schema but written inside an
override that only ever matches a *different* platform's identifiers is
still rejected, checked at `build_options()` resolution time once the
matched identifier's own platform is known ([0051]'s fifth addendum has
the full account, including a real "raw traceback instead of a clean CLI
error" bug this phase's own live testing found in both `natmod/cli.py`
and `usermod/cli.py`, unrelated to the cascade itself, and fixed the same
day).

[0051]: 0051-usermod-identifiers-have-no-version-axis.md

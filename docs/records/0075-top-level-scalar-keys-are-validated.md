# 0075 — an unrecognised top-level scalar key is an error, not a silent default

- Status: Implemented
- Related: [0048], [0051], [0052], [0074]

## What was wrong

[0074] found this while checking a claim it did not set out to change.
`design.md` asserted that writing `micropython = "v1.29.0"` (or any other
unrecognised **scalar** key) at the bare top level is "a plain unknown-key
error." Checked directly against `Options.load()`/`UsermodOptions.load()`: it
was not. Neither validates the top-level scalar keyset at all — `check_known_keys()`
and `known_option_names()` had been sitting in `cibuildmp/options.py` since
[0051]'s Phase E, defined and never called from anywhere. [0074] corrected the
sentence and left the hole open, on the grounds that it was a separate gap.

It is the same gap [0048] exists to close. [0048]'s own original bug was a `skip`
placed in the wrong table being silently ignored, so a misplaced key produced a
successful build of something you had asked *not* to build. An unrecognised
scalar key does exactly that, one level up: the option is read as absent, its
default applies, the run succeeds, and nothing anywhere says the line you wrote
did nothing. The specific shape this bites is not hypothetical — `micropython =`
was a real key [0052] retired, and a config still carrying it got no complaint.

Found alongside it, and the same class: `_validate_top_level_tables()` tested
`isinstance(value, dict)`, which is `[name]` but not `[[name]]`. A stray
`[[stm32]]` parses to a list of dicts and so was invisible to that check.
Neither of this project's own two real tables uses array-of-tables syntax
(`[override]` is keyed directly by its glob, `[override."<glob>"]`, deliberately
unlike cibuildwheel's own `[[tool.cibuildwheel.overrides]]`), so nothing real
depended on the narrow test — but with the scalar check added, `[[stm32]]` would
have been reported as an unknown *key* rather than an unknown table.

## The fix

- **`cli.py` gains `_validate_top_level_keys()`**, a sibling to the existing
  table check and called immediately after it, at the one point that already
  reads the config once for every family. It builds its keyset with
  `known_option_names()` over `FAMILIES` — no key list written out locally, so
  a third family ([0022]'s zephyr, or any of upstream's other ports) makes its
  own keys valid by declaring them, with zero edits to `cli.py`, the same
  property `_resolve_all()` already has.
- **Each family module exposes `OPTION_KEYS`**, added to the `PlatformModule`
  Protocol's own documented surface: `natmod` unions `GENERIC_KEYS`,
  `NATMOD_OVERRIDE_OPTION_KEYS` and `arch-flags`; `usermod` unions
  `GENERIC_KEYS` and `USERMOD_ONLY_GENERIC_KEYS`. The union is fourteen keys,
  and it was derived by reading every real `opt(...)`/`cascade.get(...)` call in
  both `load()` implementations rather than from the schema constants alone —
  which is how `arch-flags` was caught: global-only by construction, so it
  belongs to no override-surface set and would have been rejected as unknown.
- **`check_known_keys()` gains `error=`**, the convention `matching_overrides()`
  and `check_selector_reachable()` in the same module already follow. Without
  it the check raised `cibuildmp.options.ConfigError`, which nothing catches —
  each family owns its own hierarchy, and `cli.py` catches the `natmod.options`
  one around the sibling table check. Caught by running it, not by review: the
  first version printed a traceback instead of `cibuildmp: error: ...`.
- **`_is_table()`** replaces the bare `isinstance(value, dict)` test in both
  validators, so `[[name]]` is judged as a table by the table check rather than
  as a key by the scalar one. `and value` is load-bearing: an empty list is
  `extra-make-args = []`, a real scalar option, and an array of tables is never
  empty.

The error carries `difflib`'s close-match suggestion that `check_known_keys()`
already had and no caller had ever exercised — the same
`get_close_matches(cutoff=0.7)` upstream's own `_validate_global_option()` uses:

```
cibuildmp: error: cibuildmp.toml: unknown key `buidl`. Perhaps you meant `build`?
cibuildmp: error: cibuildmp.toml: unknown key `micropyton`.
```

## Verified

417 tests pass (five new: the unknown key, the suggestion, every one of the
fourteen valid keys accepted together, `[[stm32]]` reported as a table,
`[publish]`/`[override]` not mistaken for scalars). Every real config in reach
still resolves to exactly the identifier count it did before — this repo's own
root config (10), `examples/template` (24), `examples/natmod` and
`examples/usercmodule` (0 each, by design; their CI passes `--build`), `a7p`'s
`micropython/` (22) and `micropython-bclibc`'s (22).

One doc consequence, listed here because [0073] is about exactly this failure
mode: `design.md`'s config-schema section described this gap as open, and was
rewritten in the same change rather than left to be found later.

[0022]: 0022-zephyr-third-selector-axis.md
[0048]: 0048-build-skip-live-in-opposite-tables.md
[0051]: 0051-usermod-identifiers-have-no-version-axis.md
[0052]: 0052-config-is-a-tree-not-a-selector-matrix.md
[0073]: 0073-composite-actions-are-a-permanent-legacy-fallback.md
[0074]: 0074-usermod-family-table-and-retired-table-messages-removed.md

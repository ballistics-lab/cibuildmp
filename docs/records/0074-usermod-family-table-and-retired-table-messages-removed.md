# 0074 — `[usermod]` removed outright; the six other retired tables lose their dedicated migration message too

- Status: Implemented
- Related: [0048], [0051], [0052], [0073]

## What was wrong

`[usermod]` (record [0051]'s ninth addendum) was a shared-defaults tier for every
usermod port at once, kept alive through every later round of config retraction
"at the user's own explicit insistence" — [0052]'s own live-caught retraction removed
every per-platform table (`[unix]`, `[esp32]`, ...) but left this one standing on
principle. Checked directly against this repository's own real configs, not
recalled: **no real config anywhere in this project's examples ever actually wrote
`[usermod]`.** `examples/template/cibuildmp.toml` says so in its own header comment
("No `[usermod]` table here, deliberately... user-c-modules defaults to `.`"), and
the root `cibuildmp.toml`'s own reference config never uses it either. The mechanism
that survived on explicit insistence never had a real caller behind that insistence.

Separately, `cli.py`'s `_RETIRED_PLATFORM_TABLES` gave `[natmod]`/`[unix]`/`[windows]`/
`[qemu]`/`[webassembly]`/`[esp32]` each a dedicated, hand-written "no longer exists,
move X here instead" error message — real, load-bearing infrastructure when those
tables were genuinely retired out from under real configs micropython-bclibc/
micropython-wasm3/a7p had written by hand. All three have since fully migrated
(tracker [0038]) onto the current `build`/`skip`/`[override]` model; nothing live
depends on the specific wording of that migration message any more either.

## The fix

- `[usermod]` removed entirely: `check_usermod_family_table()`, `USERMOD_PLATFORM_KEYS`,
  and the `family_table` parameter threaded through `cibuildmp.options.Options`/
  `OptionCascade` are all deleted — there is no family-tier cascade layer left at all,
  only `default -> global -> env -> extra_layers`. `PlatformModule`'s
  `validate_family_table()` contract method is gone from the Protocol and both
  implementations (`natmod`'s no-op, `usermod`'s real one).
- No replacement migration message was written for `[usermod]` — since no real config
  ever used it, there is nothing to migrate. A stray `[usermod]` table now falls
  through to `cli.py`'s ordinary "unknown table(s) at the top level" error, the same
  one a typo like `[stm32]` gets.
- The same treatment was extended to the six real, historically-used tables:
  `_RETIRED_PLATFORM_TABLES` and its dedicated per-table message are deleted from
  `cli.py`, along with natmod's own direct `if "natmod" in raw: raise ...` guard in
  `Options.load()`. `[natmod]`/`[unix]`/`[windows]`/`[qemu]`/`[webassembly]`/`[esp32]`
  are now unrecognised top-level tables like any other — still a loud `ConfigError`
  via the CLI (`_validate_top_level_tables()`'s generic branch), just without a
  per-name explanation of what to do instead.
- `docs/reference/design.md`'s "Positioning"/"Config schema" sections, the root
  `cibuildmp.toml`, and `examples/template/cibuildmp.toml` all had prose or comments
  describing `[usermod]` as current, load-bearing config, or citing the specific
  retired-table error wording — all rewritten to describe today's flat, single-tier
  model instead.

## A gap this round did not touch, found while checking the claim

`design.md` previously claimed writing `micropython`/`mpy-abi` (or any other
unrecognised **scalar** key) at the bare top level is "a plain unknown-key error."
Checked directly against `Options.load()`/`UsermodOptions.load()`: neither validates
the top-level scalar keyset at all (`check_known_keys()`/`known_option_names()` in
`cibuildmp/options.py` are defined but never called from either). An unrecognised
scalar key is today silently absent, not flagged — a real, separate gap, corrected in
`design.md`'s own text rather than left to repeat the claim, but not closed here.

[0048]: 0048-build-skip-live-in-opposite-tables.md
[0051]: 0051-usermod-identifiers-have-no-version-axis.md
[0052]: 0052-config-is-a-tree-not-a-selector-matrix.md
[0073]: 0073-composite-actions-are-a-permanent-legacy-fallback.md

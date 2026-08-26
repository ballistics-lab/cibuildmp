# 0052 — cibuildmp's config space is a tree, not a selector matrix; the divergence from cibuildwheel is deliberate

Status: Proposed — the divergence itself is argued and decided; the concrete
mechanism (TOML shape, override resolution, migration from
`[[overrides]]`/flat sibling tables) is **not yet designed**. Needs its own
dedicated Explore/Plan pass before any code changes. Not scheduled.

## Where this came from

Surfaced while closing out record [0051]'s own last open items (the
`module-dir`/`user-c-modules` rename, the `[usermod]` family cascade tier),
in the same session, through direct, repeated user pushback that exposed a
gap this record's own earlier reasoning had not examined: every one of
[0051]'s phases (E through the ninth addendum) extended cibuildmp's
existing model — a flat identifier string, `build`/`skip`/`[[overrides]]`
as glob selectors over it, a cascade of increasingly specific *tables* — 
without ever asking whether that model, borrowed directly from
cibuildwheel, actually fits what cibuildmp's own axes look like.

The question that broke it: "чому ми не знаємо простору ідентифікаторів"
(why don't we know the identifier space) led to finding that
`resources/natmod.toml`'s own `[mpy-abi]` table already resolves
identifiers without a checkout — which led to asking why `micropython`
still needs its own key instead of being foldable into `build`/`skip` —
which led to noticing that `micropython`, `build`, `skip`, `extra-files`
and several other keys are read once, globally, with no family- or
platform-level override at all, unlike `user-c-modules`/`manifest`/
`extra-make-args`, which the same session had just given a real cascade
tier. Asked directly why the config surface for that gap looked the way
it did, the user sketched a genuinely different shape rather than another
cascade tier bolted onto the existing one — and then, challenged on
whether this diverges from cibuildwheel's own real model (verified this
session, directly, from `cibuildwheel/options.py`: a flat matrix and glob
selectors over a flattened identifier, no tree), confirmed it directly:
*"Якщо у cibuildwheel це матриця, то в нас це tree"* ("If in cibuildwheel
it's a matrix, then in ours it's a tree").

## The diagnosis: cibuildmp's own axes were never actually orthogonal

Upstream's matrix model works because upstream's own axes genuinely are a
full cross product: `cp39`/`cp310`/`cp311`/... × `manylinux`/`macosx`/
`win` × `x86_64`/`arm64`/... — every combination is at least meaningful,
and `build`/`skip` selecting arbitrary sub-rectangles of that grid via a
glob over the flattened `cp311-manylinux_x86_64` string is a natural fit
for a genuinely rectangular space.

cibuildmp's own "axes" have never been that shape, verified directly
against the real schemas this session built:

- `boards` is only ever meaningful for `esp32` — `unix`/`windows`/`qemu`/
  `webassembly` have no board axis at all.
- `variant` is a real field on three of five usermod ports' own
  `*BuildOptions`, config-surface-less on the other two.
- `arch-flags` (rv32imc's own `+0x..` suffix) is only meaningful for one
  of natmod's own ten arches.
- natmod and usermod have almost entirely disjoint option-key schemas
  (`NATMOD_SCHEMA` vs. `USERMOD_PORT_BASE` plus each port's own axis key)
  — record [0051]'s own ninth addendum's `FAMILY_SCHEMA` collision-guard
  idea exists specifically because two *families'* schemas could
  theoretically collide, which would never be a meaningful question in a
  genuinely rectangular matrix.

The identifier string (`mpy6.3-natmod-x64`, `v1.29.0-unix-manylinux_2_28_x86_64`)
was always a **flattened projection of a tree** (family → platform →
sub-axis value), not a native point in a rectangular space — `build`/
`skip`/`[[overrides]]`'s own `select` glob have been matching against
that flattened string the whole time, which is why key-collision
questions (`module-dir` meaning two different things to two different
downstream consumers, [0051]'s sixth addendum), where-does-this-key-live
questions (record [0048], then [0051]'s own cascade), and now
which-tier-does-this-key-resolve-at questions (this record) keep
recurring in slightly different shapes: they are all symptoms of forcing
a tree through a flat, string-matched interface.

## The proposed shape (sketch, not a finished design)

Nested tables return — a direct, deliberate reversal of record [0051]'s
own Phase F decision to flatten `[usermod.<port>]` into sibling top-level
tables, done for different reasons than the shape Phase F removed. Phase
F's own nesting was a *mode* table (`[usermod]` selected a build mode;
`ports = [...]` inside it selected which ports); this nesting is a *tree
address* (`[usermod.unix]` names a real node — the `unix` platform,
inside the `usermod` family — the same way a filesystem path names a
node, not a selector deciding whether that node exists).

```toml
[usermod]
build = "..."
skip = "..."
extra-files = [...]          # family-wide defaults for every usermod port

[usermod.unix]
variant = "..."
# [[overrides]] or an equivalent here target this branch specifically

[usermod.webassembly]
variant = "..."

[usermod.esp32.some_board]
# a board is itself a further node under esp32, not a value on an axis

[natmod]
build = "..."
skip = "..."
extra-files = [...]

[natmod.x64]
# arch-specific overrides live at this node directly

[zephyr]
build = "..."
skip = "..."
extra-files = [...]

[zephyr.some_board]
```

The headline change this implies: **skip and override act on a branch of
the tree, not on a glob pattern over a flattened string.** `[natmod.x64]`
*is* the natmod/x64 branch; writing values there (or a `skip` scoped to
that node) is addressing a real position in the config's own structure,
not hoping a `select = "*-natmod-x64"` glob matches the right flattened
string. Whether `[[overrides]]`'s own list-of-tables-with-a-`select`-glob
survives in any form, or is fully replaced by tree-position addressing,
is one of the open design questions below.

## What is decided, and what is not

**Decided:** the matrix-plus-glob-selector model, inherited directly from
cibuildwheel, does not fit cibuildmp's own genuinely non-rectangular axes,
and this is a deliberate, argued divergence from upstream's own real
shape (verified against `cibuildwheel/options.py` directly this session,
not assumed) — not an oversight to reconcile back toward cibuildwheel
later. CLAUDE.md's own standing instruction is explicit that a deliberate
divergence "must be argued in a record, not left implicit"; this record
is that argument.

**Not decided, and explicitly not scoped into this session:**

- The exact TOML shape beyond the sketch above — how deep can nesting go
  (`[usermod.esp32.some_board]` is three levels; does every family need
  that, or is it esp32-specific), and how a board name with characters
  TOML's own bare-key syntax cannot express (spaces, e.g. "some board")
  gets written.
- Whether `[[overrides]]`'s own `select`-glob mechanism is retained
  alongside tree addressing (for cross-branch matches a tree position
  cannot express, e.g. "every arch ending in `emsp`" spanning several
  `[natmod.<arch>]` nodes), replaced entirely, or kept only for the cases
  a tree genuinely cannot address.
- How this interacts with record [0051]'s own freshly-built `family_table`
  cascade tier (`default → global → family → platform → env → CLI`) --
  does a tree subsume that cascade, coexist with it, or turn each
  cascade tier into one tree depth level directly.
- Migration story for every existing flat-sibling-table config (this
  repo's own `cibuildmp.toml`, `examples/template/cibuildmp.toml`,
  `examples/wasm2mpy/cibuildmp.toml`) and every test fixture --
  potentially as large as record [0051]'s own Phase F migration, which
  flattened the tree Phase F itself had inherited from before this
  project's own start.
- Whether this is one phased migration (mirroring [0051]'s own E-through-I
  structure) or a wholesale rewrite, and how it sequences against [0038]
  (adopting cibuildmp in the three consuming repos) -- another
  identifier/config-shape change lands *after* this one, or this one
  lands and settles before [0038], the same ordering argument the tracker
  already makes for [0051] itself.

## Why this is its own record, not folded into [0051]

[0051]'s own scope (recapped in its own Status line) is "one selector for
both modes, and an identifier that names what a build is compatible
with" -- real, and fully landed. This record's own scope is a different,
larger question: whether the selector/override *mechanism itself*, not
just the identifier shape or the config-tree flatness, is the right one
at all. Treating it as [0051]'s own ninth-plus addendum would understate
its size (on the order of [0051]'s own Phase F+G combined, by the
user's and this record's own estimate) and would misfile a genuinely new
architectural question under a record whose own investigation is already
closed.

[0038]: 0038-m5-adopt-in-three-repos.md
[0048]: 0048-build-skip-live-in-opposite-tables.md
[0051]: 0051-usermod-identifiers-have-no-version-axis.md

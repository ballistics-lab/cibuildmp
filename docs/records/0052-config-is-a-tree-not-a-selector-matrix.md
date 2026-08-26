# 0052 — cibuildmp's config space is a tree, not a selector matrix; the divergence from cibuildwheel is deliberate

Status: Proposed — the divergence itself is argued and decided, and a wide
follow-up chat session (2026-08-26, same day as [0051]'s own ninth
addendum) settled several concrete sub-questions along the way: natmod's
own identifier grammar (`{tag}-mpy{major.minor}[-{arch}][+0x{flags}]`,
dropping the literal word `natmod`), that usermod's own identifier needs
no equivalent change, a `{name}-{version}-` artifact-filename prefix (two
new/extended global config keys), a pre-build companion to `verify_output()`'s
own post-build audit, and a correction to [0013] (byte-identical is false,
functional interchangeability is real and now verified) — all written up
below and in [0013]'s own addendum. **The tree/matrix mechanism itself —
TOML nesting depth and syntax, whether `[[overrides]]`'s own glob `select`
is fully replaced by path-globbing or keeps a residual flattened-string
fallback, migration from today's flat sibling tables — is still not
designed.** Needs its own dedicated Explore/Plan pass before any code
changes. Not scheduled. No code has changed as a result of this record;
everything below is documentation for whichever session picks this up
next.

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

## Confirmed against upstream, not assumed: MicroPython's own build tree is real, and unsolved by MicroPython itself

The user's own claim — that MicroPython's own `ports/` layout already is
a tree, and upstream itself has never built a unified model over it,
covering it instead with a patchwork of independent workflows — checked
directly against a real clone of `micropython/micropython`
(`.github/workflows/`), not recalled or assumed, the same discipline this
project's own CLAUDE.md demands for cibuildwheel:

- **28 workflow files total; 16 of them are literally `ports_<name>.yml`**
  — `ports_esp32.yml`, `ports_unix.yml`, `ports_stm32.yml`,
  `ports_zephyr.yml`, `ports_rp2.yml`, and eleven more, one per port,
  each independently authored.
- **No shared selector model ties them together.** `ports_esp32.yml`
  has its own bespoke matrix (`idf_ver` × `ci_func`, read from
  `tools/ci.sh`'s own port-specific functions) with no structural
  relationship to any other port's own workflow. `ports.yml` (no port
  suffix) is not a unified entry point either — it only builds download
  metadata (`tools/autobuild/build-downloads.py`), unrelated to
  selecting or running builds at all.
- `ports/` itself — `alif`, `esp32`, `esp8266`, `mimxrt`, `nrf`, `qemu`,
  `renesas-ra`, `rp2`, `samd`, `stm32`, `unix`, `webassembly`, `windows`,
  `zephyr`, plus `bare-arm`/`minimal`/`embed`/`cc3200`/`pic16bit`/
  `psoc-edge` — is a real directory tree today, boards nested further
  inside several of them (`ports/esp32/boards/<BOARD>/`), with no
  cross-port config format at all; each port's own build is invoked its
  own way, in its own workflow, by convention rather than by any shared
  mechanism.

This matters for this record's own argument beyond "the divergence from
cibuildwheel is justified": it means a working tree-shaped selector
model in cibuildmp would not be reinventing something upstream already
solved elegantly and cibuildmp is choosing to diverge from anyway — it
would be solving a real problem upstream MicroPython's own CI has never
addressed at all, having accreted 16+ independent workflows instead.
That is a stronger claim than "our axes don't happen to be rectangular";
it is "the tree already exists as upstream's own real structure, nothing
upstream or cibuildwheel has ever modeled it as one, and this project is
positioned to be the first thing that does."

## Identifier grammar for natmod (decided, 2026-08-26)

A separate, narrower thread of the same session's conversation, starting
from a direct question ("mpy зібраний з 1.29 не працюватиме на 1.28?") and
resolved through direct experiment rather than argument, landed a concrete,
decided grammar for natmod's own identifier — independent of the tree/
matrix question above, but feeding the same record because it changes what
a tree node's own leaf identifier looks like.

**The tag becomes a real, leading, visible identifier component.**
Today's identifier (`mpy{abi}-natmod-{arch}[+0x{flags}]`) deliberately
excludes the tag — `natmod/targets.py`'s own `Target.tag` field comment
says so explicitly: "not part of the identifier (that's ABI, the
compatibility axis)". That exclusion rested on D13's own claim that
same-ABI tags produce byte-for-byte identical output, so which one was
used is inert. **Tested directly this session, not assumed — see [0013]'s
own addendum for the full experiment — the claim is false**: `v1.28.0`
and `v1.29.0` (both ABI 6.3) produce different-sized, different-hashed
`.mpy` output from byte-identical source, because `tools/mpy_ld.py`'s own
x64 GOT-jump encoding changed between the two tags with no `MPY_VERSION`/
`MPY_SUB_VERSION` bump. **Functional/load compatibility is still real and
independently verified** (a live cross-load test: both tags' `unix`
binaries loaded and correctly ran both tags' `.mpy` output, all four
combinations) — so the practical dedup-by-ABI *decision* D13 made stays
correct, but the *reason* to keep `tag` invisible does not: which tag
actually built a given artifact is real information (reproducibility,
audit, "why does this specific file differ from that one built last
week"), even though it does not gate whether the artifact loads.

Decided shape: **`{tag}-mpy{major.minor}[-{arch}][+0x{flags}]`** — tag
leads unconditionally, the same position and the same "not conditional"
reasoning [0051] already gave usermod's own leading tag (a component that
only appears sometimes makes `build = "*-v1.29.0"` match in some configs
and not others). `natmod` itself is dropped as a literal word: `mpy` is
already a natmod-exclusive prefix (no usermod identifier has ever started
with it), so spelling out `natmod` too is exactly the redundancy a wheel
tag avoids by never writing `cpython` next to `cp311` — the prefix already
says which family this is, matching wheel's `{python_tag}-{abi_tag}`
convention where the interpreter family is implied by the tag's own
letters, not restated. `arch_flags`, when present, stays attached to
`{arch}` (`rv32imc+0x1`), not to the abi component (`mpy6.3+0x1`) — flags
are conditionally meaningful only for one arch family
(`MPY_FEATURE_ARCH_TEST(MP_NATIVE_ARCH_RV32IMC)`, verified directly in
`py/persistentcode.c`), not a property of the ABI itself.

Example, module `mylib`, `tag=v1.29.0`, `x64`:
`mylib-v1.29.0-mpy6.3-x64.mpy` (today: `mylib-mpy6.3-natmod-x64.mpy`).
`rv32imc` with `arch_flags=0x1`: `mylib-v1.29.0-mpy6.3-rv32imc+0x1.mpy`.

**This does not reopen D13's dedup decision** — tag becomes visible for
provenance, not as a new generative axis: `micropython = ["v1.28.0",
"v1.29.0"]` (same ABI) still collapses to one build; the surviving tag is
now visible in the output rather than silently chosen. Whether a future
config should be able to opt into "one build per tag, dedup off" is a real
question this record does not resolve — noted as still open below.

**A second, narrower dedup gap found while checking this: `arch_flags`
needs the same treatment `micropython`/tag already gets, and does not have
it today.** Verified directly in `natmod/targets.py:natmod_targets()`:
`for flags in arch_flags` is a plain iteration over the *parsed* integer
list, with no dedup by value at all — `parse_arch_flags()` accepts several
textual spellings for the same bitmask (a bare numeric string in `0b`/
`0x`/decimal form, or comma-separated named flags), so
`arch-flags = ["0x3", "zba,zcmp"]` (if those two spellings resolve to the
same integer) silently produces **two** `Target`s with the identical
resolved `arch_flags` value, and therefore the identical identifier
(`mpy6.3-rv32imc+0x3` twice) — the second build's output silently
overwrites the first's, the exact collision class [0051] exists to
prevent for usermod releases and D13 exists to prevent for tags, just not
yet closed for this one list. Fix is the same shape as D13's own: dedup
`arch_flags` by its *resolved* integer value before constructing targets,
not by the raw config string — pre-build, config-load time, no checkout
needed (the parse is already pure). A real, small, well-scoped bug fix,
independent of the larger tree/matrix question this record is otherwise
about — worth landing on its own rather than waiting on 0052's own larger
scope.

`mpy-cross{tag}` and `micropython{tag}` were both considered and rejected
as prefixed alternatives to bare `{tag}`: usermod's own identifier
(`{tag}-{port}-{arch}`, [0051], already shipped) already uses bare tag
with no prefix, and giving natmod a prefixed form while usermod stays bare
would be a fresh, unargued asymmetry between the two families for the
same underlying axis (this session first established that the axis really
is the same concept in both — the "build environment", loosely analogous
to a wheel's `manylinux_*` floor rather than its Python ABI tag).

## usermod's own identifier needs no change (decided)

`UsermodTarget.identifier` (`{tag}-{port}[-{arch}]`, [0051], already
shipped) never said "usermod" in the first place — verified directly,
`targets.py:357-359` and every `GROUPS` glob (`f"*-unix-*_{arch}"`) already
address ports by their own unique names (`unix`/`windows`/`qemu`/
`webassembly`/`esp32`), none of which any other family uses. Nothing to
drop here, unlike natmod's own literal `-natmod-` above. `zephyr` ([0022],
not started) is flagged as a possible future exception — a board name
could collide with an esp32 board name from a different vendor, which
might justify a real `zephyr-`-prefix at that point, for family
disambiguation rather than for the reason natmod's own word was dropped.
Not decided now, not blocking.

## Artifact filenames: `{name}-{version}-{identifier}` (decided direction, two new config keys needed)

A gap this session found by working through concrete filename examples
for both families, not by abstract argument: `natmod`'s own
`output_name()` already includes a project name (`mylib-{identifier}.mpy`)
— but that name is not a config value, it is a side effect of whatever the
built module's own `.mpy` file happened to be called (`mpy_path.stem`,
itself derived from the user's own `Makefile`'s `MOD = ...`). `usermod`'s
own `_dest_name()` has **no project identity at all**: the produced
binary's own stem is always literally `"micropython"`/`"micropython.exe"`/
`"micropython.bin"` (`build.py:769,1081,1372`), regardless of which
project's `cibuildmp.toml` built it — two different projects' firmware
artifacts are indistinguishable by filename alone.

Decided direction, mirroring wheel's own `{name}-{version}-{python_tag}-
{abi_tag}-{platform_tag}.whl` (name+version lead, separately from the
compatibility-tag portion, which stays exactly the identifier grammar
decided above):

```
natmod:  {name}-{version}-{identifier}.mpy
         mylib-1.2.0-v1.29.0-mpy6.3-x64.mpy

usermod: {name}-{version}-{identifier}[.ext]
         mylib-1.2.0-v1.29.0-unix-manylinux_2_28_x86_64
         mylib-1.2.0-v1.29.0-windows-arm64.exe
```

`micropython` is dropped as a literal word from the usermod filename for
the same reason `natmod` was dropped from natmod's own identifier above —
the whole point of a usermod build *is* a MicroPython firmware, restating
it is noise a project name already displaces.

This needs two config keys, currently in different states:

- **`version`** already exists (`GENERIC_KEYS`, `opt("version", "")`,
  written into natmod's own `package.json`) — but natmod-only; usermod
  reads it never. Needs extending to a genuinely shared/global concept and
  wiring into `_dest_name()`.
- **`name`** does not exist anywhere as a config value, for either family.
  Needs adding as new.

Both are immediate, concrete instances of the `GENERIC_KEYS`-bypasses-the-
cascade gap this whole record already names below (`micropython`/`build`/
`skip`/etc., read through a separate `opt()` closure with no family/
platform override) — not a new problem, but two new members of an
already-identified one, worth listing explicitly so a future
implementation of the cascade fix doesn't have to rediscover that `name`/
`version` belong in it too.

## `arch_flags = 0` is a stable/broad compatibility class, not just "unset" (decided, worth documenting explicitly)

Verified directly in `py/persistentcode.c` (the *loader*, not cibuildmp's
own code): `if ((arch_flags & (size_t)asm_rv32_allowed_extensions()) !=
arch_flags)` — a **subset** check, file's flags must be a subset of the
device's own supported extensions, not an exact match. `arch_flags = 0`
is a subset of anything, trivially — a build with no flags set loads on
*any* rv32/rv64 device regardless of its actual extension set, while a
build with specific flags set only loads on devices that have at least
those bits. This is structurally identical to CPython's `abi3` (broad,
portable, potentially less optimized) versus a version/feature-specific
wheel (narrower, can use more) — not a loose analogy, a matching
mechanism. `natmod/build.py`'s own `verify_output()` already knows about
the asymmetry (its docstring names mip's own "required subset of
available" rule explicitly, contrasting it with the linter's own stricter
exact-match check) but nothing in cibuildmp's own docs or config surface
calls `arch_flags = 0` out as *the* portable/default-recommended choice
the way `abi3` is a well-known, named concept for wheel authors. Worth
fixing in whichever record documents the identifier grammar for users
(this one, or a design.md update) — not a mechanism change, a naming/
documentation one.

## Pre-build audit: `auditmpy`'s missing other half (decided direction, not implemented)

`verify_output()` is already, by its own docstring, "cibuildmp's
equivalent of auditwheel" — but only for the *post-build* half: does the
artifact the linker actually produced match what the config asked for.
Nothing today validates the *pre-build* half: does what the config asked
for (a `build`/`skip` pattern, a `[[overrides]]` table's own `select`)
even match anything the configured `micropython` list can produce, before
any checkout happens. Concretely, `micropython = ["v1.28.0"]` (ABI 6.3)
plus `select = "mpy6.2-*"` in an override compiles, loads, runs — and
silently never applies, the exact "misplaced config → silent no-op
instead of an error" bug class [0048] already exists to catch, just one
level down (a selector string, not a table key).

This is fully solvable offline, verified this session: every component of
the full compatibility class (`MPY_VERSION.MPY_SUB_VERSION` from
`natmod.toml`'s own `[mpy-abi]` pin table, keyed by tag — no checkout;
native arch code from the existing static `NATIVE_ARCH_CODE` mapping — no
checkout; `arch_flags` from the target's own config value — no checkout,
no device) is knowable before any build starts. (Background: this exact
composite is what MicroPython's own `sys.implementation._mpy` exposes at
runtime — `py/modsys.c`: `MPY_FILE_HEADER_INT | MPY_FILE_ARCH_FLAGS`,
`py/persistentcode.h`: `MPY_FILE_HEADER_INT = MPY_VERSION | (SUB_VERSION|
ARCH)<<8` — cibuildmp does not need a live device to compute it, only the
same formula over already-known, already-pinned inputs.) So a validation
pass, run right after tag/ABI resolution and before any checkout, that
checks every `[[overrides]]`/`build`/`skip` pattern against the fully
resolved, offline-computed identifier space and raises loudly on zero
matches, is buildable without new infrastructure — a real, scoped
follow-on, not a research question.

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
string.

**Refined directly by the user, closing what the paragraph above left
open:** the tree path itself *is* the selector -- the same way a
filesystem glob addresses a path, not a flattened string representation
of one. `[usermod.esp32]` (a literal config node) and a `select =
"usermod.esp32.*"`-shaped override pattern (matching every board under
it) are the same addressing scheme, not two separate mechanisms bolted
together -- one writes a concrete node, the other matches a set of nodes
by pattern, both walking the identical family/platform/sub-node path
space. `[[overrides]]`'s own `select` therefore does not need replacing
so much as re-pointing: from globbing a flattened identifier string to
globbing the tree path that identifier was always secretly a projection
of. What exactly the path syntax looks like (`.`-joined, matching TOML's
own nesting; `/`-joined; whether a single glob segment can span more
than one tree depth the way `**` does in a real filesystem glob) is still
open.

## What is decided, and what is not

**Decided:** the matrix-plus-glob-selector model, inherited directly from
cibuildwheel, does not fit cibuildmp's own genuinely non-rectangular axes,
and this is a deliberate, argued divergence from upstream's own real
shape (verified against `cibuildwheel/options.py` directly this session,
not assumed) — not an oversight to reconcile back toward cibuildwheel
later. CLAUDE.md's own standing instruction is explicit that a deliberate
divergence "must be argued in a record, not left implicit"; this record
is that argument.

**Also decided, this session, independent of the tree/matrix mechanism
itself** (each detailed in its own section above): natmod's identifier
grammar (`{tag}-mpy{major.minor}[-{arch}][+0x{flags}]`); usermod's own
identifier needs no change; the `{name}-{version}-{identifier}` artifact-
filename convention and the two config keys it needs; `arch_flags = 0` as
a named, documented stable/broad compatibility class; a pre-build
reachability audit as the missing other half of `verify_output()`; the
`arch_flags`-list dedup-by-resolved-value bug; and [0013]'s own
byte-identical-vs-functionally-interchangeable correction. None of these
require the tree mechanism to land first — each is independently
implementable, and a future session could pick any one off without
waiting on the others.

**One question raised but not resolved this session:** whether `tag`
becoming a real, visible identifier component should also make it a real
*generative* axis (one build per distinct tag, dedup off) rather than
keeping today's dedup-by-ABI with tag merely visible on the survivor.
[0013]'s own addendum leans toward keeping dedup (functional
compatibility is confirmed, not merely assumed, so there is no
correctness reason to build twice) — but this record does not treat that
as fully settled, since "the exact bytes shipped are provenance-
meaningful" (this record's own reasoning for making `tag` visible at all)
is in tension with "so don't bother producing more than one set of
bytes". Whoever designs the tree/matrix mechanism should resolve this
explicitly rather than let it default silently either way.

**Not decided, and explicitly not scoped into this session:**

- The exact TOML shape beyond the sketch above — how deep can nesting go
  (`[usermod.esp32.some_board]` is three levels; does every family need
  that, or is it esp32-specific), and how a board name with characters
  TOML's own bare-key syntax cannot express (spaces, e.g. "some board")
  gets written.
- ~~Whether `[[overrides]]`'s own `select`-glob mechanism is retained
  alongside tree addressing~~ -- resolved in principle: the tree path
  itself is the selector, `select` re-points from globbing the flattened
  identifier to globbing the tree path (`usermod.esp32.*` matching every
  board under `[usermod.esp32]`, the same way a filesystem glob matches
  a set of paths, not a set of flattened strings). What is still open is
  the exact path syntax (separator, whether a segment can span more than
  one depth the way `**` does) and whether every cross-branch match this
  session's own real `[[overrides]]` examples need (e.g. "every arch
  ending in `emsp`", spanning several `[natmod.<arch>]` siblings with no
  common parent narrower than `[natmod]` itself) is expressible as a
  path glob at all, or still needs a residual flattened-string fallback
  for genuinely cross-cutting matches a tree path cannot address.
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

## Landed records this touches, and records it does not

Written for whichever session picks this record up next, so it does not
have to re-derive which of the tracker's own 45+ "Implemented" rows are
actually in scope here and which are orthogonal plumbing this record has
no opinion about.

**Directly touched — identifier shape, config shape, or override
mechanism is exactly this record's own subject:**

- **[0051]** — the flat-sibling-table model (`[unix]`/`[windows]`/.../
  `[natmod]`) and its shared `[[overrides]]` glob-over-a-flattened-string
  mechanism are precisely what this record's own "proposed shape" argues
  should become tree-addressed instead. Not superseded yet (see the
  pointer added to [0051]'s own Status line) — only once this record's
  own mechanism actually lands.
- **[0048]** — `build`/`skip` top-level placement and per-table key
  validation. Already superseded once (by [0051]'s cascade, that record's
  own addendum); the tree model would touch it again (skip/override act
  on tree branches, not flat keys), and the `GENERIC_KEYS`-bypasses-the-
  cascade gap this record names is [0048]'s own original bug class,
  recurring in a new shape (`micropython`/`build`/`skip`/`name`/`version`
  read through a separate `opt()` closure with no override surface at
  all).
- **[0045]** — `--only` as an exact-match filter, `--archs auto/native/
  all` vocabulary. The *decision* (`--only` never globs, verified against
  real `cibuildwheel/__main__.py` this session) is unaffected and
  reaffirmed; the *strings* `--only` matches against change under the new
  identifier grammar (`{tag}-mpy{abi}-{arch}` instead of
  `mpy{abi}-natmod-{arch}`) — a mechanical follow-on, not a design
  question.
- **[0023]** — usermod's own identifier scheme and output convention.
  The identifier itself (`{tag}-{port}-{arch}`) is confirmed unchanged;
  its own filename convention gains the `{name}-{version}-` prefix this
  record adds, and loses the record's own use of `micropython` as a
  literal word in the produced filename.
- **[0015]** — `rv32imc`'s `ARCH_FLAGS=` is part of the identifier. Its
  own placement decision (attached to arch, not to ABI) is reaffirmed by
  this record's own reasoning, not overturned — but a real, previously
  unnoticed dedup gap in the same list (see above: two textual spellings
  of the same integer silently produce two identical-identifier targets)
  belongs to this record's own scope, not a new one.
- **[0014]** — one self-contained mip package per identifier,
  `package.json`'s own `urls`/`version` schema. `version` becoming a
  genuinely global (not natmod-only) key, plus the new `name` key, both
  feed this record's own `package.json` output.
- **[0013]** — corrected in its own addendum this session (byte-identical
  claim false, functional interchangeability confirmed instead); this
  record's own identifier-grammar section is what the correction's
  practical consequence (`tag` becomes visible) actually lands in.
- **[0005]** — "one identifier namespace, one override mechanism,
  `[[overrides]]` collapses three shapes into one." This record's own
  proposed shape is a second such collapse-and-generalize step, same
  spirit, later mechanism.
- **[0010]** — pinned data lives in `resources/`, not Python. Reinforced,
  not overturned: the pre-build audit section above depends entirely on
  `natmod.toml`'s own `[mpy-abi]` table already following this rule: a
  formalized `build-platforms.toml` (tracker's own pending note) is a
  direct extension of [0010]'s own principle to `esp32`/`zephyr` boards,
  not a departure from it.

**Everything else in "Implemented" is orthogonal — container/image
plumbing, host provisioning, toolchain resolution, CI mechanics, or
documentation structure, none of which this record's own tree/identifier/
cascade scope touches**: [0001]-[0004], [0006]-[0009], [0011], [0012],
[0016]-[0022], [0024]-[0043], [0049], [0050]. A future session does not
need to re-open any of these to work on this record — they stay exactly
as landed.

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

[0001]: 0001-natmod-first.md
[0004]: 0004-config-file-location.md
[0005]: 0005-one-identifier-namespace.md
[0006]: 0006-no-test-runners-phase1.md
[0009]: 0009-one-job-loop-fanout-opt-in.md
[0010]: 0010-pinned-data-in-resources.md
[0011]: 0011-one-repo-absorbs-micropython-native-ci.md
[0012]: 0012-pyelftools-ar-own-deps.md
[0016]: 0016-usermod-user-c-modules-dir-vs-cmake.md
[0022]: 0022-zephyr-third-selector-axis.md
[0024]: 0024-unix-armhf-mipsel-cross-compiles.md
[0043]: 0043-unix-adopts-cibuildwheel-native-image-model.md
[0049]: 0049-no-matrix-generation-archs-vocabulary.md
[0050]: 0050-natmod-is-docker-only.md
[0013]: 0013-micropython-list-dedup-by-abi.md
[0014]: 0014-mip-package-per-identifier.md
[0015]: 0015-rv32imc-arch-flags-identifier.md
[0023]: 0023-usermod-identifier-scheme-config-output.md
[0038]: 0038-m5-adopt-in-three-repos.md
[0045]: 0045-only-is-a-filter-not-a-forced-identifier.md
[0048]: 0048-build-skip-live-in-opposite-tables.md
[0051]: 0051-usermod-identifiers-have-no-version-axis.md

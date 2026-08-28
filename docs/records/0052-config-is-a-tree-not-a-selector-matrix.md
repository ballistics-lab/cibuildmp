# 0052 — cibuildmp's config space is a tree, not a selector matrix; the divergence from cibuildwheel is deliberate

Status: In progress — **superseded framing, corrected 2026-08-28: read
the paragraphs below (and "Track B" in the Implementation plan) as
history, not the current design.** A tree-addressed config mechanism
(Track B) was proposed here, then designed in detail, then reverted
outright the same record ("table-presence activation, `--platform`/
`--only`/... all removed" addendum, 2026-08-27) in favour of the far
simpler model that actually shipped: every platform always a build
candidate, `build`/`skip` glob-matching the real identifier as the only
selector, `[override]` the only per-target override. Everything else
Track A proposed (natmod's identifier grammar, `{name}-{version}-`
filenames, the pre-build reachability audit, the [0013] correction) did
land, unaffected by Track B's reversal. Two real items remain open, per
this record's own closing text: **A6**, formalizing
`build-platforms.toml` as an explicit, documented resource (the runtime
`docker_image` resolution design is done, addendum below; the resource
itself isn't formally written up as one yet), and the ~10 usermod ports
`build-platforms.toml` already has verified rows for but no real
`build_<port>()` driver.

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

## Identifier grammar, and the elimination of `micropython`/`mpy-abi` as config keys (decided, 2026-08-26)

A separate, narrower thread of the same session's conversation, starting
from a direct question ("mpy зібраний з 1.29 не працюватиме на 1.28?") and
resolved through direct experiment rather than argument — but it kept
going past the identifier's own shape into the deeper question underneath
it, landing somewhere well beyond where it started.

**Recorded honestly rather than only kept as the final answer, since the
reasoning at each step is what a future session needs, not just the
destination — this went through five positions before landing:** tag
leading the identifier; tag repositioned after the ABI; tag dropped from
the identifier entirely (kept as `package.json` provenance instead);
ambiguous same-ABI tags in the `micropython` config list made a loud
`ConfigError`; and finally — the actual destination — **`micropython`
and `mpy-abi` removed as config keys altogether, for both families**,
once it became clear the `ConfigError` step was still patching a
symptom (an ambiguous *declared list*) rather than removing the thing
that made a list necessary in the first place.

**The final position, stated directly: version is not a special,
generative, separately-declared axis. It is exactly the same kind of
axis `archs`/`boards`/`ports` already are — a statically known domain,
selected by `build`/`skip`/`select`, nothing more.** `archs` already
proves this works: it defaults to `list(NATMOD_ARCHS)` (every known arch,
`natmod/options.py:366`), no separate "which arches to fetch" declaration
exists, `build`/`skip` narrow it. `micropython`/`mpy-abi` were the one
place this project still asked the user to *declare* a generative list
instead of just *selecting* from an already-known domain — the exact
"unclear generative thing" this whole record's own diagnosis (the
"axes were never a genuine cross product" section above) was already
naming, just not yet applied to this specific axis until this thread
forced it.

**Natmod: the domain is 3 known ABIs (`resources/natmod.toml`'s own
`[mpy-abi]` table, 23 tags collapsing to exactly `6.1`/`6.2`/`6.3`).
Default = newest ABI only (`6.3` today), not all 3 — corrected directly,
after writing out a concrete draft of the resource surfaced the actual
criterion.** `archs` defaults to *all* known values because every arch is
equally current — nothing about being `armv6m` versus `x64` makes one
more "default-worthy". ABI does not have that property: the newest known
tag *producing* an older ABI (`6.1`'s own newest known producer is
`v1.22.0-preview` — a years-old preview tag) is not something a bare
invocation should build against by default. The right criterion is
recency, not domain size — the same reason usermod's own domain (below)
defaults to newest-only despite being unrelated in size. **This also
means natmod's own zero-config behavior does not change at all** — today
defaults to ABI 6.3 (via `micropython`'s own default), all archs; the new
mechanism produces the identical result through a different path.
`build`/`skip`/`select` opt into older ABIs explicitly, symmetric with
usermod's own `auto`/`all`-style distinction below, not with `archs`'s
"default to everything". A selector names either just the ABI
(`mpy6.3-*`), which
resolves to that ABI's own newest known tag by semver automatically and
deterministically (`newest_tag_for_abi()`, already exists, unchanged);
or an ABI with an explicit tag pinned, when the auto-picked newest is not
what's wanted (the exact syntax for writing an explicit pin — a compound
selector segment, a per-node config value, something else — is not
decided here, flagged below). Two *different* explicit pins for the same
ABI anywhere in one resolved config is the one real ambiguity left,
and stays a loud error — not because a declared list collided (there is
no declared list any more), but because two parts of the config
disagree about which tag services one ABI. This directly closes D13's
own original complaint ("білдиться перше і неочікувано") at its root: an
ambiguity can only exist when the user *writes* two conflicting explicit
pins, never as a side effect of list order, because there is no longer
a list to order.

**Corrected again, directly: `archs` crossed with ABI is not actually a
safe cross-product — verified live, not assumed, and this is the same
lesson A6's own cibuildwheel-reading below teaches, just not yet applied
here when this paragraph was first written.** `rv32imc`/`rv64imc` do not
exist in `py/dynruntime.mk` at all for ABI 6.1 or 6.2 — cloned `v1.20.0`
(6.1) and `v1.23.0-preview` (6.2) directly and grepped their own
`dynruntime.mk`: no `ARCH),rv32imc`/`ARCH),rv64imc` branch in either,
RISC-V natmod support only exists from ABI 6.3 onward. So `archs` (a
domain with no per-cell data on its own, correctly a bare list) still
produces invalid combinations once crossed against ABI at runtime — the
exact PyPy-on-`riscv64` mistake A6's own cibuildwheel reading warns
against, just discovered here independently before that section was
written, not after. **Corrected once more, directly, after reaching for
cibuildwheel's own flat `python_configurations` row-per-identifier shape
as the fix and being pushed back on: that is not what this record's own
central argument calls for.** The bug is real, but the fix is not
flattening into one table — it is scoping `archs` to the *right node* of
the tree this whole record already argues for: `[natmod."6.1"]` and
`[natmod."6.2"]` each carry their own `archs` list (eight arches, no
`rv32imc`/`rv64imc`), `[natmod."6.3"]` carries its own (all ten). No
global `archs` list crossed against a separate ABI table, no need to
flatten to one row per identifier either — the tree structure itself
makes the invalid combination unwritable, the same way a tree node makes
a per-board override unwritable-as-ambiguous elsewhere in this record.
See A6 below for the corrected resource shape; both this paragraph's
"crossed at runtime" description and its own immediately-prior "flat
list of facts" correction are superseded by it — third position on this
one narrow point, recorded rather than silently overwritten again.

**Usermod: the domain is every known tag (the same pin table's own 23
keys, not collapsed — [0051]'s own point stands, every usermod tag is
its own real target, nothing to collapse). Default = newest known tag
only** — the same recency-not-size criterion natmod's own default above
settles on, applied to a domain that happens to be larger (23 versus 3)
for an unrelated reason (no ABI-collapse exists for usermod at all).
Same "auto vs. all" distinction `--archs auto/native/all` ([0049])
already established elsewhere in this project, not a new invention.
`build`/`skip`/`select` reach further back when wanted. **No ambiguity/
conflict-checking logic is needed for usermod at all** — confirmed
directly, mid-thread: usermod never collapses tags in the first place
(`usermod/targets.py`'s own `usermod_targets()` has no dedup step,
verified earlier this session), so there is nothing two explicit
selections could conflict *about*. Natmod's own "two pins, one ABI"
error is a real consequence of natmod's own collapsing; it is not a
general rule this project now applies to every version axis.

**`resources/natmod.toml`'s `[mpy-abi]` table (and its usermod-side
equivalent, the same 23 tags read as a flat list) is now load-bearing for
both families' entire version axis, not just a natmod-internal detail —
this elevates [0052]'s own `build-platforms.toml` proposal (A6) from
"closes one gap, esp32/zephyr boards" to the central resource this whole
mechanism is built on.** Both are already static, checked-in, checkout-
free — nothing here needs new provisioning, only a change in how the two
platform modules *use* what already exists.

**Identifier shape, decided (unaffected by the elimination above — this
part survives from the earlier positions):** `mpy{major.minor}
[-{arch}][+0x{flags}]` for natmod — unchanged from today except dropping
the literal word `natmod` (`mpy` is already a natmod-exclusive prefix, so
spelling out `natmod` too is exactly the redundancy a wheel tag avoids by
never writing `cpython` next to `cp311`). Tag never appears in it —
`natmod/targets.py`'s own `Target.tag` field comment ("not part of the
identifier") turns out to have been right all along, just for the wrong
reason (it said so because it assumed same-ABI tags are byte-identical,
which [0013]'s own addendum shows is false — but the identifier's own job
is naming compatibility, and tag never named that regardless). Tag is
recorded as build provenance in `package.json` (D14) instead. Example,
module `mylib`, `x64`: `mylib-mpy6.3-x64.mpy`; `rv32imc` with
`arch_flags=0x1`: `mylib-mpy6.3-rv32imc+0x1.mpy`.

**Genuinely still open, not decided here:** the exact selector syntax for
an explicit tag pin at natmod's version axis (needed for the "auto vs.
pinned" distinction above to be writable at all) — this is real, new
syntax design, not a detail to guess at inline. Whoever designs Track B's
own tree/selector mechanism should settle this alongside it, since a
version-axis pin and a tree-node override are close cousins mechanically
(both are "the default resolution isn't what I want for this branch").

**Superseded by this section: the `resolve_micropython_tags()`
`ConfigError`-on-ambiguous-tags mechanism, committed earlier the same
session (`adfa932`).** Not wrong, exactly — a real intermediate
improvement over silently picking a winner — but built to guard a
*declared list* that this section removes as a concept entirely. Left in
place in git history as a real, working step in the reasoning chain
(this record's own established practice of recording churn rather than
only the destination); superseding it in code is Track A work, tracked
below, not something this doc edit itself performs.

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

**Fixed, 2026-08-26 (A1 below).** `resolve_arch_flags()`
(`natmod/targets.py`, next to `parse_arch_flags()`), `dict.fromkeys`
dedup by resolved integer, wired into both `Options.targets()` and
`Options.all_targets()`; regression tests in `tests/test_targets.py` and
an end-to-end one in `tests/test_options.py`
(`test_arch_flags_list_dedupes_two_spellings_of_the_same_value`). Full
suite (410, four new), `ruff`, `pyright` all clean. Unaffected by the
`micropython`/`mpy-abi` elimination above — `arch_flags` was never part
of that axis, this fix stands on its own.

(`mpy-cross{tag}`/`micropython{tag}` as prefixed forms for a leading tag
segment were considered and rejected earlier in this same thread — moot
now that tag is not part of the identifier at all; kept only as a note
that the naming question was asked and answered before the bigger
question above overtook it.)

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
         mylib-1.2.0-mpy6.3-x64.mpy

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
grammar (`mpy{major.minor}[-{arch}][+0x{flags}]`, `natmod` dropped, tag
never part of it); usermod's own
identifier needs no change; the `{name}-{version}-{identifier}` artifact-
filename convention and the two config keys it needs; `arch_flags = 0` as
a named, documented stable/broad compatibility class; a pre-build
reachability audit as the missing other half of `verify_output()`; the
`arch_flags`-list dedup-by-resolved-value bug; and [0013]'s own
byte-identical-vs-functionally-interchangeable correction. None of these
require the tree mechanism to land first — each is independently
implementable, and a future session could pick any one off without
waiting on the others.

**A question raised, and then actually resolved, later the same
session:** whether `tag` should become a visible identifier component,
and whether that makes it a real *generative* axis (one build per
distinct tag, dedup off). Resolved past even its own first resolution —
tag never becomes visible in the identifier at all (a build input, not a
compatibility fact), and `micropython`/`mpy-abi` are removed as config
keys entirely: there is no declared list left to dedupe or not-dedupe,
version becomes a statically known domain selected by `build`/`skip`,
exactly like `archs` already is. Full reasoning, and the four intermediate
positions this went through before landing there,
in "Identifier grammar for natmod" above.

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
  identifier grammar (`mpy{abi}-{arch}` instead of `mpy{abi}-natmod-{arch}`
  — only `natmod` drops, tag was never added) — a mechanical follow-on,
  not a design question.
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
  record's own identifier-grammar section is where the correction's
  practical consequence actually lands — not by making `tag` visible
  (considered, then dropped), but by turning D13's own silent "two same-
  ABI tags, keep the first" into a loud `ConfigError`.
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

## Implementation plan (addendum, 2026-08-26, later the same session)

The Status line above calls for "its own dedicated Explore/Plan pass
before any code changes." This addendum is that pass: it rereads every
file the mechanism actually touches directly — `cibuildmp/selector.py`,
`cibuildmp/options.py`, both `platforms/*/options.py`, both
`platforms/*/targets.py`, `cli.py`, `platforms/__init__.py`,
`resources/natmod.toml`, and every real config this repo has
(`cibuildmp.toml`, `examples/template/cibuildmp.toml`,
`examples/wasm2mpy/cibuildmp.toml`) — rather than reasoning about them
from this record's own earlier description, the same discipline
CLAUDE.md's own first rule demands for cibuildwheel, applied here to this
project's own source instead. **It proposes concrete answers to every
item the "What is decided, and what is not" section above leaves open,
each argued from what those files actually contain — it does not decide
them; that is still whoever reviews this addendum's own call**, which is
exactly why the Status line above stays `Proposed` rather than being
flipped to `Accepted` by this addendum's own landing. Nothing described
below has been implemented. Where a proposal here turns out wrong, the
fix is to correct this addendum in a later dated addendum of its own —
append, per this project's own record convention — not to silently code
around it.

### How the two tracks relate

Two independent tracks, not one. **Track A** is every item this record's
own "Also decided" paragraph already called out as independently
implementable — landable today, in any order, each its own PR, without
the tree mechanism existing at all. **Track B** is the tree/matrix
mechanism itself, and its own steps *are* sequential — each one's
migration depends on the previous step's shape already existing, the
same reason [0051]'s own Phase E through I landed in a fixed order
rather than all at once. Track A should go first, purely because it is
cheap and de-risks Track B: A2 below (natmod's new identifier grammar)
changes the exact string Track B's own migration has to carry every test
fixture and example config through, so doing that move twice — once for
A2 landing alone, once again for the tree — is waste Track A avoids by
going first. The full order is spelled out in "Suggested landing order"
below.

### Track A — independent, no design dependency

**A1. `arch_flags` list dedup-by-resolved-value bug — landed 2026-08-26.**
(`natmod/targets.py`, function `natmod_targets()`, called from
`natmod/options.py`'s `Options.targets()`/`Options.all_targets()`.) Shipped
as `resolve_arch_flags()` rather than the `_dedupe_arch_flags()` name
sketched below — it does the parse-and-dedupe together, replacing the
duplicated four-line list comprehension both call sites had, not just
adding a dedup step after it. Steps below kept as the original plan for
the record.

1. Add a `_dedupe_arch_flags(values: list[int]) -> list[int]` helper next
   to `parse_arch_flags()`: dedup by the *resolved* integer
   (`dict.fromkeys`), preserving first-seen order — the same shape D13's
   own tag dedup already uses for the same class of problem.
2. Call it in `natmod/options.py`'s `Options.targets()` and
   `Options.all_targets()`, right after each one's existing
   `[parse_arch_flags("rv32imc", value) for value in self.arch_flags]`
   list comprehension, before the result reaches `natmod_targets()`.
3. Regression test in `tests/test_targets.py`: `arch-flags = ["0x3",
   "zba,zcmp"]` must produce exactly one `+0x3` target, not two — this is
   a real collision, not a hypothetical one, confirmed directly against
   `resources/natmod.toml`'s own `[arch-flags.rv32imc]` table (`zba = 1`,
   `zcmp = 2`, so `zba,zcmp` resolves to `1|2 = 3 = 0x3`).
4. No config-shape change and no doc update beyond marking this record's
   own bug-list entry above as fixed.

**A2. natmod's identifier drops the literal word `natmod`; tag is never
part of it. `micropython`/`mpy-abi` removed as config keys — the version
axis becomes a statically known domain (`resources/natmod.toml`'s own
`[mpy-abi]` table), selected by `build`/`skip`/`select` exactly like
`archs` already is. This is Track A's own largest single item, upgraded
from the smaller "identifier grammar only" scope it started as — see this
section's own note above on the five positions it went through.**

1. `natmod/targets.py`'s `Target.identifier` (currently `base =
   f"mpy{self.abi}-{self.mode}-{self.arch}"`) becomes `base =
   f"mpy{self.abi}-{self.arch}"` — `self.mode` stops being read here;
   grep every `\.mode\b` reference under `platforms/natmod/` before
   deciding whether to delete the field outright. No change to
   `Target.tag`'s own presence on the dataclass (still needed to know
   which checkout to build against), only to whether the identifier
   reads it — it does not.
2. **Superseded before landing in code**: an earlier version of this step
   added a `ConfigError` to `resolve_micropython_tags()` for two distinct
   tags sharing one ABI (committed at `adfa932`) — left in git history as
   a real intermediate step, not reverted, but not the destination either.
   The actual step 2 is larger: delete `micropython`/`mpy-abi` from
   `GENERIC_KEYS`/the `Options` dataclass entirely; `Options.tag_groups()`
   (today's `if isinstance(self.mpy_abi, list): ... else
   resolve_micropython_tags(...)` branch) is replaced by one function that
   always iterates the full `[mpy-abi]` table's own 3 distinct ABIs
   (default) or a `build`/`skip`-narrowed subset, resolving each surviving
   ABI to its own newest tag via the already-existing
   `newest_tag_for_abi()` — no user-declared list, ever. An explicit-tag
   pin (needed when the auto-picked newest is not wanted) still needs its
   own selector syntax, genuinely undecided (flagged above, not guessed
   at here) — this step should not block on that syntax being finished;
   land the no-pin-needed common case first, add pinning once B0-B3's own
   review pass (which the pin syntax question was folded into) settles it.
3. `resolve_micropython_tags()`/`resolve_abi_selector()` themselves likely
   collapse into the one function step 2 describes — confirm by writing
   it, do not assume the merge shape in advance.
4. Audit every literal identifier-shaped string in `cibuildmp.toml`'s own
   root example and `examples/template/cibuildmp.toml`'s header comment:
   the now-dropped `-natmod-` segment (`mpy6.3-natmod-x64` ->
   `mpy6.3-x64`), and the deleted `micropython = [...]`/`mpy-abi = [...]`
   keys themselves — both example configs currently set one or the other,
   confirm directly which before deleting.
5. `tests/test_selector.py`/`tests/test_overrides.py`/`tests/test_options.py`:
   every hardcoded `mpy6.3-natmod-*`-shaped literal needs the `-natmod-`
   removal; every test that sets `micropython`/`mpy-abi` in a fixture TOML
   needs rewriting against the new no-config-key default (this is a
   larger fixture pass than the original A2 scope, closer in size to
   [0051]'s own Phase F migration — size it accordingly, do not treat as
   a quick follow-on to step 1).
6. `docs/reference/design.md`'s own natmod identifier and config-schema
   sections — verify directly whether they document `micropython`/
   `mpy-abi` as config keys before editing (near-certain they do) — both
   need removing, replaced by a description of the static domain and how
   `build`/`skip` narrow it.
7. Real breaking change, larger than the original A2 scope: every config
   with an explicit `micropython`/`mpy-abi` key (this repo's own included)
   stops parsing. Fold into [0038]'s own migration list, called out
   explicitly and separately from the `-natmod-` identifier change — two
   distinct breaks landing together, not one.
8. `natmod/build.py`'s D14 `package.json` writer gains the tag actually
   used as a new field (provenance, not identifier); sequenced with A3
   below since both touch that writer.

**A3. `{name}-{version}-{identifier}` artifact filenames; `version`
promoted to a genuinely global key; `name` added as new.**

1. Confirm directly (`grep -n '"version"' src/cibuildmp/platforms/usermod/options.py`)
   that usermod's own schema and `opt()` closure read `version` nowhere
   today, matching this record's own claim, before treating the key as
   safe to add. Add `"name"` to `GENERIC_KEYS` in `natmod/options.py`
   alongside the existing `"version"` entry — that module's copy is the
   one both platform modules already share (`usermod/options.py` imports
   from it directly), so there is no second copy to touch.
2. `natmod/options.py`'s `Options` dataclass already carries `version:
   str`; add `name: str = ""` beside it, read the same `opt("name", "")`
   way `version` already is.
3. `usermod/options.py`'s `UsermodOptions` dataclass has neither field
   today — add both, read through the same top-level `opt()` closure
   `UsermodOptions.load()` already has.
4. `natmod/build.py`'s output-naming function (reread it directly before
   changing it — this record's own claim is that today's `mylib-
   {identifier}.mpy` name is a side effect of `mpy_path.stem`, itself
   derived from the user's own Makefile, not a config value at all) gains
   the `{name}-{version}-` prefix only when `name` is non-empty, so a
   project that has not set it yet keeps exactly today's filename rather
   than gaining a bare leading `-`.
5. `usermod/build.py`'s `_dest_name()` (three call sites this record
   already names — `build.py:769,1081,1372`, each hardcoding
   `"micropython"`/`"micropython.exe"`/`"micropython.bin"`) needs the
   same prefix, and the literal `"micropython"` stem dropped, at all
   three call sites together — a partial fix leaving one port on the old
   bare name recreates the exact "two projects' firmware artifacts
   indistinguishable" gap this step exists to close for the other two.
6. Confirm the `package.json` writer (D14) already reads `version` off
   the now-global key rather than a natmod-local one after step 2 — no
   behaviour change expected, worth confirming rather than assuming.
7. New tests: `tests/test_build.py` gains name-set/name-unset cases for
   natmod's own output naming; `tests/test_usermod_build.py` the same for
   all three usermod `_dest_name()` call sites.
8. `docs/reference/design.md`'s config-schema section gains `name`/
   `version` as documented global keys — check directly whether `version`
   is already documented as natmod-only there before editing.

**A4. `arch_flags = 0` as a named, documented compatibility class.**
Pure documentation, no code: a paragraph in `docs/reference/design.md`
(wherever A2's grammar update lands, or beside it) stating the subset-
check fact this record already verified directly in
`py/persistentcode.c` (`(arch_flags & device_extensions) != arch_flags`),
naming `arch_flags = 0` as the `abi3`-equivalent broad/portable default,
and cross-referencing `natmod/build.py`'s `verify_output()` docstring,
which already half-documents the asymmetry from the mip-subset side. One
PR, no tests needed.

**A5. Pre-build reachability audit — the missing other half of
`verify_output()`.**

1. New function — `natmod/options.py`, or a new small module
   (`natmod/audit.py`) only if it grows past a screenful; decide by
   actual size once written, not in advance. `check_reachable(cfg:
   Options) -> None`, called once from `Options.targets()` rather than
   from each of `cli.py`'s own call sites separately — `targets()` is
   where the real build path, `--print-build-identifiers` and `--dry-run`
   already converge, so one call site there covers every caller for
   free, matching how `all_targets()` itself is already the one place
   every caller goes for the full identifier space.
2. Implementation: `all_targets()` (already offline, already exists) is
   the full identifier space; for every `[[overrides]]` entry and for
   `build`/`skip` themselves, run `matches()` (`selector.py`) against
   that full set and raise `ConfigError` naming the specific selector
   string and its config location the moment one matches zero
   identifiers.
3. Keep the distinction this record's own text already draws: this is a
   *reachability* check (could this selector ever match something), not
   a *selection* check (`build`/`skip` narrowing to zero targets is
   legitimate today and must stay legitimate) — run only against
   `all_targets()`, never against `targets()`'s own filtered result, or a
   deliberate `skip = "*"` config becomes a false-positive error.
4. Extend the identical way to `usermod/options.py`'s `UsermodOptions`,
   against `all_usermod_targets()`.
5. New tests: an override `select` that can never match (`mpy6.2-*` when
   `micropython = ["v1.29.0"]` only ever produces ABI 6.3) raises a named
   error; a legitimate `skip = "*"` config does not raise — the second
   case is what actually proves the reachability/selection distinction
   holds rather than merely being asserted.
6. Real ordering dependency on A2: write these new tests against the
   identifier's post-A2 shape (`mpy{abi}-{arch}`, `natmod` dropped), so
   sequence A5 after A2 within Track A even though the two are nominally independent
   of each other.

**A6. `build-platforms.toml`, formalized — elevated, mid-session, from
"closes one gap" to the single static resource both families' entire
version and board axes are built on (see "Identifier grammar" above);
shape corrected directly against a real reference, not designed from
scratch.**

**CLAUDE.md's own first rule, applied here directly, three times over —
read the real file; over-corrected toward its literal flat shape; landed
on the actual lesson underneath both attempts.** cibuildwheel ships a
real `cibuildwheel/resources/build-platforms.toml` — read directly this
session, not recalled. Its own structure is a flat `python_configurations
= [{identifier, version, url, sha256}, ...]` list per platform. The real
lesson is **fact-first, not axis-first: never store an assumed
combination, only a verified one** — cibuildwheel gets there by
flattening (no tree depth exists to organize by instead); a first
attempt here copied the flat row shape directly, which was itself
corrected back toward this record's own tree argument (one `archs` list
per ABI node) — **which turned out to still be axis-first, just one
level less wrong**: it silently assumed every tag *within* one ABI group
shares the same arch support, an assumption checked for exactly two of
23 tags (`v1.20.0`, `v1.23.0-preview`) and extrapolated across the rest.
**Landed shape: one row per independently-verified `(tag, arch[,
arch_flags])` fact**, `family`/`port`/`board` stated explicitly on every
row (self-describing outside its own nesting, not only implied by table
position) — `mpy6.3-v1.28.0-x64` and `mpy6.3-v1.29.0-x64` are two
distinct rows despite sharing ABI 6.3, because both are independently
real. This *is* still a tree at the top level (`[natmod]`,
`[usermod.unix]`, `[usermod.esp32]` — not one undifferentiated
cibuildwheel-style list mixing every family together);
the correction is that each leaf's own contents are flat, verified rows,
not a further-abstracted axis list that can silently assume homogeneity
it was never checked for. `identifier` here is the fact table's own key
(tag included) — not the same string as the selector-facing output
identifier (`mpy6.3-x64`, tag excluded, decided earlier in this record);
one addresses a verified fact, the other addresses a compatibility class
several facts can share.

Applying this per axis, checked directly, not assumed:

- **`boards` (qemu), `archs` (unix/windows)** — checked directly, not
  assumed safe by analogy: `ports/unix/Makefile` has no `ifeq($(ARCH),...)`
  gate at all, in either `v1.20.0` or `v1.29.0` — arch there is a
  toolchain/Docker-image concern (`pinned_docker_images.toml`, already
  independent of any MicroPython tag), not something the port's own
  source restricts per release the way `dynruntime.mk` does for natmod.
  So this class of bug genuinely does not recur here — confirmed, not
  merely unexamined this time. `qemu`'s own three boards and `windows`'s
  own arch list were not independently checked the same way; treat as
  the same open item until they are, not assumed safe by analogy either.
- **natmod's own version×arch space — one row per verified `(tag, arch[,
  arch_flags])`. Since completed for real: all 22 known tags, not a
  sample.** Cloned and grepped every one of them directly (not two
  extrapolated to the rest) — 189 real rows, sent to the user as
  `build-platforms.natmod-full.toml`. The result sharpens the bug this
  section already found, one level further: `rv32imc` does not appear
  until `v1.25.0` (not from the start of ABI 6.3, which begins at
  `v1.23.0`) and `rv64imc` not until `v1.28.0` — so even a per-*ABI*-node
  `archs` list (this section's own second, already-rejected position)
  would have been wrong *within* ABI 6.3 itself, not only across ABI
  boundaries. Per-tag rows are not a stricter-than-needed precaution;
  they are the minimum granularity the real data actually has.
  `arch_flags` compounds onto the same row shape (one row per
  `arch_flags` value actually valid for that specific `(tag, arch)`
  pair, not independently reverified per tag this pass — `RV32_ARCH_FLAGS`
  itself, i.e. whether `zba`/`zcmp` were both available from `v1.25.0`
  onward or introduced later, is flagged, not checked).
- **`esp32`'s own board *count* per tag, checked across all 22 —
  confirms the same instability far past one example, then a further,
  sharper one: the naming scheme itself changed, not just which names
  exist.** `ls ports/esp32/boards/` per tag: from 29 boards (`v1.24.1`)
  to 81 (`v1.29.0`), no monotonic trend. Listed actual names for
  `v1.20.0`/`v1.24.1`/`v1.28.0`/`v1.29.0` directly: `v1.20.0`'s own
  boards are named `GENERIC`, `GENERIC_C3`, `GENERIC_S3` — no `ESP32_`
  prefix at all — while `v1.24.1` onward uses `ESP32_GENERIC`,
  `ESP32_GENERIC_C3`. A `board = "ESP32_GENERIC"` row for `v1.20.0`
  would not merely be an unverified guess, it would be flatly wrong — no
  board by that name exists in that tag's own checkout. This closes any
  remaining case for deriving board identity from a formula or a recent
  tag's own vocabulary — the row for each tag has to come from that
  tag's own real directory listing, individually, full stop.

**Pushed to completion, directly requested: every platform's own
`identifiers` list, generated for real across all 22 tags, not samples
— 1,304 rows total, sent to the user as `build-platforms.full.toml`.**
Per platform, what was actually checked before generating (not
assumed):

- **`natmod`** — 189 rows, `dynruntime.mk` grepped per tag directly
  (already covered above).
- **`unix`/`windows`** — 330 + 66 rows. Confirmed, for all 22 tags this
  time (not two samples): neither `ports/unix/Makefile` nor
  `ports/windows/Makefile` has an `ARCH`-conditional gate in *any* of
  them — a genuine full cross-product, not an assumption extended from
  a partial check.
- **`webassembly`** — 22 rows (one per tag, no sub-axis); `ports/
  webassembly/` confirmed present in all 22.
- **`qemu`** — real per-tag board lists, not a fixed three: the port
  **does not exist before `v1.24.0`** (`v1.20.0`-`v1.23.0-preview`
  checkouts have no `ports/qemu` directory at all); `v1.24.0`-`v1.26.1`
  have 5 boards (`.mk` files: `MICROBIT`, `MPS2_AN385`, `NETDUINO2`,
  `SABRELITE`, `VIRT_RV32`); `v1.27.0`-`v1.29.0-preview` add
  `MPS2_AN500`/`MPS3_AN547`/`VIRT_RV64` (8); `v1.29.0` adds `POWERNV9`
  (9, now directories not `.mk` files). cibuildmp's own current default
  (`MPS2_AN385`/`VIRT_RV32`/`VIRT_RV64`) is a real, live-verified subset
  of what upstream actually offers at the newest tag, not the full set —
  worth a real decision (stay a curated subset, or track upstream's own
  growth) once this lands, not resolved here.
- **`esp32`** — 616 rows, **names only** (`identifier`/`tag`/`date`/
  `board`, no `mcu`/`product`/`vendor`/`variants`) — full per-board
  metadata across all 22 tags would be 600+ individual `board.json`
  reads, declined as disproportionate for one documentation pass;
  genuinely the refresh script's own job, not a gap left by oversight.

**`date` added as a field on every row, all platforms — a real, useful
fact that was missing, caught directly**: preview tags carry no date in
their own tag *name* (confirmed against the real upstream tag list —
`v1.22.0-preview`, no timestamp suffix), but every tag's own git commit
does (`git log -1 --format=%cs`) — `v1.22.0-preview` was committed
2023-10-06, `v1.22.0` itself 2023-12-27, `v1.29.0-preview` 2026-04-07,
`v1.29.0` 2026-08-24. Worth having on every row (not only previews) for
the same reason `newest_tag_for_abi()`'s own semver-only ordering can be
ambiguous or surprising — a real timestamp is a second, independent
check on "which one is actually newest," not redundant with the tag
string itself.

Also surfaced in passing, worth its own follow-up rather than silently
noted here: `v1.30.0-preview` already exists upstream — newer than
anything `[mpy-abi]` currently pins, confirming the pin table needs
periodic refreshing (its own stated purpose) rather than being a
one-time artifact.

**Decided, directly: only the most recent preview tag is pinned, every
earlier preview dropped.** A superseded preview (`v1.22.0-preview`
through `v1.28.0-preview`, once `v1.22.0` through `v1.28.0` themselves
shipped) adds real row count for no ongoing value — its own final
release already exists, is more authoritative, and is what any real
config should actually build against. The single most recent preview
(`v1.29.0-preview`, or `v1.30.0-preview` once the table is refreshed)
stays pinned because it is the only one naming a version whose final
release does not exist yet — genuinely the newest thing available to
build against, not historical. Pruned file sent to the user
(`build-platforms.pruned.toml`): 15 tags instead of 22, 904 rows instead
of 1,304. The refresh script's own selection rule, stated plainly: keep
every non-preview tag, plus the single newest preview tag, drop every
older preview.
- **`[mpy-abi]` (tag -> abi)** — already exactly the flat-map-of-real-facts
  shape this lesson calls for; unchanged, and still the source `family =
  "natmod"` rows above derive their own `abi` field from (one lookup per
  tag, not duplicated data).
- **`pinned_docker_images.toml` (arch -> image)** — same, already correct,
  unchanged.
- **`esp32`'s (and `zephyr`'s) own boards — one `identifiers` list, board
  metadata folded directly into each row, not a separate sidecar table.**
  Two real gaps caught in sequence and both closed the same way: first,
  `esp32` initially had board *metadata* (`mcu`/`product`/`vendor`/
  `variants`, confirmed real and necessary directly against
  `usermod/boards.py`'s own `Board` dataclass, `boards.py:141-172` —
  `variants: list[Variant]` is a board's own further nested sub-axis,
  `usermod -> esp32 -> <board> -> <variant>`, one level deeper than this
  record's own earlier sketches assumed) but no `identifiers` list of
  `(tag, board)` rows at all — every other platform in this record had
  one, esp32 did not. Second, once added, a `[usermod.esp32.boards.<name>]`
  sidecar table for the metadata was itself dropped — metadata now lives
  directly on each `identifiers` row (`mcu`, `product`, `vendor`,
  `variants`, alongside `identifier`/`family`/`port`/`tag`/`board`), one
  list, no cross-referencing between two structures for one platform.
  Not merely simpler — board metadata was never verified invariant
  across tags either, so repeating it per row is the honest fact-first
  shape, the same reasoning natmod's own per-`(tag, arch)` rows already
  follow. Verified live, not assumed, on both axes: `ESP32_GENERIC_S3`'s
  own `board.json` is byte-identical between `v1.28.0` and today's
  `master` (metadata stable, at least for this one board, this one
  comparison); `ESP32_GENERIC_H2` exists in `v1.29.0`'s own
  `ports/esp32/boards/` but is absent from `v1.28.0`'s (existence is
  not stable) — diffed both real checkouts directly, metadata and
  existence are independent facts, neither derivable from the other.
  All metadata pulled from a live checkout of `master`, not a tagged
  release — flagged for the refresh script to re-pull per-tag too, not
  yet done here.

Refreshed by a maintainer-run script (not part of any build invocation)
that clones MicroPython once, walks `ports/esp32/boards/*/board.json` via
the existing `Board.factory()`, and writes the result — the same
one-time, checked-in, periodically-refreshed shape `[mpy-abi]` already
has, and the convention the user's own `o-murphy/rp2040py` repo already
follows. A stale board list (a board or variant added upstream since the
last refresh) fails the same way a stale `[mpy-abi]` tag would today —
not tested here, not a new failure mode. Whether this lives as one new
`resources/build-platforms.toml` or as `resources/natmod.toml` itself
renamed/elevated (it already holds most of the flat-fact data this
resource needs) is a naming detail for whoever implements A6, not decided
here — but it should be **one file, not two**, to avoid the exact
two-sources-of-truth drift risk a duplicate would create.

### Track B — the tree/matrix mechanism

This is the part the record's own Status line says still needs a
dedicated design pass. What follows is that pass's own output: concrete
proposals for each of the "not decided" section's four bullets above,
each argued from the code reread for this addendum, followed by a phased
landing plan. Every proposal below is exactly that — a recommendation for
whoever reviews this addendum to accept, amend or reject, not a decision
this addendum is entitled to make unilaterally on its own; only this
record's own explicitly-marked "Decided" sections carry that weight.

**B0. How the tree interacts with [0051]'s own cascade tiers (the
record's own third open bullet) — proposed: the tree *replaces*
`platform_tables` as an addressing scheme; `global_table`/`family_table`/
`env`/`extra_layers` are untouched.**

Rereading `cibuildmp/options.py`'s own `Options.get()` with this question
in mind: today's cascade has five tiers — `default -> global_table ->
family_table -> platform_tables[platform] -> env(+platform)`, plus
`extra_layers` the caller appends for CLI values and `[[overrides]]`
matches. Of those, only `platform_tables` is genuinely about *where in
the tree* a value lives: `global_table` is the tree's own root,
`family_table` is one specific interior node one level below root
(`usermod`, sibling to `natmod`), and `env`/`extra_layers` are not tree
positions at all — separate input sources layered on afterward regardless
of tree shape. **Proposed: the tree subsumes exactly `global_table` +
`family_table` + `platform_tables` into one recursively-addressed
structure** — root = today's `global_table`, `usermod` = today's
`family_table`, `usermod.unix` = today's `platform_tables["unix"]`,
`usermod.esp32.SOME_BOARD` = a node one level deeper than the current
three-tier scheme can address at all — **`env` and `extra_layers` stay
exactly as they are**, appended after tree resolution the same way
`Options.get()` already appends them after `platform_tables` today.
Concretely, the five-line layer list in `Options.get()` collapses to:
walk the target's own tree path from root to leaf, collecting one
`(value, InheritRule.NONE)` layer per node that defines `name`, in
root-to-leaf order (most-specific-wins falls out for free, since
`resolve_cascade()` already takes lowest-priority-first and lets later
layers win); then append `env`/`extra_layers` exactly as today. This is a
strict generalization, not a rewrite: natmod's own path (`natmod`, one
segment) walks to exactly two layers — root, `natmod` — byte-identical to
today's `global_table -> platform_tables["natmod"]`; a board-less usermod
port (`unix`) walks to three layers — root, `usermod`, `usermod.unix` —
identical to today's `global -> family -> platform`; only
`esp32.SOME_BOARD` (four layers) reaches a depth the current dataclass
cannot express, which is exactly the gap this record exists to close.

**B1. TOML syntax — proposed: dotted segments, matching TOML's own native
nested-table addressing directly; no new mini-language for writing
config.**

The record's own sketch (`[usermod.unix]`, `[usermod.esp32.some_board]`)
is already legal TOML nested-table syntax today — `tomllib` parses `[a.b.c]`
into `{"a": {"b": {"c": {...}}}}` with no special handling, confirmed
directly against this repo's own `tomllib.load()` call in
`natmod/options.py`'s `_load_toml_tree()`. **Proposed: the config file's
own nesting *is* the tree; no separate path syntax for writing config,
only for `select` (see B2).** A board name TOML's bare-key syntax cannot
hold (a space, e.g. "some board") is written the way TOML has always
supported this — a quoted key, `[usermod.esp32."some board"]` — rather
than inventing a cibuildmp-specific escaping convention; `tomllib`
round-trips this with zero cibuildmp-side parsing. Depth is not uniform:
`natmod`/`unix`/`windows`/`qemu`/`webassembly` bottom out at platform
level (two from root); only `esp32` (and `zephyr`, [0022], not started)
has a real board sub-node (three from root). **The B0 tree-walk must not
assume a fixed depth** — walk however many segments the config actually
nests and stop at the deepest one present for this target's own path,
which recursive `dict.get()` chaining already does with no per-platform
special-casing needed.

**Confirmed explicitly, since it is the whole point of this shape: a
per-port override and a per-board override are the same mechanism at two
different depths, no separate feature for either.**

```toml
[usermod.unix]
extra-make-args = ["-DFOO=1"]        # every unix build gets this

[usermod.esp32.ESP32_GENERIC_S3]
extra-make-args = ["-DBAR=1"]        # only this one board does
```

Neither line needs `[[overrides]]`/`select` at all — writing directly
into the tree node *is* the per-port or per-board override, B0's own
tree-walk picks both up automatically at whatever depth they were
written. `[[overrides]]`'s own `select` (B2, next) is only for the
residual case neither of these can express — a pattern spanning several
nodes with no single common parent narrower than the whole family (e.g.
"every arch ending in `emsp`," which touches sibling `[natmod.<arch>]`
nodes directly, not one port or one board).

**B2. `[[overrides]]`'s own `select` — proposed: dotted-segment fnmatch,
joined by literal `.`, added as a second matching mode alongside today's
identifier-glob matching, not a replacement for it.**

The record's own refinement already settled the *principle* (tree path is
the selector, not a flattened-string glob); what is still open is the
exact matching semantics, and rereading `selector.py`'s own `matches()`/
`_expand_braces()` with that question in mind surfaces something the
record's own text does not yet distinguish: `fnmatch.fnmatch()` already
treats `*` as "anything, including characters that would look like a
separator" — fnmatch has no separator concept at all, unlike
`glob.glob()`'s own `/`-aware `*` — so `usermod.esp32.*` as one fnmatch
pattern against the dot-joined string `"usermod.esp32.ESP32_GENERIC"`
already matches with zero changes to `selector.py`, because fnmatch's `*`
already crosses what would be a `.` boundary. **But a config node's own
tree address (`usermod.esp32`, which boards/archs/options that node sets)
is not the same string as a target's own identifier** (`v1.29.0-esp32-
ESP32_GENERIC` for usermod, A2's `mpy{abi}-{arch}` for natmod) — a natmod
target's identifier carries no literal tree-path segment at all (`natmod`
has no `{abi}` sub-node in the config tree; that is a resolved value, not
an address). Treating both as "the selector" without distinguishing
them, as the record's own sketch risks by implication, would silently
break `build`/`skip`, which must keep matching the identifier — an ABI,
an arch, neither an addressable tree node. **Proposed resolution: `matching_overrides()`
(`cibuildmp/options.py`) tries a `select` pattern against the *tree path*
of every node from root to the target's own leaf first** (so `select =
"usermod.esp32.*"` matches "every esp32 board", the authoring convenience
the tree exists to provide) **and, unchanged, against `target.identifier`
second** (so `select = "*-armv7emsp"`, a real cross-cutting arch-suffix
pattern with no single tree node addressing it, keeps working exactly as
today) — the two string shapes are different enough that an accidental
double-match across both modes is unlikely, but should be checked
explicitly in the B4 test pass below rather than assumed safe. This
directly answers the record's own residual-fallback question ("whether
every cross-cutting `[[overrides]]` example ... is expressible as a path
glob at all, or still needs a residual flattened-string fallback") —
**yes, keep identifier-glob matching, permanently, not as a migration
shim** — the two modes answer genuinely different questions (address a
tree node vs. address a compatibility-axis subset) and neither subsumes
the other.

**B3. `**`-style multi-depth spanning — proposed: not needed for
`select` itself** (B2's plain fnmatch `*` already crosses `.` boundaries,
covering every cross-cutting example this record's own text gives);
**needed, if ever, only for a future "list every node under this branch"
convenience on top of `--print-build-identifiers`, out of scope for this
record's own landing.**

**B4. Migration story — proposed: five sequential sub-phases, each
independently testable, matching how [0051] itself sequenced Phase E
through I rather than landing atomically.**

- **B4.1 — data model.** Replace `Options.platform_tables: Mapping[str,
  Mapping[str, Any]]` (the one field both `natmod.options.Options` and
  `usermod.options.UsermodOptions` construct today) with a recursive
  `raw` tree walk per B0. `Options.get()`'s own `platform: str | None`
  parameter needs to become path-shaped (`path: Sequence[str]`, or
  `platform: str | tuple[str, ...] | None`) — decide the exact signature
  by writing both real call sites first (`natmod/options.py` and
  `usermod/options.py` each currently pass one bare platform string) and
  seeing which shape keeps both callers simplest, rather than guessing
  ahead of either caller existing.
- **B4.2 — config loading.** `read_config()` itself is untouched (it
  already returns the raw parsed tree with no interpretation); what
  changes is each platform module's own `check_keys()`/`SCHEMAS` walk,
  today exactly one level deep (`raw.get(port)` in
  `usermod/options.py`'s `UsermodOptions.load()`) and needing to become
  recursive for `esp32`/`zephyr`'s own board sub-nodes. **A genuinely new
  sub-question surfaces here, not present in the record's own original
  "not decided" list**: does a board become addressable two ways at once
  — the existing `boards = [...]` list-valued axis key *and* a real
  `[esp32.BOARD_NAME]` tree node — or does the tree node replace the
  list outright? This needs its own explicit answer before B4.2 can be
  implemented; flagged here rather than silently resolved either way (see
  "What this addendum deliberately does not resolve" below).
- **B4.3 — `[[overrides]]` dual matching.** Land B2's two-mode
  `matching_overrides()` behind a change that behaves identically to
  today until a config actually writes a tree-path-shaped `select` — a
  fnmatch pattern that reads ambiguously between "identifier prefix" and
  "tree path" appears in zero real configs today, confirmed by checking
  both example configs and this repo's own directly, so this phase is
  additive with no risk to any existing config.
- **B4.4 — `targets.py` changes.** Neither `Target` nor `UsermodTarget`
  gains a new field for the tree itself — the tree lives in config, not
  in a resolved target. What changes is which config *node*
  `build_options()` reads from for a given target, which is B0's own
  tree-walk, driven by the target's own already-known port/board, not a
  new field on the target.
- **B4.5 — example/test/fixture migration.**
  `examples/template/cibuildmp.toml`'s own `[esp32]` table has no board
  sub-table today at all — this repo's own fixtures have zero real
  board-axis configs to migrate, so nothing forces B4 to prove the
  three-deep case end-to-end against a real file unless one is added
  deliberately as part of this phase (add `[esp32.ESP32_GENERIC]` with
  one real per-board override, specifically so the new depth is exercised
  by the same "every claimed target actually builds here" discipline that
  file's own header comment already holds itself to). Every test file
  touching `platform_tables`/`SCHEMAS`/`family_table` needs a pass —
  `tests/test_options_cascade.py`, `tests/test_overrides.py`,
  `tests/test_usermod_options.py` — roughly 2,100 combined lines across
  the option/override/cascade test files by direct `wc -l`, not guessed.

**B5. Sequencing against [0038].** Per the tracker's own already-stated
ordering argument, repeated here rather than re-litigated ("don't tell
three repos to migrate twice"): Track B must land *before* [0038]'s own
repo migration starts, the same way [0051]'s full landing was itself the
tracker's own recorded precondition for starting [0038]. A2 (identifier
grammar) is the same kind of external-facing break and belongs in the
same pre-[0038] window, not shipped separately ahead of it — shipping A2
alone first would mean the three consumer repos migrate their `build`/
`skip`/`[[overrides]]` strings once for A2 and again for Track B's own
tree-addressed `select`, exactly the double-migration cost this reasoning
exists to avoid.

**This record's own priority is over the tracker as a whole, not only
[0038]** — clarified directly, since the point above reads narrower than
intended. Every other "In progress / Proposed" epic that touches config
shape or identifiers waits on this one, not just [0038]: **[0022]**
(zephyr as a third family) is the actual generalization test for the
family-registry dispatch [0051] already built and for this record's own
tree depth — starting it against today's still-flat config, only to
re-shape it again once Track B lands, is the same double-work risk B5
already names for [0038], one level earlier. **[0040]** (usermod
test-runner axis) adds config surface of its own and should wait for the
same reason. Epics this record's own "Landed records this touches"
section already marked orthogonal — **[0028]**/**[0032]**/**[0044]**/
**[0046]**/**[0047]**/the remaining pieces of **[0050]** — are container/
CI/runner plumbing this record has no opinion about and are not blocked
by it; nothing here asks a future session to hold off on those.

**B6. The tag-generative-axis question (the record's own "one question
raised but not resolved") — resolved, in the "Identifier grammar" section
above, by removing the premise the question was asked inside of.** The
question assumed a `micropython` list stays a declared, generative
config concept, and only asked whether dedup-by-ABI or one-build-per-tag
was the right policy for it. **That framing itself is gone**: `micropython`/
`mpy-abi` are removed as config keys entirely, for both families — version
becomes a statically known domain (natmod: 3 ABIs; usermod: every known
tag, un-collapsed) selected by `build`/`skip`/`select`, exactly like
`archs`/`boards` already are, no declared list to dedupe or not-dedupe in
the first place. Tag itself never appears in natmod's identifier (a build
input, not a compatibility fact — `package.json` provenance instead, A2's
own step 8). D13's own silent-pick bug is closed at the root: an
ambiguity can now only exist if two *different* parts of one resolved
config explicitly pin conflicting tags for the same ABI — never as a side
effect of list order, since no list exists to order. A per-target
tag-pinning override was considered and dropped as solving a case
(pinning a different `dynruntime` per architecture) nobody actually has;
if that need turns out real later it is new mechanism, its own record,
not a speculative knob here. Usermod needs no equivalent ambiguity
handling at all — confirmed directly mid-session, `usermod_targets()` has
no dedup step, nothing to conflict about.

### Suggested landing order

1. A1 — isolated bug fix, one PR, no dependencies.
2. A2 — identifier grammar. Before A5 (which tests against the new
   shape) and before B4.5 (which would otherwise migrate fixtures twice).
3. A6 — `build-platforms.toml`'s own board data, before A5 and before
   B4.2: both need a real, checkout-free board list to validate against,
   and B4.2 cannot land at all without it now that boards are tree nodes,
   not a list.
4. A5 — reachability audit, sequenced after A2 and A6 per their own
   notes above.
5. A3, A4 — either order, independent of everything else.
6. B0–B3 — a review/accept pass over this addendum's own proposals by
   whoever reads it next, *before* B4 writes any code: B4's five
   sub-phases assume B0–B3's answers are settled first.
7. B4.1 → B4.2 → B4.3 → B4.4 → B4.5, strictly in that order — each
   depends on the previous one already existing, and B4.2 specifically
   depends on A6.
8. [0038] starts only once B4.5 is fully green, per B5 above.

### B4.2's own flagged question, resolved

**The tree node replaces the `boards = [...]` list outright — decided,
not dual-addressable.** Reasoning given directly: per-board settings can
genuinely differ (a real, distinct `[esp32.ESP32_GENERIC_S3]` node needs
its own overrides, not just its own presence in a flat list), which a
list-valued axis key has never been able to express at all — `boards =
[...]` only ever said *which* boards are in scope, never let one carry
its own settings the way every other tree node already can. Keeping both
forms alive at once would mean two ways to select the same board
(`boards = ["ESP32_GENERIC_S3"]` and `[esp32.ESP32_GENERIC_S3]` both
present) with no defined precedence between them — exactly the kind of
two-mechanisms-for-one-concept problem this whole record exists to
remove, not reintroduce at the leaf. `boards = [...]` is deleted as a
config key for `esp32`/`zephyr` once B4.2 lands; presence of a board's
own tree node is what selects it, the same "table presence is the
selector" rule `[natmod]`/`[unix]`/etc. already follow one level up.
B4.2's own migration step needs a concrete plan for reading the boards
that exist without a checkout, in order to validate `[esp32.<name>]`
node names the same way A5's pre-build audit validates everything else
offline — see the new "`build-platforms.toml`, formalized" section below,
added for exactly this reason.

## Addendum, 2026-08-27 — A6 continued: `docker_image` must resolve at runtime from
`cross`/`port`/`arch`, not live as static data anywhere; A6's own "already correct,
unchanged" line about `pinned_docker_images.toml` was premature

Two false starts, both caught and reverted before landing on the real requirement —
recorded because both are instructive, not just the outcome. First attempt: a
`docker_image` field added directly to every one of `build-platforms.toml`'s 3354 rows
(computed by three ad-hoc dicts inside `bin/refresh_natmod_archs.py`/
`bin/refresh_usermod_boards.py`). Wrong for the same reason A6's own "fact-first, not
axis-first" lesson already argued against `refresh_*.py` inventing anything: which Docker
image a target builds in is not a fact about that MicroPython tag at all — it is
infrastructure the refresh scripts have no business computing, exactly the "an item must
resolve automatically, and `docker_image` cannot [the way an upstream-README fact can]"
distinction the user drew directly. Reverted (`git revert 3eed752`, commit `ce92d7e`).
Second attempt considered and also rejected before being written: storing `docker_image`
as static per-row data in `build-platforms.toml` at all, computed once by a maintainer
script and committed. Still wrong, one level further down — a *runtime* fact
(`dockerrun.py`'s own docstring already says so: "cibuildmp itself never builds a Docker
image... a maintainer edits *data*, not something an end user configures") belongs
resolved by code from other already-verified facts (`cross`, `port`, `arch`) each time a
build runs, not duplicated as a third copy of information `cross` already carries.

**The mechanism the second attempt was reaching for already exists and does not need
inventing**: `dockerrun.py`'s `image_for()`/`ensure_image()`, resolving from the
already-separate `resources/pinned_docker_images.toml` (never `build-platforms.toml`)
with a `CIBMP_<PORT>_<TARGET>_DOCKER_IMAGE` env override that always wins. `natmod`/
`unix`/`qemu`/`webassembly`/`windows` are already wired to it through the real CLI;
`esp32` alone has no image yet ([0028], host-provisioned). So A6's own line above —
`"pinned_docker_images.toml (arch -> image) — same, already correct, unchanged"` — was
premature: the *existence* of a resolver was correct, but not its *shape*. That line is
left standing above rather than edited, per this record's own append-only discipline;
this addendum is the correction.

**What is actually wrong with the shape, verified directly against
`build-platforms.toml`'s own now-complete `cross` column (not recalled from an earlier,
design-only sketch this same session produced before this column existed):**

- `image_for()` hardcodes two shapes: `unix` keyed per `(arch, floor)`, every other port
  keyed by port name alone, one image each. That undercounts the real toolchain overlap
  — `arm-none-eabi-` alone is natmod's `armv7m`/`armv7emsp`/`armv7emdp` *and* eight usermod
  ports (`qemu` partially, `mimxrt`, `samd`, `stm32`, `psoc-edge`, `cc3200`, `renesas-ra`,
  `nrf`) — eleven targets that could share one image and today have up to nine separate
  `[port]` entries plus natmod's own `[port].natmod` doing the same `arm-none-eabi-gcc`
  work nine-plus times over. `xtensa-lx106-elf-` is natmod's `xtensa` *and* `esp8266`,
  two more currently-separate images for one toolchain.
- Joining `xtensawin` (natmod, real `cross = "xtensa-esp32-elf-"`) with `esp32` (usermod,
  stores no `cross` at all — ESP-IDF resolves its own toolchain internally, confirmed
  this session, not assumed) cannot be done by string-equality on `cross`: `esp32`'s row
  has nothing to match against. Any shared-image rule needs an explicit port/arch
  exception list alongside the `cross`-keyed groups, not a single lookup.
- **The bigger correction: `cross` is not uniformly a per-port fact, so "one image per
  port" is not a valid target shape even for the ports that keep their own image.**
  `qemu` alone carries three distinct `cross` values across its own boards
  (`arm-none-eabi-` for six boards, `riscv64-unknown-elf-` for `VIRT_RV32`/`VIRT_RV64`,
  `powerpc64le-linux-gnu-` for `POWERNV9`) and `windows` carries three across its arches
  (`x86_64-`/`aarch64-`/`i686-w64-mingw32-`) — both confirmed live against
  `build-platforms.toml`'s own rows this session, not assumed uniform by port the way
  `image_for()` currently treats them. `windows`'s single shared image may still be
  correct if `llvm-mingw` genuinely bundles all three target triples in one image (not
  yet verified against the real Dockerfile/toolchain) — but `qemu`'s riscv/ppc boards
  resolving to whatever single image its port-keyed entry names today would be
  outright wrong, the same class of bug 0043 already fixed once for `unix`
  cross-compiling from the wrong architecture. `qemu` needs the same per-row
  granularity `unix` already has, not the single-image treatment it currently gets
  alongside `windows`/`webassembly`.

**A narrower, already-landed, and genuinely orthogonal simplification shipped this same
session, ahead of any resolver redesign** (commit `ce94021`, record [0044]'s own new
addendum has the full account): nine of `unix`'s fifteen `(arch, floor)` cells were
verified to add no cibuildmp layer over their pypa base at all (a bare `FROM` and
nothing else) and no longer get a cibuildmp-published image — `pinned_docker_images.toml`
points those nine cells straight at `pinned_pypa_images.toml`'s own digest instead.
This is data cleanup within the *existing* resolver shape (`image_for()`'s own
`unix`-keyed branch needed no code change), not the toolchain-grouping redesign above —
worth stating plainly so the two are not conflated: one is done, the other is not.

**Left open, on the user's own direction not to spin up a separate design document for
it — this addendum is that record, in place of a new one.** Concretely undecided:
whether the toolchain-group key becomes a new field (`toolchain` / `image_group`) derived
once by a refresh-adjacent step from each row's own `cross` (plus the `esp32`/`xtensawin`
exception), or a pure function computed by `dockerrun.py` itself from `cross` at
resolution time with no new stored field at all — the latter keeps `build-platforms.toml`
describing only verified upstream facts (A6's own governing rule) and treats the
toolchain grouping as what it actually is, infrastructure policy, not a fact about a
MicroPython tag. Also open: the concrete Dockerfiles for the four proposed consolidated
images (`arm_embedded`, `riscv_embedded`, `xtensa_lx106`, `esp_idf` — sketched, none
written), `qemu`'s move to per-board resolution, and whether `windows`'s single image is
actually correct or itself needs splitting. No code for any of this has been written.

## Track C (addendum, 2026-08-27) — `build-platforms.toml` becomes the packaged source of
truth CLI/options/selector resolve against, replacing live discovery

A6 built `build-platforms.toml` as a fact table; nothing in `src/` has read it back yet.
Confirmed directly: `grep`ing every module under `src/` for `build_platforms`/
`build-platforms` finds only `bin/refresh_natmod_archs.py`/`bin/refresh_usermod_boards.py`
(which only *write* it) and this record's own prose. The real runtime today still uses
two older, narrower sources this track supersedes:

- **natmod**: `resources/natmod.toml`'s `[mpy-abi]` (tag -> abi, hand-curated, gaps filled
  by `LATEST_KNOWN_ABI` for any unlisted tag) and a flat `[arch]` table `natmod/targets.py`
  treats as available for *every* tag unconditionally — `NATMOD_ARCHS` is one 10-arch tuple
  with no per-tag gating at all. This is the exact bug A6's own research already proved:
  `rv32imc`/`rv64imc` do not exist for every ABI-6.3 tag, and today's code would not catch
  a config asking for one anyway until a real build fails deep inside `dynruntime.mk`.
- **usermod**: `usermod/boards.py`'s `Database` scans a *live checkout*'s real
  `board.json` files — `--print-build-identifiers`, `--only` validation and even config
  loading for a board.json-backed port cannot run at all without first fetching the
  MicroPython tag in question. `build-platforms.toml`'s own `[usermod.<port>].identifiers`
  rows are exactly this scan's own output, pre-run across every tag the refresh scripts
  have walked — the whole reason A5's "pre-build audit... validates everything else
  offline" note above named this table as what closes that gap.

**Decided this session, each confirmed directly rather than assumed (the questions were
asked because a wrong guess here would have meant discarding real implementation work,
not because the answer was unclear which way this project leans):**

1. **An unknown tag is a hard, loud error — no live-checkout fallback.** `"tag not in
   build-platforms.toml -- refresh it first"`, naming `bin/refresh_natmod_archs.py`/
   `bin/refresh_usermod_boards.py`. Corollary, confirmed directly rather than left
   implicit: `LATEST_KNOWN_ABI`'s current silent-fallback behavior for any tag
   `natmod.toml` doesn't list is *deleted*, not kept as a secondary fallback under the new
   table — one unknown-tag policy, not two layered ones that could disagree.
2. **A requested arch not available in the specific tag chosen to represent its ABI group
   is also a hard error, not a smarter re-resolution — and needs no bespoke error path of
   its own.** The real collision: `resolve_micropython_tags()` narrows a tag list to one
   representative tag per distinct ABI (earliest match wins) — `rv32imc`'s own late
   arrival within ABI 6.3 means `archs=["rv32imc"]` against an early-6.3 representative tag
   would ask `natmod_targets()` to build an arch that tag's own source does not have.
   Rejected: re-resolving the tag *per arch* within an ABI group (so one invocation could
   silently fetch and build against several different tags that all happen to share one
   ABI) — the representative tag stays exactly what `resolve_micropython_tags()` already
   picks. Also rejected, on the user's own correction: a bespoke error naming which other
   tag(s) would have worked. Simpler than that, and already the right shape: this is
   ordinary selector validation, the same "you asked for something that does not exist
   among known identifiers" case any typo'd identifier already produces — `natmod/
   targets.py`'s own existing `UnknownArchError` (today only checking "is this arch one of
   the ten `dynruntime.mk` knows at all") widens its check to "is this arch available for
   *this specific tag*," reusing the one exception class and message shape that already
   exists rather than adding a second one beside it.
3. **`post_checkout`/`pre_checkout` stay documentation of a verified upstream fact, not
   something executed as a shell string at build time.** Every existing build function in
   this codebase (`usermod/build.py`'s `build_unix()`, `run_unix_deplibs()`; natmod's
   `_run_in_image()`) constructs a typed `list[str]` command, never a shell string —
   `dockerrun.run()` itself takes `command: list[str]`. Executing a stored one-liner
   verbatim inside whichever container happens to be resolved would also reintroduce the
   apt-vs-alpine collision this same session already found in `unix`'s own `pre_checkout`
   (a single Debian-flavored string, while `unix`'s real container matrix spans dnf/apt/apk)
   — a Python function that already knows which image it is running in has no such
   problem, since it can name the right package manager instead of guessing one string
   for all of them. These two fields' job stays what A6 already built them for: a verified
   fact a maintainer reads while writing (or auditing) the real `build.py` step, not input
   `cibuildmp` itself interprets.

**Not yet decided, and not blocking Phase C1 below**: whether `resources/natmod.toml`'s
`[mpy-abi]` table is fully superseded by `build-platforms.toml`'s own per-row `mpy` field
(sample row: `{tag = "v1.12", mpy = "5", arch = "x86", ...}` — independently populated by
the refresh script reading each real tag's `persistentcode.h`, not derived from
`natmod.toml`, so the two could already disagree and neither has been diffed against the
other this session) or kept as a second, narrower source for something Phase C1 turns out
to still need. `[arch]` (native-code values, `dynruntime.mk`'s own `ARCH=` vocabulary) and
`[arch-flags.rv32imc]` (`mpy_ld.py`'s `RV32_EXTENSIONS`) are tag-independent MicroPython
source facts, not gated by tag at all, and stay exactly as they are — only the *tag-gating*
question moves to `build-platforms.toml`.

### Phase C1 — natmod (smallest, self-contained; this addendum's own next concrete step)

- `resources.py`: new `build_platforms_data()` loader, same `@cache`/`files()` shape as
  `natmod_data()`/`usermod_data()`.
- `natmod/targets.py`: build a per-tag arch-availability index from
  `build_platforms_data()["natmod"]["identifiers"]` (`{tag: frozenset(arch for row where
  row["tag"] == tag)}`, plus the same table's own `arch_flags`/`arch_code`/`cross` per
  `(tag, arch)` for anything that needs them). `abi_for_tag()` reads the same table's
  `tag -> mpy` mapping and raises on an unknown tag (decision 1) instead of falling back
  to `LATEST_KNOWN_ABI`, which is deleted. `natmod_targets()` gains a tag-availability
  check per requested arch, raising on a mismatch per decision 2's exact wording above.
- Tests: an early-ABI-6.3 tag + `archs=["rv32imc"]` must raise `UnknownArchError`, the
  same class and shape a genuinely nonexistent arch already raises today — no new
  exception type; a genuinely unknown tag (anything not in the table) must raise on
  `abi_for_tag()` before any target is built; every existing `NATMOD_ARCHS`-based test
  needs its fixture tag checked against the real table rather than assumed to still carry
  every arch.
- Not in this phase: usermod (`boards.py`/`_PORT_AXES`), `cli.py`, `selector.py` — selector
  itself needs no change confirmed by re-reading it: it already matches against whatever
  `Target` list a platform's own `targets()`/`all_targets()` produces, tag-agnostic by
  construction, so this phase's only surface is where that list comes from.

### Phase C2 — usermod (deferred until C1 lands and is verified; not designed in full here)

Structurally the same replacement (`Database`'s live `board.json` scan ->
`build_platforms_data()["usermod"][port]["identifiers"]`), but with a real, not-yet-solved
wrinkle C1 does not have: what happens when `--only`/`--print-build-identifiers` is asked
about a tag+port this table has never walked (a real gap, not the "wrong tag entirely"
case decision 1 already covers) — same hard-error direction, in all likelihood, but worth
confirming once C1 is landed and this phase is actually being scoped, not assumed here.

## Addendum, 2026-08-27 — A5 landed, for both families, per the "Suggested landing order"

`check_reachable()` — natmod's own in `platforms/natmod/options.py`, usermod's own in
`platforms/usermod/options.py` — called once each from `targets()`, the one place every
caller (the real build path, `--print-build-identifiers`, `--dry-run`, `--only`, which all
call `targets()` before any further narrowing) already converges, exactly as A5's own
point 1 specified. Checked against `all_targets()` (the full, unfiltered identifier
space), never against `targets()`'s own already-`build`/`skip`-filtered result — a
deliberate `skip = "*"` narrowing a real, reachable domain to zero *selected* targets
stays legitimate, proven by its own direct test (`test_reachability_audit_allows_a_
deliberate_skip_everything`, both families) rather than merely asserted.

The shared per-pattern-group mechanism (`check_selector_reachable()`) lives in
`cibuildmp/options.py`, alongside `matching_overrides()` — the established home for logic
generic across both families, `error` parameterized the same way `matching_overrides()`
already is so each caller's own exception class (`natmod.options.ConfigError` /
`usermod.options.UsermodConfigError`) is preserved rather than replaced by a third,
shared one; existing tests assert the specific class each mode already raises, and this
does not change that. Checks each pattern in a `build`/`skip`/`select` group individually
rather than the group as one OR'd whole, so one working pattern next to one typo'd one
does not hide the typo.

Sequenced after A2 exactly as A5's own point 6 required — every new test written against
the post-A2 identifier shape (`mpy{abi}-{arch}`, no `-natmod-`) directly, not adjusted
after the fact.

408 tests pass; ruff and pyright clean. A3/A4 (independent of each other and of
everything landed so far) and all of Track B remain open.

## Addendum, 2026-08-27 — A4 and A3 landed, per the "Suggested landing order"'s own step 5

**A4**, docs-only exactly as scoped: `docs/reference/design.md`'s Identifier scheme
section gains the `arch_flags = 0` compatibility-class paragraph, citing
`py/persistentcode.c`'s own subset check and cross-referencing `natmod/build.py`'s
`verify_output()` docstring for the mirror side of the same asymmetry.

**A3** — `{name}-{version}-{identifier}` artifact filenames, for both families:

- `version` (already `GENERIC_KEYS`, already a natmod `Options` field, already written
  into natmod's own `package.json`) is now genuinely shared: `UsermodOptions` gained the
  same field, read the same top-level-with-environment-override way. `name` is wholly new
  for both, added to `GENERIC_KEYS` once (the shared constant both families' `check_keys()`
  calls already read, confirmed directly rather than assumed — no second copy to touch).
- `natmod/build.py`'s `output_name()` and `usermod/orchestrate.py`'s `_dest_name()`
  (the record's own step 5 named `build.py:769,1081,1372` — stale line numbers from
  before Phase H's move; the function itself lives in `orchestrate.py` now, confirmed by
  reading the current tree rather than trusting the citation) both gate the whole
  `{name}-{version}-` prefix on `name` alone: unset, both keep exactly today's filename
  (`mpy_path.stem`-derived for natmod, the literal `"micropython"`/`"micropython.exe"`
  stem for usermod); set, the old stem is dropped entirely rather than prefixed, and an
  empty `version` alongside a set `name` omits the version segment rather than emitting a
  bare `mylib--mpy6.3-x64.mpy` double dash — a small, deliberate reading of the record's
  own "gains the `{name}-{version}-` prefix only when name is non-empty" wording, not
  specified in that literal form there.
- Confirmed directly, not assumed, before touching either writer: usermod's own schema
  read `version` nowhere (`grep -n '"version"' platforms/usermod/options.py` — zero hits),
  and the natmod `package.json` writer already reads `version` off the now-global key with
  no change needed (it always did — `version` only *became* global in name, its plumbing
  was already there).
- New tests: `tests/test_build.py` (name-unset/name-only/name-and-version cases for
  `output_name()`), `tests/test_usermod_orchestrate.py` (the same three cases for
  `_dest_name()`, plus one full `build_one()` integration test proving `options.name`/
  `options.version` actually reach the written file), `tests/test_options.py` and
  `tests/test_usermod_options.py` (both families' own `name`/`version` load-and-default
  tests, mirroring the existing `version`-only tests each file already had for natmod).
- Not done, deliberately out of scope: the D14 `package.json` writer gaining the tag
  actually used as a provenance field (A2's own step 8, sequenced "with A3... since both
  touch that writer" by the record's own text) — a genuine A2 leftover, not an A3 step;
  left open rather than folded in silently.

417 tests pass; ruff and pyright clean. All of Track A is now landed. Only Track B remains
open, gated on its own B0–B3 review pass per the "Suggested landing order."

## Addendum, 2026-08-27 — B0–B3 review/accept pass, per the "Suggested landing order"'s own
step 6

Whoever the record's own B0–B3 text asked to review it, doing that review now, before B4
writes any code — each proposal re-checked against the real, current source rather than
taken on the strength of its own write-up, per this project's own first rule. **All four
accepted**, two with a clarification worth pinning down explicitly so B4's implementer
does not have to re-derive it; one genuinely new question surfaced by the re-read, flagged
rather than silently resolved either way.

**B0 — accepted, unamended.** Re-read against the real `cibuildmp/options.py`'s
`Options.get()`, not recalled: today's five layers are exactly `default -> global_table ->
family_table -> platform_tables[platform] -> env(+platform)`, then `extra_layers`
appended by the caller — confirmed line-for-line, including that `family_table` defaults
to `{}` for natmod's own `Options` (never passed at all in `platforms/natmod/options.py`'s
`load()`) and that `env`/`extra_layers` are appended *after* the tree tiers today, exactly
where B0 proposes they stay. The proposed tree-walk collapse degrades to today's exact
behaviour at both shallow depths (natmod: root, `natmod` — two layers; a board-less
usermod port: root, `usermod`, `usermod.<port>` — three layers, byte-identical to today's
global/family/platform triple) and only gains real new depth at `esp32`/`zephyr`'s own
board level — precisely the gap this whole record exists to close, not a wider change than
that.

**B1 — accepted, unamended.** Live-verified rather than trusted from the record's own
citation: `tomllib.loads('[usermod.esp32."some board"]\nextra-make-args = ["-DBAR=1"]\n')`
parses to `{"usermod": {"esp32": {"some board": {"extra-make-args": [...]}}}}` with zero
special handling needed — quoted-key dotted tables are standard TOML, not a cibuildmp-side
parsing addition. Worth stating plainly since it is easy to miss on a first read: **this is
a deliberate, already-flagged reversal of [0051]'s own Phase F flat-sibling-table shape**
(`[unix]`, `[windows]`, ... as top-level siblings), not a new conflict this review is
discovering — [0051]'s own status line already says so directly: "a further divergence
from this record's own flat-sibling-table model ... is argued, in detail, in [0052] — not
yet landed, so nothing here is superseded until it does." B4.5 is where that supersession
actually lands; nothing about accepting B1 here changes what ships today.

**B2 — accepted, with one clarification pinned down.** Live-verified: `selector.py`'s own
`matches()` is exactly `fnmatch.fnmatch()` per brace-expanded pattern (read directly, not
recalled), and `fnmatch.fnmatch("usermod.esp32.ESP32_GENERIC_S3", "usermod.esp32.*")` is
`True` — fnmatch's `*` has no separator concept and already crosses a `.` the way B2's own
text claims. The record's own phrasing — "tries a `select` pattern against the tree path of
**every node** from root to the target's own leaf" — reads ambiguously between two
implementations: (a) match once against a single root-to-leaf dotted string
(`"usermod.esp32.ESP32_GENERIC_S3"`), or (b) match separately against every ancestor
prefix (`"usermod"`, `"usermod.esp32"`, `"usermod.esp32.ESP32_GENERIC_S3"`) as three
candidate strings. **Clarified here: (a) is correct, and (b) is unnecessary** — since
fnmatch's `*` already spans multiple segments in one match (re-verified above), a single
full-path match already covers every case B2's own examples name (`select =
"usermod.esp32.*"` matches the leaf path directly; no per-ancestor loop needed to reach the
same result). Implementing (b) would not be wrong, only redundant work B4.3 does not need
to write. Two more points worth pinning down for the same implementer, both straightforward
readings of the record's own text rather than new decisions: **matching is additive (an OR
of the two modes)**, not a "try tree-path, fall back to identifier only if that fails"
priority order — an override applies if *either* mode matches, matching the record's own
"the two modes answer genuinely different questions ... neither subsumes the other"; and
**this dual-mode matching is scoped to `[[overrides]]`'s own `select` only** — `build`/
`skip` stay identifier-only glob matching, unchanged (B0's own text already draws this
boundary: "[[overrides]]'s own `select` ... is only for the residual case neither
[a tree node nor a family-wide default] can express"), so A5's already-landed
`check_reachable()` (which checks `build`/`skip` reachability against `all_targets()`'s own
identifiers) needs no change under B2 at all.

One genuinely new question, surfaced by this re-read, not present in B0–B3's own text and
not resolved here: `OVERRIDE_UNION_KEYS` (`platforms/natmod/options.py`) deliberately
excludes `arch-flags` today, specifically because "resolved once for the whole config,
never per target, so an override carrying it would be silently ignored" — a limitation that
existed only because a flat `select` glob had no way to unambiguously address "just this
one arch." Under B0/B1's real tree nodes, `[natmod.rv32imc]` *would* unambiguously address
exactly that arch — the same reason a per-board override already works for `esp32`. Whether
`arch-flags` should become a legal per-arch-node key once Track B lands, or whether the
"resolved once globally" constraint is actually load-bearing for some reason this review
did not surface, is a real open question for B4 to answer explicitly — flagged here rather
than assumed either way, since accepting B0–B2 as written does not itself answer it.

**B3 — accepted, unamended.** Re-verified alongside B2's own fnmatch check above: since a
plain `*` already crosses every `.` boundary, a `**`-style multi-depth-only wildcard adds
no matching power `select` does not already have. Deferred exactly as proposed — a future
"list every node under this branch" convenience on top of `--print-build-identifiers`,
out of this record's own landing.

B0–B3 are now settled for B4's own five sub-phases to build against. B4.2's own flagged
question (boards: tree node replaces the list, not dual-addressable) was already resolved
earlier in this same record; the new `arch-flags`-per-node question above is the one
addition this pass leaves open for B4 itself, not for a further review round.

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
[0028]: 0028-container-per-port-migration-plan.md
[0032]: 0032-unix-docker-default-and-webassembly-wiring.md
[0040]: 0040-usermod-tests-deferred.md
[0044]: 0044-unix-native-images-landed.md
[0046]: 0046-pin-staleness-checker.md
[0047]: 0047-run-output-parity-with-cibuildwheel.md
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
## Addendum, 2026-08-27 — Track B's own B4.1–B4.3 reverted: the tree-path `select` mode was
solving a problem cibuildmp's own identifier scheme already closes

**B4.1 (`abc4a20`), B4.2 (`f294dea`), B4.3 (`f4be1ca`) are reverted** (`4c62ec7`, `9b6c4b5`,
`20cf60e`), back to the exact state as of the B0–B3 review pass (`9550dcc`). Only one piece
of B4.2 survives, reapplied fresh on top: esp32's own `boards = [...]` values are now
validated against `resources/build-platforms.toml`'s own known board list (`f66d2b5`) --
`boards = [...]` itself, as a config key, is unchanged.

**What was found, live, that the B0–B3 review pass itself did not check.** That pass
accepted B2's own premise almost verbatim: "a natmod target's identifier carries no literal
tree-path segment at all... a usermod-port identifier is matched by fnmatch against a
flattened string with no family/platform prefix to glob against." True for natmod. **False
for usermod, checked directly rather than trusted from the record's own earlier prose**:
`UsermodTarget.identifier` is `f"{tag}-{port}-{arch}"` -- `port` is a literal, stable
substring of every usermod identifier, confirmed live:

```
fnmatch("v1.29.0-esp32-ESP32_GENERIC_S3", "*-esp32-*")  -> True
fnmatch("v1.28.0-unix-manylinux_2_28_x86_64", "*-esp32-*") -> False
fnmatch("mpy6.3-x64", "mpy*") -> True   # natmod's own equivalent, already worked
```

No board name contains a dash (checked against all 57), so `*-esp32-*`/`*-esp32-BOARD` are
unambiguous, exact, and were **already sufficient** for "every board under this port" and
"this one board specifically" -- the exact two cases B2/B4.3 were built to answer. Tree-path
matching added no reachable case flat identifier globbing did not already have. Confirmed
by writing the counter-example directly (`select = "*-esp32-*"` reaching every board,
`select = "*-esp32-ESP32_GENERIC_S3"` reaching exactly one, both zero-risk against real
board names) rather than merely asserting it.

**A second finding, from rereading `cibuildwheel/options.py` directly rather than recalling
it (this record's own first rule), that reframes what the actual missing piece was.**
`OptionsReader.get()` reads every option -- `build`/`skip` included
(`self.reader.get("build", env_plat=False, ...)`) -- through the identical cascade every
other option uses, and `_validate_platform_option()` allows `self.default_options.keys() |
self.default_platform_options.keys()` inside `[tool.cibuildwheel.<platform>]` -- meaning
`build`/`skip` genuinely are settable per-platform in real upstream configs
(`[tool.cibuildwheel.linux] build = "cp312-*"`), unlike cibuildmp's own `GENERIC_KEYS`
mechanism ([0048]'s own design), which has always forced `build`/`skip` to the top level
only, a loud error anywhere else. `DISALLOWED_OPTIONS` (`options.py:210-214`) is a small,
separate "this key is meaningless on this platform" guard (`manylinux-*-image` on
macos/windows) with nothing like a tree behind it either. Upstream's own `[[overrides]]`
matches `select_pattern` against one flat identifier string, same as cibuildmp's own
pre-B2 mechanism -- no dotted-path mode anywhere in the real source.

**What this means for Track B's own original diagnosis.** The record's central argument --
non-rectangular axes need a tree -- held for the *fact* layer (Track C:
`resources/build-platforms.toml`, one row per independently-verified `(tag, arch)`/`(tag,
board)` pair, exactly cibuildwheel's own flat `python_configurations` shape, not a tree at
all) but did not hold for the *selector* layer, where cibuildmp's own identifier scheme --
deliberately keeping `{port}`/`{arch}`/`{abi}` as literal, stable substrings -- already gives
flat globbing everything a tree-path mode would add. The real, upstream-precedented gap is
different from what B2/B4.3 built: cibuildmp forbids `build`/`skip` from ever living inside a
platform's own table at all, where upstream allows it. That is the next thing to design, not
yet started, not yet even written up -- flagged here rather than assumed either way.

**B0–B3's own "accepted" verdicts stand corrected, not deleted** -- the review pass's own
text stays as the honest record of what was reasoned through and accepted before this gap
was found; this addendum is what closes it, the same "argue the reversal in the record,
don't silently edit history" rule the rest of this record already follows for A2's own
`resolve_micropython_tags()` misstep. B4.4/B4.5 do not proceed as scoped -- there is no more
board-level tree node for them to wire into.

## Addendum, 2026-08-27 — per-platform `build`/`skip` landed, closing the real gap the
reverted tree was mistaken for

`build`/`skip` are settable inside `[natmod]`, `[usermod]` (family, usermod only), and each
platform's own table (`[unix]`, `[esp32]`, ...) now -- matching upstream's own
`[tool.cibuildwheel.<platform>] build = "..."`, confirmed live against real
`cibuildwheel/options.py` in the addendum above, not assumed. More specific wins, the same
cascade order `archs`/`extra-make-args` already have.

**Schema split, mirrored on both sides, to avoid a real circularity risk found while
designing this**: `build`/`skip` moved out of `GENERIC_KEYS` (natmod's own shared constant)
into `NATMOD_SCHEMA` directly, and into a new `USERMOD_PLATFORM_KEYS` (`USERMOD_PORT_BASE |
{"build", "skip"}`) on the usermod side -- deliberately *not* folded into `USERMOD_PORT_BASE`
itself, since that constant is also `build_options()`'s own tier-2 `[[overrides]]` schema:
`build`/`skip` decide *which targets exist at all*, a question already answered before any
`[[overrides]]` entry can match, so accepting them there would be circular, not a real
per-target option -- the same split `NATMOD_SCHEMA`/`NATMOD_OVERRIDE_OPTION_KEYS` already
keeps.

**natmod's own side is close to trivial**: one platform, ever, so `[natmod] build = "..."`
resolving through the cascade rather than the old ad-hoc `opt()` closure changes nothing
about what a config that never writes `build`/`skip` inside `[natmod]` resolves to -- only
what becomes legal to write there. Live-verified: `[natmod] skip = "*-armv7emsp"` alongside
a top-level `skip = ""` correctly narrows only natmod's own targets.

**usermod's own side needed real restructuring, because more than one port can be active at
once, each potentially wanting its own `build`/`skip`.** `UsermodOptions.build`/`.skip` stay
the global-*and*-family-resolved baseline (`family_table.get()` is consulted by
`Options.get()` regardless of whether `platform=` is passed, so `[usermod]`'s own value
already applies here for free); `targets()` additionally resolves each active port's own
`build`/`skip` via `self._cascade_env.get(..., platform=port, default=self.build)`, applies
`select()` per port-group, then **reassembles in `all_targets()`'s own original order**
(tag-outer, port-inner) rather than concatenating groups, which would have silently
reordered every multi-tag, multi-port config's own output -- caught by design, not by a
failing test. A second cascade instance, `_cascade_env` (env included), sits alongside the
existing file-only `_cascade` (`build_options()`'s own per-target resolution, which checks
env itself already) -- mirrors natmod's own `cascade_env`/`cascade_file` split.

**A5's own `check_reachable()` needed the per-port value checked too, scoped to that port's
own identifiers -- and a real false positive, caught live by the first test written against
it, not foreseen in the design.** `[usermod] skip = "*-webassembly"` is a legitimate
family-wide pattern; checked against `[unix]`'s own narrow identifier subset specifically
(since `_port_build_skip("unix")` falls back to the family-resolved `cfg.skip` when `[unix]`
sets nothing of its own), it reads as unreachable even though it correctly matches something
in the full domain. Fixed by checking the port's own resolved value against `cfg.build`/
`cfg.skip` first: only when they differ (the port's own table genuinely set something) does
the scoped, per-port check run at all -- when they're equal, the value is only the inherited
default resolving here too, already correctly checked against the full domain by the
existing top-level call. Unlike the shared `[[overrides]]` list (the separate, still-open,
pre-existing cross-family bug this same session already found and tracked), a per-port
`build`/`skip` value is unambiguous by construction -- it lives inside that port's own table,
no guessing which family it was meant for.

423 tests pass; ruff and pyright clean. Live-verified end to end for both families, not just
unit-tested.

## Addendum, 2026-08-27 — task #66 fixed, one direction: `[[overrides]]` reachability now
sees natmod's own identifiers from usermod's own `check_reachable()`

Not a design task -- a live, blocking bug, reported directly against this project's own
root `cibuildmp.toml`: `cibuildmp --dry-run --platform unix` failed with
`[[overrides]] #1: '*-armv7emsp' matches no known identifier`, even though that override
(`select = "*-armv7emsp"`, an `extra-make-args` tweak) is entirely valid natmod config. Root
cause: `[[overrides]]` is one shared, top-level list (Phase G), but each family's own
`check_reachable()` checked every entry's `select` against only *that family's own*
`all_targets()` domain -- an entry meant for a currently-inactive family failed as
"unreachable" purely because the invocation never loaded that family at all, not because the
selector was wrong.

Fixed on `usermod/options.py`'s own side only. `usermod/options.py` already imports from
`natmod/options.py` (the established one-way direction -- natmod is the shared base module,
never imports back), so a new `_foreign_override_identifiers()` widens usermod's own
override-reachability domain by constructing a `NatmodOptions` from the very same raw config
(`cfg._cascade.global_table`, via the existing `preread` mechanism -- no second file read)
and adding its `all_targets()` identifiers to the check. `NatmodOptions.load()` never calls
its own `check_reachable()` (that only runs from `targets()`, not `load()`), so this cannot
recurse into a natmod-specific reachability failure -- only its plain identifier space is
read. Wrapped in `except NatmodConfigError: return []`: an unrelated, genuine `[natmod]`
config mistake is natmod's own to report when natmod is actually loaded, not something that
should surface as a confusing failure from an unrelated usermod-only invocation.

**Deliberately asymmetric, and said so in the code, not silently left inconsistent**: the
mirror direction -- a natmod-only invocation flagged by an override meant only for a usermod
port -- is not fixed by this. `natmod/options.py` must never import `usermod/options.py`
back (the one constraint this whole redesign has kept since Phase E), so natmod's own
`check_reachable()` has no equivalent widening available to it without either breaking that
direction or plumbing the union through `cli.py`/`platforms/__init__.py` instead (both
already import both families) -- a real, larger restructuring of *where* override
reachability is checked, not a small fix, and not what this session's live bug needed. Left
as task #66's own residual, tracked, not solved here.

Regression test: `test_reachability_audit_rejects_an_override_select_that_can_never_match`'s
sibling, `test_reachability_audit_allows_an_override_meant_only_for_natmod` -- the exact
repro (`[unix]` active, no `[natmod]` table at all, `select = "*-armv7emsp"`,
`extra-make-args` deliberately used since it is one of the few keys shared by both families'
own override schemas, to make sure the fix is about identifier reachability and not merely
about which key happened to be written). 424 tests pass; ruff and pyright clean; the exact
failing command from the live report re-run against a copy of this project's own real
`cibuildmp.toml` now exits 0.

## Addendum, 2026-08-27 — natmod's own identifier stops being rebuilt and starts being
matched: rows are the fact, `Target.identifier` looks one up instead of computing one

Raised directly by the user, live, against real CLI output: `mpy6.3-x86` etc. is the correct
string, but it was assembled by an f-string (`f"mpy{abi}-{arch}"`), never checked against
`resources/build-platforms.toml`'s own `identifier` field for that row -- which was itself
stale (`identifier_format = "mpy{mpy}-{tag}-{arch}"`, a pre-A2 shape that still spelled out
the tag A2 deliberately dropped). Confirmed directly against real cibuildwheel source (not
recalled, per this file's own first rule): `PythonConfiguration.identifier` is a **literal
field**, read straight off `resources/build-platforms.toml`'s own row
(`PythonConfiguration(**item) for item in config_dicts`, `cibuildwheel/platforms/linux.py`) --
never computed. cibuildmp's own natmod rows were regenerated to the current, tag-free format
(`identifier = "mpy{mpy}-{arch}"`, 205 rows, mechanical script); `Target.identifier` now looks
its base string up in `_IDENTIFIER_BY_ABI_ARCH` (keyed by `(abi, arch)`, built once from those
rows) and appends the config-driven `arch_flags` suffix on top -- the one part of the
identifier no row can pre-declare, since every row's own `arch_flags` column is `0`
unconditionally (confirmed by inspection: it never varied per row to begin with, so it was
never really an axis the data tracked).

**A second, larger correction followed from the same live conversation**: why does
`archs_available_for(tag)` (Phase C1's own per-tag arch-availability table) exist at all, if
matching real rows already answers "does this combination exist"? It existed because the old
design computed *before* selecting -- `tag_groups()` picked one newest tag per ABI, then
swept that tag's own available arches, intersecting against a purpose-built lookup table
*before* `select()`'s own glob ever ran. The user's own correction: collapse *after* matching,
not before -- `natmod_all_targets()` is now literally one `Target` per real `(tag, arch)` row
(the same shape cibuildwheel's own `get_python_configurations()` has: filter a literal row
list by `build_selector`, no parallel availability table at all), `select()` glob-matches
`build`/`skip`/`[[overrides]]` against that raw list exactly as it always has, and the new
`collapse_newest_tag()` runs **after** selection -- group survivors by `.identifier`, keep
whichever carries the newest `tag` (the actual checkout a build fetches). `archs_available_for()`,
`_TAG_ARCHS` and `natmod_targets()` (the function that needed the availability table to
validate a single tag's own requested arch list) are deleted outright as the exact "100500
checkers" class this correction removes -- dead once nothing calls them pre-selection, and a
duplicate of what row-matching-then-collapsing already gives for free. `known_abis()`,
`newest_known_abi()`, `abi_for_tag()`, `newest_tag_for_abi()`, `all_tag_groups()` all stay:
each answers a real, still-needed question (which ABI is newest for an unconfigured `build`
default, which tag a checkout should fetch) that is not itself an availability gate, and
nothing about this correction touches them.

`Options.tag_groups()` (the method, forwarding to `all_tag_groups()`) is deleted too -- its
only caller was `targets()`/`all_targets()`, both rewritten to no longer need it.

**Verified, not just asserted**: a full `Options.all_targets()` identifier snapshot taken
before this change and one taken after are byte-for-byte identical (42 identifiers, diffed),
and `cibuildmp --dry-run --platform natmod` against this repo's own real config produces the
exact same ten-line output before and after. 423 tests pass (one net fewer than before,
`natmod_targets()`'s own dedicated tests replaced by tests of `natmod_all_targets()`/
`collapse_newest_tag()`); ruff and pyright clean.

**Left open, correctly scoped as its own, larger piece, not attempted here**: usermod's own
side has the identical problem in a more literal sense -- `usermod_targets()` builds targets
from static Python axis-value lists (`_PORT_AXES`) cross-produced with freely-typed
`micropython` tags, consulting `resources/build-platforms.toml` not at all (Track C's own
Phase C2, tracked since before this addendum, still not started). Doing it properly touches
`auto`/`native`/`all` keyword expansion, the `unix-emulated-everywhere` opt-in group, and a
real data inconsistency this same investigation surfaced: `windows`'s own stored `arch` values
(`win32`/`win_amd64`/`win_arm64`) do not match the runtime's own (`x64`/`x86`/`arm64`,
`WINDOWS_ARCH_SETTINGS`), and `webassembly`'s stored rows carry an `arch = "wasm32"` axis the
runtime identifier does not (a bare `{tag}-webassembly`, no arch segment at all) -- both need
an explicit reconciliation decision, not a mechanical port of natmod's own fix.

## Addendum, 2026-08-27 — the immediately preceding addendum's own core claim reversed: tag
*is* part of natmod's identifier, live-corrected against real per-row evidence

The addendum directly above this one shipped `identifier = "mpy{mpy}-{arch}"` (no tag) and
`collapse_newest_tag()` to resolve the resulting ambiguity. Both are wrong, and both are
reverted here -- caught live by the user against the real, regenerated
`resources/build-platforms.toml`, not by re-deriving the shape from first principles a second
time. The concrete evidence: ABI `6.3` alone spans tags `v1.23.0` through `v1.30.0-preview` in
that file, and a tag-free identifier collapses every one of them onto one string per arch --
`mpy5-x86`, checked directly, actually names **seven** distinct real rows (`v1.12` through
`v1.18`), each a genuinely different MicroPython checkout with its own toolchain/ABI
particulars. `collapse_newest_tag()` existed only to paper over that collapse by picking one
survivor -- which is exactly the "match against fact, don't build/pick a fact" violation this
whole record argues against everywhere else. The other three examples the user gave, matched
directly against this project's own real rows, confirm there is no *uniform* rule to invent
either way (natmod always drops its own no-longer-existing `natmod` segment; unix and windows
never carry a `unix-`/`windows-` port prefix at all; qemu and webassembly do carry their own
port segment) -- each platform's own stored `identifier` is simply authoritative as written,
never rebuilt toward a shape that "looks more consistent":

- `identifier = "v1.20.0-manylinux_2_28_x86_64"` (unix -- no port prefix)
- `identifier = "v1.20.0-win32"` (windows -- no port prefix; the arch segment is the literal
  stored value `win32`, not the runtime's own current `x64`/`x86`/`arm64` spelling -- the
  windows/webassembly stored-vs-runtime arch-format mismatch the previous addendum's own
  closing paragraph already flagged as still open stays exactly that open)
- `identifier = "v1.24.0-qemu-MICROBIT"` (qemu -- does carry its own port prefix)

**The fix**: `resources/build-platforms.toml`'s natmod rows are regenerated a second time,
`identifier_format` restored to `"mpy{mpy}-{tag}-{arch}"` (205 rows, e.g.
`mpy6.3-v1.30.0-preview-armv7emsp`). `natmod/targets.py`'s lookup dict is rekeyed from
`_IDENTIFIER_BY_ABI_ARCH: dict[(abi, arch), str]` to `_IDENTIFIER_BY_TAG_ARCH: dict[(tag,
arch), str]` -- every `(tag, arch)` row is now a genuinely unique, unambiguous fact, so
`collapse_newest_tag()` is deleted outright rather than reworked; there is nothing left for it
to collapse.

**What replaces it is narrower than a collapse, not a rebuild of one.** The real question
`collapse_newest_tag()` was answering ("an unconfigured `build` should still resolve to one
tag per arch, not every tag this project has ever verified") only applies when the config's
own `build` selector never names a tag in the first place -- when it does
(`build = "mpy6.3-v1.23.0-*"`, or the reachability-audit test fixtures throughout this file
that pin a specific historical tag on purpose), every match is real config intent and must be
trusted as-is, not narrowed. Two small, direct functions carry this, replacing every "which
tag wins" design this record and its predecessor addendum explored (a `preread`-based
ambiguity check, an explicit `pick=` config key, a *hierarchical* tree-glob mechanism deep
enough to disambiguate tag from arch structurally -- all rejected in the same live exchange as
over-engineering a problem a two-line regex already answers):

```python
_TAG_SHAPE = re.compile(r"v\d+\.\d+(?:\.\d+)?(?:-preview)?")


def selector_names_a_tag(patterns: Sequence[str]) -> bool:
    """Does any build pattern literally name a tag-shaped substring? If
    so every match is real, deliberate config intent -- trust it as-is,
    the same way `mpy6.3-v1.23.0-*` naming an old tag on purpose already
    has to work."""
    return any(_TAG_SHAPE.search(p) for p in patterns)


def narrow_to_newest_tag(targets: Sequence[Target]) -> list[Target]:
    """Only called when build names no tag at all: group by (abi, arch,
    arch_flags), keep the newest tag per group -- today's zero-config
    behaviour ('build the current release'), now expressed as a plain
    post-selection filter instead of a pre-selection availability
    table."""
    ...
```

`UsermodOptions.targets()`'s own equivalent call site: `select(candidates, self.build,
self.skip)`, then `narrow_to_newest_tag(selected)` only `if not
selector_names_a_tag(self.build)` -- `all_targets()` (existence, not selection) stays
untouched, exactly as `collapse_newest_tag()` never touched it either. `default_build` reverts
to the simple, tag-free `f"mpy{newest_known_abi()}-*"` it had before the previous addendum
pinned an explicit tag into it -- the general mechanism now does what the explicit pin was
working around.

**Ripple, mechanical**: every test asserting a bare `mpy6.3-x64`-shaped identifier now needs
the real tag included (`mpy6.3-v1.30.0-preview-x64`) -- `tests/test_targets.py`,
`tests/test_selector.py`, `tests/test_build.py`, `tests/test_options.py`, `tests/test_cli.py`,
`tests/test_cli_multi_platform.py`. One fixture needed more than a string update:
`test_only_overrides_skip_for_print_build_identifiers` used `skip = "mpy6.3-x64"` (bare, no
wildcard) to prove `--only` overrides `skip` -- under the tag-included identifier space that
exact literal string now matches nothing at all (the reachability audit correctly flags it:
`skip: 'mpy6.3-x64' matches no known identifier`), so the fixture's own `skip` pattern became
the broader `"*-x64"`, which reaches every tag's own x64 row regardless of which one `--only`
names, preserving the test's actual intent rather than papering over a selector that no longer
means what it used to.

**Verified, not just asserted**: `Options.load('.', preread=(None, {})).targets()` against
this repo's own zero-config default produces exactly ten targets, each a real
`mpy6.3-v1.30.0-preview-{arch}` identifier; `--dry-run --platform natmod --only
"mpy6.3-v1.23.0-x64"` (a selector that does name a real historical tag) resolves to exactly
that one target, proving the trust-as-is branch works, not just the narrow-to-newest branch.
Full suite green (423 passed), ruff and pyright clean.

## Addendum, 2026-08-27 — `[override]`, not `[[overrides]]`: the override table is keyed by
its own glob directly, syntax simplified below what upstream's own shape needs here

The still-open question this record's own "Not decided" section (Track B, above) left hanging
-- whether `[[overrides]]`'s own `select`-glob mechanism survives as-is, gains a tree-path
mode, or gets a residual flattened-string fallback -- is closed here, and closed toward the
simplest of the three, not the most upstream-faithful one. Track B's own tree-walk mechanism
(B4.1-B4.3, built and reverted the same day, per this file's own earlier addendum) already
established live that cibuildmp's identifiers have no real nesting depth for a path glob to
address that a flat glob does not already reach just as well (`*-esp32-*` already matches
every esp32 board without a tree). The same live conversation went one step further, applied
to `[[overrides]]`'s own TOML *syntax* rather than its matching semantics: an array of tables
each carrying a separate `select = "..."` field is doing more work than this project's own
override space needs, when the array index carries no meaning and the table's real identity
*is* the glob it selects on.

**The change**: `[[overrides]]` (an array, each entry `{select = "glob", ...options}`) becomes
`[override]` (one table, keyed directly by the glob itself -- `[override."*-armv7emsp"]`
holding `...options` straight, no `select` field inside). This is a real divergence from
upstream's own `[[tool.cibuildwheel.overrides]]` shape, argued and decided rather than
inherited by default (per this project's own first rule: cibuildwheel was read, not
paraphrased, before diverging) -- upstream's own array-of-tables makes sense there because an
override's own identity is genuinely secondary to its position (upstream selectors can be
compound boolean expressions, not always a single glob); cibuildmp's own overrides have always
been "one glob, some options" with nothing else in an entry's own identity, so the glob can
simply *be* the table's name.

**Precedence is unaffected, because nothing about how it worked changes.** `[[overrides]]`
never had explicit priority rules beyond file order (`matching_overrides()` walks the list in
declaration order; `override_extra_layers()`/`resolve_cascade()` treat the last matching
layer as the one that wins, `inherit="none"`'s default fully replacing the running value). A
TOML table's own keys parse into a plain `dict` (`tomllib`, insertion-ordered since the
grammar itself does not permit reordering a document's own keys), so `[override]`'s
declaration order carries exactly the same meaning `[[overrides]]`'s array order did -- a
narrower, more specific glob written further down the file still wins over a broader one
written above it, with **no separate depth/specificity mechanism needed or built**. This was
floated directly and rejected in the same exchange: a scheme that sorts overrides by selector
specificity (segment count, wildcard position, whatever) would be exactly the kind of "smart
multi-level selector" machinery this project keeps deliberately not building --
`build`/`skip`/`select` are plain `fnmatch` globs precisely because a config author who wants
narrower-wins-over-broader can already get it for free by writing the narrower one later,
`git blame`-legible and requiring zero new code.

**Mechanically, the change is small.** `natmod/options.py`'s `load_overrides()` is the only
function that changes shape -- it now reads `raw.get("override")` (a dict) instead of
`raw.get("overrides")` (a list), and for each `(glob, body)` pair builds the exact same
`{"select": glob, **body}` dict the rest of the mechanism (`matching_overrides()`,
`override_extra_layers()`, `check_reachable()`, `build_options()`'s own tier-2 check) already
consumed unchanged -- none of those four needed to change at all, since the normalized
in-memory shape never did. A `select` key surviving inside an override's own body is a new,
explicit parse-time error (it would only duplicate the table's own name and silently shadow
it otherwise). `cli.py`'s own `_reject_unknown_tables()` gains `"override"` alongside
`"publish"`/`"usermod"` in `_NON_PLATFORM_TABLES`, since `[override]` is now a dict-valued
top-level key exactly the shape a real platform table has, and would otherwise misfire the
unknown-top-level-table check that exists to catch a typo'd platform name.

**Verified**: every existing `[[overrides]]`-shaped test fixture across
`tests/test_options.py`, `tests/test_usermod_options.py`, and `tests/test_overrides.py`
rewritten to `[override."glob"]`, no assertion changed in substance (only the two error
messages that named `[[overrides]]`/an array index directly, now naming the glob itself,
which is if anything a more useful error). This repository's own real `cibuildmp.toml`
rewritten to the new syntax and loaded live end to end -- `Options.load(Path('.'),
env={}).overrides` returns the same normalized shape as before, and
`build_options()` for the `armv7emsp` target still resolves `MP_BCLIBC_PRECISION=single`
correctly through it. Full suite green (423 passed), ruff and pyright clean.

## Addendum, 2026-08-27 — `archs` is gone as a config concept entirely: it duplicated
exactly what `build`/`skip` already expresses

Raised live, prompted by the root `cibuildmp.toml`'s own `[natmod] archs = [...]`
line: with every real natmod arch listed (all ten `dynruntime.mk` values), that line
was the config's own default, spelled out in full, doing nothing at all -- the most
literal possible demonstration of the user's own complaint. `archs` filtered
`natmod_all_targets()`'s own candidate rows by `.arch` alone, **before** `build`/`skip`
ever ran (`candidates = [t for t in natmod_all_targets(arch_flags) if t.arch in
self.archs]`) -- a second, parallel selection mechanism narrowing exactly the same
axis a `build`/`skip` glob over the identifier already reaches directly (`build =
"*-x64"`, or `"mpy6.3-*-x64"` to also pin the ABI). Removed outright, not
deprecated, the same treatment `collapse_newest_tag()` got two addenda up: a second
way to say the same thing is the thing this record keeps arguing against, whichever
direction it points.

**Mechanically:** `Options.archs` (the field), `archs_value` (the cascade lookup in
`load()`), `"archs"` from `NATMOD_SCHEMA`, and `validate_archs_recognized()`
(`natmod/targets.py`, now dead -- its own job, catching an arch `dynruntime.mk` has
never heard of, is already covered by `check_reachable()`'s existing "pattern matches
no known identifier" audit, one level up at the selector-string level) are all gone.
`targets()` now builds `candidates = natmod_all_targets(arch_flags)` directly, with
no arch pre-filter at all -- `build`/`skip` are the only selection mechanism left,
for every axis natmod has.

**`--archs` on the CLI is natmod's one real, honest capability loss** -- there is no
`--build`/`--skip` CLI flag to fall back on (only the config file and
`CIBMP_BUILD`/`CIBMP_SKIP`), and no safe way to translate an arbitrary CLI arch list
into an equivalent `build`/`skip` glob rewrite: the flag's own contract was to
*replace* the archs axis wholesale while leaving `build`/`skip`'s own ABI/tag
narrowing untouched, and mechanically reconstructing that as a glob transform on top
of whatever `build` pattern a config already has (which may itself already carry an
arch segment, brace groups, or no wildcard at all) has no single, generally-correct
answer -- exactly the kind of clever synthesis this whole record keeps rejecting in
favor of writing the glob directly. Rather than ship something fragile, natmod's own
`resolve_options()` now raises a specific, actionable `ConfigError` naming the
replacement (`build`/`skip`, or `CIBMP_BUILD`/`CIBMP_SKIP`) the moment `--archs` is
passed for a natmod invocation -- loud, not silent, the same 0048-era guarantee
every other retired config surface in this project gets. `--archs` is unaffected for
usermod ports (`archs`/`boards` stay real per-port axis keys there, untouched by this
addendum).

**Ripple:** every fixture across `tests/test_options.py`, `tests/test_cli.py`,
`tests/test_cli_multi_platform.py` and `tests/test_overrides.py` that used
`[natmod] archs = [...]` as its minimal natmod config rewritten to a `build` glob
instead (`mpy{abi}-*-{arch}`, brace-expanded for more than one arch; `rv32imc` gets a
trailing wildcard to still reach its own `+0x..`-suffixed rows) -- most fixtures that
only needed *some* deterministic natmod target dropped the arch narrowing
entirely, since removing `archs` means nothing left to narrow by default either.
`test_archs_stays_dual_read_and_is_not_flagged` (proving dual-read worked) is
replaced outright by `test_archs_is_gone_as_a_config_key` (proving the opposite: it
is now a loud "unknown key" error). `test_bad_arch_is_an_error` now exercises the
reachability audit directly, with a real gotcha caught while writing it: a
brace-expanded pattern (`"mpy6.3-*-{x64,aarch64}"`) is checked as **one** whole
pattern string by `check_selector_reachable()`, and passes reachability on the `x64`
alternative alone -- hiding the `aarch64` typo entirely. The fix is two
space-separated patterns instead of one brace group, matching how
`check_selector_reachable()` actually iterates `parse_selector()`'s own list.

A second, unrelated gotcha surfaced fixing `tests/test_cli_multi_platform.py`:
`build`/`skip` are dual-read (global default, per-platform override, more-specific-
wins) across *every* active platform, natmod and usermod ports alike -- setting
`build` at the bare top level to narrow natmod's own default to one arch silently
became unix's own default `build` too, in every fixture spanning `[natmod]` +
`[unix]` in one invocation, since unix's own cascade reads the same top-level key
when its own `[unix]` table sets nothing. The fix is scoping the override inside
`[natmod]` specifically, not the top level -- the same "more specific wins" rule
`[natmod] build = "..."`/`[unix] build = "..."` already documents, just easy to
forget when writing a fixture meant for one platform only.

Two corrections to the previous addendum's own claims, from the same live
conversation: "unix identifiers carry `-unix-` as a stable literal substring" is
false -- the real, confirmed identifier is `v1.20.0-manylinux_2_28_x86_64` (no
`unix` segment at all; the correct unique marker is `manylinux`/`musllinux`, unix's
own libc tags). And "unix is special in having a marker at all" overstates it --
every platform has its own (`win32` for windows, `webassembly` for wasm, the `mpy`
prefix for natmod); unix is not an exception, its marker is just spelled
differently than a literal port name.

**Left open, raised in the same conversation, not yet acted on:** the same argument
extends one level further, to the cascade's own `platform_tables` tier for the
override-able option keys (`module-dir`/`make-target`/`extra-make-args`/
`pre-build-command` for natmod; `user-c-modules`/`manifest`/`extra-make-args` for
usermod ports) -- `[unix] user-c-modules = "..."` is exactly `[override."*-{manylinux,
musllinux}*"] user-c-modules = "..."` restated, the identical "two ways to say the
same thing" shape this whole addendum just removed for `archs`. Not designed or
implemented yet -- the next piece of work this record's own thread points to.

Full suite green (423 passed after the rewrite), ruff and pyright clean. Live
smoke-tested against the real root `cibuildmp.toml` (now with no `archs` line at
all) -- byte-identical ten-target `--dry-run` output before and after -- and against
both `--archs`'s new failure mode for natmod and its unaffected usermod path.

## Addendum, 2026-08-27 — `platform_tables` retracted entirely: a per-platform TOML
table was always a sufficiently-scoped global (or `[override]`) value restated

The same live conversation, extended one tier further: `[unix] user-c-modules =
"..."` is exactly `[override."*-{manylinux,musllinux}*"] user-c-modules = "..."`
restated, for the identical reason `archs` above was removed -- every platform's
own real identifier already carries a marker (`manylinux`/`musllinux` for unix,
`win32` for windows, the literal `mpy` prefix for natmod, `qemu-`/`esp32-` port
segments for those two) a `build`/`skip` glob or an `[override]` selector can
already address directly, so a *third* place to write the same value (a
per-platform table, sitting between global and `[override]`) is the identical
"two ways to say the same thing" shape this whole record keeps refusing to build.
Retracted: the "per-platform build/skip" addendum (`docs/records/0048`'s own,
cross-referenced from here) and Phase F's own per-platform option-key wiring both
land back where 0048 originally put `build`/`skip` -- global-only -- joined now by
every option key that previously lived in a platform table at all.

**What is *not* retracted, on direct instruction:** `[usermod]`, the family tier
sitting between global and (the now-gone) per-platform table. It was added at the
user's own explicit insistence (record 0051's ninth addendum) specifically because
a family-wide usermod default distinct from natmod's own global default is a real,
still-load-bearing distinction `extra-make-args` genuinely needs (natmod and every
usermod port both read that one key by the same name) -- retracting the tier
sitting *below* it (per-platform) does not retract this one. Also not retracted:
the per-platform *environment* override (`CIBMP_BUILD_NATMOD`,
`CIBMP_MODULE_DIR_NATMOD`, ...) -- a real, distinct capability (a one-off CI
override with no config-file edit at all) untouched by the TOML-redundancy
argument above, and still reachable through `Options.get()`'s own `platform=`
parameter, which no longer selects a table at all, only the env var's own name.

**Mechanically:** `cibuildmp/options.py`'s `Options` dataclass loses its
`platform_tables` field outright (a `platform_tables=` constructor keyword is now
a plain `TypeError`) and the platform-tier lookup layer inside `.get()`; the
method's own precedence collapses to `default -> global -> family -> env ->
env(platform) -> extra_layers`. `natmod/options.py`'s `NATMOD_SCHEMA` -- the set
of keys `[natmod]` itself may carry -- is now empty: `[natmod]`'s own presence
still matters (platform activation, unchanged), its *content* does not, any more.
`GENERIC_KEYS` grows to include `build`/`skip`/`extra-make-args` (truly shared,
identically named and meant on both sides); a new `NATMOD_ONLY_GENERIC_KEYS`
(`arch-flags`/`module-dir`/`make-target`/`pre-build-command`) and
`usermod/options.py`'s own new `USERMOD_ONLY_GENERIC_KEYS`
(`user-c-modules`/`manifest`) hold the keys that are generic *to one side* but
would misleadingly imply a top-level meaning to the other (natmod has no
`user-c-modules` key at all, usermod has no `module-dir`). `check_keys()` gained
an `extra_generic` parameter for exactly this split, defaulting to empty (every
existing call site's behaviour is unchanged unless it opts in) -- the two calls
that validate a platform's own table (`[natmod]`, each `[<port>]`) are the only
ones that pass one, turning a stray `[unix] user-c-modules = "..."` into a
specific "move it to the top level" redirect instead of a bare "unknown key".
`usermod/options.py`'s own `SCHEMAS[port]` shrinks to just that port's own axis
key (`archs`/`boards`) -- nothing else is legal inside a port's own table any
more. `_port_build_skip()` (usermod) keeps its exact shape -- it was already only
ever reading through the cascade's own `platform=` parameter, which now silently
degrades to "env-only," no code change needed beyond the docstring.

**A real gap surfaced, not fixed here, the same shape as task #66's own residual
half:** `check_reachable()` (both sides) validates every `build`/`skip`/
`[override]` selector against *that family's own* identifier universe only.
With `build`/`skip` now genuinely global (shared by every active platform in one
invocation), a single pattern meaningful to one platform but not another --
`build = "mpy6.3-*-x64"` when `[natmod]` and `[unix]` are both active -- fails
unix's own reachability check, which has no way to know the pattern was never
meant for it. This is *not* the already-fixed direction (usermod's own
`check_reachable()` already widens for `[override]` using natmod's own
`all_targets()`, since usermod may import natmod) -- it is the mirror, natmod-side
gap that direction's own fix explicitly left open, now reachable through
`build`/`skip` too, not just `[override]`. `CIBMP_BUILD_NATMOD`
(the retained per-platform env tier, see above) is today's real answer for
"restrict one of several simultaneously-active platforms without touching the
others" -- proven live in `tests/test_cli_multi_platform.py`'s own multi-platform
fixtures, rewritten onto it. Left open, not scheduled, same residual-task shape as
#66's own natmod-side half.

**Ripple:** every fixture across `tests/test_options.py`,
`tests/test_options_cascade.py`, `tests/test_overrides.py`,
`tests/test_usermod_options.py`, `tests/test_usermod_orchestrate.py` and
`tests/test_cli_multi_platform.py` that wrote an option key inside `[natmod]` or a
usermod port's own table moved that key to the top level (or, for
`tests/test_overrides.py`'s own cross-family composition test, re-expressed as a
platform-scoped `[override]` entry instead, matching a `mpy*`/manylinux-marker
glob directly, with the underlying `Target`/`UsermodTarget` constructed by hand
rather than resolved through `.targets()` to sidestep the still-open reachability
gap just described -- that gap is not what the test is about). Several tests whose
entire premise was "a per-platform table beats the top level" were replaced
outright with tests proving the opposite (a loud, specific redirect error), the
same treatment `test_archs_is_gone_as_a_config_key` already got one addendum up.

Full suite green (421 passed, two fewer than before -- two now-inverted-premise
tests replacing, not joining, the ones they superseded), ruff and pyright clean.

## Addendum, 2026-08-27 -- table-presence activation, `--platform`/`--only`/
`--archs`'s `auto`/`native`/`all`, and `enable`/`GROUPS` all retracted in one
round; Track C's own Phase C2 (usermod real rows) finally lands; the
cross-family reachability gap (task #66's own residual half) fully closed;
zero-config now genuinely builds nothing; `--build`/`--skip` added to the CLI

The single largest round this record has seen, and the one that finally
answers the question its own title asks: **cibuildmp's config is not a
selector matrix, and by the end of this round it stops pretending to be
one anywhere at all.** Every remaining structural element that let a
config *select which platforms are in scope* -- `[natmod]`/`[unix]`/
`[windows]`/`[qemu]`/`[webassembly]`/`[esp32]` as tables, `--platform`/
`CIBMP_PLATFORM`, `--only`, `--archs auto`/`native`/`all`, `enable`/
`GROUPS` -- is retracted, live, in one continuous session, each step
confirmed explicitly before being built rather than assumed. What
remains, stated in full: **`build`/`skip` glob-matching a real
identifier, `[usermod]`'s own shared defaults, global option keys, and
`[override."<glob>"]`. Nothing else.**

**Trigger.** The user pointed at this repo's own root `cibuildmp.toml`'s
`[natmod] archs = [...]` block -- the same shape [0052]'s own earlier
addendum had already found and deleted once for natmod specifically --
and asked directly whether the whole table-presence-activation model
should go the same way `archs`/`platform_tables` already had: "Я просто
думаю взагалі обійтись без каскадів коли достатньо лише глоб і
оверрайдів" (musing, not yet a directive), then, after the zero-config
question was settled explicitly ("має ПЕРЕСТАТИ будувати щось за
замовчуванням... так пустий конфіг не білдить НІЧОГО взагалі"),
confirmed the full scope directly: "Конфіг НЕ МАЄ більше [unix] без
всяких axis, є лише глоби і оверрайди - все елементарно", "--archs
auto/native/all - нахрін не треба", and, closing the loop on my own
open design question about `GROUPS`/`--enable`: "Без ніяких додаткових
механізмів, --build/--skip + global keys + override.glob keys".

### Zero-config builds nothing

`selector.select()`'s own `build_patterns = parse_selector(build) or
["*"]` fallback -- the actual mechanism behind "an empty config still
builds everything" -- is gone: `parse_selector(build)` alone, an empty
list, and `matches()`'s own `any(...)` over it correctly returns
`False`. Both `Options.load()` (natmod) and `UsermodOptions.load()`
(usermod) resolve `build`/`skip` with `default=""` now, not a computed
"narrow to the newest known ABI" (natmod) or `"*"` (usermod, pre-existing
from before this record). This is the single root-cause line; everything
else in this addendum either depends on it or follows from removing the
same "give the user something sensible with no config" instinct
elsewhere.

### Every per-platform table retracted; candidates = every real row, always

`[natmod]` carried zero settable keys already (a previous addendum
emptied `NATMOD_SCHEMA`); its only remaining job was activation. That
job is gone too -- `Options.load()` now rejects `[natmod]` outright with
a `ConfigError` naming the real replacement, and `cli.py`'s own
`_validate_top_level_tables()` catches it even earlier, before any
family-specific loading runs. `[unix]`/`[windows]`/`[qemu]`/
`[webassembly]`/`[esp32]` are retracted the same way, for the same
reason: once every real `(port, tag, arch/board)` combination is read
directly from `resources/build-platforms.toml` as a candidate row,
*always*, a per-port table has nothing left to select or configure --
its own axis (`archs =`/`boards =`) duplicated exactly what a `build`/
`skip` glob over the real identifier already expresses, the identical
argument that already killed natmod's own `archs` key one addendum
earlier, now applied to every remaining table at once. `[usermod]` is
**not** one of the six -- it survives, unaffected, as usermod's own
shared-defaults tier (record 0051's ninth addendum, reaffirmed through
every round of retraction this record has produced): it gates nothing,
so nothing about this round's own reasoning touches it.

This closes **Track C's own Phase C2**, open since this record's very
first version: usermod gets the identical real-row model natmod's own
Phase C1 already had. `cibuildmp/platforms/usermod/targets.py` is
rewritten around `all_usermod_targets()`, one `UsermodTarget` per real
row in `resources/build-platforms.toml["usermod"][port]["identifiers"]`
for every port in the newly-constant `KNOWN_PORTS = ("unix", "windows",
"qemu", "webassembly", "esp32")` -- the five with a real `build_<port>()`
driver; the other ten ports the same resource file already has verified
rows for (`rp2`, `mimxrt`, `samd`, `stm32`, `psoc-edge`, `alif`,
`esp8266`, `cc3200`, `renesas-ra`, `nrf`) are a separate, much larger
piece of unstarted work -- writing each one's own build pipeline -- not
a config-surface gap this round could close by itself (the user's own
words, mid-session: "Набагато важливішим і складнішим буде дописати
решту білд пайплайні для всього списку фактів"). `_PORT_AXES`,
`archs =`/`boards =` config, `axis_key()`/`all_axis_values()`/
`default_axis_values()`/`parse_axis_values()`, `GROUPS`, `ARCH_KEYWORDS`
and every keyword-expansion helper (`host_arch()`, `resolve_axis_keyword()`,
`_NATIVE_SIBLINGS`, `_MACHINE_ALIASES`, `_ARCH_OCI_PLATFORMS`) are all
deleted outright, not deprecated.

**A real, live-caught fact this rewrite surfaced, previously tracked
only as tracker item #54's own unread note:** `resources/build-platforms.
toml`'s own `identifier_format` is not uniform across usermod ports.
`unix`/`windows`/`webassembly` carry no port name at all
(`"{tag}-{arch}"`, e.g. `v1.20.0-manylinux_2_28_x86_64`); `qemu`/`esp32`
do (`"{tag}-{port}-{board}"`, e.g. `v1.24.0-qemu-MICROBIT`). The
pre-rewrite `UsermodTarget.identifier` property unconditionally built
`f"{tag}-{port}-{arch}"` -- meaning every `unix`/`windows`/`webassembly`
identifier this project ever printed, matched, or built against was
wrong relative to the file's own recorded ground truth (`unix-manylinux_
2_28_x86_64` instead of the real `manylinux_2_28_x86_64`), silently, the
whole time. Fixed the identical way natmod's own analogous bug was fixed
two addenda ago: `UsermodTarget.identifier` now looks its value up from
a real `(port, tag, arch/board) -> identifier` table built straight from
the resource file, for every tagged target -- never reconstructed by an
f-string. A hand-built, tag-less `UsermodTarget` (most existing
build/orchestrate tests, which are about build mechanics rather than
real-row verification) still falls back to the old `{port}-{arch}`
shape, which is what let the large majority of `tests/
test_usermod_orchestrate.py` pass completely unchanged.

Usermod needs no `narrow_to_newest_tag()` equivalent, unlike natmod:
natmod's identifier leads with an ABI that several distinct MicroPython
tags can share, so an ABI-only glob needs disambiguating; a usermod
identifier's own leading tag already names one exact release with
nothing left to disambiguate (`unix`/`windows`/`webassembly`) or is
matched against a real, explicit `(tag, board)` pair directly (`qemu`/
`esp32`). The `micropython = [...]` config key -- usermod's own
tag-list axis, closed for truncation by record 0051 -- is retracted for
the same reason `archs` was: candidates are every real row, always;
`build`/`skip` glob-matching the tag is what narrows them now, mirroring
natmod's own A2 retraction exactly. `DEFAULT_MICROPYTHON` becomes dead
code in `natmod/options.py` (it was already unused there since A2; this
removes its last real consumer) and is deleted.

### `--platform`/`--only`/`--archs auto`/`native`/`all`/`--enable` all removed from the CLI

`cli.py` loses `active_platforms()`, `_parse_platform_names()`,
`ALL_PLATFORMS`, `_reject_unknown_tables()`, and the `--platform`/
`--only`/`--enable`/`--archs` argparse entries -- every one of them
existed to resolve or narrow which platforms were in scope, a question
that no longer has a nontrivial answer (every platform always is).
`platforms/__init__.py`'s `PLATFORM_FAMILY: dict[str, PlatformModule]`
(keyed by six platform names, for `--platform` lookups) becomes
`FAMILIES: tuple[PlatformModule, ...] = (natmod, usermod)` -- a fixed,
two-element tuple, since there is no longer any name to look one up by.
Both family modules lose their own `ports: list[str]` parameter on
`resolve_options()`/`run()` for the identical reason (natmod's own
`ports` was always `["natmod"]`; usermod's is always the constant
`KNOWN_PORTS`).

`--build`/`--skip` are new CLI flags, replacing `--only`/`--platform` as
the "build exactly this one thing" / "spread work across a CI matrix by
hand" mechanism: same glob syntax as the config's own `build`/`skip`,
applied as a straight override of `options.build`/`options.skip` inside
each family's own `resolve_options()`, after `.load()`. `--archs` (with
its `auto`/`native`/`all` keyword vocabulary, record 0049's own answer
to "how does cibuildmp spread work across CI runners without generating
a matrix") and `--enable` (record 0051 point 8's own `GROUPS` opt-in
mechanism) are removed outright, not folded into `--build`/`--skip`:
everything either one could reach, an ordinary `build`/`skip` glob
against the real identifier already reaches directly, and a named-group
opt-in is exactly the kind of second, parallel selection mechanism this
whole round's own argument keeps landing on. `selector.select()` drops
its own `enable`/`groups` parameters entirely as a result -- the
mechanism this record's own predecessor (record 0051 point 8) added is
now fully retracted, not merely unused.

**A genuinely new capability was required, not just a subtraction, to
make this land without a UX regression:** every family is now always
resolved, every invocation -- `cli.py`'s own `_resolve_all()` calls
`resolve_options()`+`.targets()` for every entry in `FAMILIES`
unconditionally, no longer gated by which tables a config happens to
write. The old per-family "no targets selected -> error" check, which
used to make sense because a family only ran when its own table said to,
would misfire constantly under this model: a config that only ever
configures natmod's own `build` (the ordinary case) would leave
usermod's own `build`/`skip` unset, which now, correctly, selects
nothing from usermod -- and reporting that as an error would make every
single-family config need `--allow-empty` to work at all. Fixed by
moving the "nothing at all was selected" decision to `cli.py`'s own
coordinator, checked **once**, jointly, across every family's own
selected-target count; a family with zero selected targets while another
has some is silently skipped in the real-build/`--dry-run` dispatch loop
that follows, not reported as its own error. Each family module's own
`run()` (still the full single-family flow, used directly by tests) is
split into `resolve_options()` (unchanged shape) + a new `run_resolved()`
(the `--dry-run`/build tail, given an already-nonempty target list) so
`cli.py`'s coordinator can call the latter directly without re-deriving
the "no targets" check per family. Each module also now exports
`LOAD_ERRORS`/`BUILD_ERRORS` tuples so the coordinator can catch each
family's own exception hierarchy by name without importing either
module's exception classes directly -- exception handling stays
deliberately un-unified across families (documented, unchanged reasoning
from `platforms/__init__.py`'s own docstring), this is only how the
*coordinator* participates in that split.

### The cross-family reachability gap (task #66) closed, both directions, for real

Every previous addendum in this record left half of this gap open,
explicitly, because closing the natmod-side half would have needed
natmod to import usermod -- a one-way dependency this project has never
crossed. That constraint still holds; what changed is *where* the fix
lives. `Options.targets()` (natmod) and `UsermodOptions.targets()`
(usermod) both gained an optional `foreign_identifiers: Sequence[str]`
parameter, threaded into `check_reachable()`'s own widened domain for
`build`/`skip`/`[override]` reachability. `cli.py`'s own `_resolve_all()`
-- since it already sees every family, being the sole caller with that
vantage point -- resolves every family's own `all_targets()` first, in
a separate pass, then calls each family's own `.targets(foreign_identifiers
=<every other family's own identifiers>)` in a second pass. Natmod never
imports usermod; it simply receives what it needs as a parameter from
the one caller positioned to supply it. Usermod's own pre-existing
`_foreign_override_identifiers()` (the reload-based widening this record's
own earlier addendum built for a *direct*, cli.py-bypassing caller) is
kept, unioned with the explicit parameter rather than replaced by it, so
a standalone `UsermodOptions.load()` caller (most tests) keeps its exact
prior widening for free.

This was not a nice-to-have found in review -- it was a **hard
regression this round's own live smoke test hit immediately**: with
`build`/`skip` global and every family always resolved, `build =
"mpy6.3-*-x64"` alone (an entirely ordinary, natmod-only config) failed
outright with `[unix] build: 'mpy6.3-*-x64' matches no known identifier`,
since unix's own `check_reachable()` had no way to know the pattern was
never meant for it. Every previous addendum's framing of this gap as "a
real, separately-tracked, deliberately-scoped-out issue" stops being
accurate the moment table-presence activation is gone: what used to be
an edge case (both families explicitly activated in one config, a real
but uncommon shape) becomes the universal case (both families are always
"activated"), so the fix that was deferred three times in a row became
load-bearing on the very first manual smoke test this round ran.

### `narrow_to_newest_tag()`: a stable release now always beats a preview sharing the same ABI

A separate, later live finding, also user-driven: with the zero-default
retraction meaning an unpinned `build = "mpy6.3-*"`-style glob is now
the *only* way most configs will ever resolve a tag, which tag it
resolves to matters more than it used to. `newest_tag_for_abi("6.3")`
(and, through it, the pre-existing `narrow_to_newest_tag()`) picked
`v1.30.0-preview` over `v1.29.0` purely by version-number recency --
correct as "the newest thing", wrong as "the newest thing safe to build
against by default": a preview tag is, definitionally, less verified
than a real release sharing the same ABI, and `--archs auto`'s own
removal (see above) means there is no longer a keyword-driven fallback
path that would have made this less consequential. `narrow_to_newest_tag()`
now prefers a stable release over a preview within the same `(abi, arch,
arch_flags)` group, even a numerically older one, only falling back to a
preview when a given group has no stable candidate at all (an ABI walked
so far only against an in-progress preview). `newest_tag_for_abi()`
itself is unchanged -- still the true newest, preview included -- since
it answers a different question (`all_tag_groups()`'s own domain
enumeration) that this correction does not touch; a new
`newest_stable_tag_for_abi()` is the one that mirrors the corrected
`narrow_to_newest_tag()` behaviour, exported for tests and any future
caller that needs "what would an unpinned build glob actually resolve
to" without duplicating the preference logic. Decided live via
`AskUserQuestion` after the user raised the concern directly and I
proposed the narrower fix (skip previews when a stable alternative
exists) over the broader one floated first (always prefer the oldest
known tag) -- the user's own reasoning ("dynruntime важливіший і
автовибір тегу може не спрацювати") was about *tag stability*
specifically, which the narrower fix addresses without giving up "the
current release" as the ordinary-case default the way an oldest-tag rule
would.

### TOML migrations and CI wiring

Every live config this repo owns is migrated in the same round, not
left for a follow-up: the root `cibuildmp.toml` (reference example --
`build = "mpy6.3-*"` replaces the old implicit default, `[natmod]`'s own
keys promoted to the top level), `examples/template/cibuildmp.toml` (one
`build` glob spanning natmod's own ten arches plus real unix/windows/
webassembly cells, `micropython = "v1.29.0"` removed, `skip` excluding
the six emulated-everywhere cells explicitly now that `GROUPS` cannot do
it implicitly), and `examples/wasm2mpy/cibuildmp.toml` (`[natmod] archs
= [...]` becomes a flat `build` glob, pinned to a literal stable tag
rather than a bare ABI wildcard -- a second, independent application of
the same stable-over-preview reasoning above, since `mpy6.3-*` would
otherwise have let this dynruntime-sensitive integration test drift onto
`v1.30.0-preview` unnoticed). `action.yml`'s own `only`/`archs` inputs
become `build`/`skip`, mapped straight to the CLI flags of the same
name. `.github/workflows/build-examples.yml`'s `CIBMP_PLATFORM=natmod`/
`=unix,webassembly,windows` env vars and `archs: auto`/`only: <name>`
action inputs are replaced with explicit, per-runner `build` globs (one
matrix leg's own native cells spelled out by hand, since there is no
more keyword vocabulary computing them) -- verified live, not just
read: every rewritten config's own `--print-build-identifiers --json`
output checked directly against the exact identifier set the old
mechanism used to produce.

### Ripple and verification

Every test file touching `[natmod]`/`[unix]`/`[esp32]`/etc. tables,
`archs=`/`boards=`/`micropython=` config, `--platform`/`--only`/
`--enable`/`--archs`, or `GROUPS`/`ARCH_KEYWORDS` needed rewriting:
`tests/test_active_platforms.py` deleted outright (its entire subject,
`active_platforms()`, no longer exists); `tests/test_cli_multi_platform.py`
renamed to `tests/test_cli_multi_family.py` and rewritten around the new
always-both-families model; `tests/test_usermod_targets.py`,
`tests/test_usermod_options.py` rewritten around real rows and build-glob
narrowing; `tests/test_cli.py`, `tests/test_overrides.py`,
`tests/test_options.py`, `tests/test_selector.py` fixed for zero-default,
`[natmod]` rejection, the retired `enable`/`groups` `select()` parameters,
and the stable-tag preference; `tests/test_usermod_orchestrate.py` needed
only two identifier-format fixes (tagged `UsermodTarget` construction),
confirming the "hand-built, tag-less falls back to the old shape"
compatibility choice did its job.

Full suite green (357 passed), ruff and pyright clean. Live smoke-tested
directly, not just via the hermetic suite: zero-config both dry-run and
`--print-build-identifiers` correctly report "no targets selected"/empty
output; a natmod-only `build` glob resolves and dry-runs correctly
without touching usermod; a combined natmod+usermod `build` glob in one
invocation resolves both families' own identifiers with no reachability
false positive (the exact regression described above, re-verified fixed
after the `foreign_identifiers` change); `--build`/`--skip` CLI overrides
work standalone and in combination; every migrated example config
(`examples/template`, `examples/wasm2mpy`, root `cibuildmp.toml`)
resolves its own real identifier set correctly, including both
`build-examples.yml` matrix legs' own per-runner `build` glob.

**Explicitly out of scope for this round, left as tracker items:** the
ten usermod ports `resources/build-platforms.toml` already has verified
rows for but no real `build_<port>()` driver -- flagged by the user
directly as the genuinely larger remaining piece of work, not touched
here; and A6's own docker-image-resolver redesign.

**Decided, not implemented:** the "defaults themselves as a built-in
lowest-priority `[override."*"]` entry" idea, floated earlier in the same
conversation that produced this whole round, is rejected outright by the
user's own explicit call once the rest of this round had landed --
"defaults як `[override."*"]` - зайве" (redundant/unnecessary). `default=`
stays a real, distinct parameter on `Options.get()`, not folded into the
override mechanism. Closing this is what lets [0052]'s own status move
past "the divergence itself is argued and decided, with unresolved
sub-questions" -- only A6 and the unwired usermod ports remain open, and
neither is a config-*shape* question this record's own title is about.

[0051]: 0051-usermod-identifiers-have-no-version-axis.md

# 0051 — one selector for both modes, and an identifier that names what a build is compatible with

Status: In progress — Shape points 1/2/3/5/7/8 implemented 2026-08-26; 4/6 target architecture decided and phased (see third addendum), Phases E, F and G of it landed the same day (fourth/fifth addenda); a `module-dir`/`user-c-modules` key split decided but not yet implemented (sixth addendum)

Rewritten twice the same day it was written, before anything was built on it.
The first draft framed this as "usermod cannot build two MicroPython versions",
which is a symptom; the second still treated the selector machinery as a
separate concern. It is not. The identifier, what selects over it, and where
that selection lives are one design, and cibuildmp has all three wrong in ways
that only look separate.

## The rule

cibuildwheel's shape, and the reason its selectors work at all: **the build
identifier is the complete description of one build, and selection is globbing
over it.** `cp313-manylinux_x86_64` names the interpreter and the platform, so
`CIBW_BUILD="cp313-*"` means something. Every axis that can vary is in the
identifier; nothing that varies is anywhere else.

cibuildmp adopted the identifier ([0005]) and the globs ([0045]) and then broke
the rule in both modes, differently.

## What each mode's axis actually is

The axis is **what the artifact is compatible with** -- not which release tag
produced it. Those differ, and that is the whole point:

| mode | axis | the release tag is |
| --- | --- | --- |
| natmod | the `.mpy` **ABI** | whichever release supplies it -- an implementation detail |
| usermod | the **MicroPython release** | the axis itself; a port binary fits nothing else |

natmod's identifier is right (`mpy6.3-natmod-x64`) and [0013] argued it
correctly: a native `.mpy` loads into any runtime with a matching ABI, and 6.3
alone spans v1.23.0 through v1.29.0, so naming the release would claim far
narrower compatibility than the artifact has.

usermod's identifier is `unix-manylinux_2_28_x86_64`. It names the port and the
platform tag and says nothing about which MicroPython it *is*.

## Both failures, from that one rule

**natmod names the axis and selects it backwards.** You give tags; the ABI is
derived from them and deduped:

```python
resolve_micropython_tags(tags, override)   # tags in, one (tag, abi) per ABI out
```

So to build for ABI 6.2 you must already know which release carried it. The
table that answers exactly that -- `[mpy-abi]`, tag → ABI -- ships in
`resources/natmod.toml` and is readable only in the direction that does not
help. `mpy-abi` exists as a config key today and is an *override*: it forces the
ABI attributed to tags you named. The axis being the ABI means the input should
be the ABI:

```toml
mpy-abi = ["6.3", "6.2"]     # the axis, stated
micropython = "v1.29.0"      # optional: pin the checkout, not the compatibility
```

**usermod does not name the axis at all** -- and not only in the identifier. A
real run's own summary:

    unix-manylinux_2_28_aarch64   micropython-unix-manylinux_2_28_aarch64
    unix-musllinux_1_2_aarch64    micropython-unix-musllinux_1_2_aarch64

Identifier, output filename and output directory all omit it. Two runs against
different releases produce identically named files in identically named
directories, and the second silently replaces the first.

Which is why `micropython` is a `str` here while natmod's is a list, and why a
config naming two tags silently builds one. The truncation is not laziness; it
is the only thing standing between that config and silent data loss:

```python
micropython: str                                 # a single tag
identifier = f"{port}-{arch}"                    # no version component
identifier_dir = output_dir / target.identifier  # so two tags share one directory
```

Fix the identifier and the truncation stops being necessary. Add the list
without fixing the identifier and it becomes an overwrite.

## The second axis, and why `--archs` cannot be the primitive

The same rule decides this, so it belongs here rather than beside it.

cibuildwheel has one shape, `{python_tag}-{platform_tag}`, with one architecture
axis -- which is what lets `CIBW_ARCHS` be a flat list. usermod's second axis
has **three** shapes:

| port | axis | identifier |
| --- | --- | --- |
| `unix`, `windows` | `archs` | `unix-manylinux_2_28_x86_64` |
| `qemu`, `esp32` | `boards` | `esp32-ESP32_GENERIC` |
| `webassembly` | none | `webassembly` |

A flat `--archs` cannot address that, and the evidence is the implementation
[0049] landed: the flag had to be split, explicit names reaching only
`archs`-keyed ports and keywords reaching all of them. That split is a
workaround wearing the shape of a feature.

What generalises is the rule itself. The identifier already encodes port and
axis value for all three shapes, so `build`/`skip`/`--only` work uniformly over
them today -- `--only esp32-ESP32_GENERIC` and `skip = "windows-*"` both do the
right thing. The one question a glob cannot express is *"what does this runner
build without emulation"*, which is not about architectures at all: it is
whether an **image's** platform is native here, which is how [0049] implemented
it (`platform_for()`, per cell for `unix`, per port for the rest). Only the name
came from upstream, where the semantics were narrower.

## What upstream's selector actually is, read rather than recalled

`cibuildwheel==4.2.0`, installed and read. This matters because every divergence
this project has paid for came from paraphrasing upstream from memory: [0045]
found `--only` documented in-code as matching upstream semantics when it did
not, and [0049] deleted a `default_runner` concept upstream never had.

**It is one module, `selector.py`, 135 lines, at the package root** -- imported
by `__main__.py`, `options.py`, and every platform module (`linux.py`,
`pyodide.py`, …). One selector for every platform, constructed once in options
and carried through. cibuildmp has `select()` written twice, in
`natmod/targets.py` and `usermod/targets.py`, with the second's docstring
admitting the duplication is deliberate. That is the wrong shape and it is the
reason the two modes drifted into reading `build`/`skip` from opposite tables
([0048]).

Four things it has that cibuildmp does not:

**`EnableGroup` — opt-in is a first-class concept, not an absence.** An
identifier exists in the matrix *always*; groups (`pypy`, `graalpy`,
prereleases, EoL) are filtered out unless enabled, and that filter runs **before
`build`/`skip` and outranks them**:

```python
if EnableGroup.PyPy not in self.enable and is_pypy:
    return False
should_build = selector_matches(self.build_config, build_id)
```

So `build = "*"` never sweeps in PyPy by accident, while `enable = ["pypy"]`
plus `build = "*"` does. **cibuildmp expresses opt-in by keeping cells out of
the default axis** (`_UNIX_DEFAULT_TARGETS`), which is weaker and different: the
cell is unreachable by any glob at all, only by `--only` or by being named in
`archs`. It also conflates two things that are not the same -- "not proven yet"
and "not wanted by default". Every "opt-in cell" the tracker has talked about
for weeks -- the musllinux column before it was proven, the six
emulated-everywhere cells, a MicroPython prerelease tag -- is an `EnableGroup`
in upstream's model and nothing at all in ours.

**`requires_python` — the project declares what it supports, and the matrix
narrows itself.** Upstream reads `requires-python` from the project's own
metadata and drops identifiers outside it before any glob runs. That is the
version behaving as a *constraint on the matrix* rather than as a list the user
must curate, and it is exactly the shape the ABI axis wants: a project says
which MicroPython or which `.mpy` ABI it supports, once, and identifiers outside
that stop existing for it.

**`selector_matches` expands braces.** `cp{36,37}-*` via `bracex`, on
whitespace-separated patterns. cibuildmp uses bare `fnmatch`, so braces are
literal characters that match nothing.

**`--only` clears everything, including groups.** Upstream sets `build_config`,
empties `skip_config`, selects all architectures *and* turns on every enable
group. [0045] implemented the first three; the fourth does not exist here
because groups do not.

## `--platform` is one level too high, and that is what makes the second axis look heterogeneous

The deepest of these, and it dissolves the previous section rather than adding
to it.

`--platform` today means the *build mode*: `natmod` or `usermod`. Upstream's
means the thing being built for -- and every value has its own module:

    cibuildwheel/platforms/   android  ios  linux  macos  pyodide  windows

cibuildmp has six build functions with six option shapes -- `build_unix`,
`build_windows`, `build_qemu`, `build_webassembly`, `build_esp32`, and natmod's
own `build_target` -- and hides all six behind two `--platform` values. **The
ports are the platforms.** `natmod` is one too: one build function, one arch
axis, one artifact kind.

What that buys is not tidiness. Look at the axes once the level is right:

| platform | axis |
| --- | --- |
| `natmod` | `archs` |
| `unix`, `windows` | `archs` |
| `qemu`, `esp32` | `boards` |
| `webassembly` | none |

**Every platform has exactly one axis.** The "second axis has three shapes"
problem above exists *only* because `usermod` bundles five platforms and
pretends they share one, which is also why a flat `--archs` had to be split in
two to work at all. Upstream never faces it because `CIBW_ARCHS` always applies
to the one platform being built. Move `--platform` down a level and the
heterogeneity is not solved, it stops existing.

`natmod`/`usermod` remain a real distinction -- different artifacts (`.mpy`
versus a port binary), different packaging ([0014]'s mip package versus a raw
file) -- but as an internal grouping, not a user-facing axis. Upstream's
`linux.py` and `pyodide.py` differ at least that much and are both platforms.

### And the config tree falls out of it

Upstream's own check, one line:

```python
allowed_option_names = self.default_options.keys() | PLATFORMS | {"overrides"}
```

The top level takes global options, **platform names**, and `overrides`. With
the port as the platform that is exactly what cibuildmp's config becomes:

```toml
micropython = "v1.29.0"      # global
build = "*"

[unix]                       # per-platform, as [tool.cibuildwheel.linux] is
archs = ["auto"]

[esp32]
boards = ["ESP32_GENERIC"]
```

against today's `[usermod.unix]`, which carries a level naming a mode rather
than a platform.

Per-axis-value options are then a real fork worth deciding rather than
inheriting. Nested tables (`[esp32.ESP32_GENERIC]`) read well for a small fixed
set; upstream deliberately chose `[[overrides]]` with a `select` glob instead,
because a glob expresses what a table cannot -- `select = "*-unix-musllinux_1_2_{i686,armv7l}"`,
"all 32-bit", "everything except". natmod already has `[[overrides]]`; usermod
has none.

**`variant` surfaces here too.** `unix` and `webassembly` carry a `variant`
field (`standard`, `pyscript`) that is an option today, not an axis, and is
absent from the identifier. Under this record's own rule that is the same defect
as the missing version: two variants would collide on one identifier and one
output path. Either it is an axis and belongs in the name, or it is genuinely
one-per-build and belongs in an override.

## Shape

1. **natmod:** `mpy-abi` becomes a selector -- a list of ABIs, each resolved to
   the newest tag carrying it by reading `[mpy-abi]` backwards. `micropython`
   stays, demoted to "pin this checkout".
2. **usermod:** `micropython` becomes a list; `UsermodTarget` gains a `tag`;
   `usermod_targets()` takes the product of (tag, port, axis value).
3. **The identifier carries it, always** -- `v1.29.0-unix-manylinux_2_28_x86_64`,
   `v1.29.0-webassembly` -- leading, matching natmod's `mpy6.3-` position so both
   modes read the same left to right. **The output filename and directory follow
   it**, which is the half that stops one release overwriting another.
4. **`--archs` loses its usermod meaning.** Identifier globs are the primitive;
   host-nativeness gets its own keyword under a name that is not "archs".
5. **One `cibuildmp/selector.py` for the mechanism, per-mode tables for the
   data.** The split is not "one module or two" -- it is *what belongs in a
   selector at all*.

   Upstream hardcodes its group predicates inside the shared
   `BuildSelector.__call__` (`fnmatch(build_id, "cp316*")`, `pp3?-*`, `gp*`),
   which is fine for one product with a fixed set of Python implementations and
   is exactly wrong here: a module holding both natmod's `mpy6.*` groups and
   usermod's `unix-*`/`esp32-*` ones would know about both modes, and that is
   the coupling to avoid.

   So `selector_matches` (fnmatch + brace expansion) and `BuildSelector`
   (build/skip, groups, compatibility constraint) are shared and **take their
   groups as data**; which groups exist, the patterns defining them, and what
   the constraint means -- ABI for natmod, release for usermod -- come from
   each mode. Upstream itself parameterises where the thing is data
   (`Architecture.all_archs(platform)` takes the platform and stays one module)
   and hardcodes only where it has one product; cibuildmp needs the former in
   both places.

   This is the split the repo already uses everywhere else: mechanism in code,
   tables in `resources/` ([0010]). Groups are tables. `dockerrun.py` moved to
   the package root in [0050] on the same reasoning -- it stopped belonging to
   one mode the moment both used it. The two `select()` copies go.
6. **`--platform` becomes the port**, `natmod` alongside `unix`/`windows`/
   `qemu`/`webassembly`/`esp32`, each with its own module under a `platforms/`
   tree. `natmod`/`usermod` survive as an internal grouping, not as an axis.
   The config's top level then takes platform names directly (`[unix]`, not
   `[usermod.unix]`), matching upstream's own
   `default_options | PLATFORMS | {"overrides"}`.
7. **Decide per-axis-value config explicitly**: nested tables or
   `[[overrides]]` + `select`. Upstream chose the second for expressiveness;
   usermod has neither today.
8. **Opt-in cells become groups rather than omissions.** The six
   emulated-everywhere `unix` cells stop being absent from the default axis and
   become a group that `build = "*"` does not reach and `enable` does. That
   answers [0044]'s standing descope question by making it a user's choice
   instead of a maintainer's, which is what it should have been.

Not conditional on how many tags are selected. Adding the version only when more
than one is chosen looks conservative -- existing identifiers stay
byte-identical, the way [0015]'s `+0x..` arch-flags suffix does -- and is wrong
for a reason that does not apply there: `arch-flags` genuinely does not exist for
most targets, while a MicroPython version always does. A conditional component
makes `build = "*-v1.29.0"` work in some configs and match nothing in others,
which is worse than not having it. cibuildwheel puts the version in
unconditionally, and that is what makes `CIBW_BUILD` mean anything.

## What it costs

**Every usermod identifier changes**, which is [0038]'s three consuming repos
again, for the second time this session -- [0044] renamed every `unix` one
already. That argues for doing this *before* telling those repos to migrate
rather than after: one migration instead of two, the same reasoning [0038]'s own
tracker row gives for holding off.

Nothing else does. `--only` already resolves against the full matrix ([0045]),
`select()` already globs identifiers, and per-identifier output directories
already exist -- the collision that forced the truncation disappears the moment
the identifier distinguishes the builds.

## Meanwhile

The truncation should not be silent. A config naming two tags and getting one
build, with nothing said, is [0048]'s class exactly -- the config states one
thing and the tool does another -- and one line on stderr costs nothing while
this waits.

## Addendum, 2026-08-26 — Shape points 1/2/3/5 landed

Implemented against the exact code this record read, not re-derived from
memory: `natmod/targets.py`, `natmod/options.py`, `usermod/targets.py`,
`usermod/options.py`, `usermod/orchestrate.py`.

**Point 1 (natmod's `mpy-abi` axis).** `mpy-abi` is now dual-shape rather
than replaced: a bare string keeps its pre-existing, narrower meaning
(override -- force this ABI onto every `micropython` tag). A **list**
states the axis directly, each ABI resolved to its own newest known tag by
reading `resources/natmod.toml`'s `[mpy-abi]` table backwards
(`newest_tag_for_abi()`/`resolve_abi_selector()`, `natmod/targets.py`). This
distinction was not settled by the record's own "Shape" section --
`micropython`/`mpy-abi`'s exact interaction when both name an axis was left
implicit -- so it is written down here: with `mpy-abi` as a list,
`micropython` is not consulted for axis purposes at all, only the ABI list
is. A version-sort key for "newest tag" was hand-rolled
(`_tag_sort_key()`) rather than adding a `packaging` dependency, matching
D12's reasoning for this project's two existing runtime dependencies.

**Points 2/3 (usermod's leading tag, unconditional).** `UsermodTarget`
gained `tag: str = ""`; `identifier` prepends it unconditionally when set
(`f"{tag}-{port}[-{arch}]"`), matching natmod's `mpy{abi}-` slot exactly, as
argued ("not conditional on how many tags are selected"). `UsermodOptions
.micropython` is `list[str]`, the truncation-to-first-entry deleted.
`usermod_targets()`/`all_usermod_targets()` both gained a leading `tags`
parameter and now product over `(tag, port, axis value)`.
`orchestrate.build()` groups targets by `.tag` and fetches/builds each
group's own checkout once, mirroring natmod's `cli.build()` `dict.fromkeys()`
idiom exactly -- previously it fetched once for the whole run, which was
only correct because there was never more than one tag. Output
directory/filename needed no code change, as the record's own "cost"
section predicted: both already key off `target.identifier`.

**Point 5 (shared selector, partial).** `parse_selector()`/`matches()`/
`select()` moved to a new `cibuildmp/selector.py`, generic over a
`Protocol` (`.identifier: str`) rather than a concrete `Target` type, so
both `natmod.targets.Target` and `usermod.targets.UsermodTarget` share one
implementation. `matches()` also gained brace expansion (hand-rolled, not
`bracex`, same dependency reasoning as the tag-sort key above), closing the
one concrete upstream-parity gap the record named. **Not done**: `EnableGroup`
and `requires_python` (that is point 8, tracked separately below) --
`selector.py` today is exactly `parse_selector`/`matches`/`select`, nothing
about groups or a compatibility constraint.

**Points 4 and 6 — deliberately not attempted in this pass; points 7 and 8
landed in a second pass the same day (see the addendum below).**
`--archs` keeps its current usermod meaning (a real but narrower shape than
upstream's, per point 4); `--platform` still means the build mode, not the
port (point 6). None of this is a regression -- deferring them left
existing behavior unchanged, only without their improvements -- and the
reasoning for the split (real, separable epic; disruptive part done once
while the three consuming repos are still unmigrated) is recorded in the
session that did this work rather than here. Whoever picks these up next
should re-read this record's own "Shape" section 4/6 rather than start from
an addendum.

Verified: full test suite green (323 tests, three new/expanded files --
`tests/test_selector.py` is new); live `--print-build-identifiers` against
`examples/template` for `mpy-abi = ["6.3", "6.2"]` (natmod) and
`micropython = ["v1.28.0", "v1.29.0"]` (usermod), both producing distinct,
correctly-shaped identifiers; `--only` resolving against the full matrix
post-refactor in both modes.

## Addendum, 2026-08-26 (second pass) — Shape points 7/8 landed

Point 6 (`--platform` becomes the port) turned out to be a bigger and
more consequential change than a rename once looked at closely: today one
usermod invocation builds several ports at once
(`examples/template/cibuildmp.toml`'s real config is
`ports = ["unix", "webassembly", "windows"]` in one `[usermod]` table, one
CI job) — making `--platform` mean one port the way upstream's own
`--platform` means one OS would mean one invocation builds one port,
splitting that job into several. This record's own "Shape" section does
not resolve that, so it stayed out, and point 4 (`--archs` losing its
usermod meaning) stays with it, since the record's own text says the
"second axis looks heterogeneous" problem "exists only because usermod
bundles five platforms" — it dissolves once point 6 lands, not before.
Points 7 and 8 were independent of that and got done instead.

**Point 7 (`[[usermod.overrides]]`).** A design decision the record left
open, resolved here: usermod's overrides are their **own** nested
`[[usermod.overrides]]` array (`USERMOD_OVERRIDE_TABLE_KEYS` in
`usermod/options.py`: `select`/`module-dir`/`manifest`/`extra-make-args`),
not a share of natmod's top-level `[[overrides]]`. Reason: the two modes'
override tables accept different keys, and a config with both `[natmod]`
and `[usermod]` tables (the real `examples/template` shape) would
otherwise need one shared list whose keys mean different things depending
which mode reads it. `UsermodOptions.build_options()` now layers
`file -> matching override -> environment`, the exact shape
`natmod/options.py`'s own `build_options()` already had. `variant` (a real
field on `UnixBuildOptions`/`WebassemblyBuildOptions`/`WindowsBuildOptions`,
still hardcoded, still no config surface) stayed out, on purpose — wiring
it needs `orchestrate._port_build_options()` to pass it through per port,
its own smaller follow-up.

**Point 8 (opt-in groups, upstream's own `EnableGroup`).** `cibuildmp
.selector.select()` gained `enable`/`groups` parameters, backward
compatible (natmod's existing calls pass neither and are unaffected). A
target matching an unenabled group's glob patterns is dropped before
`build`/`skip` is even checked, matching upstream's own
`BuildSelector.__call__` order. The concrete target was the tracker's own
`[0044]` row ("the six emulated-everywhere cells: build them or
descope"): `usermod.targets.GROUPS["unix-emulated-everywhere"]` covers
`ppc64le`/`s390x`/`riscv64`, both libcs. Doing this properly meant the six
cells stopped being absent from `unix`'s own axis at all
(`default_axis_values("unix")` is now `all_axis_values("unix")` in full;
`_UNIX_DEFAULT_TARGETS` is deleted) — what still keeps a bare
`build = "*"` at nine cells is the group, not axis membership, exactly as
the record's own text specifies. One narrow, deliberate, and
called-out-rather-than-hidden behaviour change: `--archs all` now resolves
the axis to all fifteen cells but the group filter still applies on top,
so it alone no longer reaches the six without `--enable
unix-emulated-everywhere` too — matching upstream precedent
(`CIBW_ARCHS=all` does not alone build `pypy`) and unlikely to break
anything real, since the tracker's own words are that nothing has ever
built these six cells. `enable` is a genuinely shared top-level config key
(`TOP_LEVEL_ONLY_KEYS` in `natmod/options.py`) even though only usermod
defines any groups today; natmod's own `Options` gained no `enable` field,
since a config surface with nothing to gate would be speculative.

Verified: full test suite green (341 tests); `ruff`/`pyright` clean on
every touched file; live `--print-build-identifiers`/`CIBMP_ENABLE`/
`--enable`/`--archs all` combinations against `examples/template` and a
scratch copy carrying a `[[usermod.overrides]]` table, matching every case
this addendum describes.

## Addendum, 2026-08-26 (third pass) — points 4/6 target architecture decided, phased, Phase E landed

Prompted by a live design conversation that pushed on exactly the three
things this record's own "Shape" section 4/6 had left underspecified or
mis-scoped, each checked against real code rather than settled by argument
alone:

**Overrides are already upstream-shaped; the gap is `inherit`.** Verified
against `cibuildwheel/options.py`: `[[tool.cibuildwheel.overrides]]` is a
list of tables with `select`/`inherit` popped and the rest read as option
values — the same shape `[[overrides]]`/`[[usermod.overrides]]` already
have. The real, missing piece is `InheritRule` (append/prepend/none) — see
below, folded into Phase G rather than done as a standalone addition.

**Why upstream gets away with one shared `[[overrides]]` across
different-key-domain platforms, and why cibuildmp's own two tables were not
simply a smaller version of the same thing:** `cibuildwheel.Options` takes
`platform` as a constructor argument and is built once per platform; an
override's own option keys are **never validated at parse time** —
`config_override.pop("select", None)` / `.pop("inherit", {})`, and
everything left just sits in `Override.options`, read only if some
platform's own `get(name)` later asks for that exact name. A macOS-only key
inside an override matching a Linux identifier is silently never read —
which is a milder instance of the exact bug class [0048] fixed here. One
shared list is only safe *without* losing that guarantee if key validation
moves from parse-time-against-a-fixed-set to **runtime-against-the-specific-
platform the matched identifier resolves to** — which only has real meaning
once natmod is a platform among six, not a mode with its own table shape.
This is why the previously-planned `[[overrides]]` → `[[natmod.overrides]]`
rename (mirroring `[[usermod.overrides]]`, to fix the session's own earlier
naming asymmetry) was **abandoned before being implemented**: it would have
been the wrong intermediate shape, nesting overrides under a mode-table
concept (`[natmod]` as "natmod's own umbrella") that this addendum's own
target architecture deletes outright.

**Why the invocation-model concern that justified deferring points 4/6 in
the second addendum does not actually hold:** cibuildwheel's platforms are
bound to host OS — macOS wheels cannot be built on a Linux runner — so one
platform per invocation is structural there, not a design choice. cibuildmp's
six platforms are already just different Docker images (except `esp32`,
host-provisioned but not OS-bound) on the *same* host; nothing forces one
platform per invocation the way it does upstream, which is exactly why
`ports = ["unix", "webassembly", "windows"]` already builds three ports in
one invocation today. The "splits one CI job into several" framing imported
upstream's own constraint without checking why upstream has it, and it does
not transfer.

**A larger, related discovery, written up as its own addendum to [0048]:**
tracing the "why one shared list" question surfaced that upstream's whole
option-resolution model is a **cascade** (`default → global → platform →
environment → CLI`, most-specific-wins, nothing is an error to place at any
layer), not [0048]'s own partition-with-errors model (`TOP_LEVEL_ONLY_KEYS`
etc.). The cascade satisfies [0048]'s real guarantee (a misplaced key must
never silently do nothing) by a more general mechanism — there is no "wrong
location" left to protect against — and it is what makes one shared
`module-dir`/`manifest`/`extra-make-args` sane across six platforms without
either forced repetition or a bespoke per-key sharing rule. See [0048]'s own
addendum for the full argument.

### Target architecture

`--platform` stops meaning "natmod or usermod" and means one of six platform
names (`natmod`, `unix`, `windows`, `qemu`, `webassembly`, `esp32`), matching
this record's own original "the ports are the platforms" diagnosis exactly.
Every platform gets its own top-level config table (`[natmod]`, `[unix]`,
...), sibling to each other — no more `[usermod]` umbrella, no more
`ports = [...]` selector (table presence is the selector, generalising
`detect_mode()`'s own existing "no config → natmod" rule to six values).
`[[overrides]]` returns to being one shared top-level list, validated loosely
(does this key exist anywhere) at parse time and strictly (does it belong to
*this* matched identifier's own platform) at resolution time. `inherit =
{key = "append"|"prepend"|"none"}` joins it, scoped to list-valued keys
(`extra-make-args`, the one option genuinely list-shaped across every
platform). `natmod.targets.Target` gains a `.port` property (`"natmod"`) so
it satisfies the same shape `UsermodTarget` already does — no dataclass
merge needed, `cibuildmp.selector`'s own `_HasIdentifier` Protocol already
covers both.

### Phasing

Large enough to land in ordered, independently-verifiable phases, the same
discipline this record's own first two passes used (A/B/C, then points 7/8):

- **Phase E (landed 2026-08-26)** — `cibuildmp/options.py`: the cascade
  mechanism (`Options.get()`, `resolve_cascade()`, `InheritRule`,
  `known_option_names()`/`check_known_keys()`), standalone and unit-tested
  (`tests/test_options_cascade.py`, 24 tests) against synthetic fixtures.
  **Not yet wired to any real config loading** — `natmod/options.py`/
  `usermod/options.py` are untouched and behave exactly as before this
  addendum; nothing a real build depends on can regress from this phase.
- **Phase F (landed 2026-08-26)** — flatten the config tree: every
  `[usermod.<port>]` becomes `[<port>]`; `ports = [...]` deleted, replaced
  by table presence; `detect_mode()` replaced by `active_platforms()`.
  Breaking — this repo's own `cibuildmp.toml`, `examples/template`, and
  every test fixture using the old shape migrated in the same commit. See
  the fourth addendum below for what actually landed and where it diverged
  from this phase's own original scoping.
- **Phase G (not started)** — one shared `[[overrides]]` with runtime
  per-platform key validation, `inherit`, and `Target.port`.
- **Phase H (not started)** — unify CLI dispatch: `natmod_cli.run`/
  `usermod_cli.run`'s split becomes one loop over the combined target list,
  dispatching per-target by `.port`. Packaging (`package_target()`, D14's
  mip step) stays natmod-only and version-gated, called explicitly rather
  than something every platform's build function has to know about.
  `stepsummary.write_step_summary()` and `sources.py`
  (`fetch_micropython`/`build_mpy_cross`) need no change — already
  mode-agnostic, already shared by both today (confirmed this session,
  `usermod/orchestrate.py:30` imports the latter directly).
- **Phase I (not started)** — README's "Target support" tables reconciled
  into one scheme; `action.yml` (confirmed to need no change — no
  `platform` input exists today, matching `CIBW_BUILD`'s own env-only
  shape); this record's own status line and the tracker's `[0051]` row
  updated to "fully landed" once I is done.

Each phase gets its own plan-review checkpoint before implementation, the
same way this record's own points 1/2/3/5 and 7/8 passes did.

[0005]: 0005-one-identifier-namespace.md
[0013]: 0013-micropython-list-dedup-by-abi.md
[0015]: 0015-rv32imc-arch-flags-identifier.md
[0023]: 0023-usermod-identifier-scheme-config-output.md
[0038]: 0038-m5-adopt-in-three-repos.md
[0044]: 0044-unix-native-images-landed.md
[0045]: 0045-only-is-a-filter-not-a-forced-identifier.md
[0048]: 0048-build-skip-live-in-opposite-tables.md
[0049]: 0049-no-matrix-generation-archs-vocabulary.md

---

## Addendum, 2026-08-26 — Phase F landed: the flattened tree, and one
## real invocation building natmod and usermod ports together

Landed the same day as Phase E, in the same session. `natmod/options.py`
and `usermod/options.py` are both wired onto `cibuildmp/options.py`'s
cascade now — the "not yet wired" caveat in Phase E's own description
above no longer holds.

**The config tree, live.** `[usermod]` no longer exists at all — every
usermod port table (`[unix]`, `[windows]`, `[qemu]`, `[webassembly]`,
`[esp32]`) sits at the top level, sibling to `[natmod]`, exactly as the
target architecture above described. `cli.py`'s `detect_mode()` is gone,
replaced by `active_platforms(raw, explicit) -> list[str]`: every platform
table `raw` actually has, in a fixed order (`natmod` first), or `["natmod"]`
when none are present — the zero-config case, byte-for-byte unchanged. A
lingering `[usermod]` table is a loud, specific `ConfigError` naming the
exact migration, not a silent no-op or a generic "unknown key" — this was
always going to be the one real breaking change point 6 promised, and there
is no deprecation window, matching the plan's own framing.

**More than one platform, one invocation, confirmed live** — not just
designed:

```
$ cibuildmp examples/template --dry-run
cibuildmp: 10 target(s) against MicroPython v1.29.0
  [ 1/10] mpy6.3-natmod-x86            make -C natmod ARCH=x86 dist
  ...
cibuildmp: 13 usermod target(s) against MicroPython v1.29.0
  [ 1/13] v1.29.0-unix-manylinux_2_28_x86_64
  ...
  [13/13] v1.29.0-webassembly
```

One `cibuildmp` call, no `--platform`, natmod and three usermod ports all
resolved and printed. `--print-build-identifiers --json` against the same
config emits exactly one JSON array spanning all four platforms — the
detail that actually needed engineering, not just table-presence resolution:
`cli.py`'s own dispatch is still two functions (`natmod_cli.run`/
`usermod_cli.run`, Phase H's own job to unify), so a new `_run_multi_platform()`
bridges them for the `>1` active case — sequential dispatch with a merged
`--print-build-identifiers` document (naive sequential dispatch would emit
two separate JSON arrays under `--json`, which is exactly what
`cibuildmp-matrix`'s own `json.loads()`, [0048], would choke on) and
`--only` narrowed to whichever single side actually names that identifier.
A `--only` value matching neither side is the one acknowledged rough edge
(each side reports its own "not known" separately) — Phase H's real unified
loop removes it by construction, not worth building throwaway merge logic
for a gap that phase closes for free.

**`--platform` is a filter over six names now**, comma- or
whitespace-separated, no longer `choices=["natmod","usermod"]`. The old
single-mode spelling `--platform usermod` is rejected the same way any
other unknown name is (`usermod` was never a platform); `--platform natmod`
still works, since it is a real platform name today.

**The cascade wiring, done, bounded exactly as planned:** `Options.get()`
resolves `module-dir`/`make-target`/`extra-make-args`/`pre-build-command`
(natmod) and `module-dir`/`manifest`/`extra-make-args` (every usermod port)
through `default → global → platform → env`, but *not* `[[overrides]]` or
`inherit` — those stay [0048]'s own addendum's "Phase G" promise, layered
in afterward through the exact same `opt()`-closure override loop both
`build_options()` methods already had, untouched. One real, load-bearing
consequence worth recording precisely: `module-dir` cannot be promoted to
the bare top level in a config that has *both* `[natmod]` and usermod
ports wanting a different value — natmod's own module-dir default
("natmod") and a usermod port's ("usermod", or a project's own override)
are genuinely different values, and the top level is every platform's own
default, natmod included. `examples/template/cibuildmp.toml` hit this for
real: `module-dir = "."` had to move into each of `[unix]`/`[webassembly]`/
`[windows]` individually rather than being promoted alongside `manifest`
(which natmod's own schema does not read at all, so it *is* safely global).
This is the practical shape of the "every location is a real layer" cascade
argument [0048]'s own addendum made in the abstract.

**Record 0048's own guarantee, re-verified under the cascade.** A key valid
for one platform's schema, written inside a *different* platform's own
table (e.g. `make-target`, natmod-only, inside `[webassembly]`), is still a
loud, specific `UsermodConfigError` — validated per-platform-table against
only that platform's own schema, never the union of every platform's,
which is what keeps a misplaced key from silently becoming "just another
platform's default" the way a careless cascade implementation could allow.
`TOP_LEVEL_ONLY_KEYS`/`NATMOD_TABLE_KEYS`/`USERMOD_TABLE_KEYS`/
`check_table_keys()` are retired; `GENERIC_KEYS`/`NATMOD_SCHEMA`/
`SCHEMAS`(usermod, keyed by port) plus a shared `check_keys()` (natmod's
own module, imported by usermod's) replace them, still naming the "read
from the top level" case specially and now also suggesting a close match
via `difflib` (`cibuildmp.options.suggest()`) the way upstream's own
`_validate_global_option()` does — a real, if small, upgrade over the
message record 0048 originally shipped.

**A second, related diagnostic Phase F had to add, not inherited from
0048:** presence-based platform selection has no equivalent to the old
`ports = [...]` list's own `KNOWN_PORTS` validation, so a typo'd table name
(`[stm32]`) was, on the first working version of this phase, simply never
selected — silently, not an error. `cli.py`'s own
`_reject_unknown_tables()` closes this: any top-level table whose name is
neither a known platform nor `[publish]` (the one legitimate non-platform
table) is a loud error naming what exists. Found by writing the test for
exactly the case the old `ports = ["stm32"]` config used to catch
(`unknown usermod port`) and confirming presence-based selection quietly
dropped it — the same "verify a diagnostic still fires after changing its
mechanism" discipline [0048]'s own resolution used for `archs`/
`arch-flags`'s dual-read.

**What did not change:** `DEFAULT_PORTS`/`_NON_DEFAULT_PORTS` (esp32's old
opt-out-by-default within a bare `[usermod]`) are deleted as dead code —
table-presence selection subsumes them without a special case, `esp32`
included: it now needs its own `[esp32]` table exactly as much as every
other port does. `[[usermod.overrides]]` is renamed to a top-level
`[[usermod-overrides]]` (forced only by `[usermod]`'s disappearance) but
deliberately *not* merged with natmod's own `[[overrides]]` yet — Phase G's
own job, argued for explicitly in the second addendum above ("What changed
since the last plan") and still true after seeing Phase F built: the merge
needs runtime per-matched-identifier key validation that only has a real
meaning once `natmod.targets.Target` has a `.port` property to resolve
against, which Phase G is what adds.

Verified: full test suite green (`tests/test_cli_multi_platform.py`,
renamed from `test_cli_usermod_mode.py` and substantially rewritten;
`tests/test_active_platforms.py`, new; `tests/test_usermod_options.py`,
`tests/test_usermod_orchestrate.py`, fixtures flattened), `ruff`/`pyright`
clean, and the live smoke tests quoted above run against the real,
migrated `examples/template/cibuildmp.toml` — not just synthetic
`tmp_path` fixtures.

Phase G (one shared `[[overrides]]`, `inherit`, `Target.port`) is next.

---

## Addendum, 2026-08-26 — Phase G landed: one shared `[[overrides]]`,
## `inherit`, `Target.port`

Landed the same day as Phases E and F, in the same session.
`natmod.targets.Target` gains a `.port` property (always `"natmod"`);
natmod's own top-level `[[overrides]]` and Phase F's `[[usermod-overrides]]`
merge into one shared top-level `[[overrides]]`, read once by a new
`natmod/options.py::load_overrides()` both `Options.load()` and
`UsermodOptions.load()` call; `inherit = {extra-make-args =
"append"|"prepend"|"none"}` is real now, wired through
`cibuildmp/options.py`'s `InheritRule`/`resolve_cascade()`/
`Options.get(..., extra_layers=...)` machinery — built in Phase E,
deliberately left unused until this phase had a real caller for it.

**The one hard design problem, and how it resolved.** Tier-1 validation
("is this override key valid for *any* active platform's own override
surface") genuinely needs cross-platform knowledge: a real mixed config
(`[natmod]` + `[unix]`, one shared `[[overrides]]` entry carrying only
`manifest`, a usermod-only key) must not have natmod's own loading path
reject it as a typo. But `natmod/options.py` must not import
`usermod/options.py` — the established direction (usermod imports from
natmod, never the reverse; natmod is the shared base `check_keys`/
`GENERIC_KEYS`/`read_config` already live in) stays. Resolved with a
small, explicit, **tested** data duplication rather than an import:
`natmod/options.py` gains `_USERMOD_OVERRIDE_OPTION_KEYS_MIRROR`, three
literal strings restating usermod's own `USERMOD_PORT_BASE`, used only to
build the public `OVERRIDE_UNION_KEYS`. `tests/test_overrides.py`'s own
`test_override_union_keys_covers_usermod_port_base` guards against drift
by importing both real constants and asserting the union is a superset —
this codebase already accepts exactly this tradeoff elsewhere
(`natmod/targets.py`'s `NATMOD_ARCH_NATIVE_CODE`/`NATIVE_ARCH_CODE`, two
separately-named constants built from the same data for two call sites);
tests may cross-import freely, production code may not.

**Two validation tiers, both real errors, matching record 0048's own
guarantee under the cascade.** *Loose* (tier-1), at parse time
(`load_overrides()`): a key valid on *no* platform's override surface at
all is a typo, caught immediately regardless of which target (if any)
ever matches that override — this is what keeps an override whose
`select` never matches anything from silently going unvalidated, the
exact "declared but never checked" shape 0048 was written for. *Strict*
(tier-2), at `build_options()` resolution time, once the matched
identifier's own platform (`target.port`) is known: a key valid
*somewhere* but not on *this* specific platform's own schema is still a
loud, specific error — validated against that platform's own schema
alone, never the union, which is what keeps a misplaced key from
silently becoming "just another platform's default" under a careless
cascade implementation. Both directions tested directly
(`test_natmod_only_override_key_rejected_for_a_usermod_target`,
`test_usermod_only_override_key_rejected_for_a_natmod_target`).

**Environment-beats-override, verified not inverted.** `Options.get()`'s
own internal layer order is `default → global → platform → env →
extra_layers`, so naively threading overrides through `extra_layers` on a
cascade instance with a real `env` mapping would put overrides *after*
environment — inverting the tested "environment beats override"
guarantee. It doesn't, because it doesn't need to: Phase F already
constructs `_cascade_file`/`_cascade` with `env={}` (both modules already
commented why — `build_options()` checks the real environment itself,
after overrides, matching the precedence it has always had). With
`env={}`, the cascade's own env layer always contributes `None` and is
skipped, so `extra_layers` is effectively the only thing layered after
`platform`; `build_options()`'s own `opt()` closure still checks the real
`environ` first and returns immediately when set, before ever calling
`.get()`. Nothing about cascade construction changed — this is a reuse of
an existing Phase F decision, not a new mechanism, and every existing
environment-precedence test (`test_environment_beats_override`,
`test_usermod_environment_beats_override`) stayed green unmodified.

**A real bug this phase's own live testing found and fixed, not
introduced by it.** `build_options()` could already raise `ConfigError`/
`UsermodConfigError` before this phase (a missing `select` key), but
neither `natmod/cli.py`'s `run()` (its `--dry-run` plan-line loop, and its
`build(options, targets)` wrapper) nor `usermod/cli.py`'s `run()` (its own
`orchestrate.build()` wrapper) caught it — `options.targets()`'s own
try/except runs *before* any individual target is resolved into
`BuildOptions`, so an error only `build_options()` itself can raise was
never in scope. Phase G's own tier-2 check makes this a real,
easy-to-hit path (a plausible config mistake, not a rare edge case), so
it surfaced immediately on the first live `--dry-run` smoke test against
a real cross-platform override — a raw Python traceback instead of
`cibuildmp: error: ...`. Fixed in both CLI modules; regression test
`tests/test_overrides.py::test_tier_2_rejection_is_a_clean_cli_error_not_a_traceback`
asserts a clean message and no `Traceback` in stderr.

**Deliberately not done in this phase**, and why: `check_known_keys()`/
`known_option_names()` (`cibuildmp/options.py`, built in Phase E, still
unused) were not converged with `natmod/options.py`'s own `check_keys()`
(GENERIC_KEYS-aware, per-caller `error`-parameterized) — a real,
separable cleanup with no functional payoff for this phase, deferred
rather than done as scope creep.

Verified: full test suite green (`tests/test_overrides.py`, new, 11
tests; five `[[usermod-overrides]]` tests in `tests/test_usermod_options.py`
mechanically renamed to `[[overrides]]`), `ruff`/`pyright` clean, and live
smoke tests — `inherit = {extra-make-args = "append"}` actually composing
in a real `make` invocation's own argument list, and the tier-2 rejection
producing a clean CLI error — both run against real configs, not just
`tmp_path` fixtures.

Phase H (unify CLI dispatch and the build loop) is next.

---

## Addendum, 2026-08-26 — `module-dir` is one name for two different
## things, and that is *why* it has to be repeated per usermod port

Surfaced by direct questioning after Phase G landed, working through a
real config (`examples/template/cibuildmp.toml`'s own `[unix]`/
`[webassembly]`/`[windows]` each repeating `module-dir = "."`) rather than
assumed. Verified against real code and a real directory tree, not
recalled — this addendum records a genuine naming defect and its fix,
**not yet implemented**.

### The confusion

`module-dir` names the same *purpose* in both schemas — "where does your
module's own source live" — but two different *consumers* read it, and
they need genuinely different values:

- **natmod**: `natmod/cli.py:48` runs `make -C <module-dir>` directly.
  That directory must itself contain the project's own Makefile
  (`include $(TOP)/py/dynruntime.mk`). Default `"natmod"`.
- **usermod**: the value is forwarded as `USER_C_MODULES=<module-dir>`
  into the *MicroPython port's own* Makefile/CMake — a file that lives
  inside the fetched checkout, not in the consumer's repo at all
  (`usermod/portinfo.py::resolve_user_c_modules()`, `usermod/orchestrate.py:96`).
  `module-dir` itself never needs its own Makefile: `py/py.mk` globs
  `$(USER_C_MODULES)/*/micropython.mk` — **one level below** whatever
  `module-dir` points at — and picks up every subdirectory that has its
  own `micropython.mk`. Default `"usermod"`, on the assumption a project
  puts its actual C-module folder(s) one level inside that.

That default assumption doesn't hold for `examples/template`: its own
`usermod/micropython.mk` sits *directly* inside `usermod/`, one level
shallower than the default glob expects, precisely because
`natmod/template.c` and `usermod/template_usermod.c` both wrap the shared
`src/template_core.c` and `usermod/micropython.mk`'s own `SRC_USERMOD`
entry needs to see `src/` too (`dockerrun.py` only mounts `USER_C_MODULES`
itself). So the config overrides `module-dir = "."` (the whole project
root) instead — which makes `usermod/` itself the one subdirectory the
glob picks up. This override is legitimate and necessary; the problem is
where it *has* to be written.

### Why it has to be repeated three times

Phase F/G's cascade treats the global (top-level) table as every
platform's own default, natmod included. Because both schemas read the
identical key name `module-dir`, writing `module-dir = "."` once at the
top level would silently become natmod's own default too — overriding
`"natmod"` with `"."` and pointing `make -C` at the wrong directory. There
is no "usermod-family" tier between "global" and "one specific platform"
to write a value shared by the five usermod ports but not natmod, so the
only safe place left is each usermod port's own table — hence three
copies of the identical value in `examples/template/cibuildmp.toml`.

### The fix: two distinct key names, one of them promotable

Rename usermod's own key to `user-c-modules` — the literal name of the
variable it feeds — and leave natmod's own `module-dir` untouched. Once
the two schemas no longer share a key name, the collision that forces the
repetition disappears on its own: `user-c-modules = "."` written once at
the top level becomes every active usermod port's own default (natmod's
schema simply never reads a key by that name, so it is untouched),
without inventing any new cascade tier. `examples/template/cibuildmp.toml`
collapses from three repeated `module-dir = "."` lines to one shared
`user-c-modules = "."`.

**Scope, sketched, not yet sized into a phase:**
- `usermod/options.py`: `USERMOD_PORT_BASE`'s `"module-dir"` member
  becomes `"user-c-modules"`; `UsermodOptions`'s and
  `UsermodBuildOptions`'s own `module_dir` field renames to
  `user_c_modules` throughout (`build_options()`'s own `opt("module-dir",
  ...)` call becomes `opt("user-c-modules", ...)`).
- `usermod/orchestrate.py`: `build_options.module_dir` references rename
  to match.
- `examples/template/cibuildmp.toml` and this repo's own commented usermod
  sketch in `cibuildmp.toml` migrate to the new key, `module-dir` promoted
  from three per-port copies to one shared top-level `user-c-modules`.
- Every `module-dir`-shaped usermod test fixture renames.
- Breaking, no deprecation window — the same precedent Phase F's own
  `[usermod]` removal already set, for the same reason: nothing outside
  this repo consumes the usermod config shape yet ([0038] is still
  pending on all of E–I landing first).

Independent of Phase H's own scope (CLI dispatch unification) — could
land before it, after it, or folded in alongside it as a small addition;
not yet decided which.

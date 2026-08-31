# cibuildmp — design reference

Living reference for the current design: positioning, the identifier scheme,
the phase-1 config schema, the toolchain map, and what "local use" means.
This is not a decision history — see [docs/0000-TRACKER.md](../0000-TRACKER.md)
and [docs/records/](../records/) for that. When this file and a numbered
record disagree, the record is the historical account of *why*; this file
should be kept current with *what is true today*.

<!-- migrated verbatim from docs/BACKLOG.md lines 12-33 (Positioning) -->

## Positioning

This repository is `ballistics-lab/cibuildmp`, and it superseded
`ballistics-lab/micropython-native-ci` (**D11**): the composite actions and
the tool live together, one version line, one place a fix lands.

The composite actions in `.github/actions/` solved the toolchain problem,
but only inside GitHub Actions, and only hand-driven per consumer.
`cibuildmp` — the CLI, wrapped by the root `action.yml` — is what actually
absorbed that ground: the arch matrix, `runs-on:` selection, artifact
layout, the version pin, and local reproducibility all now go through one
config and one action, for natmod fully and for six of the fifteen
verified usermod ports (see the README's own "Target support" table).

**Not** absorbed the way this section originally expected: the plan to
fold `.github/actions/build-natmod` into a thin `cibuildmp --build`
wrapper (the `pypa/cibuildwheel@v3`-style relationship this paragraph used
to describe) was proposed and explicitly rejected — see tracker [0038],
"Rejected". `.github/actions/*` stays a permanent, separate legacy layer,
not a temporary one being absorbed over time; it survives specifically
because `a7p`'s own `unix-mipsel` cross-compile still depends on
`build-usermod-unix` directly, with no native runner to move it off of
([0067]). Read `docs/ACTIONS.md` only as reference for that kind of
holdout, not as an alternate way to use `cibuildmp`.

<!-- migrated verbatim from docs/BACKLOG.md lines 433-476 (Identifier scheme) -->

## Identifier scheme

Shaped after `cp311-manylinux_x86_64` = *{ABI}\_{arch}*, but with no literal
mode segment (record [0052], Track A/A2), and with the MicroPython tag as
part of it — a live, user-caught correction of that same record's own
earlier draft, which dropped the tag and had to collapse several real,
distinct rows onto one identifier to compensate:

```
mpy6.3-v1.30.0-preview-armv7emsp
mpy6.3-v1.30.0-preview-x64
```

- **`mpy6.3`** — the `.mpy` ABI: `MPY_VERSION`.`MPY_SUB_VERSION` from
  `py/persistentcode.h`. This is the correct compatibility axis, not the
  MicroPython release tag by itself: a native `.mpy` loads into any runtime
  with a matching `MPY_VERSION`/`MPY_SUB_VERSION` pair, which spans several
  releases — but a real `(tag, arch)` row is still its own distinct fact
  (a different checkout, different toolchain particulars), so the tag stays
  part of the identifier rather than being collapsed away once one is
  picked.

  There is no `micropython`/`mpy-abi` config key any more ([0052], A2): the
  version axis is a statically known domain — `resources/build-platforms.toml`
  records every real `(tag, arch)` row this project has actually verified
  (five ABIs today: `5`, `6`, `6.1`, `6.2`, `6.3`, several tags each).
  `build`/`skip` glob-match directly against these real identifiers; a
  pattern that never names a tag-shaped substring
  (`selector_names_a_tag()`) narrows to the single newest tag per arch
  automatically (a bare, unconfigured `build` keeps a zero-config
  invocation building only the current release, not every tag this
  project has ever verified), while a pattern that does name one
  (`build = "mpy6.3-v1.23.0-*"`) is trusted as-is, tag and all — the
  "pin a specific tag" gap this section used to flag as undesigned is
  closed by that same mechanism, not a separate config key.
- No literal mode/platform segment — `natmod` is one platform among the
  usermod ports too now ([0051]), all sharing this same tag-included
  *{ABI}-{tag}-{arch}* shape rather than natmod alone spelling its own
  name into the string.
- **arch** — one of `dynruntime.mk`'s ten `ARCH` values. There is no
  `archs` config key either (the same live correction, applied one axis
  over): it filtered candidate rows by `.arch` alone, before `build`/`skip`
  ever ran, duplicating exactly what a `build`/`skip` glob over the
  identifier already expresses directly (`build = "*-x64"`).
- **`+0x..`** (optional, `rv32imc` only) — `arch_flags`, present only when
  `arch-flags` is set (**D15**): `mpy6.3-v1.30.0-preview-rv32imc+0x3`.
  Absent for every other arch and for `rv32imc` with no `arch-flags`
  configured.

`arch_flags = 0` (the unconfigured default) is not merely "no flags set" —
it is a named compatibility class, the `abi3`-equivalent broad/portable
build ([0052], A4). `py/persistentcode.c`'s own install-time check is a
subset test, `(arch_flags & device_extensions) != arch_flags`, i.e. "does
this device support every extension this .mpy was built assuming" — a
`.mpy` built with `arch_flags = 0` asks for nothing extra and therefore
passes that check on every rv32imc device, while one built with a specific
flag set only runs on devices that declare a superset. `natmod/build.py`'s
`verify_output()` docstring already documents the mirror side of this same
asymmetry (an *exact* match is required between what the linker actually
encoded and what the target's own config asked for — that check has
nothing to do with whether some other device could also run the file);
this paragraph is the mip/install-time half.

No separate float/precision field. Precision is already encoded in the arch
itself (`MP_NATIVE_ARCH_ARMV7EMSP` vs `…ARMV7EMDP` are distinct values, and
`MPY_FEATURE_ARCH` is selected from `__ARM_FP` at compile time). bclibc's
`MP_BCLIBC_PRECISION` / `_sp` / `_dp` suffixes are a *project-level source
define and module-naming convention*, not part of the `.mpy` ABI — they
belong in that project's own Makefile and, where CI must set them, in an
`extra-make-args` override.

Glob-friendly in both directions: `mpy6.3-*`, `*-armv7em*`, `*-x64` — though
an exact-arch pattern with no trailing `*` (`skip = "*-rv32imc"`) will not
match a `+0x..`-suffixed variant; `*-rv32imc*` does.

**What is actually true today**, since this is a living document rather than
a decision record: a usermod identifier is `{tag}-{port}` or
`{tag}-{port}-{axis value}` ([0023], leading tag added by [0051]) — the
MicroPython release always leads, the same slot natmod's own `mpy6.3-`
occupies, so both modes read left to right the same way:
`v1.29.0-unix-manylinux_2_28_x86_64`, `v1.29.0-webassembly`,
`v1.29.0-esp32-ESP32_GENERIC`, `v1.29.0-qemu`. `micropython` is a real list
([0051] closed the truncation-to-first-entry this used to have), so more
than one release can be selected in one invocation without one overwriting
another's output — the tag makes every build's output directory and filename
unique too, not only the identifier.

For `unix`, the axis value is a **PEP 600 / PEP 656 platform tag** —
`manylinux_2_28_x86_64`, `musllinux_1_2_aarch64`, `manylinux_2_39_mipsel`.
Records [0043]/[0044] put the libc floor and pypa's own architecture spelling
into the name deliberately, so the identifier states a compatibility claim
the build then verifies against the finished ELF, rather than labelling one.
The floor is *inside* the identifier here, unlike cibuildwheel's own
`cp313-manylinux_x86_64`, because cibuildmp curates exactly one floor per
architecture and offers no knob to choose another.

Landed as of [0051]'s Phases F, G, H and I, then substantially retracted
by [0052]'s own live-caught corrections (see that record's own
addenda): **there is no per-platform activation concept left at all.**
`--platform`, `CIBMP_PLATFORM`, `--only`, `--enable`/`GROUPS`, and
`--archs`'s `auto`/`native`/`all` keyword vocabulary are all gone — every
platform (natmod, and every usermod port) is always in scope, every
invocation, and `build`/`skip` glob-matching each platform's own real
identifiers is the only thing that decides what actually gets built. An
unconfigured `build` selects nothing at all, from any platform — the
zero-config default used to mean "natmod, narrowed to the newest known
ABI"; it now means nothing is built until a config says what it wants,
explicitly, via a glob. `--build`/`--skip` on the CLI (and
`CIBMP_BUILD`/`CIBMP_SKIP`) replace `--only`/`--platform`: name a glob
specific enough to match one identifier for "build exactly this one
thing", or list several to spread work across a CI matrix by hand — there
is no more keyword vocabulary computing that for you.

`[natmod]`/`[unix]`/`[windows]`/`[qemu]`/`[webassembly]`/`[esp32]` do not
exist as config tables at all any more — each one used to gate
activation (table presence as selection) and, before that, to carry a
per-platform axis (`archs =`/`boards =`). Both concepts are retracted:
every real `(platform, tag, arch/board)` combination is read directly
from `resources/build-platforms.toml` as a candidate row, always, the
identical model natmod's own arch axis already had before this round
(record 0052's own Track C) — `natmod_all_targets()`/
`all_usermod_targets()` are now the *only* place that enumerates what
exists; `build`/`skip` narrow it, nothing else does. `[usermod]` survived
this round as a seventh table, shared defaults for every usermod port at
once — since removed too (record 0074, see below); every one of these
seven names is now just an unrecognised top-level table, with no
per-name migration message.

`cibuildmp/options.py`'s cascade-based option resolution (`default →
global → environment → CLI`) is wired into both
`cibuildmp/platforms/natmod/options.py` and
`cibuildmp/platforms/usermod/options.py`, for the base layers *and* for
`[override]`/`inherit` — one shared top-level `[override]` table, keyed
directly by its own glob (`[override."*-armv7emsp"]`, no separate
`select =` field — a deliberate simplification over cibuildwheel's own
`[[tool.cibuildwheel.overrides]]` array-of-tables shape, decided live
2026-08-27: this project's own overrides are already a flat glob-matched
space, so the glob can simply *be* the table's own name, and declaration
order — which `tomllib` preserves — is what already decided precedence),
validated loosely (valid on some platform) at parse time and strictly
(valid on the *matched* identifier's own platform) at build time,
`inherit = {extra-make-args = "append"|"prepend"|"none"}` layered in via
`Options.get()`'s own `extra_layers`. `natmod`/`usermod` are physically
under `cibuildmp/platforms/` (Phase H), each a `PlatformModule`
(`resolve_options()`/`run_resolved()`) that `cli.py`'s own coordinator
reaches through a fixed `FAMILIES` tuple — it never names either module
directly, so a future platform family (zephyr, [0022]) costs one new
module plus one tuple entry, not a `cli.py` change. Since both families
are now always resolved together, `cli.py`'s coordinator does the "no
targets selected" check jointly, once, across every family's own
selected targets — one family selecting nothing while another selects
something is the ordinary case (a config that only configures one
family's own `build`), not a per-family error.

`build`/`skip`/`[override]` being shared, top-level config now (instead
of scoped by table presence) reopened a reachability question record
0052's own task #66 had left deliberately unresolved: a pattern meant
only for natmod (`build = "mpy6.3-*"`) must not read as a mistake just
because it matches nothing among usermod's own identifiers, and vice
versa. Fixed properly this round, not deferred again:
`Options.targets()`/`UsermodOptions.targets()` both take an optional
`foreign_identifiers` sequence, and `cli.py`'s own coordinator supplies
each family with every *other* active family's own `all_targets()`
identifiers before either does its own reachability audit — natmod still
never imports usermod (the established one-way dependency), it just
receives what it needs as a parameter from the one caller that already
sees every family.

The same live-caught round also corrected `narrow_to_newest_tag()`
(what an unpinned `build` glob resolves an ABI to, for natmod): a stable
release now always outranks a preview sharing the same ABI, even a
numerically older one, so an unpinned glob never silently lands on an
in-progress preview tag just because it happens to be the newest thing
verified for that ABI.

**Superseded, record 0074:** `[usermod]` used to sit one cascade tier
above the bare top level (`default → global → [usermod] → env → CLI`),
kept through every earlier round of retraction "at the user's own
explicit insistence" (record 0051's ninth addendum) as a value-holding
tier, not a selection mechanism. That tier is gone now, `Options` itself
no longer has a family layer at all: no real config in this project's own
examples ever actually wrote `[usermod]`, so the principle that kept it
alive never had a real caller behind it. `user-c-modules`/`manifest`/
`extra-make-args` resolve from `default → global → env → CLI` only, the
same as every other option.

[0022]: ../records/0022-zephyr-third-selector-axis.md
[0043]: ../records/0043-unix-adopts-cibuildwheel-native-image-model.md
[0044]: ../records/0044-unix-native-images-landed.md
[0051]: ../records/0051-usermod-identifiers-have-no-version-axis.md
[0052]: ../records/0052-config-is-a-tree-not-a-selector-matrix.md

<!-- migrated verbatim from docs/BACKLOG.md lines 477-518 (Config schema) -->

## Config schema (phase 1)

```toml
# cibuildmp.toml — repo root

output-dir = "mpyhouse"       # output-dir/<identifier>/ per target (D14)
build = ""                    # glob(s) over identifiers, space-separated --
                              # NOTHING builds until this names something.
                              # There is no version/tag config key at all
                              # any more, for either family: every real
                              # (tag, arch/board) row resources/
                              # build-platforms.toml has verified is a
                              # candidate, always, narrowed by build/skip
                              # glob-matching directly against each row's
                              # own real identifier.
skip = ""
name = ""                     # ([0052], A3) project identity for artifact
                              # filenames -- {name}-{version}-{identifier}
                              # instead of natmod's mpy_path.stem-derived
                              # default / usermod's literal "micropython"
                              # stem. Empty keeps today's filename exactly;
                              # setting it drops the old stem entirely
                              # rather than prefixing it.
version = ""                 # ([0052], A3 extended this to usermod too;
                              # previously natmod-only) set (CIBMP_VERSION
                              # in CI) to also write each natmod identifier's
                              # package.json (D14) and feed both families'
                              # {name}-{version}- filename prefix above --
                              # empty means just the .mpy/binary, no
                              # package.json yet for natmod, and no version
                              # segment in the filename for either family

# natmod's own keys -- no [natmod] table to hold them in any more (record
# 0052's own live-caught retraction: neither activation nor a settable
# schema of its own survives on it), so they live at the bare top level
# like every other global option. natmod-only by name, but there is no
# ambiguity about where they apply: usermod reads no key under any of
# these names at all.
module-dir = "natmod"         # dir containing the Makefile
make-target = "dist"
extra-make-args = []          # shared by name/meaning with usermod's own
pre-build-command = ""        # run in module-dir after mpy-cross, before make
                              # (a7p: "make fetch-nanopb")
arch-flags = ""               # rv32imc only, e.g. "zba,zcmp" (D15) -- part
                              # of that arch's identifier, so this cannot be
                              # set per-[override], only here

# usermod's own shared-across-every-port keys -- user-c-modules/manifest
# are usermod-only by name (natmod has no such keys at all), set at the
# bare top level like every other global option; no [usermod] table (or
# any other family-level tier) exists to hold them separately any more
# (record 0074 -- see below).
user-c-modules = "."
manifest = "usermod/manifest.py"

[publish]
extra-files = []              # copied into every identifier's own directory,
                              # untagged in package.json (D14) -- a facade
                              # or anything else install-everywhere (ffimod)

[override."*-armv7emsp"]
extra-make-args = ["MP_BCLIBC_PRECISION=single"]
# inherit = {extra-make-args = "append"}   # default "none" (replace);
                              # "append"/"prepend" only apply to
                              # extra-make-args, the one option genuinely
                              # list-shaped across every platform's own
                              # override surface ([0051] Phase G)
```

`[override]` is shared by every platform now, natmod and every usermod
port alike — the example above matches natmod's own; a usermod-port
identifier is matched by the identical glob mechanism, with
`user-c-modules`/`manifest`/`extra-make-args` as its own three settable
option keys instead of natmod's four. An override's own keys are
validated twice: loosely (is this key valid for *any* platform's override
surface — a typo check) when the config is loaded, and strictly (is this
key valid for the *specific* platform the matched identifier belongs to)
once the glob has actually matched a real target — `natmod`-only
`make-target` inside an override that only ever matches `unix`
identifiers is still a loud, specific error, not silently ignored.

Every option is overridable by environment variable, `CIBMP_`-prefixed and
screaming-snake-cased: `CIBMP_BUILD`, `CIBMP_SKIP`, `CIBMP_OUTPUT_DIR`,
`CIBMP_EXTRA_MAKE_ARGS`, `CIBMP_NAME`, `CIBMP_VERSION`, `CIBMP_ARCH_FLAGS`,
… — and `build`/`skip` also by `--build`/`--skip` directly on the CLI, the
replacement for the old `--only`/`--platform`/`--archs`. Precedence,
lowest to highest: defaults → config file → `[override]` matching the
identifier → environment → CLI flags.

**Where a key goes is part of the schema, and getting it wrong is an
error** ([0048], generalised into a cascade by [0051]'s own Phase F, then
simplified further by [0052]'s own retraction of every per-platform
table, and again by [0074]'s own removal of the family tier). The keys
above the first table header — `output-dir`, `build`, `skip`, `name`,
`version`, `micropython-submodules` — are invocation-wide and are read
**only** from the top level. `[0048]`'s own original bug (a `skip` placed
in the wrong table was silently ignored, so a misplaced key produced a
successful build of something you had asked not to build) is what every
one of these rounds has been about; today an unrecognised top-level
*table* (`[natmod]`, `[usermod]`, a typo like `[stm32]`, ...) is a plain
"unknown table" error via `cli.py`'s own `_validate_top_level_tables()`.
An unrecognised bare *scalar* key at the top level (`micropython =`,
`mpy-abi =`, or a plain typo) is the same kind of error, via the sibling
`_validate_top_level_keys()` ([0075]) — with a `difflib` close-match
suggestion, so `buidl = "..."` answers "Perhaps you meant `build`?".
Neither `Options.load()` nor `UsermodOptions.load()` validates that
keyset itself; the check lives in `cli.py` because only the coordinator
sees every family at once, and it unions each family module's own
`OPTION_KEYS` over `FAMILIES` rather than listing keys locally — a third
family's keys become valid by declaring them, with no edit to `cli.py`.
Until [0075] this was the one real hole left in the [0048] story: an
unrecognised scalar key was read as simply absent, its default silently
applying, which is [0048]'s own original bug wearing different clothes.

[0048]: ../records/0048-build-skip-live-in-opposite-tables.md
[0074]: ../records/0074-usermod-family-table-and-retired-table-messages-removed.md
[0075]: ../records/0075-top-level-scalar-keys-are-validated.md

Usermod's own real identifier space is documented in [0023] rather than
transcribed here — it is a genuinely different shape from natmod's
(`{tag}-{arch}` for `unix`/`windows`/`webassembly`, `{tag}-{port}-{board}`
for `qemu`/`esp32`; see the README's own "Identifiers and selectors"
section for the full table), not a variant of the example above. There is
no per-port config table at all any more (`[unix]`, `[esp32]`, ... —
[0051]'s Phase F introduced them, [0052]'s own live-caught retraction
removed them again along with the `archs =`/`boards =` axis config they
carried): every real `(port, tag, arch/board)` row is a candidate always,
narrowed only by `build`/`skip`. `[usermod]` outlived that round as
shared defaults for every port at once — it was never a selector, so none
of that retraction touched it directly — but is gone too now ([0074]):
`user-c-modules`/`manifest`/`extra-make-args` are plain top-level keys,
narrowed per port the same way everything else is, through
`[override."<glob>"]`.

**Opt-in groups and host-convenience keywords are both gone** ([0051]
point 8 added `enable`/`GROUPS` and record 0049 added `--archs auto`/
`native`/`all`; [0052]'s own live-caught retraction removed both, in the
same round that removed table-presence activation). Everything either
one could reach, an ordinary `build`/`skip` glob against the real
identifier already reaches directly — the six `unix`
ppc64le/s390x/riscv64 cells (both libcs) that `enable` used to gate are
reached (or excluded) the same way every other cell is, e.g.
`skip = "*_ppc64le *_s390x *_riscv64"` to exclude them, or naming them
directly in `build` to reach them. `auto`/`native`/`all` computed "what
runs natively on this machine" from `platform.machine()` at CLI-parse
time; a CI matrix now spells that out per runner by hand instead (see
`.github/workflows/build-examples.yml`'s own `build-usermod` job for a
worked example) — the README's own identifier reference plus a config's
own comments are meant to carry that teaching burden now, not a keyword
vocabulary the tool computes for you.

<!-- migrated verbatim from docs/BACKLOG.md lines 519-546 (Toolchain map); rewritten for the container era, [0050]/[0058] -->

## Toolchain map (arch → cross-compiler prefix, from `py/dynruntime.mk`)

Ten arches, five distinct cross-compiler prefixes:

| ARCH | `CROSS` |
| --- | --- |
| `x64` | *(none)* |
| `x86` | *(none)*, `-m32` |
| `armv6m` `armv7m` `armv7emsp` `armv7emdp` | `arm-none-eabi-` |
| `xtensa` | `xtensa-lx106-elf-` |
| `xtensawin` | `xtensa-esp32-elf-` |
| `rv32imc` `rv64imc` | `riscv64-unknown-elf-` |

This table only answers "which compiler does this arch need" — it says
nothing about how that compiler actually reaches a build, and that half
moved to containers entirely ([0050]): there is no host toolchain resolver
left at all (`natmod/toolchains.py`, its `--toolchain` flag, and
`resources/natmod.toml`'s own `[[toolchain]]` table were all deleted), and
no bare-host natmod build path survives it. Every arch above now runs inside
a pulled image — one of six toolchain-group images keyed by what they hold,
not by port ([0058]), several shared across natmod arches and usermod ports
alike. See [docs/reference/vendored-images.md](vendored-images.md) for the
full group model: which arch/port/board resolves to which image, how a build
actually picks one at runtime, and how those images get published.

`xtensawin` needing no full ESP-IDF (only `xtensa-esp32-elf-` on `PATH`) and
RISC-V needing a picolibc-shipping toolchain (`dynruntime.mk` probes
`$(CROSS)gcc --print-file-name=picolibc.specs` and falls back to `nosys`
otherwise, silently, if the toolchain lacks it) were both open questions
here once; [0036] resolved and verified both, and [0050]'s own image build
later baked the same prefix reconciliation in permanently, via symlinks
rather than a `CROSS=` override on every make invocation.

<!-- migrated verbatim from docs/BACKLOG.md lines 547-570 (Local use) -->

## Local use

Running the same build on a laptop that CI runs is a goal, not a
side effect — it is most of why the tool exists rather than more composite
actions (**D3**). `cibuildmp --dry-run` and `cibuildmp` behave the same
locally as on a runner, with the same config.

**Superseded from what this section originally described, as of
[0030]/[0033]/[0050]:** every build — natmod and every usermod port alike —
is Docker-only now, with no bare-host path left for either family. This
section used to carry a per-arch table ("`x64` works with the host gcc,
nothing to install", tarballs downloaded into `~/.cache/cibuildmp/` for the
rest) describing natmod's own host toolchain resolver; [0050] deleted that
resolver outright, along with the last arch (`x64`/`x86`, `natmod_host`
below) that used to run directly on the invoking machine. There is nothing
left that self-provisions onto the host — `x86`'s 32-bit multilib included,
which is exactly what makes it buildable on an arm64 runner now, inside an
amd64 container.

Nothing about this is CI-specific: the resolved image, the container
invocation and the build loop are the same code path in both places — a
runner only starts with an empty local image cache. `docker` (a reachable
daemon) is now a hard local-use prerequisite for every target, natmod
included; see [docs/reference/vendored-images.md](vendored-images.md) for
exactly what each target pulls. Non-Linux hosts (reaching a docker daemon,
not a toolchain) are an open question — see
[docs/reference/open-questions.md](open-questions.md).

<!-- migrated verbatim from docs/BACKLOG.md lines 3649-3666 (Non-goals) -->

## Non-goals

- Being a general-purpose stock-firmware builder/browser with no module
  attached — that is `mpbuild`. This is not a limit on which boards
  `cibuildmp` can target: **D7** vendors `mpbuild`'s whole board database,
  not a curated subset, precisely so any board it knows can be a usermod
  target. The line is that every `cibuildmp` firmware build always has a
  project's own module baked in via `USER_C_MODULES=` and is treated as a
  verification output, never a bare "give me board X's stock firmware"
  product with no module involved.
- Compiling anything itself. `dynruntime.mk` and the project's Makefile own
  that (**D2**).
- Replacing `mpremote`/`mip` on the install side.
- Creating a release or uploading anything (**D14**). `cibuildmp` assembles
  a ready-to-install `output-dir/<identifier>/` tree; turning that into a
  GitHub Release, a PyPI-style index, or any other host stays the
  caller's own CI step — cibuildwheel draws the identical line at
  `wheelhouse/`, and never runs `twine upload` itself either.

[0006]: ../records/0006-no-test-runners-phase1.md
[0007]: ../records/0007-usermod-vendors-mpbuild-board-db.md
[0011]: ../records/0011-one-repo-absorbs-micropython-native-ci.md
[0013]: ../records/0013-micropython-list-dedup-by-abi.md
[0014]: ../records/0014-mip-package-per-identifier.md
[0015]: ../records/0015-rv32imc-arch-flags-identifier.md
[0023]: ../records/0023-usermod-identifier-scheme-config-output.md
[0030]: ../records/0030-container-approach-natmod-and-docker-vs-qemu.md
[0033]: ../records/0033-cibuildmp-never-builds-docker-image-itself.md
[0036]: ../records/0036-m2-toolchain-resolver.md
[0050]: ../records/0050-natmod-is-docker-only.md
[0058]: ../records/0058-image-groups-are-toolchains-not-ports.md

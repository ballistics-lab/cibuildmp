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

The composite actions in `.github/actions/` solve the toolchain problem, but
only inside GitHub Actions. Everything around them stays hand-copied in each
consuming repo:

- the arch matrix itself (`natmod.yml`'s 10-entry `arch:` list, duplicated
  per repo),
- `runs-on:` selection, which a composite action structurally cannot do for
  itself (documented under `build-usermod-unix` in `README.md`),
- `upload-artifact` name/path globs, deliberately left to the caller,
- the `@v0.2.0` pin, repeated ~15 times across three repos,
- and there is no way to reproduce any of it locally.

`cibuildmp` absorbs those five. The actions stay as the low-level layer until
`cibuildmp` covers their ground, then become thin wrappers over it (the same
relationship `pypa/cibuildwheel@v3` has with `python -m cibuildwheel`).

<!-- migrated verbatim from docs/BACKLOG.md lines 433-476 (Identifier scheme) -->

## Identifier scheme

Shaped after `cp311-manylinux_x86_64` = *{ABI}\_{arch}*, but with no literal
mode segment (record [0052], Track A/A2):

```
mpy6.3-armv7emsp
mpy6.3-x64
```

- **`mpy6.3`** — the `.mpy` ABI: `MPY_VERSION`.`MPY_SUB_VERSION` from
  `py/persistentcode.h`. This is the correct compatibility axis, not the
  MicroPython release tag: a native `.mpy` loads into any runtime with a
  matching `MPY_VERSION`/`MPY_SUB_VERSION` pair, which spans several
  releases.

  There is no `micropython`/`mpy-abi` config key any more ([0052], A2): the
  version axis is a statically known domain — `resources/build-platforms.toml`
  records every `.mpy` ABI this project has actually verified against a real
  MicroPython tag (five today: `5`, `6`, `6.1`, `6.2`, `6.3`), each resolved
  to its own newest known tag automatically. `build`/`skip` narrow that
  domain by matching identifiers, exactly the way they already narrow
  `archs`; a bare, unconfigured `build` selector narrows it further still, to
  the single newest known ABI, so a zero-config invocation keeps building
  only that one ABI rather than every one this project has ever verified.
  There is currently no way to pin an explicit tag instead of the
  auto-picked newest one for a given ABI — a real, open gap, not yet
  designed.
- No literal mode/platform segment — `natmod` is one platform among the
  usermod ports too now ([0051]), all sharing this same *{ABI}\_{arch}*
  shape rather than natmod alone spelling its own name into the string.
- **arch** — one of `dynruntime.mk`'s ten `ARCH` values.
- **`+0x..`** (optional, `rv32imc` only) — `arch_flags`, present only when
  `arch-flags` is set (**D15**): `mpy6.3-rv32imc+0x3`. Absent for every
  other arch and for `rv32imc` with no `arch-flags` configured.

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

Landed as of [0051]'s Phases F, G, H and I (see that record's own
fourth/fifth/seventh/eighth addenda): `--platform` names one or more of
six platforms (`natmod`, `unix`, `windows`, `qemu`, `webassembly`,
`esp32`) rather than a build mode, the way upstream's own `--platform`
names an OS, and the config tree matches — `[unix]`/`[esp32]` sibling to
`[natmod]`, no more `[usermod.<port>]` nesting and no more `ports =
[...]` list, table presence alone selects a platform.
`cibuildmp/options.py`'s cascade-based option resolution (`default →
global → platform table → environment → CLI`, matching upstream's own
`Options.get()`) is wired into both `cibuildmp/platforms/natmod/options.py`
and `cibuildmp/platforms/usermod/options.py`, for the base four layers
*and* for `[override]`/`inherit` now — one shared top-level `[override]`
table, keyed directly by its own glob (`[override."*-armv7emsp"]`, no
separate `select =` field — a deliberate simplification over
cibuildwheel's own `[[tool.cibuildwheel.overrides]]` array-of-tables
shape, decided live 2026-08-27: this project's own overrides are already
a flat glob-matched space, so the glob can simply *be* the table's own
name, and declaration order — which `tomllib` preserves — is what already
decided precedence), validated loosely (valid on some platform) at
parse time and strictly (valid on the *matched* identifier's own
platform) at build time, `inherit = {extra-make-args =
"append"|"prepend"|"none"}` layered in via `Options.get()`'s own
`extra_layers`. `natmod`/`usermod` are physically under
`cibuildmp/platforms/` too (Phase H), each a `PlatformModule`
(`resolve_options()`/`run()`) that `cli.py`'s own dispatch reaches only
through a `PLATFORM_FAMILY` registry — it never names either module
directly, so a future platform family (zephyr, [0022]) costs one new
module plus registry entries, not a `cli.py` change.

`[usermod]` itself came back after Phase I landed, the same day, in a
same-day design discussion this record's ninth addendum covers in full:
not the pre-Phase-F selector (`ports = [...]`, nested port sub-tables —
both still gone, both still loud errors), but a genuine third cascade
tier — `default → global → family → platform → env → CLI` — shared
defaults for every active usermod port at once, sibling to `[natmod]`,
validated by every registered family unconditionally
(`platforms.PlatformModule.validate_family_table()`, called from
`cli.py`'s own `active_platforms()` before any platform is known to be
active, so a stale family table is still caught even when nothing else
would ever load that far). `natmod`'s own implementation is a no-op —
one platform is already its only family. The same design pass renamed
usermod's own `module-dir` to `user-c-modules` (natmod's own stays
`module-dir`, untouched — the two names collided despite meaning
different things to different downstream consumers, record 0051's sixth
addendum) and changed its default from `"usermod"` to `"."`, the broader
glob that also matches every real consuming project's own hand-written
choice.

[0043]: ../records/0043-unix-adopts-cibuildwheel-native-image-model.md
[0044]: ../records/0044-unix-native-images-landed.md
[0051]: ../records/0051-usermod-identifiers-have-no-version-axis.md

<!-- migrated verbatim from docs/BACKLOG.md lines 477-518 (Config schema) -->

## Config schema (phase 1)

```toml
# cibuildmp.toml — repo root

micropython = "v1.29.0"       # usermod only ([0052], A2): release tag(s) to
                              # build against -- also accepts a list (D13):
                              # ["v1.22.0", "v1.29.0"]. This list is the
                              # leading axis; every listed tag builds, output
                              # kept apart by identifier ([0051]). natmod has
                              # no version config key at all any more -- its
                              # own version axis is the static domain of
                              # every `.mpy` ABI resources/build-platforms.toml
                              # has verified, narrowed by build/skip matching
                              # identifiers exactly like archs already is.
output-dir = "mpyhouse"       # output-dir/<identifier>/ per target (D14)
build = "*"                   # glob(s) over identifiers, space-separated
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

[natmod]
archs = ["x64", "x86", "armv6m", "armv7m", "armv7emsp", "armv7emdp",
         "rv32imc", "rv64imc", "xtensa", "xtensawin"]
module-dir = "natmod"         # dir containing the Makefile
make-target = "dist"
extra-make-args = []
pre-build-command = ""        # run in module-dir after mpy-cross, before make
                              # (a7p: "make fetch-nanopb")
arch-flags = ""               # rv32imc only, e.g. "zba,zcmp" (D15) -- part
                              # of that arch's identifier, so this cannot be
                              # set per-[override], only here

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
screaming-snake-cased: `CIBMP_BUILD`, `CIBMP_SKIP`, `CIBMP_MICROPYTHON`,
`CIBMP_OUTPUT_DIR`, `CIBMP_EXTRA_MAKE_ARGS`, `CIBMP_NAME`, `CIBMP_VERSION`,
`CIBMP_ARCH_FLAGS`, … Precedence, lowest to highest: defaults → config
file → `[override]` matching the identifier → environment → CLI flags.

**Where a key goes is part of the schema, and getting it wrong is an
error** ([0048], generalised into a cascade by [0051]'s own Phase F). The
keys above the first table header — `micropython` (usermod only since
[0052]'s A2 removed natmod's own use of it), `output-dir`, `build`, `skip`,
`name`, `version`, `micropython-submodules`, `enable` — are invocation-wide
and are read **only** from the top level, across every platform (`mpy-abi` is gone
entirely, not merely relocated — writing it anywhere is now a plain unknown-
key error). Writing one inside `[natmod]` or a usermod port's own table
fails with a message naming where it belongs; so does any key that table's
own schema does not read at all (a typo, or an `arch-flags` inside
`[override]`). Until [0048] every one of those was silently ignored,
which meant a misplaced `skip` produced a successful build of something
you had asked not to build; the check itself moved from a fixed
per-table-shape partition to a per-platform-schema one under [0051]'s own
cascade, but the guarantee is the same. `archs`/`arch-flags` remain the one
deliberate exception: natmod reads them from the top level *or* `[natmod]`,
and both work, so neither is silent — under the cascade this is simply the
general case (global default, platform-specific override), not a
special-cased pair of keys.

[0048]: ../records/0048-build-skip-live-in-opposite-tables.md

Usermod's own per-port config shape is documented in [0023] rather than
transcribed here — it is a genuinely different shape (no ABI axis, a
per-port arch/board axis instead), not a variant of the table above. As of
[0051]'s Phase F, every usermod port is its own top-level table —
`[unix]`, `[windows]`, `[qemu]`, `[webassembly]`, `[esp32]` — sibling to
`[natmod]`; there is no more `ports = [...]` list (a port's own table
presence is what selects it, the same rule `[natmod]`'s presence has
always followed). `[usermod]` itself came back after Phase I (the
ninth addendum), but not as an umbrella over the five port tables and
not a selector — a sixth sibling table, sitting one cascade tier above
them, holding shared defaults for whichever ports are active. Its own
three settable option keys (`user-c-modules`/`manifest`/`extra-make-args`
— `user-c-modules` renamed from `module-dir`, since that name collided
with natmod's own key of the same name meaning something different, see
[0051]'s sixth addendum) are genuinely global-with-family-with-
per-platform-override now: `default → global → [usermod] → [<port>] →
env → CLI`, resolved through the same `Options` class natmod's own four
keys use, natmod's own instance simply never given a family table since
it has no sibling ports to share defaults with. `[override]` is shared
with natmod as of Phase G (see above) — the old, short-lived
`[[usermod-overrides]]` name (Phase F's rename of the even older nested
`[[usermod.overrides]]`) is gone; there is exactly one top-level
`[override]` table now, for every platform.

**Opt-in groups** ([0051] point 8, upstream's own `EnableGroup`): `enable`
(config key, top-level, space-separated string or list; `--enable`,
repeatable, on the CLI) names groups a bare `build = "*"` should reach
anyway. Only usermod defines any today —
`usermod.targets.GROUPS["unix-emulated-everywhere"]` covers
`ppc64le`/`s390x`/`riscv64`, both libcs, glob-matched rather than
enumerated. A target matching an unenabled group is excluded before
`build`/`skip` is even checked (`cibuildmp.selector.select()`), so it
cannot be worked around by naming it in `build` — only `enable` reaches it.
This is also what finally answers the six emulated-everywhere `unix`
cells' own "in the axis or not" question: they are in `default_axis_values
("unix")` now (equal to `all_axis_values("unix")` in full), and it is the
group, not axis membership, that still keeps a plain `[unix]` config at
nine cells by default.

<!-- migrated verbatim from docs/BACKLOG.md lines 519-546 (Toolchain map) -->

## Toolchain map (authoritative, from `py/dynruntime.mk`)

Ten arches, five distinct toolchains:

| ARCH | `CROSS` | Provisioning |
| --- | --- | --- |
| `x64` | *(none)* | host gcc |
| `x86` | *(none)*, `-m32` | host gcc + multilib |
| `armv6m` `armv7m` `armv7emsp` `armv7emdp` | `arm-none-eabi-` | downloadable tarball |
| `xtensa` | `xtensa-lx106-elf-` | downloadable tarball (already done in `build-natmod`) |
| `xtensawin` | `xtensa-esp32-elf-` | see below |
| `rv32imc` `rv64imc` | `riscv64-unknown-elf-` | downloadable tarball, must ship picolibc |

Two findings worth acting on:

- **`xtensawin` does not need ESP-IDF.** `dynruntime.mk` only ever asks for
  `xtensa-esp32-elf-` on `PATH`. The current `build-natmod` action installs
  the entire IDF (`--recursive` clone, the heaviest single step in this repo)
  to obtain one cross-gcc. Espressif publishes standalone crosstool-NG
  toolchain builds — **verify and switch to those**; it should cut minutes
  off every run.
- **RISC-V needs picolibc.** `dynruntime.mk` probes
  `$(CROSS)gcc --print-file-name=picolibc.specs` and only sets
  `-specs=`/`USE_PICOLIBC` if the toolchain ships it; Ubuntu 24.04's own
  bare-metal RISC-V toolchain does, and the default is otherwise `nosys`.
  Whichever tarball the resolver picks must ship picolibc, or `rv32imc` /
  `rv64imc` silently build against a different libc than CI does today.

(Resolved and shipped as of [0036] — see that record for what actually
landed, including the prefix-reconciliation and picolibc details.)

<!-- migrated verbatim from docs/BACKLOG.md lines 547-570 (Local use) -->

## Local use

Running the same build on a laptop that CI runs is a goal, not a
side effect — it is most of why the tool exists rather than more composite
actions (**D3**). From M2 on, `cibuildmp --dry-run` and `cibuildmp` behave
the same locally as on a runner, with the same config.

What that means per arch, on a Linux host:

| Target | Local story |
| --- | --- |
| `x64` | works with the host gcc, nothing to install |
| `armv6m` `armv7m` `armv7emsp` `armv7emdp` | toolchain downloaded into `~/.cache/cibuildmp/` on first use |
| `xtensa` `xtensawin` `rv32imc` `rv64imc` | same, once each tarball source is pinned |
| `x86` | needs `gcc-multilib` on the host; cannot be fixed by a download |

`x86` is the one that will not be self-provisioning, so it must fail with a
message naming the package rather than a compiler error. Non-Linux hosts are
an open question — see [docs/reference/open-questions.md](open-questions.md).

Nothing about this is CI-specific: the cache directory, the toolchain
resolver and the build loop are the same code path in both places. The only
thing a runner adds is that its cache starts empty.

**Note (as of [0030]/[0033]):** for usermod, this "no Docker, no host
mutation" story was later superseded — usermod builds are Docker-only, and
`cibuildmp` itself never builds an image, only pulls a published one. natmod
keeps the host/download story above as its preferred path, with Docker as an
additional, not required, option. See [0030] and [0033] for the full
reasoning.

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

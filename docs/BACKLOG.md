# cibuildmp — implementation backlog

`cibuildmp` is a `cibuildwheel`-shaped build driver for MicroPython native C
extensions: one declarative config in the module's own repo drives the whole
target matrix, resolves each target's toolchain itself, and runs identically
on a developer laptop and on CI.

This file is the plan. It records the decisions that are already locked, the
scheme they imply, and the order of work. It is not a changelog — see
`CHANGELOG.md` for what actually shipped.

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

## Locked decisions

**D1 — natmod first, and natmod is the wheel-shaped half.**
A natmod `.mpy` is a portable, ABI-tagged binary artifact with a real
distribution channel (GitHub release + `package.json` + `mip install`). That
maps onto cibuildwheel almost exactly. A usermod artifact is firmware — it is
not installed into a runtime, it *is* the runtime — so it gets a different
pipeline, later. Phase 1 ships natmod only.

**D2 — delegate the compile, own the environment.**
Like cibuildwheel, `cibuildmp` does not know how to compile anything. It
invokes the project's own `natmod/Makefile` (which includes
`py/dynruntime.mk` and takes `ARCH=` / `MPY_DIR=`). What `cibuildmp` *does*
own, and what no consuming repo should write again:

- fetching/checking out MicroPython at the configured tag,
- building `mpy-cross`,
- resolving and provisioning the cross toolchain for each target,
- pointing `mpy_ld.py` at its own interpreter (`PYTHON=`) so its host deps
  (`pyelftools`, `ar`) resolve from `cibuildmp`'s own dependencies (**D12**),
- collecting outputs into an output directory with unambiguous names.

**D3 — toolchain resolution is per-target, chosen by the tool (variant C).**
Download-into-cache is the default where a standalone toolchain tarball
exists; Docker and "already on PATH" are escape hatches. Selecting the
mechanism is `cibuildmp`'s job, not the user's — that self-resolution is the
part of cibuildwheel worth copying.

**D4 — config lives in `cibuildmp.toml` at the repo root.**
MicroPython C-module repos have no `pyproject.toml` and it is not their
convention. `cibuildmp.toml` uses top-level tables. If a `pyproject.toml`
exists, the same tree is also accepted under `[tool.cibuildmp]`;
`cibuildmp.toml` wins when both are present.

**D5 — one identifier namespace, one override mechanism.**
Config is scoped by build mode the way cibuildwheel scopes by platform
(`[tool.cibuildwheel.android]`, `.pyodide`, …), but *selectors* — `build`,
`skip`, and `overrides[].select` — are globs over a single flat identifier
string. The current draft config's three different override shapes collapse
into one `[[overrides]]` list.

**D6 — no test runners in phase 1.**
Execution substrates (qemu-user, qemu-system, rp2040py, node, real hardware
over `mpremote`) are a genuinely hard axis and are deferred. Phase 1 is
build-only. `[test]` keys are not parsed yet; do not ship a half-working
version of them.

**D7 — usermod vendors `mpbuild`'s board database, not depends on the
package.**
[`mattytrentini/mpbuild`](https://github.com/mattytrentini/mpbuild) (PyPI
`mpbuild`, 1.2.0) has a board database worth reusing, but the package itself
is not worth the dependency it costs. `board_database.py` is 293 lines,
stdlib-only (`glob`, `json`, `dataclasses`, `Path`), MIT-licensed (© 2024
Matt Trentini) — not enough code to justify pulling `mpbuild` itself, which
drags in `rich` + `textual` + `typer` and requires Python ≥3.12, a TUI stack
on top of a build driver that has stayed standard-library-only since M1/M2
for exactly this reason.

Extract into one vendored module (`usermod/boards.py`, MIT header kept, with
a comment naming the origin repo and the commit it was taken from — the same
discipline **D14** applies to the `package.json` schema):

- `Port`/`Board`/`Variant` plus the `ports/*/boards/*/board.json` scan,
- `check_board_json`.

Do **not** take the port → Docker-image map or command construction: that
layer is exactly what **D3** wants `cibuildmp` to resolve itself, and it is
coupled to mpbuild's own CLI.

Verified directly against mpbuild's source (`src/mpbuild/build.py` and
`board_database.py`), not assumed: the boundary above holds exactly at the
file level. `board_database.py` has zero Docker references — its own
`Board.images` field is board *photographs* from the `micropython-media`
repo, easy to misread as a hit on first grep, not container images. The
port → image resolution mpbuild actually uses lives entirely in
`build.py`, as a small, mostly-static `BUILD_CONTAINERS` dict keyed by
**port**, not by board: `"stm32"`/`"rp2"` → `micropython/build-micropython-arm`
(`ARM_BUILD_CONTAINER`), `"esp32"` → `espressif/idf:v5.4.2`
(`ESP_IDF_CONTAINER:ESP_IDF_FALLBACK_VERSION`), and so on per port. Two
special cases sit on top of the static table rather than folding into it:
`rp2` switches to `micropython/build-micropython-rp2350riscv` when its
`variant == "RISCV"` (the ARM image otherwise), and `esp32` runs a
three-tier version probe (lockfile → CI workflow → the hardcoded `v5.4.2`
fallback above) instead of one fixed tag — the only place this map is not
pure data. `docker_build_cmd()` then assembles an ordinary `docker run
--rm -v <mpy_dir>:<mpy_dir> -w <mpy_dir> --user <uid>:<gid> -e HOME=/tmp
<image> ...` — nothing mpbuild-specific in the invocation shape itself.

This narrows what "do not take the command construction" means in
practice: the `docker run` shape is generic enough not to need
transcribing at all, and the image table is small enough to fit **D10**'s
pattern directly rather than D7's own vendored-module treatment — a
`resources/usermod-images.toml` (port → image, with the `rp2` RISCV
variant as an override entry) plus one small hand-written function for the
esp32 version probe, sourced by hand from `build.py` rather than imported.
Feeds directly into **D19**: the same table this describes is exactly what
an eventual `docker` strategy for `esp32` (and `rp2`/`stm32` too, if D20's
runner story puts them on it) would pin.

Correction to a constraint this decision previously rested on: mpbuild does
**not** require a MicroPython git checkout. `Database.__post_init__` only
checks `(root / "ports").is_dir()`; nothing else in the module touches git,
and M1's release tarball satisfies that condition. That removes one of the
three original reasons mpbuild was called "complementary, not competing," so
it should not be repeated as a reason to keep the dependency.

Honest tradeoff: `board.json`'s schema and the variant convention drift
upstream, and vendoring means tracking that drift by hand. Pinning
`mpbuild==1.2.0` would not avoid tracking it either, just tie it to someone
else's release cadence instead. This is not pinned data in the **D10**
sense — it is read from the checkout at runtime, so nothing goes into
`resources/`.

**D8 — distribution of the tool itself is deferred.**
The PyPI name `cibuildmp` is free (404 on the JSON API) but not reserved.
Until it is, both actions install from their own checkout —
`uv tool install ${{ github.action_path }}` — so the version that runs is
exactly the ref the caller pinned, with no package index to keep in sync
with the action tag. Under **D11** this is no longer a workaround so much as
the natural arrangement: the action root and the package root are the same
directory. Reserving the name is still worth doing, if only to stop someone
else taking it.

**D9 — one job looping over targets is the default; fan-out is opt-in.**
Verified against cibuildwheel rather than assumed: its canonical workflow
(`examples/github-minimal.yml`) puts *runners* in `strategy.matrix` — `os:
[ubuntu-latest, ubuntu-24.04-arm, windows-latest, windows-11-arm,
macos-15-intel, macos-14]` — and loops over the Python versions inside each
job. There is no matrix over `cp311`/`cp312`/… at all, and
`--print-build-identifiers` appears in its docs exactly once, under
`build`/`skip`, as introspection; the widely copied `jq` matrix recipe is a
community pattern, not something cibuildwheel documents.

The reason is that the runner is a hard constraint there: a macOS wheel
cannot be built on Linux. **That constraint does not exist for natmod** —
all ten arches are cross-compiles on x86-64 Linux. What *does* cost is
fetching MicroPython and building `mpy-cross`, which are identical for every
arch, so a ten-leg matrix pays for them ten times.

So `cibuildmp` with no `--only` builds every selected target sequentially in
one invocation. `--only` remains for callers who want a job per target
anyway — failure isolation, wall-clock parallelism — and is what the matrix
generator feeds. Revisit for usermod, where different targets genuinely need
different runners and the fan-out becomes structural rather than a
preference.

**D10 — pinned data lives in `resources/`, not in Python.**
Checked against cibuildwheel rather than invented: it keeps
`resources/build-platforms.toml` (identifiers and interpreter versions),
`resources/pinned_docker_images.cfg` (image digests, pinned by `@sha256:`
with a dated comment), `nodejs.toml` and
`python-build-standalone-releases.json` out of its source — which is why its
`--only` reads its `choices` from `read_all_configs()`. Everything in those
files goes stale on someone else's schedule, so bumping one should be a
reviewable data diff a script can make, not a patch to resolver logic.

`src/cibuildmp/resources/natmod.toml` holds all three of ours: the arch →
`CROSS` map (transcribed from `py/dynruntime.mk`), the tag → `.mpy` ABI map
(from `py/persistentcode.h`), and the toolchain download pins. A cross-check
runs at import and fails loudly if the arch table and the toolchain table
disagree about a prefix.

**D11 — one repository: `cibuildmp` absorbed `micropython-native-ci`.**
The tool and the composite actions ship together, on one version line
continuing the old repository's (`v0.3.0` follows `v0.2.0`; the actions in
it are the same actions, moved). The old repository is deprecated and gets
archived once its three consumers have repinned.

The alternative — tool in one repo, actions in the other — split a thing
that is converging, not diverging: M5 turns `build-natmod` into a wrapper
over `cibuildmp --only`, which is awkward across a repo boundary and
impossible to release atomically. Keeping both copies alive, meanwhile, was
exactly the drift this whole project exists to end.

The cost is real and falls on consumers: bclibc, a7p and micropython-wasm3
each have ~15 `uses:` paths to repin. That is a one-line-per-reference
change with no behaviour difference, and old pins keep working until they
make it.

**D12 — `pyelftools` and `ar` are `cibuildmp`'s own dependencies, not
something it installs at build time.**
Neither is binutils. `ar` (PyPI `ar`, 1.0.1, "Access ar archive files") is a
pure-Python package that `mpy_ld.py` imports via `from ar import Archive` in
a `try`/`except`; `pyelftools` is imported directly as `elftools.elf`. No
system binary involved for either.

`ar` is formally optional in `mpy_ld.py` (`Archive = None` when the import
fails) but not practically optional for `cibuildmp`: it is needed whenever
`MPY_LD_FLAGS` contains `-l...a`, which is always true under
`LINK_RUNTIME=1` — the case bclibc uses to link `libm.a`. So both are
ordinary dependencies, not an `extra`; both are small and pure-Python, so the
cost is low. `pyelftools` should be pinned wide (`pyelftools>=0.29`), not
exact — the pin is shared across every MicroPython tag a user's config
builds, and the surface `mpy_ld.py` actually uses is narrow and stable, but a
tight pin would let one old tag break the whole tool.

Mechanism is the one already verified for `CROSS=` under M2:
`py/dynruntime.mk` line 10 assigns `PYTHON = python3` with a plain `=`, never
`override`, so a command-line variable wins. `cibuildmp` passes
`PYTHON=<sys.executable>` alongside `CROSS=`, and `make` runs `mpy_ld.py`
under the interpreter that already has both packages — the "isolated
environment" this used to require comes for free, since `uv tool install`
(**D8**) already puts `cibuildmp` in its own venv and the system interpreter
is never touched. This removes the first M3 checkbox as separate work; it is
one more argument on the `make` command line.

**D13 — `micropython` accepts a list, deduped by ABI, not by tag.**
Resolves the open question this file used to carry under that name.
`micropython` takes either a string or a list, the same "accept a list, or
a shell-ish string" idiom `archs`/`build`/`skip`/`extra-make-args` already
use (`options._as_list`) — no new config convention.

Building against several tags is a real use case only when they cross an
ABI boundary (`py/persistentcode.h`'s `MPY_VERSION`/`MPY_SUB_VERSION`);
otherwise every one of them produces a byte-for-byte identical native
`.mpy`, since the identifier — and so the output — is keyed on ABI, not
tag. So `targets.resolve_micropython_tags()` collapses the list to one
`(tag, abi)` pair per distinct ABI, keeping whichever tag came first in
the list and silently dropping a later one whose ABI an earlier one
already covers. `micropython = ["v1.23.0", "v1.28.0"]` is one build
against `v1.23.0` (both are ABI 6.3), not two; `["v1.22.0", "v1.28.0"]`
is two (6.2 and 6.3) — the real case this exists for.

Each `(tag, abi)` pair is its own ABI group: `Target` now carries the
`tag` it was resolved against (identifiers stay ABI-only, unaffected), and
`cli.build()` fetches MicroPython and builds `mpy-cross` once per group
rather than once per invocation — the D9 sharing argument still holds
*within* a group, just not across a genuine ABI boundary, where the
source is different by construction and there is nothing to share.

Verified live against a real second ABI (`v1.22.0` + `v1.28.0`, ABI 6.2 and
6.3): two groups, `fetch_micropython` called once per tag, two correctly
named outputs. One caveat surfaced by that same test, unrelated to this
decision's own logic: an old enough tag can fail to build `mpy-cross`
under a modern host `gcc` on its own merits — tried with `v1.21.0`,
upstream's `py/emitinlinethumb.c`/`emitinlinextensa.c` initialise
fixed-size `char` arrays without room for the trailing NUL (`{10,
"r10"}`), which a recent `gcc`'s `-Werror=unterminated-string-initialization`
rejects. `mpy-cross` is a host build, not a cross-compile, so this is not
a toolchain-resolution problem cibuildmp can route around; it is a real
constraint on which old tags a multi-version config can list on a modern
runner. `examples/template/cibuildmp.toml` stays single-tag for exactly
this reason — its job is to keep CI green on M3's build path, not to
chase every historical tag's own build health.

**D14 — `cibuildmp` itself writes one self-contained mip package per
identifier as part of the normal build, in today's stable schema — there
is no separate `cibuildmp publish` command.**
Originally scoped as a separate `cibuildmp publish` absorbing bclibc's
`tools/build_release_assets.py`, and around the "per-entry native code
compatibility tag" schema — [micropython#19532](https://github.com/micropython/micropython/pull/19532)
/ [micropython-lib#1144](https://github.com/micropython/micropython-lib/pull/1144)
— which would let one `package.json` list every arch's `.mpy`, each
tagged, and let `mip` pick the right one at install time. Both revisited:

- **No separate command.** `mpyhouse/` is the thing to fix, not a second
  step that reorganises it afterwards: `cli.build()` writes each target
  straight into `output-dir/<identifier>/` from the start, so an
  identifier's directory already holds its `.mpy`, any `extra-files`
  companions, and its own `package.json` the moment that target's build
  finishes. Consistent with cibuildwheel, which has no publish step
  either — `wheelhouse/` is immediately `twine upload`-able, no
  intermediate packaging command. Creating a release or uploading the
  tree stays the caller's own CI step (**Non-goals**), same as
  `wheelhouse/*` → `twine upload` is the caller's job, never
  cibuildwheel's.
- **No compat-tag schema dependency.** Both upstream PRs are
  self-authored (by this project's own maintainer), open, with no
  reviewers, and each explicitly says "not yet tested ... on real
  hardware ... before merge." That is a materially weaker foundation than
  "a proposal pending review" suggested — depending on an unmerged,
  hardware-untested, zero-review-traction PR of one's own is premature,
  however directionally sound the schema itself is.

Each identifier's `package.json` uses the plain two-element
`["path", "url"]` `urls` schema `mip` has always supported — no compat
tag, no upstream change needed, works with every `mip` in the wild today.
A consumer picks which identifier's `package.json` to `mip.install()` by
URL, the same way `--only <identifier>` already picks one target to
build; the tag-matching problem #19532/#1144 solve is sidestepped by the
*URL* being the selector instead of runtime tag matching on-device. A
single unified, tag-matching manifest stays possible as a later, additive
mode on top of the per-identifier one — gated on those two PRs actually
picking up review traction or landing, not on a fixed date.

**Companion files, the original reason for this decision:** found
inspecting a real second module in `../micropython-bclibc` — `ffimod/`
builds a native `.so` plus facade `.py` files (`ffi.py`,
`_tiny_bclibc.py`) that stay separate, unlike `natmod/`, where
`SRC = tiny_bclibc_mp.c tiny_bclibc.py` already gets merged by
`dynruntime.mk`'s own `SRC_MPY`/`--merge` rule into one `.mpy` per arch —
that merged case needs nothing from `cibuildmp`, it is `natmod/Makefile`'s
own business (**D2**). What is not covered: a facade or any other file
meant to install identically regardless of target arch. Per-identifier
packages resolve this for free: `[publish] extra-files` gets copied into
*every* identifier's directory and listed in that identifier's own
`package.json` — no separate "untagged entry" case to design, since every
entry in the (untagged) per-identifier schema already installs
unconditionally. Confirmed as a real need, not hypothetical (bclibc's own
`ffimod/` wants exactly this), but bclibc does not publish `ffimod`'s
output today, so there is no existing package.json to match against — the
shape is designed and tested against `examples/template`, not yet
verified against a real consumer's actual release.

`version` (top-level config key / `CIBMP_VERSION`) gates the whole
packaging step: empty (the default) means an identifier's directory holds
only its `.mpy` — still useful on its own (a Makefile-driven consumer
downstream just wants the file), just not mip-installable yet. Set it
(`CIBMP_VERSION: ${{ github.ref_name }}` in CI) and `extra-files` +
`package.json` are written too. No CLI flag: `--version` was already
taken (prints `cibuildmp`'s own version).

Still open: how the local `output-dir/<identifier>/` tree gets deployed.
Each `.mpy` is already named `<module>-<identifier>.mpy` (**M3**, kept
even though the directory alone would disambiguate it locally) so it
never collides even if a caller later flattens several identifiers into
one namespace — a GitHub Release's own asset list is necessarily flat
(no real subdirectories) — but `package.json` itself is not yet
identifier-qualified and would still need renaming to
`<identifier>_package.json` (or similar) on that specific upload path. A
host that preserves real paths (GitHub Pages, S3, a raw git tree) can
take the tree as-is. Not decided which target `cibuildmp` should make
easiest first — bclibc's own `release.yml` today only does GitHub
Releases.

**D15 — `rv32imc`'s `ARCH_FLAGS=` is part of the identifier, not an
invisible extra-make-args string.**
Found reading [micropython#19479](https://github.com/micropython/micropython/issues/19479)
carefully, as flagged directly: `py/dynruntime.mk` (line 197-198) turns a
consuming Makefile's `ARCH_FLAGS=` into `mpy_ld.py --arch-flags`, which
packs a variable-length uint into the `.mpy` header (feature-byte bit 6
set, the value follows as a big-endian 7-bit-group varint). Two rv32imc
builds that differ only in this value are **not** interchangeable —
`py/persistentcode.c`'s `mp_raw_code_load()` validates it as `required ⊆
available` against `asm_rv32_allowed_extensions()` (confirmed in the
issue thread: an exact-int match, the obvious first idea, does not work
for this reason) — but before this decision `Target.identifier` had no
way to say two such builds were different at all.

`arch-flags` (top-level config key, `[natmod]`-nested also accepted,
matching how `archs` itself is read) accepts a string *or a list*, the
same "accept a list, or a shell-ish string" idiom `archs`/`micropython`/
`extra-make-args` already use — because "build every arch-flags variant"
turned out to be a real, distinct request from "build every arch" (a
consuming project wanting both a baseline `rv32imc` and a
`Zba`/`Zcmp`-optimised one, say), not something a single value could ever
express. Each entry is parsed the way `mpy_ld.py`'s own
`validate_arch_flags()` does — a numeric string (`0b`/`0x`/decimal) or a
comma-separated list of named extensions (`RV32_ARCH_FLAGS` in
`resources/natmod.toml`, transcribed from `mpy_ld.py`'s
`RV32_EXTENSIONS`) — and `natmod_targets()` emits one `rv32imc` `Target`
*per entry*, side by side with every other selected arch's single Target.
Resolved before `build`/`skip`/`[[overrides]]` selection either way, since
it changes the identifier those glob against: `mpy6.3-natmod-rv32imc+0x3`,
the `+0x..` suffix present only when nonzero. Opaque hex, not named flags
reconstructed from the int: a named encoding would have to stay in
lockstep with `RV32_ARCH_FLAGS` to remain accurate, and the identifier
must still mean the same thing if that table gains a flag a given build
predates. `arch-flags` can only be set at this one place (like `archs`,
not per-`[[overrides]]`) for exactly that reason — an override selects by
identifier, and the identifier cannot depend on which override already
matched it.

`mpy_ld.py` itself restricts `--arch-flags` to `rv32imc` only (raises for
every other arch), and `persistentcode.c` only ever validates arch_flags
for `MP_NATIVE_ARCH_RV32IMC` (any other arch with the header bit set is
an unconditional `"incompatible .mpy file"` on load) — not `rv64imc`
despite the name similarity. `cibuildmp` mirrors that restriction
exactly: `natmod_targets()` only ever puts a nonzero `arch_flags` on the
`rv32imc` `Target`, zero on every other arch regardless of config.

`verify_output()` (**M3**'s `auditwheel` equivalent) now checks
arch_flags too, exact match — that is a different question from mip's
own subset check above: this asks whether the *linker* encoded what the
config asked for, not whether a *device* can run the result.

Caught while implementing this: `build.py`'s existing arch-decoding was
`header[2] >> 2`, no mask. `py/persistentcode.h`'s own
`MPY_FEATURE_DECODE_ARCH` is `((feat) >> 2) & 0x2F` — bit 6 (the
arch-flags marker) becomes bit 4 after the shift, and `0x2F` is the mask
that excludes it. Without it, `rv32imc` (native-code 11) with the
arch-flags bit set decoded as 27. Latent until now — no arch besides
`rv32imc` sets the marker bit, and nothing set it for `rv32imc` either
until this decision — but a real bug in already-shipped M3 code,
findable only by reading the upstream macro precisely rather than
inferring the shift from bclibc's own script, which carries the same
mask but not a citation of where `0x2F` comes from.

Also caught, running the list variant for real rather than trusting the
single-value case already worked: the `BUILD=` scoping fix from M3's own
"two bugs" note (`BUILD = .obj/$(ARCH)`) only accounts for `$(ARCH)`, not
`$(ARCH_FLAGS)`. `rv32imc`'s own object file does not depend on
`ARCH_FLAGS` at all, so building `arch-flags = ["", "zba", "zba,zcmp"]`
back to back in one invocation reused the *first* variant's cached
`.o`/`.mpy` for the second and third just as silently as the original
`$(ARCH)` bug did — `$(ARCH)` never changes across these three targets, so
the earlier fix alone does nothing here. `examples/template/natmod/Makefile`
now scopes `BUILD` by both:
`BUILD = .obj/$(ARCH)$(if $(ARCH_FLAGS),+$(ARCH_FLAGS))`, and README.md's
"Conventions this repo assumes" says so for every arch-flags-using natmod
Makefile too. Same class of bug, same fix shape, second axis — worth
noting as a pattern: *any* build-relevant variable dynruntime.mk does not
already fold into `BUILD` on its own needs to be added by the consuming
Makefile, or D9's one-sequential-invocation model silently serves stale
output for it.

## Identifier scheme

Shaped after `cp311-manylinux_x86_64` = *{ABI}-{platform}\_{arch}*:

```
mpy6.3-natmod-armv7emsp
mpy6.3-natmod-x64
```

- **`mpy6.3`** — the `.mpy` ABI: `MPY_VERSION`.`MPY_SUB_VERSION` from
  `py/persistentcode.h`. This is the correct compatibility axis, not the
  MicroPython release tag: a native `.mpy` loads into any runtime with a
  matching `MPY_VERSION`/`MPY_SUB_VERSION` pair, which spans several
  releases. The release tag is *what you build against* and stays a config
  key; the ABI is *where the result runs* and is derived from the checked-out
  source (and cross-checked against the built file's own header).
- **`natmod`** — the build mode, i.e. the "platform" slot.
- **arch** — one of `dynruntime.mk`'s ten `ARCH` values.
- **`+0x..`** (optional, `rv32imc` only) — `arch_flags`, present only when
  `arch-flags` is set (**D15**): `mpy6.3-natmod-rv32imc+0x3`. Absent for
  every other arch and for `rv32imc` with no `arch-flags` configured, so
  every identifier in this file predating D15 is still exactly what it
  was.

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

Usermod identifiers, when that phase lands, take the same shape with the
MicroPython release tag in the first slot, since a firmware image's identity
*is* its MicroPython version: `v1.28.0-usermod-esp32_ESP32_GENERIC` for a
board-based port. `unix`/`windows`/`webassembly` have no board, only a
`VARIANT=` (see "Later — usermod" below), so theirs is
`v1.28.0-usermod-unix_standard` — same shape, the last slot names whichever
axis that port actually selects on.

## Config schema (phase 1)

```toml
# cibuildmp.toml — repo root

micropython = "v1.28.0"       # release tag(s) to build against -- also
                              # accepts a list (D13): ["v1.22.0", "v1.28.0"]
output-dir = "mpyhouse"       # output-dir/<identifier>/ per target (D14)
build = "*"                   # glob(s) over identifiers, space-separated
skip = ""
version = ""                 # set (CIBMP_VERSION in CI) to also write each
                              # identifier's package.json (D14); empty means
                              # just the .mpy, not mip-installable yet

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
                              # set per-[[overrides]], only here

[publish]
extra-files = []              # copied into every identifier's own directory,
                              # untagged in package.json (D14) -- a facade
                              # or anything else install-everywhere (ffimod)

[[overrides]]
select = "*-armv7emsp"
extra-make-args = ["MP_BCLIBC_PRECISION=single"]
```

Every option is overridable by environment variable, `CIBMP_`-prefixed and
screaming-snake-cased: `CIBMP_BUILD`, `CIBMP_SKIP`, `CIBMP_MICROPYTHON`,
`CIBMP_OUTPUT_DIR`, `CIBMP_EXTRA_MAKE_ARGS`, `CIBMP_VERSION`,
`CIBMP_ARCH_FLAGS`, … Precedence, lowest to highest: defaults → config
file → `[[overrides]]` matching the identifier → environment → CLI flags.

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
an open question below.

Nothing about this is CI-specific: the cache directory, the toolchain
resolver and the build loop are the same code path in both places. The only
thing a runner adds is that its cache starts empty.

## Phases

### M0 — skeleton — **done**

- [x] Real CLI in `src/cibuildmp/cli.py`: `cibuildmp [package_dir]
      [--config-file] [--output-dir] [--only ID] [--print-build-identifiers]
      [--json] [--platform]`.
- [x] Config loader in `src/cibuildmp/options.py`: `cibuildmp.toml` →
      `pyproject.toml [tool.cibuildmp]` fallback; `CIBMP_*` env layer;
      `[[overrides]]` resolution. Full precedence chain implemented and
      covered by tests.
- [x] Identifier generation + `build`/`skip` glob filtering in
      `src/cibuildmp/targets.py`, including the arch→`CROSS` table and the
      release-tag→ABI table (both transcribed from MicroPython source, see
      the toolchain map above).
- [x] `--print-build-identifiers`, with `--json` for `fromJSON`.
- [x] `action.yml` installs from `${{ github.action_path }}` per **D8**, so
      the running version is exactly the ref the caller pinned.
- [x] `--dry-run`, printing the resolved plan and exiting 0 — the M0
      success path, since building itself is not implemented.
- [x] `--print-build-matrix`, emitting `{only, os}` objects, and a
      `runs-on` option resolved through the same override chain as
      everything else (`Target.default_runner` supplies the default).
- [x] `.github/actions/cibuildmp-matrix` composite action, emitting those
      objects as an `include` output. **Optional by D9**, not the default
      path: it exists for per-target failure isolation now, and for usermod's
      genuinely different runners later. Carrying the runner in the matrix
      entry is also the answer to the "a composite action cannot pick its own
      `runs-on`" limitation `README.md` documents for `build-usermod-unix`.

`--print-build-identifiers` alone removes the duplicated matrix from all
three repos, which is why M0 shipped before any build logic exists. Running
`cibuildmp` without `--dry-run` currently prints the resolved build plan and
exits 1 — deliberately, so the action fails loudly rather than appearing to
succeed while building nothing.

### M1 — MicroPython + mpy-cross provisioning — **done**

All in `src/cibuildmp/sources.py`, standard library only.

- [x] Fetch MicroPython at the configured tag, from the release **asset**
      tarball (`.../releases/download/<tag>/micropython-<ver>.tar.xz`) — the
      same URL `fetch-micropython` uses, and not GitHub's auto-generated
      archive, because only the release asset vendors the `lib/` submodules.
- [x] Shallow-clone fallback for refs that publish no asset. Verified rather
      than assumed: `v1.28.0`, `v1.25.0` and `v1.22.0` all return 200,
      `v1.29.0-preview` returns 404.
- [x] `micropython-submodules` config option, applying on the clone path
      only. **A natmod can need a submodule** — upstream's own
      `examples/natmod/btree/Makefile` builds against
      `$(MPY_DIR)/lib/berkeley-db-1.xx`, which is one. The tarball path
      needs nothing here; a `--depth 1` clone vendors none.
- [x] `urllib`, no `wget`. `README.md` records `fetch-micropython` being
      unusable on a Windows runner outside MSYS2 for exactly that reason, so
      this removes a real portability limit rather than a hypothetical one.
- [x] Cache under `~/.cache/cibuildmp/micropython/<tag>/`, honouring
      `CIBMP_CACHE` and `XDG_CACHE_HOME`. Extraction is staged in a temp
      directory and moved into place with `os.replace`, and a completion
      stamp file gates reuse, so an interrupted run cannot leave a partial
      tree that the next one trusts.
- [x] `mpy-cross` built once per checkout, cached alongside it.
- [x] `read_mpy_abi()` reads `MPY_VERSION`/`MPY_SUB_VERSION` from
      `py/persistentcode.h` and is checked against the identifier's ABI
      before any target is built. The checkout is authoritative; the
      `MPY_ABI` table exists only to answer the question with no checkout.
      A disagreement aborts rather than mislabelling output.

Measured on this machine, `CIBMP_BUILD="*-x64" cibuildmp`: **37 s cold**
(104 MiB download + extract + `mpy-cross`), **0.08 s warm**. That gap is the
whole argument for D9 — under a ten-leg matrix the cold path is paid ten
times over.

### M2 — toolchain resolver — **done**

`src/cibuildmp/toolchains.py`, with every pin in
`src/cibuildmp/resources/natmod.toml`.

- [x] Resolver returning a `ResolvedToolchain` (strategy, prefix, `bin_dir`
      for `PATH`, and any `make` overrides) or a clear "not available here"
      error naming the apt package.
- [x] Strategies `host` → `download`, `--toolchain=auto|host|download`.
      `host` is tried first so a CI runner with the apt packages installed
      behaves exactly as `build-natmod` does today and downloads nothing.
- [x] Pins verified against the real releases, not assumed: arm-none-eabi
      15.2.1-1.1 and riscv-none-elf 15.2.0-1 from xpack, xtensa-esp-elf
      16.1.0_20260609 from `espressif/crosstool-NG`, xtensa-lx106 from
      micropython.org (the tarball `ci_esp8266_setup` uses).
- [x] sha256 for every download — xpack's own `<asset>.sha` sidecar where it
      exists, a literal pin (computed locally) for Espressif and
      micropython.org, which publish none.
- [x] **Confirmed: `xtensawin` does not need ESP-IDF.** `dynruntime.mk` asks
      only for `xtensa-esp32-elf-` on `PATH`, and the `build-natmod` action's
      own comment already says `install.sh` just downloads the toolchain from
      GitHub releases. Fetching that release directly replaces an
      `esp-idf` clone plus installer — the heaviest step in this repo's CI —
      with an 84 MiB tarball. Measured end to end: 21 s cold, including the
      download.
- [ ] `docker` strategy. Dropped from natmod scope, not forgotten: every
      natmod arch is a cross-compile running on the build host, so a
      container adds isolation but no capability. It belongs to usermod.

**Prefix reconciliation.** `dynruntime.mk` hardcodes `riscv64-unknown-elf-`
(Debian's naming) and `xtensa-esp32-elf-`, while the tarballs ship
`riscv-none-elf-` and a unified `xtensa-esp-elf-`. Rather than symlinking a
fake prefix into the cache, the resolver appends `CROSS=<actual>` to the
`make` command line: `dynruntime.mk` assigns `CROSS` with `=` inside its
per-ARCH `ifeq` chain and never marks it `override`, so a command-line
variable wins — including for the `$(shell $(CROSS)gcc …)` picolibc probe
evaluated while the makefile is parsed.

**picolibc.** Resolved, and it is not the risk it looked like.
`dynruntime.mk` probes `--print-file-name=picolibc.specs` and adds `-specs=`
only when the toolchain has it; the apt path installs
`picolibc-riscv64-unknown-elf` explicitly, and the xpack build falls back to
its own newlib. Worth keeping an eye on: the two paths therefore link
against different libcs, which is invisible until something misbehaves.

**`x86` is the one arch that cannot provision itself.** What it needs is the
host compiler's 32-bit runtime, which no cross-toolchain tarball supplies.
Finding `gcc` on `PATH` proves nothing there, so the resolver compiles
a real translation unit with `-m32` (a `probe-args` entry in the resource
file) and, on failure, errors naming `gcc-multilib` rather than letting the
build fail later with a confusing compiler diagnostic.

**Fixed after M3 caught it live:** the probe originally compiled an
*empty* translation unit (`-xc -c -` on empty stdin). `-m32` alone is
always a valid codegen flag, so that always succeeds even when the 32-bit
glibc headers/libs are entirely absent — the probe never actually touches
a header. `examples/template`'s CI hit exactly this on `ubuntu-latest`
(no 32-bit multilib by default): resolution reported `x86` fine, then the
real build failed deep inside `dynruntime.mk` with `bits/wordsize.h: No
such file or directory`. The probe now compiles *and links* `#include
<stdio.h>\nint main(void) { return 0; }`, which exercises the same header
chain and the 32-bit crt/libc a real natmod build needs.
`build-template.yml` also needed its own `apt-get install gcc-multilib`
step — `.github/actions/build-natmod` already apt-installs it for `ARCH=x86`
in its own "Install cross-compiler" step, but `build-template.yml` goes
through the CLI (`action.yml`) instead of that composite action, so it
does not inherit it.

**Why not just add a `docker` strategy for `x86` and be done with it?**
It would work — `x86` is in fact the *one* natmod arch where a container's
isolation is worth something, since it is not a cross-compile at all but
the host's own `gcc -m32`, which genuinely needs an isolated 32-bit
userland the way the other nine arches' downloaded toolchain tarballs
already carry their own target sysroot without one. Not done anyway: a
container engine dependency, image pulls, and losing "runs on a laptop
with no root and no mutation of the host" (**D3**) is a real cost to pay
for one arch out of ten, when the fix is the one-line `apt-get install
gcc-multilib` every real consumer's CI already runs today (and a laptop
user hits once, not per build). `docker` stays dropped from natmod scope
for the same reason recorded above and revisits only for usermod, where
port builds have real system dependencies a cross-toolchain tarball
cannot express at all — not just x86's narrower one.

### M3 — the build itself — **done**

`src/cibuildmp/build.py`. Checked against cibuildwheel's own
`platforms/linux.py` rather than assumed: it is fail-fast per identifier too
(a `subprocess.CalledProcessError` from one platform config aborts the whole
invocation, no per-target continue-and-report), and its
`BuildProducedNoWheelError`/`RepairStepProducedMultipleWheelsError` are the
shape `collect_output()`/`verify_output()` copy.

- [x] Run `pre-build-command` in `module-dir` (`shell=True`, matching what
      `build-natmod`'s own `pre_build_command` input already does).
- [x] Invoke `make -C <module-dir> ARCH=<arch> MPY_DIR=<…>
      PYTHON=<sys.executable> <extra-make-args> <make-target>` — `mpy_ld.py`
      resolves `pyelftools`/`ar` from `cibuildmp`'s own dependencies
      (**D12**), verified for real against a live `make dist` run, not just
      by inspection.
- [x] Collect the produced `.mpy` into `output-dir/<identifier>/`
      (**D14**), named unambiguously within it too —
      `<module-stem>-<identifier>.mpy`, found by globbing
      `<module-dir>/build/<arch>*/*.mpy` — the layout `build-natmod`'s own
      artifact-upload step already assumes. Zero or more-than-one match is a
      `BuildError` naming what was found, cibuildwheel's
      `BuildProducedNoWheelError`/`RepairStepProducedMultipleWheelsError`
      shape. Cross-target collisions are structural, not a runtime check:
      distinct `Target`s (keyed on abi/mode/arch/tag/arch_flags) always
      produce distinct identifiers and therefore distinct directories, so
      there is no `AlreadyBuiltWheelError`-equivalent to run.
- [x] Verify each output's header arch against the requested identifier and
      fail loudly on mismatch — `cibuildmp`'s equivalent of `auditwheel`.
      `native-code` was added to `resources/natmod.toml`'s `[arch]` table
      (the `MP_NATIVE_ARCH_*` values `tools/mpy_ld.py` bakes into byte 2 of
      every native `.mpy`'s header, bits 2-5) so this reads the same pinned
      table the CROSS/toolchain resolution already does.
- [x] Readable per-target logging and a summary table, in `cli.build()`:
      each target prints its plan line and a `done in Ns` line as it
      finishes; a full run ends with a total duration and one line per
      built `.mpy` (identifier, filename, size) — cibuildwheel's
      `BuildInfo`/`print_summary` shape, minus the `humanize`/SHA256 parts
      that would cost a dependency for no real natmod need.

**Two bugs only a real end-to-end run against `examples/template` caught**
(both unit-tested in isolation, neither exercised the real failure mode):

- `run_make()` passed `-C <module-dir>` in the command *and*
  `cwd=<module-dir>` to `subprocess.run` — harmless when `module-dir` is
  absolute, broken when relative (the common case: `package_dir` defaults
  to `.`), since the process chdirs there and `-C` then looks for
  `<module-dir>` nested inside itself. Fixed by dropping `cwd=`; `-C`
  alone is sufficient and was already the right layer for it.
- `dynruntime.mk` defaults `BUILD ?= build`, not scoped by `$(ARCH)`. That
  is invisible to `build-natmod` (one job, one checkout, one arch each),
  but `cibuildmp` with no `--only` runs every target sequentially in the
  same `natmod/` tree (**D9**) — a second `ARCH=` finds the first arch's
  own object files "up to date" and skips rebuilding, so the merged
  `.mpy` silently stays the first arch's binary. Not a `cibuildmp` bug to
  fix in code (it is the consuming project's Makefile that owns this),
  but real enough that it needed becoming a documented requirement:
  `examples/template/natmod/Makefile` sets `BUILD = .obj/$(ARCH)` (kept
  outside `build/` so it cannot collide with the `dist` output
  `collect_output()` globs for), and README.md's "Conventions this repo
  assumes" now says so. `cibuildmp` still fails loudly instead of
  shipping the wrong arch either way — that is what the header
  verification above is for — this just avoids paying for the failed
  build at all.

**Publish, folded in (D14, D15) — this used to be a separate "M4":**

- [x] `package_target()` writes each identifier's own `package.json`
      (today's plain two-element `urls` schema, not the deferred
      compat-tag one) and copies `[publish] extra-files` into that same
      directory, gated on `version` being set — empty (the default)
      means an identifier's directory holds only its `.mpy`.
- [x] `arch-flags` (`rv32imc` only) resolved before target selection,
      folded into that arch's identifier as `+0x..`, and passed through to
      `make` as `ARCH_FLAGS=` — **D15**.
- [x] `verify_output()` also checks arch_flags, exact match. Fixed a
      latent header-decoding bug in the process: arch-code extraction was
      an unmasked `header[2] >> 2`; `py/persistentcode.h`'s own
      `MPY_FEATURE_DECODE_ARCH` masks with `0x2F` after the shift to
      exclude the arch-flags marker bit. Never triggered before D15 (no
      arch used the marker bit until now).
- [ ] Still open (**D14**): how the `output-dir/<identifier>/` tree gets
      deployed — flattening `package.json`'s own filename for a GitHub
      Release's flat asset list, vs. hosts that preserve real paths.
      Not blocking; the `.mpy` itself is already collision-safe either
      way.

### M5 — adopt in the three repos

- [x] The same three repos: replace the natmod matrix with `cibuildmp`.
      a7p was the interesting one, exactly as anticipated — non-default
      `module-dir` (`micropython/natmod`) and a `pre-build-command`
      (`test -f nanopb/pb.h || make fetch-nanopb`, guarding against a
      re-fetch on every arch since `cibuildmp`'s own D9 runs one job
      sequentially through all of them). All three (`micropython-bclibc`,
      `a7p`, `micropython-wasm3`) verified green on real CI, arch by arch —
      not `--dry-run`. Surfaced two real, previously-unknown bugs along the
      way, one per repo: a stale-facade-collision in `a7p`'s and
      `micropython-wasm3`'s own `dist:` targets (same shape as the one
      already fixed in `micropython-bclibc`'s own Makefile under M3), and
      `micropython-wasm3`'s `dist:` never cleaning up
      `$(BUILD)/$(MOD).native.mpy`, which made `cibuildmp`'s own
      `collect_output()` correctly refuse an ambiguous two-`.mpy` result
      instead of silently picking one. Neither is a `cibuildmp` bug; both
      are now fixed in their own repos' Makefiles.
- [x] `micropython-bclibc`, `a7p`, `micropython-wasm3`: repinned every
      `uses:` path from the interim `cibuildmp@<commit-sha>` pin (used
      while no tag existed past `v0.3.0a1`) to `cibuildmp@v0.3.0`
      (**D11**), now that it's cut — mechanical, no behaviour change.
      Not yet pushed/re-verified against the tag at the time of this
      note; the SHA it points to is the same commit already confirmed
      green in all three repos' CI.
- [ ] Archive `ballistics-lab/micropython-native-ci` once all three have
      repinned.
- [ ] Reduce `build-natmod` to a wrapper over `cibuildmp --only <id>` so
      there is one implementation of the toolchain logic, not two. Do not let
      the two coexist for long.

### Later — usermod

Not scheduled as tool work, but the prerequisite layer is **done and
proven**, which changes what "not scheduled" means here. `.github/actions/
build-usermod-{unix,windows,webassembly,armv7m,esp32,rp2040}` all exist in
this repo, and `o-murphy/a7p`'s own `.github/workflows/mp-usermod.yml` now
drives all six directly, across twelve identifiers (`unix` × x64/x86/
aarch64, `windows` × x86/x64/arm64, `webassembly`, `unix-cross` × armhf/
mipsel, `qemu`/armv7m, `esp32`, `rp2040`) — every job green. That is
exactly the position natmod was in before M0: a working low-level layer,
hand-driven per consumer, nothing yet absorbing the parts that are
identical across all of them. The difference is usermod now has a real
reference implementation to design the identifier/config scheme against,
instead of reasoning from the cibuildwheel analogy alone the way natmod's
M0 had to.

`cibuildmp` drives every usermod port itself, not just the ones `mpbuild`
has a board database for — correcting an earlier version of this section,
which wrongly had `unix`/`windows`/`webassembly` staying on the composite
actions permanently. That contradicts Positioning, above: every composite
action here is the low-level layer until `cibuildmp` covers its ground,
then becomes a thin wrapper over it (**M5**'s own open item for
`build-natmod`) — no port gets carved out as a permanent exception.

Two different selector axes, not the same thing under two names:

- **Board-based ports** (`qemu`/`esp32`/`rp2040`, and `stm32`/etc. when
  added) select a `board:` (`MPS2_AN385`, `ESP32_GENERIC`, `RPI_PICO`, …)
  and resolve it to a toolchain via the data vendored from `mpbuild`
  (**D7**) — confirmed as a real, present-tense input on all three
  existing board-based actions, each with its own default.
- **`unix`/`windows`/`webassembly` have no board concept at all** — they
  select a `variant:` instead: `ports/unix/variants/` (`standard` default;
  `build-usermod-unix`'s own `variant` input), `ports/webassembly`'s
  `standard`/`pyscript` (`build-usermod-webassembly`'s `variant` input,
  `pyscript` default since `standard`'s `-s ASYNCIFY` is broken on modern
  emsdk, tracked upstream at micropython/micropython#19380).
  `build-usermod-windows` carries a `variant` input too, but every real
  caller leaves it empty and it is omitted from the command line entirely
  — `ports/windows` has no `variants/<name>/` split in any consumer today,
  just one `variants/manifest.py`; the input exists for a future fork that
  adds one, not a fourth real value alongside `standard`/`pyscript`.
  `mpbuild`'s board database was never going to cover these regardless of
  the dependency-vs-vendor question **D7** is actually about — a variant
  isn't a board missing from the list, it's a different axis entirely.
- **`zephyr` fits neither axis above** — no `board.json`, no `variant:`,
  and no `mpbuild` coverage at all. See **D22**.

`cibuildmp` drives `unix`/`windows`/`webassembly`'s own port Makefile
directly, the same delegate-the-compile shape **D2** already uses for
natmod, with `variant` as their own config axis parallel to `boards` for
the board-based ports. Either way `cibuildmp` resolves the port → build
command itself and treats firmware as a verification output rather than a
published artifact by default.

Six more findings, real rather than anticipated, surfaced by the actions
themselves and by a7p's workflow actually driving them — worth locking now
even though M6+ isn't scheduled, so the eventual tool absorbs what's
already known instead of re-deriving it:

**D16 — `USER_C_MODULES` is a directory on Make-driven ports, a single
`.cmake` file on CMake-driven ones — same variable name, two incompatible
shapes.** `unix`/`windows`/`webassembly`/`qemu` glob a directory (`make`'s
own `USER_C_MODULES` convention, `py/py.mk`); `esp32`/`rp2040` are
CMake-driven ports and take one `.cmake` entry point to `include()` —
stated directly in `build-usermod-rp2040`'s own input doc ("unlike
build-usermod-unix/build-usermod-webassembly's own user_c_modules, this
one is a *file*... CMake's USER_C_MODULES takes a single .cmake entry
point to include, not a directory to glob") and mirrored in
`build-usermod-esp32`'s. A consumer therefore needs *two* files for one
module tree (`usermod/` for the directory form, `usermod/micropython.cmake`
for the CMake form) — a7p's own tree carries both. `cibuildmp` should
resolve this itself once it already knows which port it's driving (the
same D7 board-database lookup that already knows Make vs. CMake per port),
not leave a consumer to notice the split by reading a composite action's
own doc comment the way today's three consumers had to.

**D17 — combining `FROZEN_MANIFEST` with the port's own default manifest
is real, per-port, and explicitly *not* solved by the action layer.**
`build-usermod-webassembly`'s own header says so outright: "Combining
FROZEN_MANIFEST with the port's own default... is deliberately left to
the caller, not done here... Every consuming repo now writes its own
combined manifest first and passes that as frozen_manifest instead." In
`mp-usermod.yml` this is a hand-written `cat > manifest.py <<EOF` +
`include()` pair, duplicated three times for the differently-shaped ports
(`variants/<x>/manifest.py` for unix/webassembly, `boards/manifest.py` for
esp32/rp2040, nothing at all for qemu — `ports/qemu` ships no default
manifest, so combining is skipped there) and a fourth time for Windows
with its own escaping story (below). This is exactly the class of
hand-copied-and-drifting logic Positioning says `cibuildmp` exists to
absorb. Fix: extend the **D7** vendored board/variant database to also
record each port's default manifest path per board/variant
(`$(PORT_DIR)/variants/pyscript/manifest.py`, `$(PORT_DIR)/boards/
manifest.py`, or none), and have `cibuildmp` generate the combined
manifest itself from that plus the consumer's own module manifest — a
consumer supplies only the fragment that freezes their module, same shape
`natmod`'s `pre-build-command` already lets a consumer opt into
project-specific setup without owning the whole recipe.

**D18 — Windows provisioning is a fourth story, not a variant of
`download`/`docker`/`host` (**D3**).** `build-usermod-windows` cannot set
up its own MSYS2 environment: its own contract says plainly that a
composite action's `shell: bash` steps "run under plain Git Bash on a
Windows runner, not inside the MSYS2 environment, so this action cannot
set up either one for itself" — `msys2/setup-msys2` has to run as the
caller's own step first, and every path fed into the action has to be a
`$(pwd)`-relative MSYS2 path, never `$GITHUB_WORKSPACE`/`$RUNNER_TEMP`
verbatim (both are native `D:\a\...` paths; MSYS2 bash's own unquoted
backslash-escaping silently mangles them — a real failure hit and fixed in
`mp-usermod.yml`, see its own "Write combined FROZEN_MANIFEST (windows)"
step comment). `cibuildmp`'s toolchain resolver (**M2**) has no MSYS2
awareness at all today; this is real orchestration work, not config, since
it spans installing an environment *and* how every subsequent path is
formed.

**D19 — ESP-IDF provisioning is the heaviest, least locally-reproducible
step of any target here, and has no caching.** `build-usermod-esp32`'s own
header calls this out directly: "No caching yet... Left as a known
follow-up, not forgotten." A `--recursive` clone of `esp-idf` plus
`install.sh <chip>` per run is a materially stronger Docker-strategy case
than natmod's `x86` ever was (**M2**'s own "why not docker" note is
specific to x86's narrow `gcc-multilib` gap and says usermod is where that
tradeoff flips) — Espressif ships its own `espressif/idf` Docker images
built for exactly this. Revisit **D3**'s `docker` strategy here first, not
as a general-purpose escape hatch. mpbuild's own fallback tag
(`espressif/idf:v5.4.2`, **D7**) and its lockfile/CI-workflow version-probe
are a concrete starting pin, not a new lookup to invent.

**D20 (revisits D9) — usermod runner selection is structural, confirmed
live, not a hypothetical "different targets need different runners."**
`mp-usermod.yml`'s matrix already needs four distinct `runs_on:` values
(`ubuntu-latest`, `ubuntu-24.04-arm` ×2 rows, `windows-latest` ×2,
`windows-11-arm`), and unlike natmod's ten-cross-compiles-on-one-host,
several of these are load-bearing rather than a preference: aarch64 and
armhf both need to *execute* what they build (a native run, not qemu), so
the wrong runner doesn't just cost time, it silently stops proving
anything. `Target.default_runner` and `--print-build-matrix` (**M0**)
already exist for exactly this; usermod is the build mode where per-target
fan-out should probably be the default rather than **D9**'s opt-in, not
because sharing the fetch-MicroPython/mpy-cross cost stops mattering, but
because the runner constraint dominates it the way it does for
cibuildwheel's own OS axis.

**D21 — execution, not just linking, is central to usermod's value, and
is already real infrastructure — this does not fit under D6's blanket
"no test runners" deferral without saying so explicitly.** Every port in
`mp-usermod.yml` except `esp32` (build-only by design — there is no esp32
emulator to hand a firmware image to, stated directly in that job's own
header) already runs something after building: Node for `webassembly`,
the built interpreter directly for `unix`/`windows`, and two bespoke
Python harnesses (`micropython/ci/run_qemu.py`,
`micropython/ci/run_rp2040py.py`) for the bare-metal/emulated targets —
both of which shadow `open()` to inline the test fixture, since neither
target has a writable filesystem to copy one onto (`ports/qemu` links
`-nostdlib` with no VFS at all; the rp2040py path pushes a script over the
raw REPL instead of a real file). A natmod really is closer to a wheel — a
binary artifact whose job ends at "loads and the symbols resolve." A
usermod *is* the runtime; "compiles" proves much less about it than
"boots and imports" does, and the qemu/rp2040 jobs exist specifically
because a usermod that links cleanly but fails to boot is a real, observed
failure class, not a hypothetical one. This does not overturn **D6** for
natmod. It does mean usermod's own eventual phase should decide this
question on purpose rather than inherit D6's answer by default.

**D22 — `zephyr` is a third selector axis, not a board-based port that
just needs its boards added, and has no reference implementation to
design against.** Checked directly against upstream
(`ports/zephyr/boards/`), not assumed: there is no `board.json` anywhere
in it — board selection is `<board>.conf` (a Kconfig fragment) plus an
optional `<board>.overlay` (devicetree), a flat per-board-name file pair
that is MicroPython's own zephyr-specific convention, unrelated to the
`board.json` shape **D7**'s vendored `board_database.py` scans for. The
"two selector axes" split above (board.json vs. `variant:`) does not have
a third slot for this — enumerating zephyr's boards means globbing
`boards/*.conf` directly, not extending the vendored scanner, since there
is nothing in that shape for the scanner to find.

`mpbuild` itself has no opinion here either: checked its `BUILD_CONTAINERS`
dict directly (the same one **D7**'s own addendum above transcribes for
`stm32`/`rp2`/`esp32`/…) — fifteen port keys, no `zephyr` among them. So
unlike the six ports **D16–D21** rest on (all live, all proven in
`a7p`'s `mp-usermod.yml`), zephyr has neither an existing composite
action nor a working consumer workflow to design the identifier/config
scheme against — the exact position natmod's own M0 was in before it had
`cibuildwheel` to reason from by analogy, except here there is no
analogous tool at all to lean on, mpbuild included.

Build tooling is a fourth story on top of **D3**'s `host`/`download`/
`docker`, not a variant of the three already known: `west` (Zephyr's own
meta-tool) driving CMake, which in turn expects a full Zephyr SDK /
module workspace on the machine — heavier than **D19**'s ESP-IDF case,
which at least resolves to one `--recursive` clone plus one installer
script; `west`'s own workspace model pulls in Zephyr's own multi-repo
manifest. `boards/manifest.py` does exist (confirms **D17**'s
default-manifest-per-port pattern generalizes here too), but whether
`CMakeLists.txt` accepts a `USER_C_MODULES`-style entry point the way
esp32/rp2040 do (**D16**) is unverified — not read yet, and should not be
assumed either way before it is.

Not scheduled, and deliberately left out of the **M6–M12** outline below
rather than folded into `boards.py`'s (D7) or the build driver's (M8)
work: doing either now would repeat the mistake D16–D21 just corrected
in this section, reasoning about a fourth axis as if it were already
understood before any of it has been read from `west`/CMake directly.
Revisit once a real consumer wants a zephyr usermod build, the same way
the six existing ports got their own findings from `a7p` actually driving
them rather than from reading upstream cold.

**Rough phase outline, unscheduled.** Not detailed the way M0–M5 are —
none of this is implemented yet, and giving it that treatment now would
repeat the exact mistake D16–D21 above just corrected in this section
(reasoning presented as verified fact before any code exists). Names and
one line each, so M6 doesn't start from a blank page; each gets its own
citations and "verified live" notes once it's actually underway:

- **M6** — extend the **D7** vendored board/variant database with each
  port's default-manifest path and its Make-vs-CMake `USER_C_MODULES`
  shape (**D16**).
- **M7** — combined-`FROZEN_MANIFEST` generation + `USER_C_MODULES`
  resolution off that database (**D17**).
- **M8** — the build driver itself, for the ports that need no exotic
  provisioning first (`unix`, `windows` once MSYS2 is handled, `webassembly`,
  `qemu`/armv7m) — the natmod `build.py` shape, pointed at the composite
  actions' own recipes.
- **M9** — toolchain provisioning: MSYS2 orchestration (**D18**), ESP-IDF
  fetch + caching, `docker` strategy revisit for it (**D19**).
- **M10** — runner/matrix integration, fan-out-by-default for usermod
  identifiers (**D20**).
- **M11** — execution axis: qemu-system, rp2040py, node, native — four of
  seven already proven working, just not owned by `cibuildmp` yet
  (**D21**).
- **M12** — adopt in the three consuming repos, mirroring **M5**.

### Later — tests

Not scheduled (**D6**). When it lands, the design is an explicit runner axis:
`native`, `qemu-user`, `qemu-system`, `node`, `rp2040py`, `mpremote`, `none`.
`mpremote` — tests on real hardware attached to a self-hosted runner — is the
one with no cibuildwheel analogue and the most value for embedded.

Four of these seven (`native`, `qemu-system`, `node`, `rp2040py`) are no
longer hypothetical: `mp-usermod.yml` already runs all four today, hand-driven
per job (**D21**). That doesn't move this out of "not scheduled" on its own —
D6 still holds for natmod, where a build-only artifact is the actual
deliverable — but it does mean usermod's own runner-axis design, when it
happens, has four of seven cases to transcribe from a working reference
rather than design from scratch.

## Open questions

- **MSYS2 and ESP-IDF orchestration for usermod (D18, D19).** Neither fits
  the existing `host`/`download`/`docker` toolchain-strategy shape as-is —
  MSYS2 is an environment a caller sets up around the job, not a toolchain
  `cibuildmp` fetches into a cache directory, and ESP-IDF's own install is
  heavy enough that it may need its own strategy rather than reusing
  `download` unmodified. Not designed yet; flagged so M6+ doesn't rediscover
  the gap from scratch.
- **Windows/macOS hosts.** The download strategy makes a macOS host plausible
  for the arm/riscv/xtensa arches; `x86`'s multilib and the whole
  `docker` strategy are Linux-only. Decide whether phase 1 claims anything
  beyond Linux, or explicitly does not.
- **Old tags vs. a modern host `gcc`.** Found while verifying **D13** live:
  `v1.21.0` fails to build `mpy-cross` under a recent `gcc`
  (`-Werror=unterminated-string-initialization` on upstream's own
  `py/emitinlinethumb.c`/`emitinlinextensa.c`). `mpy-cross` is a host
  build, so this is not a cross-toolchain problem the resolver can route
  around. Unclear yet how far back tags stay buildable, or whether that
  is worth a documented "known good" floor, a suggested
  `CFLAGS=-Wno-error` escape hatch, or just something a user hits and
  works around per-project.
- **Toolchain pinning vs. reproducibility.** Pinned tarball versions make
  builds reproducible but drift from what a contributor has on `PATH`. The
  `host` strategy running first means a laptop and CI can silently use
  different compilers — acceptable, but the summary output must always say
  which toolchain was actually used.

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

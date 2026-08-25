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
      `CIBMP_CACHE_PATH` and `XDG_CACHE_HOME`. Extraction is staged in a temp
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
has a board database for. Every composite action here is the low-level
layer until `cibuildmp` covers its ground, then becomes a thin wrapper
over it (**M5**'s own open item for `build-natmod`) — no port gets
carved out as a permanent exception.

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

Corrected after reading `py/usermod.cmake` directly rather than trusting
`build-usermod-rp2040`'s own doc comment: the "a file, not a directory to
glob" framing above is the action author's own convention, not what CMake
actually enforces. `USER_C_MODULES` on the CMake side is a *list* of
paths, and `usermod.cmake`'s own loop accepts a directory too — it just
appends `/micropython.cmake` to it (`if (IS_DIRECTORY ...)`) rather than
globbing every subdirectory the way `py/py.mk`'s `$(wildcard
$(USER_C_MODULES)/*/micropython.mk)` does on the make side. So the real
difference is not file-vs-directory, it's *how many modules one entry can
resolve to*: one `make`-side directory can hold several modules side by
side (one per subdirectory with its own `micropython.mk`), one `cmake`-side
entry always resolves to exactly one `micropython.cmake`, whether given as
a direct path or as a directory. Verified against a real `v1.28.0`
checkout, not transcribed from a doc comment: `unix`/`webassembly`/
`windows`/`qemu` all `include $(TOP)/py/py.mk`; `esp32`/`rp2040` both
forward `-DUSER_C_MODULES=` from their own `Makefile` into `cmake`, which
then includes the single, shared `py/usermod.cmake` — not a per-port CMake
file each writes its own copy of. `build-system` per port is now pinned
data (**D10**'s own pattern) in `resources/usermod.toml`, read through
`usermod/portinfo.py`, scoped to the same six ports **D16–D21** already
has a reference for.

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
absorb. Fix: record each port's default manifest path, and have
`cibuildmp` generate the combined manifest itself from that plus the
consumer's own module manifest — a consumer supplies only the fragment
that freezes their module, same shape `natmod`'s `pre-build-command`
already lets a consumer opt into project-specific setup without owning
the whole recipe.

Corrected twice now, which is itself the finding worth recording: reading
paths directly off a `v1.28.0` checkout is not the same as reading how a
real consumer resolves them. The first pass concluded "one shared
`manifest.py` per port, not per-board or per-variant" — true of the
*files on disk* (`ports/unix/variants/manifest.py` exists as one file),
false of what actually gets *built*: `unix`'s `Makefile` sets a
port-level default (`FROZEN_MANIFEST ?= variants/manifest.py`), but
`variants/standard/mpconfigvariant.mk` overrides that default to
`variants/standard/manifest.py` for exactly the variant `a7p`'s own
`mp-usermod.yml` builds (`webassembly`'s `pyscript` variant the same way;
`unix`'s own `minimal` variant overrides to *empty*, dropping the
manifest entirely). Board-based ports carry the identical shape one level
down — `rp2/CMakeLists.txt`'s own comment says the quiet part directly:
"Include board config, it may override MICROPY_FROZEN_MANIFEST" — most
`esp32`/`rp2` boards do ship their own `boards/<BOARD>/manifest.py`.
`qemu` was right both times — confirmed no `manifest.py` anywhere under
`ports/qemu` on disk, not assumed from the action's own behaviour.

What's pinned in `resources/usermod.toml` is therefore **not** a general
per-variant/per-board resolver — building one is real, unstarted work,
out of scope for the current six ports. It is the one fixed path each
port resolves to under exactly how `a7p`'s own `mp-usermod.yml` builds it
*today*: `unix` → `variants/standard/manifest.py`, `webassembly` →
`variants/pyscript/manifest.py` (both variant overrides, because that
workflow builds those specific variants), `windows`/`esp32`/`rp2` → each
port's own unmodified default (that workflow applies no variant/board
override for any of the three). Landed as `resources/usermod.toml` +
`usermod/portinfo.py`'s `default_manifest()`, alongside `build_system()`
from **D16** above — the generation step itself (the actual
`FROZEN_MANIFEST` combine) is still M7, not this.

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
step of any target here, and (until fixed) had no caching.**
`build-usermod-esp32`'s own header called this out directly: "No caching
yet... Left as a known follow-up, not forgotten."

Running the build itself inside a container is decided, not open: `esp32`
gets a Dockerfile under **D28**'s container-per-port migration that bakes
ESP-IDF into the image the same way `webassembly`'s Dockerfile bakes in
emsdk (**D16**'s own M8 precedent), not mounted from `cache_root()` —
explicitly not started yet (ESP-IDF is multi-gigabyte, the one remaining
real sizing question), tracked there.

One real environment finding worth keeping regardless of that: `openocd-esp32`
(part of ESP-IDF's own default toolset for a target, installed by
`install.sh esp32` regardless of what a usermod build actually needs it
for — flashing/JTAG debug, not building) failed its own post-install
check with `error while loading shared libraries: libusb-1.0.so.0`, in
this dev sandbox specifically. `apt install libusb-1.0-0` fixed it — an
ordinary Linux runtime dependency of upstream's own binary, already
present on any real dev machine or CI image (a GitHub-hosted runner
included).

What actually needed fixing was D19's own real complaint: **no caching**.
Landed as `usermod/espidf.py` — `fetch_esp_idf()`
caches the clone by version, `resolve_esp_idf()`'s own tool-install step
caches the toolchain + Python venv by `(version, idf_target)`, both via
the same `sources.cached_dir()` primitive `fetch_micropython()` already
uses (M1). `ResolvedEspIdf.env()` asks `idf_tools.py export --format
key-value` for the actual environment (`PATH`, `IDF_PYTHON_ENV_PATH`,
`OPENOCD_SCRIPTS`, `ESP_ROM_ELF_DIR`, ...) rather than reconstructing that
resolution by hand -- delegated, not reimplemented, matching `D2`. Not
`toolchains.py`'s `ToolchainSpec` shape, the same reason `emsdk.py` isn't
either (**D16**'s own M8 addendum): there is no single `<prefix>gcc` to
find on `PATH` here.

**D18 addendum — MSVC investigated and rejected as an alternative to
MSYS2.** `ports/windows` also supports building via `msbuild
micropython.vcxproj`, but neither it nor `msvc/sources.props` references
`USER_C_MODULES`/`FROZEN_MANIFEST` anywhere (confirmed by grep across
the whole `msvc/` tree) — `sources.props`'s file list is fixed at
project-authoring time, so a usermod's C sources could only be added by
hand-editing the `.vcxproj` per module, defeating the point of a driver
that takes them as parameters. Ruled out; MSYS2 (and later, its own
supersession below) is the only one of MicroPython's three Windows build
methods that takes those as parameters at all, and what `a7p`'s own
`mp-usermod.yml` already used in production.

**D18, final state — MSYS2 fully superseded, no Windows runner needed for
any arch.** `usermod/msys2.py` first landed and genuinely worked (a real
`windows-latest` run produced a real `micropython.exe` with a usermod
module linked in), catching four real bugs along the way: `build.py`'s
`Path` handling needed `.as_posix()` everywhere (bare `str()` is
backslash-separated on Windows and breaks GNU Make); two `test_emsdk.py`
tests were silently coupled to the CI host being linux-x64;
`tests/test_build.py`'s `touch`-based test needed a `cmd.exe`-compatible
replacement (`echo hi > marker`); and `ResolvedMsys2.to_posix_path()` had
to trust only the last non-empty stdout line, since MSYS2's own first-login
"Copying skeleton files..." notice was corrupting captured `cygpath -u`
output.

Superseded by two live-verified findings, not a clean first-guess: upstream
MicroPython's own CI (`tools/ci.sh`'s `ci_windows_setup`/`_build`) cross-compiles
`x64`/`x86` from Linux with a plain `apt install gcc-mingw-w64-x86-64`/
`gcc-mingw-w64-i686` and `make CROSS_COMPILE=...`, no Windows host at all;
`llvm-mingw` (`mstorsjo/llvm-mingw`) does the same for `arm64`, needing
three real Clang-vs-GCC diagnostic fixes (`-Wno-double-promotion`,
`-Wno-uninitialized`/`-Wno-default-const-init-var-unsafe`,
`COMPILER_TARGET=mingw-forced`/`STRIP=`/`SIZE=true`). All three verified
live with a real custom C module producing a genuine linked
`micropython.exe`/`.exe` for that arch.

Landed as `build.py`'s current `build_windows()` (`WindowsArchSettings` per
arch) plus `usermod/llvmmingw.py` for `arm64`'s toolchain (`x64`/`x86` need
only an apt-installed cross-gcc, no dedicated resolver). `usermod/msys2.py`
and its own CI jobs were deleted outright, not kept as a fallback: a second
working path to the same Makefile is surface area nothing exercises.
`windows` needs no `windows-latest`/`windows-11-arm` runner at all now, for
any of its three arches — relevant to **D20** below, which had assumed one
for all of them.

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

**D20 addendum — `windows` no longer needs `windows-latest` at all, for
any of its three arches — a deliberate divergence from `a7p`'s own matrix
above, not an oversight.** **D18**'s own two-stage supersession (MSYS2 →
Linux-hosted cross-compiles: apt-gcc for `x64`/`x86`, a downloaded
`llvm-mingw` for `arm64`) means `build_windows()` runs on the same host
every other usermod port here does — `ubuntu-latest`, all three arches,
no ARM host needed either (the `llvm-mingw` resolver is itself pinned to
a `linux-x64`-hosted release tarball, `usermod/llvmmingw.py`'s own
`_host_platform_key()`). The `runs_on:` table above still accurately
describes what `a7p`'s own workflow needs, matched target-for-target; it
does not describe what this project's own `--print-build-matrix` should
emit for the `windows` identifiers once **M10** wires this up — that
table should list `ubuntu-latest` for all three, not `windows-latest`/
`windows-11-arm`. Left as a note for whoever implements **M10**, not
acted on here.

Does not generalize to "usermod needs only `ubuntu-latest`" quite as far
as it might first look: `unix`'s own `aarch64` arch used to assume a
native ARM64 host too (`UNIX_ARCH_SETTINGS["aarch64"]` had an *empty*
`cross_compile`) — corrected the same way `windows` was, once actually
tested rather than assumed. A real `ubuntu-latest` run (this project's
own `usermod-dev.yml`, its `unix-aarch64-cross-check` job before it was
folded in and removed) showed `apt install gcc-aarch64-linux-gnu
libffi-dev:arm64` cross-compiles cleanly from x86_64, no native ARM64
host needed after all — the only real wrinkle was that `libffi-dev:arm64`
needs `dpkg --add-architecture arm64`'s own sources pointed at
`ports.ubuntu.com` first (Ubuntu's default `archive.ubuntu.com`/
`security.ubuntu.com` mirrors only carry `amd64`/`i386`; this is real for
any Ubuntu host, not specific to this project's own dev sandbox or to
GitHub's runners). `UNIX_ARCH_SETTINGS["aarch64"]` now has a real
`cross_compile="aarch64-linux-gnu-"` and `apt_package` for it.
`armhf`/`mipsel` were the same story a second time (**D24**): apt
cross-compilers, no execution-host constraint, no special runner
needed — just a genuinely new host dependency (`libltdl-dev`) neither
`aarch64` nor `windows` needed, found only by actually running the
build rather than assuming the pinned settings alone were enough.
`windows` and now `unix/aarch64`/`armhf`/`mipsel` are what stopped
needing a special-case runner; the runner matrix as a whole still has real,
load-bearing entries beyond `ubuntu-latest` for what's left.

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

**Rough phase outline.** Still names-and-one-line for M7 onward, so they
don't get reasoned about before any code exists — the exact mistake
D16–D21 corrected above. M6 gets its first real checkbox, in M0–M5's own
style, now that a slice of it is actually implemented:

- **M6** — extend the **D7** vendored board/variant database with each
  port's default-manifest path and its Make-vs-CMake `USER_C_MODULES`
  shape (**D16**).
  - [x] `src/cibuildmp/usermod/boards.py`: `Port`/`Board`/`Variant`/
        `Database` + `check_board_json`, vendored from `mpbuild` commit
        `972d8319f90dd5a70e3ab6fd1660b9d5a01017fe` (v1.2.0) per **D7** —
        MIT header and provenance kept in the module's own docstring, not
        just here. `tests/test_boards.py` (13 cases, hermetic fixtures)
        plus a live check against a real `v1.28.0` checkout (M1's own
        `fetch_micropython()`, not a second fetcher): 13 ports, 215
        boards found; `zephyr` correctly absent from both (**D22** —
        confirmed live, not just read from upstream source); `unix`
        alone already has 5 real variants (`minimal`, `longlong`,
        `nanbox`, `coverage`, `standard`), more than the two this file's
        own "Two different selector axes" section illustrates.
  - [x] The two fields **D16**/**D17** ask for, kept as their own pinned
        table rather than folded into `boards.py`: `resources/usermod.toml`
        (`build-system` per port, `default-manifest` per port) +
        `usermod/portinfo.py` (`build_system()`, `default_manifest()`,
        `known_ports()`). Scoped to exactly the six ports **D16–D21**
        cover — `unix`, `webassembly`, `windows`, `qemu`, `esp32`, `rp2` —
        not every port MicroPython ships. Verified live against the same
        `v1.28.0` checkout as the boards.py slice above: grepped
        `USER_C_MODULES` in `py/py.mk` and `py/usermod.cmake` directly
        rather than trusting a composite action's doc comment (which
        corrected **D16**'s own "file, not directory" framing — see its
        own addendum above), and `find`-verified every `manifest.py` path
        on disk — which turned out not to be enough on its own: reading
        paths off the checkout alone concluded one shared file per port,
        which cross-checking against `a7p`'s real `mp-usermod.yml` then
        corrected again (per-variant/per-board overrides are real; see
        **D17**'s own addendum, now written twice, for the full story).
        `tests/test_portinfo.py` (10 cases) covers both accessors and the
        unknown-port error path. **Not** in this slice: the actual
        combined-`FROZEN_MANIFEST` generation this data feeds — that stays
        M7.
- **M7** — combined-`FROZEN_MANIFEST` generation + `USER_C_MODULES`
  resolution off that database (**D17**).
  - [x] `usermod/manifests.py`'s `combined_manifest(port, module_manifest)`
        and `usermod/portinfo.py`'s `resolve_user_c_modules(port,
        module_dir)`. Verified byte-for-byte against `a7p`'s own
        `mp-usermod.yml` — its `cat > manifest.py <<EOF ... EOF` bodies
        and `user_c_modules:` inputs, not just the paths already pinned in
        **D16**/**D17** — before writing either function, at the user's
        own request: that check is what caught the `default-manifest` bug
        one commit up (see **D17**'s own addendum), so it ran again here
        rather than trusting the now-corrected table alone.
        `tests/test_manifests.py` and the new cases in
        `tests/test_portinfo.py` assert the exact literal strings that
        workflow's own heredocs and `with:` blocks produce today, for
        every one of the six ports, `qemu`'s no-default-line case
        included.
  - [ ] Not in this slice: actually writing the combined manifest to a
        file and invoking a build with it (**M8**'s own job) — `M7` stops
        at generating the *text* and the *value*, the same string-in
        string-out shape `targets.py`'s own resolvers already have.
- **M8** — the build driver itself, for the ports that need no exotic
  provisioning first (`unix`, `windows` once MSYS2 is handled, `webassembly`,
  `qemu`/armv7m) — the natmod `build.py` shape, pointed at the composite
  actions' own recipes.
  - [x] `usermod/build.py`: `build_unix()`, for `x64`/`x86`/`aarch64` only.
        `UNIX_ARCH_SETTINGS` (`CROSS_COMPILE`/`link_opts`/`standalone` per
        arch) is transcribed from `.github/actions/build-usermod-unix`'s
        own case statement and cross-checked against a real `v1.28.0`
        `ports/unix/Makefile` directly — `CROSS_COMPILE`,
        `MICROPY_FORCE_32BIT`, `MICROPY_STANDALONE` are that Makefile's
        own variables, not the action's invention. `x86` reuses
        `toolchains.resolve("x86")` — natmod's own `-m32` multilib probe
        — rather than re-implementing detection, since "x86" means the
        same thing in both places. Output collection is a plain
        `$(BUILD)/micropython` path check (`PROG ?= micropython`'s own
        default), no globbing needed the way natmod's `.mpy` collection
        needs. `tests/test_usermod_build.py` (13 cases, hermetic,
        `subprocess.run` mocked the same way `tests/test_build.py`
        already does) plus a live build: a real `v1.28.0` checkout, `make
        -C ports/unix` run for real (not `--dry-run`), 40s, a genuine
        825768-byte linked binary.
  - [x] `armhf`/`mipsel` (**D24**): both apt-provisioned
        (`gcc-arm-linux-gnueabihf`/`gcc-mipsel-linux-gnu`, same
        `shutil.which()`-plus-named-package probe `aarch64`/`windows`
        already use), both verified live end to end — real `deplibs`
        run (a genuine static `libffi.a`, `MICROPY_STANDALONE=1`), real
        main build, a genuine linked `ARM`/`EABI5` and `MIPS32` ELF
        each with a real custom C module built in. `UNIX_RUNNABLE_ARCHS`
        now covers every arch `UNIX_ARCH_SETTINGS` pins — the
        `"not buildable yet"` branch `build_unix()` used to have is
        gone, unreachable once it did.
  - [x] `usermod/build.py`: `build_qemu()`, `MPS2_AN385` only. Reuses
        natmod's own `armv7m` toolchain (`toolchains.resolve("armv7m")`,
        `arm-none-eabi-`) rather than pinning a second copy —
        `ports/qemu/Makefile`'s default-board `CROSS_COMPILE` is exactly
        that prefix, verified directly against a real `v1.28.0` checkout.
        `ports/qemu/Makefile` also has RISC-V boards
        (`riscv64-unknown-elf-`, natmod's own `rv32imc`/`rv64imc`
        toolchain) — a real, cheap extension later, not attempted since
        nothing here exercises it yet. `CROSS_COMPILE=` is qemu's own
        variable name, not natmod's `CROSS=`, so this builds its own
        override from `chain.prefix` rather than reusing
        `ResolvedToolchain.make_overrides` (that property is
        `dynruntime.mk`-specific). Output is `$(BUILD)/firmware.elf`
        (`ports/qemu/Makefile`'s own `all:` target), no globbing needed,
        same shape as `unix`'s. 6 new hermetic cases in
        `tests/test_usermod_build.py` (19 total in that file) plus a live
        build: real `v1.28.0` checkout, `make -C ports/qemu` run for
        real, 44s, a genuine 321904-byte `firmware.elf` — and the
        toolchain it linked against was the exact
        `~/.cache/cibuildmp/toolchains/arm-none-eabi/15.2.1-1.1/` M2
        already downloaded for natmod earlier, confirming the reuse
        actually works end to end, not just past a mock.
  - [x] `usermod/build.py`: `build_webassembly()`, `pyscript` variant.
        The toolchain (`emsdk`) does not fit `toolchains.py`'s
        `ToolchainSpec`/`resolve()` shape at all — no `<prefix>gcc`
        binary, two directories need to land on `PATH`
        (`emscripten/` for the `emcc`/`em++` driver scripts,
        `bin/` for the LLVM/wasm binaries they invoke) — so
        `usermod/emsdk.py` is a small, dedicated resolver instead, reusing
        `sources.py`'s own `cached_dir`/`download_file`/`verify_sha256`/
        `extract_archive` primitives rather than duplicating them.
        Pinned to one resolved version (`resources/usermod.toml`'s
        `[emsdk]` table, `6.0.8`/`linux-x64` today) rather than floating
        on `latest` the way `build-usermod-webassembly`'s own
        `emsdk_ref: latest` default does — a deliberate divergence from
        that action, argued in the table's own header comment and tied to
        the **"Toolchain pinning vs. reproducibility"** open question
        below. Bypasses `emsdk`'s own installer (`git clone emsdk` +
        `./emsdk install/activate`) entirely: downloads
        Emscripten's own `wasm-binaries.tar.xz` release asset directly
        (`storage.googleapis.com/webassembly/emscripten-releases-builds/
        {os}/{hash}/...`, resolved from `emsdk`'s own
        `emscripten-releases-tags.json` at pin time, not at build time),
        the same "verify and switch to the standalone tarball" move M2
        already made for `xtensawin` vs. the full ESP-IDF installer.
        Verified live, not assumed: extracting the tarball and
        prepending `emscripten/`+`bin/` to `PATH` is sufficient on its
        own — `emcc`'s own `tools/config.py` auto-derives `LLVM_ROOT`
        (from `clang`) and `BINARYEN_ROOT` (from `wasm-opt`) by
        searching `PATH` when no `.emscripten` config file exists, so
        none needs writing. 5 hermetic cases in `tests/test_emsdk.py` (real
        `verify_sha256`/`extract_archive`/`cached_dir` exercised against
        a small fake tarball, not mocked away) + 5 more in
        `tests/test_usermod_build.py`, plus two separate live checks: a
        real ~300 MiB download+extract+verify of the pinned tarball
        through `resolve_emsdk()` itself, and a full
        `build_webassembly()` run against a real `v1.28.0` checkout — 31s,
        a genuine `micropython.mjs` (217344 bytes, byte-identical to an
        earlier manual PATH-only proof done before any of this code
        existed) plus its `.wasm` — through the actual production code
        path, not the manual proof.
  - [x] `windows` — `usermod/build.py`'s `build_windows()`, one function
        dispatching per arch (`WINDOWS_ARCH_SETTINGS`), all three (`x64`/
        `x86`/`arm64`) now cross-compiling from a plain `ubuntu-latest`
        host, no Windows runner or MSYS2 for any of them: `x64`/`x86` via
        an apt-installed mingw-w64 GCC, `arm64` via a downloaded
        `llvm-mingw` toolchain (`usermod/llvmmingw.py`) — no Linux distro
        packages a GCC targeting `aarch64-w64-mingw32` at all, and
        `llvm-mingw` is the one alternative mingw-w64's own documentation
        names. Three approaches investigated in sequence, not assumed
        away, each corrected by the next live finding rather than
        guessed past — see **D18**'s own addenda for the full history:
        MSVC (no `USER_C_MODULES`/`FROZEN_MANIFEST` hook at all, ruled
        out for every arch), MSYS2 for all three arches (worked, proven
        live on real `windows-latest` CI), narrowed to `x64`/`x86`
        cross-compiling from Linux once upstream's own CI showed that
        works too (`arm64` kept on MSYS2 at that point — reasoned to be
        an acceptable gap, which was wrong, corrected the same session
        once a real consumer requirement was stated directly), then
        `arm64` itself moved off MSYS2 once `llvm-mingw` was confirmed
        live to build it from Linux too, with the exact Clang-vs-GCC
        `CFLAGS_EXTRA` fixes that took.
  - [ ] `rp2` — **not started**, a real gap flagged directly rather than
        left implicit: **M6**'s own `resources/usermod.toml`/
        `usermod/portinfo.py` slice already scoped `rp2` in (its
        `build-system = "cmake"`/`default-manifest = "boards/manifest.py"`
        pins exist, target selection is ready), but no `build_rp2()` ever
        got written — no Pico SDK resolver, no live verification, not
        attempted this session. Caught only when the README's own
        "Target support" table was checked against a real count of
        upstream's ports (20, not the 6 this project scopes to) and it
        turned out the table itself had silently dropped the one port
        that was scoped in but never driven — worth recording as a
        reminder that a summary table can go stale exactly the same way
        code does, not just be written once and trusted.
- **M9** — toolchain provisioning: ESP-IDF fetch + caching, `docker`
  strategy revisit for it (**D19**). MSYS2's own D18 role (windows
  provisioning) ended up superseded entirely — see the `windows` bullet
  above and **D18**'s own addenda.
  - [x] ESP-IDF side: `usermod/espidf.py` (`fetch_esp_idf()`,
        `resolve_esp_idf()`, `ResolvedEspIdf.env()`) + `usermod/build.py`'s
        `build_esp32()`, driving `ports/esp32` the same way the other
        three ports already do. `docker` revisited and dropped for real
        reasons, not left unexamined — see **D19**'s own addendum for the
        live verification (Docker does not run in this project's dev
        sandbox at all; the official clone+install recipe works there
        directly) and the `libusb`/`openocd-esp32` finding that looked
        like a Docker argument on first read and was not one. Both the
        clone and the toolchain+Python-env install are now cached, the
        real gap D19 flagged. 12 hermetic cases across
        `tests/test_espidf.py` and `tests/test_usermod_build.py`, plus a
        full live build: real `v5.5.1` ESP-IDF, `make -C ports/esp32
        BOARD=ESP32_GENERIC`, a genuine `micropython.bin` — through the
        official recipe run by hand first, then again through the actual
        `espidf.py`/`build_esp32()` code path.
  - [x] `windows` toolchain provisioning (**D18**), final state:
        `usermod/llvmmingw.py` (`resolve_llvm_mingw()`, pinned in
        `resources/usermod.toml`'s own `[llvm-mingw]` table, same
        `cached_dir`/`download_file`/`verify_sha256` shape `emsdk.py`
        already uses) for `arm64`; `x64`/`x86` need no dedicated resolver
        at all, just a `shutil.which()` PATH probe for an apt-installed
        `<prefix>gcc` (`build.py`'s own `_resolve_windows_toolchain`
        logic, inlined into `build_windows()`). MSYS2 (`usermod/msys2.py`)
        did real, credited work before being fully superseded: its own
        `usermod-dev.yml` `windows` job (a plain on-push scratch workflow,
        no PR — MSYS2 could not be verified in a Linux sandbox at all)
        caught and fixed four real bugs across its runs before this
        supersession — `usermod/build.py`'s `Path` handling used bare
        `str()`, which is backslash-separated on Windows and breaks any
        GNU Make invocation (fixed to `.as_posix()` everywhere, still the
        rule for every port here); two of `test_emsdk.py`'s own tests
        were silently coupled to the CI host actually being linux-x64;
        `tests/test_build.py`'s own
        `test_pre_build_command_runs_in_module_root` used `touch`, which
        `cmd.exe` has no equivalent for (fixed to `echo hi > marker`);
        and `ResolvedMsys2.to_posix_path()`'s own first-login-shell
        skeleton-banner bug (**D18**'s own addendum has the detail). None
        of these were "not this work's problem" — a bug found while doing
        this work got fixed as part of it, whoever's line it originally
        was. 13 hermetic cases across `tests/test_usermod_build.py` for
        the final `windows`/`x64`/`x86`/`arm64` shape, plus the live
        proofs **D18**'s own addendum records for all three arches.
- **M9b — CLI/config wiring (D23): the five usermod build drivers
  (unix/windows/qemu/webassembly/esp32) are reachable from the actual
  `cibuildmp` CLI now, not just from Python.** Not anticipated when the
  M9-M12 sequence above was first written (README's own "no `--mode
  usermod` entrypoint yet" caveat was still true at the start of this
  slice) -- inserted here rather than renumbering M10-M12, since those
  three describe later work this one is a real prerequisite for, not
  work this one replaces.
  - [x] `usermod/targets.py`: `UsermodTarget` (`{port}` or
        `{port}-{arch}`, no `.mpy` ABI axis at all -- **D23** explains
        why that axis doesn't apply here), a `port -> (axis config key,
        default axis values)` registry, `usermod_targets()`/`select()`.
  - [x] `usermod/options.py`: `[usermod]` config table (+ per-port
        `[usermod.<port>]` sub-tables for the real axis, `archs` or
        `boards` depending on the port) -- **D5**'s own "config scoped
        by build mode" precedent, genuinely followed a second time
        rather than just cited.
  - [x] `usermod/orchestrate.py`: resolves a target's `UsermodBuildOptions`
        into the port-specific `*BuildOptions` `usermod/build.py` already
        has (`user_c_modules` via `portinfo.resolve_user_c_modules()`,
        a combined manifest via `manifests.combined_manifest()` written
        to a real file, a per-identifier `build_dir`), calls the
        matching `build_<port>()`, collects the result into
        `output-dir/<identifier>/` -- no `package.json` (**D23**).
  - [x] `cli.py`: `detect_mode()` auto-picks `natmod`/`usermod` from
        which top-level table the config has, `--platform` becomes its
        explicit override (only needed when a config genuinely defines
        both) rather than the natmod-only stub it was before. No
        config and no table at all still defaults to `natmod`,
        unchanged, so every existing consumer's behaviour is untouched.
  - [x] `usermod/cli.py`: the usermod half of `main()`'s own dispatch --
        `--dry-run`/`--only`/`--print-build-identifiers`/
        `--print-build-matrix`/`--allow-empty`, all working the same
        way they already do for natmod.
  - [x] Verified live, end to end, not just against the hermetic suite:
        a real `[usermod]` config (`ports = ["unix"]`), a real custom
        `mymod` C module, run through the actual `cibuildmp` CLI (no
        mocking) -- fetched v1.28.0 for real, ran the real `make`,
        produced a genuine linked `unix-x64` binary, collected it into
        `mpyhouse/unix-x64/`, and running it directly confirmed the
        custom module actually works: `import mymod; mymod.hello()` ->
        `42`.
  - Deliberately not done in this slice, flagged rather than silently
    skipped: no `[[overrides]]` glob mechanism for usermod yet (the
    per-port option shapes are not uniform enough to reuse natmod's own
    unmodified), no `extra-files`/`pre-build-command` equivalents, no
    `CIBMP_*` environment overrides for `[usermod]`'s own keys beyond
    the genuinely shared `micropython`/`output-dir`, and `--archs`/
    `--toolchain` stay natmod-only (a usermod target's axis is
    config-only; toolchain resolution always goes through whatever each
    `build_<port>()` already does internally).

**D23 — usermod's own identifier scheme, config shape, and output
convention are each genuinely different from natmod's, not reused
unmodified, and each difference is deliberate.**

- **No ABI axis in the identifier.** natmod's `Target.identifier` is
  `mpy{abi}-{mode}-{arch}` because a `.mpy` is compiled *against* a
  specific running MicroPython's compatibility tag -- the whole reason
  D14's packaging step exists at all is to let `mip` match a `.mpy` to
  a device's own ABI. A usermod build has no such relationship: it *is*
  the MicroPython, a full port binary meant to be flashed or run
  directly, not installed into one already running. `UsermodTarget`'s
  own identifier is just `{port}` or `{port}-{arch}` -- reusing
  natmod's `Target` dataclass (even just its `mode` field, which does
  read as though it was left generic for exactly this) would have
  carried an ABI axis that means nothing here, so a new, smaller
  dataclass instead.
- **No `package.json` in `output-dir/<identifier>/` either, for the
  same reason** -- confirmed with the user directly before writing any
  of `usermod/orchestrate.py`, not assumed either way from D14's own
  text alone. The identifier-scoped *directory* convention is kept
  (same "no reorganising step between building and having the output"
  reasoning D14 already gives), just without the `mip`-specific
  manifest next to it.
- **Config is scoped by build mode a second time, genuinely, not just
  cited.** D5 already named cibuildwheel's own `[tool.cibuildwheel.
  android]`/`.pyodide` sub-tables as the model for *natmod's* own
  `[natmod]` table; `[usermod]` plus its own per-port
  `[usermod.<port>]` sub-tables (`archs` for `unix`/`windows`,
  `boards` for `esp32`, nothing yet for `qemu`/`webassembly`, which
  have no configurable axis at all today) follow the same model a
  second time, for a second axis cibuildwheel itself has no equivalent
  of at all (which *port*, not which OS).
- **Mode is auto-detected, not asked for.** The user's own question,
  asked directly rather than assumed away: "isn't it obvious from the
  config already?" -- yes, almost always. `cli.detect_mode()` reads
  which top-level table (`natmod`/`usermod`) the config actually has
  and picks that; `--platform` (previously a `choices=["natmod"]` stub
  that did nothing real) becomes an explicit override, needed only
  when a config genuinely defines both tables at once (a real,
  legitimate case: one module shipping both a natmod extension and a
  full usermod port build) -- ambiguity is the one case a flag earns
  its keep for, not the common one.
- **One MicroPython tag, not D13's own list-spanning-an-ABI-boundary
  mechanism.** A usermod build has no ABI to span in the first place,
  so `UsermodOptions.micropython` is a plain `str`; the shared
  top-level `micropython` key can still be a list (natmod's own D13
  case), and only its first entry is taken -- explicit, not a silent
  `str()` of a Python list into nonsense (a real bug caught and fixed
  while writing `UsermodOptions.load()`, before it shipped).
- **A target's own build directory is `mpy_dir/ports/<port>/
  build-<identifier>/`, not the port's own bare default.** Two arches
  of the same port (`unix-x64` and `unix-aarch64`, say) share one
  MicroPython checkout and one `mpy-cross` (the same D9 sharing
  natmod's own `build()` already does, and for the same reason: none
  of usermod's own axes change which MicroPython release is being
  built) -- without a per-identifier build directory, building both in
  one invocation would have the second overwrite the first mid-build.
  `esp32` is the one exception: it has no `build_dir` field at all
  (`usermod/build.py`'s own `Esp32BuildOptions`), since its own
  CMake-driven build already keys its directory on `BOARD=` alone
  (`build-<BOARD>/`) and passing a competing `BUILD=` override breaks
  its internal mpy-cross sub-build (that module's own docstring has the
  real CI failure this caused, found before **M9**'s own esp32 work
  shipped).
- **`qemu`'s board is never passed through as `board=""`.** `qemu` has
  no configurable axis yet, so `UsermodTarget.arch` is always `""` for
  it -- a real bug caught while writing this (and now covered by
  `test_build_one_qemu_uses_default_board_not_empty_string`): passing
  that empty string through to `QemuBuildOptions(board=...)` would have
  silently overridden its own `"MPS2_AN385"` default with nothing,
  instead of just not passing `board=` at all and letting the
  dataclass default apply.

**D24 — `unix/armhf` and `unix/mipsel` are real, verified-live cross-compiles
now, closing M8's own acknowledged gap; the missing piece was never the
cross-compiler.** `UNIX_ARCH_SETTINGS["armhf"]`/`["mipsel"]` had been
pinned since **M8**'s first `build_unix()` slice, with `build_unix()`
deliberately raising `"not buildable yet"` rather than pretending —
both need a glibc-hosted cross-toolchain natmod's own bare-metal
`arm-none-eabi-`/`riscv64-unknown-elf-` pins don't cover, plus
`MICROPY_STANDALONE=1`'s own static-link `deplibs` pre-step (already
implemented, `run_unix_deplibs()`, but never actually run against a
real toolchain before now).

Both `gcc-arm-linux-gnueabihf` and `gcc-mipsel-linux-gnu` are plain
apt packages — confirmed live, no `ports.ubuntu.com` mirror dance at
all, unlike `aarch64`'s own `libffi-dev:arm64` (**D20**'s own
addendum): these are cross-compilers that *run* on `amd64`, not
target-arch libraries multiarch has to resolve. Wired the same
`shutil.which()`-plus-named-`apt_package` probe `aarch64`/`windows`
already use.

The one real, non-obvious blocker: `run_unix_deplibs()` failed on a
real host with `autoreconf: error: ... possibly undefined macro:
LT_SYS_SYMBOL_USCORE` — `deplibs`' own `./autogen.sh` regenerates
vendored `lib/libffi`'s `configure` from `configure.ac`, and that
macro is `ltdl.m4`'s, not `libtool.m4`'s. `autoconf`/`automake`/
`libtool` alone (all present on this project's own dev host already)
do **not** ship `ltdl.m4` — only the separate `libltdl-dev` package
does. Not documented anywhere upstream this was checked against
(neither `.github/actions/build-usermod-unix`'s own comments nor
libffi's own `README`/`INSTALL` mention it); found only by actually
running `deplibs` for real against a genuine cross-toolchain, exactly
the kind of gap that stays invisible until someone tries the real
thing rather than trusting the pinned settings table alone. Once
installed, both `deplibs` and the main build ran clean end to end —
verified twice: once calling `usermod/build.py`'s own functions
directly, once through the full `cibuildmp` CLI (`[usermod.unix]
archs = ["armhf"]`), each producing a genuine linked `ARM`/`EABI5` (or
`MIPS32`) ELF with a real custom C module built in and callable.

`UNIX_RUNNABLE_ARCHS` now equals every key `UNIX_ARCH_SETTINGS` pins
(`x64`/`x86`/`aarch64`/`armhf`/`mipsel`) — the `"not buildable yet"`
branch `build_unix()` used to raise is gone rather than left
unreachable; `usermod/targets.py`'s own default `unix` axis values
grew to include both, the same "default = everything currently
provable" rule `windows`/`arm64` and `unix`/`aarch64` already
followed once each was proven simple enough, not left as an opt-in
special case. `action.Dockerfile` does not yet bake in either
toolchain (same open gap **D23**'s own note already has for
`aarch64`) — a real, separate, still-open item for whoever tackles
that Docker-action gap next.

**D25 — both Dockerfiles now bake in every `unix` cross toolchain
(`aarch64`/`armhf`/`mipsel`) closing D23/D24's own open item, and the
first real `docker build` of either image (neither had ever actually
been built before this -- both predate real usermod CLI usage
entirely) surfaced six genuine, non-obvious apt/gcc problems no amount
of reading package lists would have caught -- one of them (the
`i386-linux-gnu` symlink) initially "fixed" wrong and only caught by a
later, unrelated real build failure, and two of them (`libc6-dev-<arch>-cross`,
`libtool`) sharing the exact same root shape: a package only
`Recommends:`, not `Depends:`, what `--no-install-recommends` then
silently drops -- and both masked, at first, by this project's own dev
sandbox happening to have them installed from unrelated earlier work.** `examples/usermod-unix`
(a real `USER_C_MODULES` module, `cibuildmp.toml` defaulting to all
five `unix` arches) wired into `build-examples.yml`'s own `uses: ./`
step is what proved it -- this project's dev sandbox has no Docker
daemon at all (**D19**'s own finding), so every ingredient was
verified individually there and the actual `docker build` had to run
for real on CI, exactly the same "only a real build catches this"
lesson **D18**'s own `action.Dockerfile`-location bug already taught.

- **`gcc-multilib` unconditionally `Conflicts:` every single
  `gcc-N-<target>-linux-gnu` cross-compiler package, every GCC major
  version 4.9 through 15** -- confirmed directly from `apt-cache show
  gcc-multilib`'s own `Conflicts:` field, not a resolver quirk a
  differently-ordered `apt-get install` would sidestep: installing
  `gcc-multilib` after the cross packages are already present offers
  to *remove all three of them*. This dev sandbox never surfaced it
  while every individual cross-compiler was being verified earlier
  (**D20**/**D24**) because `gcc-multilib` itself was never actually
  installed there at all (`dpkg -s gcc-multilib` said so directly) --
  only the versioned sub-packages from separate, earlier installs.
  Fix: `gcc-13-multilib` (the real, versioned package `gcc-multilib`
  itself only wraps) carries no such `Conflicts:` and provides the
  identical `-m32` support -- verified live, installed alongside all
  three cross packages in one transaction with no conflict, then a
  real `gcc -m32` compile-and-run.
- **`gcc -m32` cannot find `<asm/errno.h>` after that substitution**
  -- a second, separate real failure, this time inside natmod's own
  `x86` arch build (`examples/template`), not usermod at all: `gcc -m32
  -E -v`'s own header search list names `/usr/include/i386-linux-gnu`
  as a search directory (`gcc -m32 -print-multiarch` names the same
  path) but no apt package actually creates it by default -- gcc simply
  skips the nonexistent directory and fails to find the header at all.
  First fix tried: `ln -sf /usr/include/x86_64-linux-gnu
  /usr/include/i386-linux-gnu` -- confirmed live, a real `-m32` compile
  and run succeeding immediately after. **Later found wrong** -- see
  the next bullet -- and replaced.
- **`unix/x86`'s own `modffi.c` (`MICROPY_PY_FFI`) needs `pkg-config`
  and the *native* `libffi-dev`, not just the target-arch
  `libffi-dev:arm64` already installed for `aarch64`/`armhf`/`mipsel`**
  -- a third real failure, `fatal error: ffi.h: No such file or
  directory`, caught only once `examples/usermod-unix` started
  exercising `unix/x64` inside the real Docker image (nothing needed
  `libffi-dev` at all before usermod's own unix arches built here for
  the first time). Two combined gaps: plain `libffi-dev` (native amd64)
  had never been added, only the `:arm64` one; and
  `ports/unix/Makefile`'s own `LIBFFI_CFLAGS`/`LIBFFI_LDFLAGS` resolve
  via `pkg-config --cflags/--libs libffi` (confirmed directly from the
  real cached `Makefile`), so even with `libffi-dev` present, no
  `pkg-config` on the image left those flags empty. Fix: add both
  `libffi-dev` and `pkg-config`.
- **The `i386-linux-gnu` symlink above was itself wrong, not just
  incomplete -- a fourth real failure, on `unix/x86` specifically,
  once `pkg-config`/`libffi-dev` made `modffi.c` actually reach
  `ffi.h`:** `#warning ... X86 IS DEFINED [-Werror=cpp]` out of
  libffi's own `ffitarget.h`, turned fatal by `-Werror`. Root cause:
  libffi's `ffitarget.h` is genuinely word-size/ABI-specific (it
  encodes the target's calling convention), so serving the *64-bit*
  package's `ffitarget.h` under a 32-bit `-m32` compile is a real
  correctness bug, not a missing-file one -- it happened to compile
  (with warnings) rather than silently miscompiling, only because
  `-Werror` was on. The symlink's only genuinely correct job was
  `asm/errno.h` (Linux UAPI kernel headers, which *are* arch-generic
  enough for this to be harmless); it was never the right tool for
  `ffi.h`. Fix, verified live end-to-end (a real `unix/x86` build with
  a custom C module, run and returning the right value): drop the
  symlink entirely, and instead
  `dpkg --add-architecture i386 && apt install libffi-dev:i386
  linux-libc-dev:i386`. Unlike `arm64`, `i386` is **not** a "ports"
  architecture -- it already lives on the regular
  `archive.ubuntu.com`/`security.ubuntu.com` mirrors (confirmed live:
  `apt-cache madison libffi-dev:i386` resolved there directly, no
  `ports.ubuntu.com` stanza needed), so this only widens the existing
  stanzas' own `Architectures:` line to `amd64,i386`, the same stanzas
  `arm64`'s own fix above already restricts to `amd64`.
  `linux-libc-dev:i386` is what actually ships a real, arch-correct
  `asm/errno.h` under `i386-linux-gnu/` -- the symlink's one genuine
  job, now done by a real package instead of a borrowed path.
- **A fifth real failure, on `unix/aarch64` -- the first arch past the
  two x86 fixes above to ever actually reach its own compiler in
  either image:** the same `fatal error: asm/errno.h`, this time out
  of the *cross* compiler (`aarch64-linux-gnu-gcc`), not `-m32`.
  Root cause: `gcc-aarch64-linux-gnu` only `Recommends:` its own
  `libc6-dev-arm64-cross` (confirmed via `apt-cache depends`), not a
  hard `Depends:` -- and both Dockerfiles use
  `apt-get install --no-install-recommends` throughout, which silently
  skips it. The cross-compiler itself still installs and runs; only
  the target's own kernel/libc headers are missing, so anything
  touching `<asm/errno.h>` (most of `ports/unix`) fails to even
  preprocess -- link-time problems would have been obvious immediately,
  a missing-header compile failure only shows up once a real build is
  attempted. `gcc-arm-linux-gnueabihf`/`gcc-mipsel-linux-gnu` carry the
  identical gap (`libc6-dev-armhf-cross`/`libc6-dev-mipsel-cross`,
  same `Recommends:`-not-`Depends:` shape) -- neither `armhf` nor
  `mipsel` had been reached yet in either image (`aarch64` fails
  first, alphabetically/list-order before them), so this was caught
  and fixed for all three at once, not discovered arch-by-arch.
  Verified live end to end for all three: purged the cross-libc
  packages, reproduced the exact failure reinstalling with
  `--no-install-recommends` alone, then fixed it by naming
  `libc6-dev-arm64-cross`/`libc6-dev-armhf-cross`/
  `libc6-dev-mipsel-cross` explicitly (each pulls its own
  `linux-libc-dev-<arch>-cross` as a hard `Depends`, so naming these
  three is enough) -- followed by a full real `unix/aarch64`,
  `unix/armhf`, `unix/mipsel` build each, with a custom C module, three
  genuine linked binaries (`ARM aarch64`, `ARM armhf`, `MIPS32`) with
  no header errors at all.
- **A sixth real failure, on `unix/armhf`'s own `deplibs` step,
  immediately past the fifth fix landing on real CI:** `libtoolize: No
  such file or directory`, then (once `libtoolize` itself is on PATH
  but never actually invoked to regenerate the vendored `lib/libffi`
  tree's own macros) `Makefile.am:39: error: Libtool library used but
  'LIBTOOL' is undefined`. Exactly the same shape as the fifth bug,
  one package over: `libltdl-dev` only `Recommends:` `libtool`
  (confirmed via `apt-cache depends`), not a hard `Depends:` --
  `--no-install-recommends` skips it. This project's own dev sandbox
  already had `libtool` installed from unrelated earlier work in this
  session, which is exactly why **D24**'s own `armhf`/`mipsel` live
  verification (and this very D25 entry's fifth-bug verification,
  above) looked complete at the time -- neither ever actually
  exercised a sandbox without it. Caught for real only once a
  genuinely libtool-free image (the real `docker build`/`docker run`
  from the previous commit) tried the same step. Verified live the
  same rigorous way this time, specifically to avoid repeating the
  false-positive: purged `libtool`, *and* deleted the already-generated
  `lib/libffi/configure` this session's own earlier runs had left
  behind (its own Makefile rule only regenerates `configure` when it is
  missing or older than `autogen.sh` -- reusing a stale, already-good
  `configure` is exactly how the first "live verification" of this
  fix silently proved nothing), reproduced the exact CI failure,
  installed `libtool`, deleted the stale `configure` again, and only
  then confirmed a genuine fresh `unix/armhf` and `unix/mipsel` build
  each -- two real statically-linked binaries (`ARM EABI5`, `MIPS32`)
  with the custom C module built in.
- All six fixes are Dockerfile-only, not `cibuildmp` itself: none
  affect a bare `ubuntu-latest` runner running the CLI directly
  (**M9b**'s own live verification, and every `build-examples.yml` run
  before this one, already exercised `gcc -m32` successfully outside
  Docker) -- only these two custom images, which now need
  `gcc-13-multilib`, `libffi-dev`, `pkg-config`, the real `:i386`
  packages (not a symlink), the three `libc6-dev-<arch>-cross`
  packages, and `libtool` -- everything `--no-install-recommends` was
  silently dropping -- to combine x86 multilib support with three
  cross-compilers in one filesystem. README's own bare-metal install
  instructions get the same fixes, at the point a reader would
  actually hit them -- though a reader running a plain `apt install`
  (recommends on by default) would never have hit the fifth or sixth
  bug at all; both are purely a consequence of
  `--no-install-recommends`, which only these two Dockerfiles use.
- **cibuildwheel's own answer to "many architectures, one toolchain
  set" is structurally different, not comparably fixed** -- asked and
  answered directly, not assumed: cibuildwheel never combines
  cross-compilers in one image at all. Linux wheels build inside one
  container *per target architecture* (`manylinux_x86_64`,
  `manylinux_aarch64`, ...), each with only its own architecture's
  native toolchain; non-x86 targets on an x86 runner go through QEMU
  user-mode emulation (registered via `docker/setup-qemu-action` on
  GitHub Actions) rather than cross-compiling, so the *emulated*
  container's own gcc is always native to what it's building for.
  macOS wheels build natively via one Xcode toolchain's own
  `-arch x86_64 -arch arm64` (`universal2`), no container or conflict
  surface at all. `cibuildmp`'s own choice -- real cross-compilation
  from one x86_64 host, not a container/QEMU per target -- is
  deliberate (**D2**/**M2**'s own "why not docker for x86" reasoning:
  MicroPython's build is light enough that cross-compiling beats
  emulation) and it is exactly what both bugs above are the real,
  concrete cost of; not a flaw unique to this project's own approach,
  a structural tradeoff already made with eyes open.

**D26 — usermod moves to one Docker image *per port*, not one combined
image; `action.yml` stops being a Docker action itself and becomes a
thin composite action that ensures Docker is present, then runs
`cibuildmp` directly on the bare runner; `cibuildmp` itself launches
sibling per-port containers rather than running inside one.** Direct
follow-up to D25's own cibuildwheel comparison and the six real bugs
found there -- the user's own proposal, refined once from "per
architecture" to "per port" citing `mpbuild`'s own precedent of
separate containers per port.

- **Not a new idea grafted on** -- `toolchains.py`'s own module
  docstring already said this outright, before any of D25's bugs were
  found: "Docker is deliberately absent for natmod... It is planned
  for usermod, where port builds have real system dependencies." This
  decision is that plan, made concrete.
- **Why sibling containers, not Docker-in-Docker:** today's
  `action.yml` already runs entirely *inside* one container
  (`action.Dockerfile`, D18's own conversion). If `cibuildmp` itself
  tried to launch per-port containers from in there, it would need the
  host's Docker socket passed through (`-v /var/run/docker.sock:...`)
  -- a real, fragile pattern (DinD), not free. Flipping it -- the
  action installs/confirms Docker and runs `cibuildmp` bare on the
  runner, which then runs ordinary sibling `docker run` calls -- avoids
  DinD entirely, since GitHub-hosted runners already have a working
  Docker daemon with no container boundary in the way. natmod is
  unaffected either way: every natmod arch is a cross-compile that
  already runs directly on the host (D2/M2), no container at all,
  today or after this change.
- **Honest limit: per-port splitting does not, by itself, avoid the
  six bugs D25 just fixed.** Every one of them was `unix` colliding
  with itself -- its own five architectures (`x64`/`x86`/`aarch64`/
  `armhf`/`mipsel`) sharing one filesystem, not `unix` colliding with
  `windows` or `esp32`. A `unix`-only image still combines all five
  unix cross-compilers in one place and would still need every fix
  D25 documents. The real, distinct benefits are: (1) no DinD, as
  above; (2) a caller building only `unix` never pulls `windows`'s
  `gcc-mingw-w64-*` or `esp32`'s multi-gigabyte ESP-IDF checkout at
  all -- today's single image pays that cost for everyone regardless
  of `ports = [...]`; (3) blast radius -- a broken `esp32` image
  (ESP-IDF's own churn is real and frequent) can't block a `unix`-only
  build the way one shared image's failed `docker build` does today;
  (4) matches `mpbuild`'s own independently-arrived-at shape (cited by
  the user, not yet independently verified against `mpbuild`'s own
  source by this project).
- **Scope, not yet built:** a new `docker` toolchain strategy in
  `cibuildmp` (build/pull a port's own image, run the port's existing
  `make`/`cmake` invocation inside a container via ordinary volume
  mounts -- `mpy_dir` and the caller's `package_dir` cover every path
  the existing commands already reference, no path translation needed
  since mounts land at identical absolute paths); five per-port
  Dockerfiles replacing today's one `action.Dockerfile` (`unix`,
  `windows`, `qemu`, `webassembly`, `esp32`); `action.yml` rewritten
  from `runs: using: docker` to a composite action; `publish.yml`'s
  GHCR push extended from one image to five. Each per-port image needs
  only that port's own toolchain, not `cibuildmp` itself baked in --
  `cibuildmp` stays on the bare runner and only ever `docker run`s the
  port's own build command, keeping every image far smaller than
  today's combined one.
- **First slice, agreed with the user:** a proof-of-concept for `unix`
  only -- a `resources/docker/unix.Dockerfile` (just that port's own toolchain,
  the exact package set D20/D24/D25 already verified live, minus
  `windows`/`esp32`-only packages) and a minimal `docker`
  toolchain-strategy path in `usermod/build.py`, opt-in and not yet
  wired into the public `action.yml` at all. This project's dev
  sandbox has no Docker daemon (**D19**), so unlike every apt-level fix
  above, an actual `docker build`/`docker run` of this slice cannot be
  verified here at all -- only on real CI, the same round-trip
  constraint D25's own six-bug chain already worked under, now one
  level higher (a whole new image, not one more apt package).
- **Amended (D31): "one image per port" was still too coarse for
  `unix` specifically.** The user's own correction, directly: `unix`
  needed cutting further, into one image per *(arch, libc)* --
  cibuildwheel's own `manylinux_x86_64`/`musllinux_aarch64` shape, not
  one combined "unix" image the way this decision first described it
  above. `resources/docker/unix.Dockerfile` (one image, all five
  arches) was replaced by five separate
  `resources/docker/unix-manylinux-<arch>.Dockerfile` files, each only
  that arch's own packages -- real isolation this decision's own bullet
  above already argued for at the *port* level now also holds at the
  *arch* level (an armhf toolchain bump can no longer touch an x64
  image's own build). `natmod` is explicitly NOT part of this
  refinement -- the user's own point: a `.mpy` is loaded by an
  already-running target interpreter, not exec'd as its own process, so
  the build host's own libc linkage never enters the picture the way it
  does for a full `unix` port executable; one combined `natmod`
  Dockerfile (**D30**'s own point 2) stays correct. `windows` also
  stays one combined image (this file's own `resources/docker/windows.Dockerfile`
  header has the reasoning: no manylinux/musllinux-shaped axis exists
  for Windows at all). See **D31** for the full musllinux gap this
  correction sits inside, and `usermod/dockerrun.py`'s own resolver,
  now keyed by `(port, arch)` with an optional trailing `libc` segment
  rather than `port` alone.

**D27 — the sixth Dockerfile fix (libtool) finally got real CI past every
`unix` arch's own build, and immediately surfaced two genuine `cibuildmp`
bugs of its own -- not Dockerfile/apt gaps this time, but real defects in
`usermod/orchestrate.py`, invisible in every prior verification in this
whole session because none of it had ever run the real CLI with
`package_dir != cwd`, or actually tried to execute a collected binary.**
`cibuildmp` itself reported all five `unix` arches built successfully
(`cibuildmp: 5 usermod target(s) built in 209.7s`, real byte sizes for
each) -- CI still failed, on the unrelated "List built artifacts" step,
because the output never landed where it should have.

- **`build_one()`'s own `identifier_dir = options.output_dir /
  target.identifier` never joined `package_dir` in** -- `output_dir`
  defaults to the bare relative string `"mpyhouse"` (`DEFAULT_OUTPUT_DIR`,
  shared with natmod), meant to resolve *against `package_dir`*, exactly
  the join natmod's own `cli.py` already does
  (`options.package_dir / build_options.output_dir`) before ever calling
  `collect_output()`. `orchestrate.py` skipped that join entirely, so the
  usermod build wrote to `<process cwd>/mpyhouse/...` instead of
  `<package_dir>/mpyhouse/...`. Invisible until now because every earlier
  verification in this session -- direct `build_unix()` calls, the M9b
  CLI proof, D20/D24's own live checks -- happened to run with cwd already
  equal to `package_dir`; a real Docker-action run is what caught it, since
  `action.yml`'s own container always has cwd at the repo root
  (`/github/workspace`) while `package-dir` points at
  `examples/usermod-unix`, a genuinely different directory. Fixed by
  making `orchestrate.py` do the identical join natmod's `cli.py` already
  proved correct: `options.package_dir / options.output_dir /
  target.identifier`. Verified live: a real CLI invocation with
  `package_dir` pointed at a tree copied well outside the repo and cwd
  left at `/`, confirming the output landed under `package_dir/mpyhouse/`
  and nothing at all appeared at the bare cwd-relative path.
- **`build_one()`'s own `shutil.copyfile(produced, dest)` doesn't
  preserve the executable bit `produced` already has** -- `copyfile()`
  copies content only, by Python's own documented contract; the
  collected binary came out `-rw-r--r--` and failed "Permission denied"
  on the very first attempt to run it. Harmless for natmod's own `.mpy`
  output (never executed directly -- always `mip.install()`-ed or
  imported, **D23**'s own distinction), a real, user-facing defect for
  usermod: the whole point of a usermod build's output is that it's a
  runnable binary. Fixed by switching to `shutil.copy()` (copies mode
  along with content). Verified live in the same run as the fix above --
  the collected `mpyhouse/unix-x64/micropython-unix-x64` ran immediately,
  no manual `chmod` needed, and the custom C module inside it still
  returned the right value.
- Both are genuine `cibuildmp` defects, not Dockerfile issues -- unlike
  every fix in **D25**, neither is scoped to the two custom images; both
  would misbehave identically for any caller running the bare CLI with
  `package_dir` set to something other than the process's own cwd, or
  ever trying to run a collected usermod binary directly. Two new
  regression tests cover each (`tests/test_usermod_orchestrate.py`),
  confirmed to fail without their respective fix before being confirmed
  to pass with it, not just written and trusted.

**Superseded by D33, below: `ensure_image()`'s own "build cibuildmp's
packaged Dockerfile locally when nothing is registered" fallback,
described throughout this entry (and D26/D30/D31/D32), no longer
exists. cibuildmp never builds a Docker image itself any more -- see
D33 for the current design (checked against cibuildwheel's real source
before deciding, not assumed) and `usermod/dockerrun.py`'s own module
docstring for the code as it stands today. The rest of D28 stays as the
real record of how the container-per-port migration actually happened
-- the isolation argument, the per-arch image split, the buildx/type=gha
caching mechanics later removed by D33 are all still true engineering
history, just not the current build-vs-pull design.**

**D28 — full migration plan: container-per-port for usermod (D26),
written as a standalone handoff for a fresh session to execute.
Isolation between ports is the primary driver, not a side benefit** --
the user's own framing, directly: real builds should not be able to
break each other across ports the way **D25**'s six bugs all did within
`unix` alone, and CI's own cache story needs a documented, deliberate
answer before the migration starts, not discovered mid-flight the way
**D25**'s bugs were. Originally written as a plan, not a status report
-- since substantially updated in place, this same session, as steps 1
through most of 3 actually landed. The **"Handoff: exact state as of
this session's end"** block immediately below is the one to read first
if picking this up fresh; everything after "Why isolation is the real
driver" is the original plan text, kept (and updated in place) as the
detailed record of *why* each piece looks the way it does, not
re-derived from scratch.

---

**Handoff: exact state as of this session's end, for whoever (or
whatever session) picks this up next.**

**Done and verified on real CI:**
- Migration step 1 -- `action.yml` is a composite action, not a
  Docker action. Live-verified: natmod + all 5 `unix` usermod arches
  build correctly through it.
- Migration step 2 -- `usermod/dockerrun.py`'s resolver is real:
  `image_for(port, arch, libc=None)`, `PORT_IMAGES: dict[str, str]`
  keyed `"{port}-{arch}"` / `"{port}-{arch}-{libc}"`, env var override
  `CIBMP_<PORT>_<ARCH>[_<LIBC>]_DOCKER_IMAGE`. Covered by
  `tests/test_usermod_dockerrun.py` (6 cases). **`PORT_IMAGES` is still
  empty** -- nothing is registered as any caller's default yet, on
  purpose (see "the one real gap" below).
- Migration step 3, six of seven Dockerfiles written and building green
  in CI (`build-examples.yml`'s `verify-docker-images` matrix job,
  build-only + push on `push:` events):
  `unix-manylinux-{x64,x86,aarch64,armhf,mipsel}`, `windows` (x64+x86
  only, arm64 stays bare-host), `qemu`, `webassembly` (emsdk baked in,
  ~1.5GB image, **now wired to `ensure_image()` -- see D32's own
  "webassembly landed next" note below**). **Not started: `esp32`** --
  the one remaining port. Bake-vs-mount is decided (bake ESP-IDF in,
  same as `webassembly`'s emsdk, per **D19**); the Dockerfile itself
  just hasn't been written.
- Every Dockerfile that builds green also gets pushed to
  `ghcr.io/ballistics-lab/cibuildmp-<dockerfile>:sha-<gitsha>` on every
  real push (not gated behind a release tag -- the user's own explicit
  call: without a real pullable image, `PORT_IMAGES` could never be
  exercised end to end on a dev branch at all).
- `resources/docker/*.Dockerfile` all live as real package resources
  (`pyproject.toml`'s own `package-data`), not a top-level `docker/`
  directory -- verified live by building a real wheel and confirming
  every file lands inside it.
- Two real CI bugs found and fixed this session, both root-caused from
  actual job logs, neither guessed: (1) the `CIBMP_*`/`ACTION_*` env
  var collision (the composite action's own plumbing vars silently
  overrode `cibuildmp.toml` config -- see the ninth-bug writeup under
  migration step 1's own detail below); (2) the apt-archives GHA cache
  never actually saved even once (`Failed to save: Unable to reserve
  cache with key ..., another job may be creating this cache`, on
  every run checked) -- root cause: rapid-fire pushes left the cache
  key genuinely stuck (not just racing -- confirmed by a later run's
  own *restore*, uncontested by any save-timing collision, never once
  hitting either). Fixed by adding real `concurrency:` blocks to
  `build-examples.yml`/`usermod-dev.yml` (matching `publish.yml`'s own
  existing pattern, confirmed live to actually cancel superseded runs)
  plus minting a fresh `v2-`-prefixed cache key once the old one proved
  unrecoverable. **Confirmed fixed with real log evidence**: the first
  run on the new key logged `Cache saved with key:
  v2-apt-archives-Linux-<hash>` cleanly.

**The one real gap left before this stops being "images exist" and
starts being "the feature works": nobody has ever run a real usermod
build *through* `dockerrun.run()` against one of these pushed images.**
Every image proven so far only proves `docker build` (and `docker
push`) succeeded -- not that `cibuildmp` can actually use one to
produce a real binary. **Closed by D32, below**, in a slightly different
shape than the paragraph originally proposed here: rather than a
one-off manual env-var pointed at `unix`/`x64` alone, `unix` now
defaults to Docker for every one of its five arches via
`ensure_image()`, and `build-examples.yml`'s own CI proves the real
`ghcr.io/...:sha-<gitsha>` pull-and-run path on every push. Only after
that succeeds does registering anything in `PORT_IMAGES` as a real
pinned-release default become a reasonable next move.

**Explicitly not started at all:** `esp32.Dockerfile` (bake-vs-mount is
decided, see **D19** -- bake ESP-IDF in, same as `webassembly`'s emsdk;
just not written yet); `natmod`'s
own single combined Dockerfile (**D30**'s own point 2 -- a genuinely
separate track from this port-per-image work, confirmed out of scope
for the manylinux/musllinux split specifically: a `.mpy` loads into an
already-running target interpreter, no build-host libc linkage
involved at all); the musllinux identifier axis and any real musl
toolchain (**D31** -- large, multi-session, not attempted); registering
anything real in `PORT_IMAGES`; wiring `--platform usermod` or any CLI
flag to actually select a Docker-backed build by default (today it's
still opt-in only, via the env var, and not reachable from the CLI or
`action.yml` at all).

---

**Why isolation is the real driver, restated plainly.** Today, one
combined image (`action.Dockerfile`, and the standalone `Dockerfile`)
bakes every port's toolchain into one filesystem: `unix`'s five
cross-compilers, `windows`'s mingw pair, `esp32`'s ESP-IDF-adjacent
`libusb-1.0-0`. **D25**'s own six bugs were all *internal* to `unix`
(its own five architectures colliding), so per-port splitting alone
would not have caught any of them -- but it does bound the blast
radius going forward: an ESP-IDF version bump breaking `esp32`'s image
cannot silently break a `unix`-only build's image the way one shared
`apt-get install` line can today, and a caller building only `unix`
never pays for `windows`/`esp32`/`webassembly` toolchain weight at all
(today's single image pays that cost for every caller, every port,
unconditionally).

**Current state, precisely.**

- `resources/docker/unix-manylinux-<arch>.Dockerfile` exists for all
  five arches (`x64`/`x86`/`aarch64`/`armhf`/`mipsel`) -- one image per
  arch, not one combined `unix.Dockerfile` any more (this decision's
  own amendment above, **D31**): each holds only that arch's own
  packages (the exact per-arch set **D20/D24/D25** verified live,
  cross-checked directly against a real `v1.28.0` `ports/unix/Makefile`
  for which arches even need `pkg-config`/`libffi-dev` at all --
  `MICROPY_STANDALONE=1` arches, armhf/mipsel, build libffi from the
  vendored submodule instead and need neither). No `cibuildmp`
  installed inside any of them -- deliberately, since the whole point
  of the split is that `cibuildmp` stays on the bare host and only ever
  `docker run`s a port's own build command as a sibling container
  (never Docker-in-Docker; **D26**'s own reasoning for why: today's
  `action.yml` already runs *inside* one container, so nesting a second
  `docker run` from in there would need the host's Docker socket passed
  through -- fragile, avoidable by flipping which side runs bare).
- `usermod/dockerrun.py` exists: a sibling-container runner with a real
  resolver, migration step 2 (below), now implemented -- and corrected
  twice mid-session, on review. `image_for(port, arch, libc=None)`
  checks `CIBMP_<PORT>_<ARCH>[_<LIBC>]_DOCKER_IMAGE` first (an override
  for local testing/forks), then falls back to `PORT_IMAGES`, a plain
  `dict[str, str]` **in this file's own source** that a maintainer edits
  to register a port's canonical image -- not a `cibuildmp.toml` key.
  Keyed by `(port, arch)`, with an optional trailing `libc` segment only
  for ports that actually have one (`unix`, passing `"manylinux"`
  explicitly from `build_unix()`) -- `windows`/`qemu`/`webassembly`/
  `esp32` call it with no `libc` at all rather than defaulting to a
  "manylinux" label that means nothing for them. `PORT_IMAGES` is still
  empty today: the five `unix-manylinux-*` images above all exist and
  build correctly (inferred, not yet docker-built) but aren't published
  to GHCR yet (step 5), and registering any of them before a real
  pullable image exists would make every unopted-in `unix` usermod
  build for that arch start trying, and failing, to pull it -- so
  `image_for()` still returns `None` for every real caller today,
  unchanged. `build_unix()` in `usermod/build.py` checks this and, when
  it returns an image, routes both `run_unix_deplibs()` and the main
  `make` invocation through `dockerrun.run()` instead of a bare
  `subprocess.run()`. `dockerrun.run()` itself passes `docker run
  --pull missing` explicitly -- Docker's own default, confirmed live
  via `docker run --help`, pinned rather than relied on -- which is the
  entire answer to "how does cibuildmp decide build-vs-cache": it never
  decides anything, Docker does, and that only stays correct because
  every image this project resolves to is `:sha-<gitsha>`-tagged
  (immutable by construction) rather than `:latest` -- a cached local
  copy and a still-correct one are the same fact for a sha tag, which
  is not true for a mutable one.
- **`action.yml` is now a composite action -- migration step 1, done
  and live-verified on real CI, not just implemented.** `runs: using:
  "docker"` → `"composite"`, `entrypoint.sh` deleted (dead code,
  nothing references it any more), the apt-prerequisite list kept
  byte-for-byte identical to `action.Dockerfile`'s own (deliberately
  -- see migration step 1's own note on why slimming it now would have
  broken every existing usermod build), env vars renamed to clean,
  explicit names (`ACTION_PACKAGE_DIR`, not `INPUT_PACKAGE-DIR`) per
  the cibuildwheel-confirmed win noted above. `publish.yml`'s own
  `publish-docker` job and `action.Dockerfile` itself both still
  exist, now explicitly standalone (no longer feeding `action.yml`'s
  own `runs.image`, since there is no longer one). README updated to
  match.
  - **A ninth real bug, caught on the very first real CI run of this
    conversion:** the plumbing env vars were first named `CIBMP_*`
    (`CIBMP_PACKAGE_DIR`, `CIBMP_OUTPUT_DIR`, ...) -- and collided
    outright with `cibuildmp`'s own real, pre-existing, documented
    `CIBMP_<KEY>` config-override convention (`options.py`'s own
    `opt()`, the same mechanism `CIBMP_VERSION`/`CIBMP_CACHE_PATH` already
    use, checked *before* the config file and before any default).
    GitHub Actions always sets a step's own `env:` vars, even for an
    empty-string input, so every push silently exported
    `CIBMP_OUTPUT_DIR=""` -- and `opt()`'s own `environ.get(...) is
    not None` check has no way to tell "empty" from "unset", so it
    read that as an explicit override, replacing `DEFAULT_OUTPUT_DIR`
    ("mpyhouse") with nothing. Every natmod example built
    successfully (`cibuildmp: 10 target(s) built`,
    `cibuildmp: 7 target(s) built`) but collected its own output one
    directory too high (`examples/template/mpy6.3-natmod-x64/...`
    instead of `examples/template/mpyhouse/mpy6.3-natmod-x64/...`) --
    the mismatch only surfaced on the unrelated "List built artifacts"
    step, `ls: cannot access 'examples/template/mpyhouse': No such
    file or directory`. Confirmed live, both the reproduction and the
    fix: `CIBMP_OUTPUT_DIR=""` in the environment resolves
    `Options.load()`'s own `output_dir` to `Path('.')`; unset, or
    renamed to `ACTION_OUTPUT_DIR`, it correctly resolves to
    `Path('mpyhouse')`. Fixed by renaming every one of this step's own
    plumbing vars to an `ACTION_*` prefix, which cannot collide with
    any real `cibuildmp.toml` key, present or future.
  - **Still not yet done:** `--platform usermod` still always builds
    on the bare host inside this new composite action too -- there is
    no flag or config key yet that makes a caller's own build actually
    go through one of the `unix-manylinux-*` images as a sibling
    container (migration step 2's own resolver exists now, but nothing
    calls it with an image registered -- `PORT_IMAGES` is still empty).
    This remains the single largest gap before the `unix` slice is a
    real, usable feature rather than a proof-of-concept -- step 1 only
    removed the *structural* blocker (Docker-in-Docker), it did not yet
    wire the mechanism through.
- `resources/docker/windows.Dockerfile` also now exists (migration step
  3's first item -- one combined x64+x86 image, the two apt-installed
  mingw-w64 GCC packages `build_windows()` already proves work for this
  port; `arm64` stays bare-host-only until step 4 gives `dockerrun.py`
  real mount coverage for `sources.cache_root()`, where `llvm-mingw`
  downloads). Not split per arch the way `unix` is -- this port has no
  manylinux/musllinux-shaped axis, so the isolation argument for
  splitting `unix` doesn't carry over. Same open verification gap as
  every `unix-manylinux-*` image: not yet built for real via `docker
  build` (no reachable Docker daemon in the sandbox this was written
  in) -- correctness inferred from matching `action.Dockerfile`'s own
  already-proven package list for this exact port/arch pair, not yet
  confirmed independently. `build-examples.yml` now has a
  `verify-docker-images` job (matrix over all six Dockerfiles) that
  build-only `docker build`s each of them on every push -- no publish,
  no GHCR credentials, independent of `publish.yml`'s own `v*`-tag-gated
  `publish-docker` job -- closing this specific gap for real the moment
  it runs, not just documenting it as open.
- All six Dockerfiles live under `src/cibuildmp/resources/docker/`, not
  a top-level `docker/` directory -- moved there mid-session, on the
  user's own correction, once it was pointed out that a top-level
  `docker/` never shipped in the installed package at all
  (`pyproject.toml`'s own `package-data` only listed
  `resources/*.toml`). Real package resources now, the same as
  `natmod.toml`/`usermod.toml` already are -- `package-data` extended
  to `resources/docker/*` to match, verified live by building a real
  wheel and confirming all six files land inside it.
- `qemu`/`webassembly`/`esp32` still have no Dockerfile of their own at
  all yet.
- `action.yml`'s own apt-prerequisites step also now caches
  `/var/cache/apt/archives` via `actions/cache@v4.3.0` (pinned by
  commit SHA, verified live against a real `git ls-remote --tags` on
  `actions/cache` before pinning, not guessed), keyed on this file's
  own hash so a future package-list change busts the cache
  automatically. Orthogonal to the Docker migration above and not
  waiting on it -- the user's own observation, directly: this step is
  the slow part of every run today, independent of *which* toolchains
  it installs.
  - **A real bug, caught live by directly asking "did this actually
    help" rather than assuming it did -- the cache never saved even
    once.** `build`'s own duration got slightly *worse* after this
    landed (~355-365s before, ~410-415s after, both measured directly
    from real job timestamps), not better. Root-caused from real job
    logs, not guessed: every save attempt, on every run checked, failed
    with `Failed to save: Unable to reserve cache with key
    apt-archives-Linux-<hash>, another job may be creating this cache`
    -- and there is never a single "cache restored"/"cache hit" line
    for that key anywhere, on any of the (several, individually
    checked) runs this session pushed. The cause: seven commits landed
    in about 15 minutes, most sharing an unchanged `action.yml` (hence
    an identical hash-derived cache key), so multiple
    `build-examples.yml` runs raced each other to reserve+save it.
    **Not just simple two-run overlap, checked and ruled out as the
    whole story**: one run (`3f66aa6`) still failed all three of its
    own save attempts even though its own save-phase timestamps don't
    clearly overlap any single other run's own save phase -- consistent
    with GitHub's own cache API leaving a *stuck* reservation (a
    `reserve` that never reaches a completed `commit`, from an earlier
    run in the same pileup) rather than every failure being a clean
    two-way race at that exact instant. (Also confirmed separately:
    `action.yml`'s own composite action runs 3 times *within* one
    `build` job -- template/wasm2mpy/usermod-unix -- each with its own
    identical-keyed "Cache apt archives" step; harmless on its own,
    since only the first of the three needs to actually win the save
    and the other two would see the key already exists and skip
    cleanly -- but every one of the three failed here too, on every run
    checked, which is itself part of what points at a stuck reservation
    rather than a plain race.) **Fix attempted**: `build-examples.yml`
    and `usermod-dev.yml` both now have a real `concurrency:` block
    (`group: <workflow>-${{ github.workflow }}-${{ github.ref }}`,
    `cancel-in-progress: true`), the same pattern `publish.yml` already
    used -- a superseded run on the same branch gets cancelled outright
    instead of racing the newer one, live-confirmed to actually cancel
    a run (`3c1b389`'s own run was cancelled the moment `160a361` was
    pushed, and again when `160a361` itself was cancelled by `cf40ca5`
    moments later). **Confirmed the concurrency fix alone was not
    enough**: `cf40ca5` -- a completely clean run, nothing else active,
    nothing racing it -- still failed all three save attempts,
    identically. Conclusive, not just suspected: a later run's own
    *restore* (early in the job, before any same-job-save timing
    collision can even happen) never once found anything for this key
    either, across every run checked including `cf40ca5` -- if any save
    had genuinely completed at any point this session, some later run
    sharing that key would have hit it on restore. GitHub's own cache
    API documents no way to clear a stuck reservation directly, so the
    real fix was simpler: mint a fresh key. `action.yml`'s own cache
    key now has a `v2-` prefix (bump to `v3-`, etc. if this one also
    ends up stuck). **Confirmed fixed, real log evidence**: the very
    next run (`4837c58`) logged `Cache saved with key:
    v2-apt-archives-Linux-<hash>` on its own first of three save
    attempts -- the other two got the same "another job may be creating
    this cache" message, but this time it's the genuinely benign case
    (already saved earlier in the same job, moments prior), not a stuck
    reservation. This closes the apt-cache saga for real: the mechanism
    itself was always sound, the specific key it landed on this session
    just got stuck by a self-inflicted pileup of rapid pushes. The next
    real push after this one is the first that can show an actual
    restore/hit, still worth a glance but no longer in doubt.

**The full migration plan, in dependency order -- reordered from the
first pass above, per the user's own explicit follow-up.** The
original order built all five Dockerfiles before touching `action.yml`
at all; now that the Docker-daemon-reachability question is answered
(confirmed live, see the former "open question" below, now resolved)
and Docker is a required dependency rather than an optional path
(point 2 above), there is no more reason to keep writing Dockerfiles
nobody can reach yet -- wiring the mechanism through first, proven on
the one port (`unix`) that already has a real image, unblocks every
port after it and gives each new port a working end-to-end path the
moment its own Dockerfile lands, rather than five unreachable images
followed by one big wiring pass at the end.

1. **`action.yml` stops being a Docker action, becomes a composite
   action.** Moved first: this is the actual blocking gap ("not yet
   wired into the CLI or `action.yml` at all," the largest one flagged
   in this plan's own "current state" above), and nothing about it was
   waiting on more Dockerfiles existing -- `unix`'s own image already
   proves the mechanism. `runs: using: "docker"` → `runs: using:
   "composite"`, steps: ensure `cibuildmp` is installed on the runner
   (`uv tool install` from a pinned ref or, once GHCR-published images
   exist, possibly nothing at all if a future release ships a
   self-contained binary -- not decided, flag it as an open question
   rather than assuming), then invoke it directly. `entrypoint.sh`'s
   own input-parsing logic (the `INPUT_PACKAGE-DIR` etc. env-var
   reading, including the documented bash-not-dash requirement) moves
   into a composite action's own `run:` step -- and this is not just a
   move, it genuinely simplifies, confirmed against `pypa/cibuildwheel`'s
   own real `action.yml` (the user supplied its actual source directly,
   not a description of it): a composite action's own step-level
   `env:` block maps `${{ inputs.package-dir }}` to *any* env var name
   the step chooses, e.g. `INPUT_PACKAGE_DIR` with an underscore --
   cibuildwheel's own action does exactly this. That sidesteps
   `entrypoint.sh`'s whole `printenv 'INPUT_PACKAGE-DIR'` workaround
   entirely, not just moves it: the hyphen problem only exists because
   a *Docker* action's auto-generated `INPUT_<NAME>` env vars keep the
   input's own hyphens verbatim (undocumented by GitHub, found the hard
   way, `entrypoint.sh`'s own header comment has the full story) --
   nothing forces a composite action's own `env:` block to reuse that
   same broken naming, so the new composite `action.yml` should define
   clean, underscored env var names explicitly from the start rather
   than reproducing the workaround.
   - Two more real patterns worth deliberately deciding on, not just
     copying, from that same cibuildwheel `action.yml`: it builds an
     **isolated venv** per run (`venv.EnvBuilder`, installed into
     `$RUNNER_TEMP`) and exposes only the `cibuildwheel` binary (plus
     `uv` if requested via `extras`) on `PATH`, rather than a plain
     `pip install`/`uv tool install` into whatever Python the runner
     already has -- avoids polluting a job's own Python environment
     with `cibuildmp`'s own dependencies, relevant since composite
     actions run directly on the bare runner (unlike today's Docker
     action, where the whole container is disposable and pollution
     never mattered). Decide deliberately whether `cibuildmp` needs
     the same isolation or whether `uv tool install`'s own existing
     isolation (already a separate venv under `~/.local/share/uv/tools`,
     not the runner's system Python) already covers it -- plausibly
     yes, worth confirming rather than assuming either way.
   - It also branches explicitly on `runner.os == 'Windows'` (`pwsh`
     vs `bash`, quoting rules genuinely differ) -- irrelevant to
     `cibuildmp` today (Linux-runner-only, per the open questions
     below), but exactly the shape this migration would need to
     extend into if the Windows/macOS open question ever resolves
     towards "yes."
2. **The Docker-image resolver becomes real -- done, refined twice.**
   `usermod/dockerrun.py` now has `PORT_IMAGES: dict[str, str]`, a
   maintainer-owned mapping in the module's own source, plus
   `image_for(port, arch, libc=None)` checking
   `CIBMP_<PORT>_<ARCH>[_<LIBC>]_DOCKER_IMAGE` first (override) and
   falling back to `PORT_IMAGES` (the registered default). This is the
   literal shape of the user's own framing: adding a new port's support
   becomes "write one Dockerfile, then declare it in the resolver" -- a
   one-line addition to `PORT_IMAGES`, a maintainer editing source, not
   an end user's `cibuildmp.toml`.
   - **A real misunderstanding, caught and corrected before any wrong
     code shipped.** The first pass at this step started down a
     config-file path instead -- threading a `docker-image` key through
     `[usermod.<port>]` in `cibuildmp.toml`, `UsermodOptions.load()`, and
     a new field on `UnixBuildOptions`, on the theory that "declare it in
     the resolver" meant an end user's own config declaring which image
     to use. The user stopped this immediately: *"Стоп при чому тут
     конфіг???????"* / *"Я думав ми постачатимемо Dockerfile's для
     портів а не юзер через конфіг додаватиме"* (I thought **we** would
     ship the Dockerfiles for the ports, not that the user adds them via
     config) -- "the resolver" is `dockerrun.py`'s own Python source;
     "declare" means a maintainer registers a port's image there when
     its Dockerfile lands, the same way `UNIX_ARCH_SETTINGS` in
     `usermod/build.py` is itself a maintainer-owned dict, not a config
     surface. No `Edit`/`Write` had happened yet under the wrong
     reading -- caught at the investigation stage, corrected.
   - **Refined again, same session: keyed by `(port, arch)`, not `port`
     alone.** First implemented as `image_for_port(port)`/
     `PORT_IMAGES.get(port)`; the user then pointed out `unix.Dockerfile`
     itself was the wrong shape ("це херня, я думав ми наріжемо
     manylinux-x64 muslinux-aarch64 тощо") -- cibuildwheel's own
     per-(arch, libc) image shape, not one combined `unix` image (this
     decision's own amendment above, **D31**). Re-implemented as
     `image_for(port, arch, libc=None)`, `PORT_IMAGES` keyed
     `"{port}-{arch}"` or `"{port}-{arch}-{libc}"` -- `libc` stays
     optional (not defaulted to `"manylinux"`) so `windows`/`qemu`/
     `webassembly`/`esp32`, none of which have any libc axis at all,
     never carry a meaningless label; only `build_unix()` passes
     `"manylinux"` explicitly, `unix`'s own only real value today.
     `tests/test_usermod_dockerrun.py` covers six cases (no override +
     no registration → host build; registered default used; env
     override wins; an unregistered arch stays a host build even when a
     sibling arch is registered; an unregistered port stays a host
     build; `libc` omitted uses a two-part key/env name, not a
     `"manylinux"` stand-in). `PORT_IMAGES` stays empty until step 5
     actually publishes a pullable image for at least one `(port, arch)`
     pair -- registering one before that would break every unopted-in
     build for that exact pair the moment this step lands, not just
     when the port's own Dockerfile does.
3. **The remaining three per-port Dockerfiles, one at a time, each
   immediately usable the moment it lands** (step 1 and 2 already
   wired the mechanism, so this stops being "write five images, then
   wire them all at the end"). Any `resources/docker/unix-manylinux-*.Dockerfile`
   is the template to copy for a port with no libc axis (just drop the
   trailing `-<arch>` split unless the port genuinely needs it the way
   `unix` does): only that port's own toolchain, no `cibuildmp` baked
   in. `windows` was next -- apt-only toolchain, no large download like
   `esp32`'s ESP-IDF or `webassembly`'s emsdk, closest in shape to
   `unix` (**D26**'s own "first slice" precedent: one port, proven
   live, before the next).
   - **`resources/docker/windows.Dockerfile` -- written.**
     `gcc-mingw-w64-x86-64`/`gcc-mingw-w64-i686` only; `arm64` downloads
     `llvm-mingw` at build time regardless (`usermod/llvmmingw.py`),
     same as today. Not registered in `PORT_IMAGES` -- same as `unix`,
     not yet published (step 5), and not yet confirmed via a real
     `docker build` (see "current state" above).
   - **`resources/docker/qemu.Dockerfile` -- written, one combined
     image (no `unix`-style per-arch/libc split -- `qemu` only ever
     targets one board, `MPS2_AN385`, and a bare-metal ELF has no
     libc/musl axis at all).** Package list confirmed against two real
     sources, not memory (this bullet's own original instruction): (1)
     `o-murphy/a7p`'s own real `mp-usermod.yml`, whose
     `usermod-qemu-armv7m` job installs the toolchain via
     `cibuildmp/.github/actions/build-usermod-armv7m` --
     `gcc-arm-none-eabi libnewlib-arm-none-eabi`, `qemu-system-arm`
     installed separately, in the *caller's* own job, explicitly not a
     build dependency ("QEMU itself is deliberately NOT installed here:
     it is a runtime emulator... not a build dependency"); (2) this
     project's own `resources/natmod.toml`'s `arm-none-eabi` toolchain
     entry, whose `apt-packages` field is the identical string --
     `build_qemu()` already resolves this exact toolchain via
     `toolchains.resolve("armv7m")`, whose own "auto" strategy checks
     PATH before ever downloading the pinned xpack tarball, so
     apt-installing it here needs no code change to `build_qemu()` at
     all for this image to be usable. `qemu-system-arm` (the
     *execution* axis, **D21**) deliberately stays out of this image,
     matching `a7p`'s own split exactly -- registered in
     `verify-docker-images`'s own matrix, so it now builds (and
     publishes, on a real push) for real like every other Dockerfile
     here, not left open as a documented gap.
   - **`resources/docker/webassembly.Dockerfile` -- written, emsdk
     baked in.** A first pass here mounted emsdk from the host's own
     `sources.cache_root()` instead, on reasoning that does not
     actually hold: a Dockerfile `RUN` step's own output is a real
     image layer, reused unchanged by every later `docker run --rm`
     (only the ephemeral *container* is discarded per run, never the
     *image* a `RUN` step wrote into) -- there was never a
     "redownloads every run" problem baking in would have caused,
     unlike unix's own apt packages this reasoning was supposed to
     mirror. Asked the user directly once the real tradeoff (image
     size, not correctness) was clear: the extracted emsdk here is
     ~1.5GB, measured live via a real download + `tar tJf`, not
     guessed -- baking it in duplicates that download against
     `resolve_emsdk()`'s own bare-host cache rather than sharing one
     copy the way a mount would, but needs no `dockerrun.py`
     mount/PATH-injection support at all (a plain `ENV PATH` in the
     Dockerfile is enough) and ships a genuinely self-contained image
     the moment `docker build` finishes, consistent with every other
     image here. Baking in won. The pinned URL/sha256 (transcribed from
     `resources/usermod.toml`'s own `[emsdk]` table, `version =
     "6.0.8"`) was verified live before pinning -- downloaded for real,
     `sha256sum -c`'d, and its own internal `tar tJf` layout confirmed
     (a top-level `install/` containing `install/emscripten/` and
     `install/bin/`, exactly what `ResolvedEmsdk.env()` already
     expects) rather than assumed from the tarball's name. Real,
     live-checked finding while writing this: `ports/webassembly/Makefile`
     also declares `TERSER`/`NODE` (`npx terser`, for `.min.mjs`) --
     but only the `min`/`repl`/`test` targets touch them, never the
     default `all` target `webassembly_make_command()` always builds,
     so Node.js/npm are deliberately not installed here at all, not an
     oversight.
   - `resources/docker/esp32.Dockerfile` -- the heaviest one: ESP-IDF itself is
     a multi-gigabyte checkout with its own Python env bootstrap
     (`usermod/espidf.py`). Worth deciding explicitly whether ESP-IDF
     bakes into the image (large image, fast job) or stays a
     download-at-build-time step (small image, slow first job, cache
     shared across jobs via the cache strategy below) -- a real
     tradeoff, not an oversight, and should get its own one-paragraph
     decision when this Dockerfile is written, not silently default
     one way.
4. **`usermod/dockerrun.py` grows real mount coverage -- probably only
   for `esp32`, revised from the original three-port scope below once
   its own reasoning turned out flawed.** Originally written as: every
   port whose toolchain is a downloaded tarball rather than an apt
   package (`windows/arm64`'s `llvm-mingw`, `webassembly`'s `emsdk`,
   `esp32`'s `esp-idf`) would need `sources.cache_root()` bind-mounted
   into its container at *run* time, "or the image rebuilds/redownloads
   every single run." **That premise is wrong** -- caught while
   actually writing `webassembly.Dockerfile`: a Dockerfile `RUN` step's
   own output is a real image layer, reused unchanged by every later
   `docker run --rm` (only the ephemeral *container* is discarded per
   run, never the *image* a `RUN` step wrote into), so there was never
   a correctness reason to avoid baking a downloaded toolchain straight
   into the image the way `unix`'s own apt packages already are.
   `webassembly.Dockerfile` now bakes `emsdk` in directly (see "current
   state" above) -- no mount, no `dockerrun.py` changes needed at all
   for that port. The only real reason left to ever prefer mounting
   over baking is image size / avoiding a duplicate download between
   the host's own cache and the image layer (`emsdk`'s own ~1.5GB,
   measured live, was judged worth baking in anyway, on the user's own
   call) -- `windows/arm64`'s `llvm-mingw` is almost certainly small
   enough that the same call goes the same way when that arch's own
   Dockerfile coverage is written (not attempted yet -- `windows.Dockerfile`
   still explicitly excludes `arm64`). `esp32`'s `esp-idf` is the one
   case genuinely large enough (multi-gigabyte) that this decision
   still needs making deliberately rather than assumed either way --
   see its own bullet in step 3. If `esp32` does end up mounted rather
   than baked, this step is exactly that: `dockerrun.py` grows real
   mount coverage for `sources.cache_root()`, and `build_esp32()` needs
   its own docker-image-selection branch added alongside
   `build_unix()`'s existing one (`build_windows()`/`build_webassembly()`
   need no such branch for this reason any more -- both bake their own
   toolchain, `webassembly` already does, `windows/arm64` almost
   certainly will too). If `esp32` also ends up baked, this step may
   turn out to have nothing left to do at all -- genuinely open until
   that Dockerfile is written and its own tradeoff decided.
5. **`publish.yml`'s existing `publish-docker` job extends from one
   image to six** -- the job already exists (`docker/build-push-action`
   with `cache-from/cache-to: type=gha`, pushing
   `ghcr.io/ballistics-lab/cibuildmp:<tag>`/`:latest`); it needs a
   matrix over the six Dockerfiles (`unix-manylinux-x64`/`x86`/
   `aarch64`/`armhf`/`mipsel`, `windows`), pushing
   `ghcr.io/ballistics-lab/cibuildmp-<port>[-<arch>][-<libc>]:<tag>`/`:latest`
   each. Note the existing job's own comment: `action.yml` does not
   even consume this published image today -- it rebuilds
   `action.Dockerfile` from source on every single consuming job,
   across every repo, forever. That gap should very likely close in the
   same pass as this migration (composite `action.yml` pulls the
   pinned per-port image by default), not stay open a second time.
   - **Real correctness gap in this trigger, caught by the user's own
     question -- resolved, but not the way this bullet first
     described.** Copying `publish-docker`'s own trigger as-is (`if:
     github.event_name == 'push'`, and `publish.yml`'s only `push:`
     trigger is `tags: v*`) would mean per-port images publish *only*
     on a real release tag. But `cibuildmp` itself installs from
     `$GITHUB_ACTION_PATH` fresh on every ref (`uv tool install`
     already gives this reproducibility for the Python side) -- once
     `PORT_IMAGES` actually references a GHCR tag, a consumer on
     `@main` or any commit SHA that isn't an exact release tag would
     hit a real code/image mismatch: `dockerrun.py`'s own registered
     tag either doesn't exist yet, or points at a stale image built
     from an older Dockerfile. First asked directly and answered "leave
     this as a TODO, don't wire real pushes yet" -- then revised in the
     same session once the actual cost of that became concrete: without
     a real, currently-pullable image, `PORT_IMAGES` can never be
     exercised end to end on a dev branch at all, and waiting for a
     real release just to prove the mechanism this decision exists to
     build isn't reasonable ("щоб не чекати по пів року").
     **Implemented, in `build-examples.yml`'s own `verify-docker-images`
     job, not `publish.yml`** -- every `push:` event (never
     `pull_request`, so a fork's own PR never needs registry
     credentials) now also pushes each Dockerfile that builds green to
     `ghcr.io/ballistics-lab/cibuildmp-<dockerfile>:sha-<gitsha>`,
     `docker/build-push-action` with `cache-from/cache-to:
     type=gha,scope=<dockerfile>` (per-leg cache scope, so one image's
     rebuild can't invalidate another's). Deliberately `:sha-<gitsha>`
     only, no `:latest` -- a shared mutable tag across arbitrary
     branches would let one branch's push silently clobber what another
     branch, or a real release, expects `:latest` to mean; a real
     stable `:vX.Y.Z`/`:latest` alias still belongs to `publish.yml`'s
     own release-tag-gated job specifically, not here -- so this step's
     own "extends from one image to six" work above is still real,
     separate work, not superseded by this. `PORT_IMAGES` itself is
     still empty -- this only makes a real image reachable by an exact
     sha tag; registering one as every unopted-in caller's default is a
     separate, deliberate step once a specific `(port, arch[, libc])`
     combination has actually been proven end to end through
     `dockerrun.run()`, not just built.

**Cache strategy -- the direct answer to "we need a `CIBW_CACHE_PATH`
equivalent," in two genuinely separate parts.** cibuildwheel's own
`CIBW_CACHE_PATH` covers two different things at once (downloaded
build dependencies, and pulled container images); cibuildmp already
has a real answer for the first and needs a deliberate one for the
second -- conflating them would be a mistake.

1. **Toolchain/source cache -- already exists, `CIBMP_CACHE_PATH`.**
   `sources.cache_root()` (`src/cibuildmp/sources.py`) already reads
   `CIBMP_CACHE_PATH`, falling back to `$XDG_CACHE_HOME/cibuildmp` or
   `~/.cache/cibuildmp` -- this *is* the direct analogue of
   `CIBW_CACHE_PATH` for MicroPython checkouts, `mpy-cross`, and every
   downloaded toolchain (`toolchains.py`, `llvmmingw.py`, `emsdk.py`,
   `espidf.py` all resolve under it). Nothing new needs inventing
   here. What genuinely is new, for the migration:
   - Every sibling container needs the *right* subset of
     `cache_root()` bind-mounted in (see migration step 2 above) --
     today only `unix` is exempt from needing this at all.
   - `mpy-cross` itself should keep building on the bare host, not
     inside any per-port container -- it is architecture-independent
     shared infrastructure (`sources.build_mpy_cross()`, called once
     per `orchestrate.build()` invocation, before the per-target loop
     starts), not a port-specific toolchain artifact. Do not move it
     into a container "for consistency" -- there is no real reason to,
     and it would need its own image otherwise.
   - In CI, once `action.yml` is a composite action (migration step
     3), a caller gets to add a completely ordinary `actions/cache`
     step over `~/.cache/cibuildmp` (or wherever `CIBMP_CACHE_PATH` points)
     around the `cibuildmp` invocation -- something a Docker action
     structurally cannot offer at all today (GitHub's Docker-action
     mechanism has no way for a caller to mount a volume into the
     container it creates; the composite-action conversion is what
     actually unlocks this, not a new cache mechanism of its own).
     Document this prominently in README once it's real: it is the
     single biggest CI speed win this whole migration produces,
     independent of the isolation motivation.
2. **Docker image cache -- new, needs a real design, currently only
   half-built.** Two related but distinct things:
   - *Building* a per-port image already has a real cache
     (`publish.yml`'s own `cache-from/cache-to: type=gha`, GitHub's
     own Actions cache backend, persists across workflow runs in this
     repo) -- extending this to five images (migration step 5) is
     mechanical, the pattern is already proven.
   - *Consuming* a per-port image (any caller's own `uses:
     ballistics-lab/cibuildmp@vX` build) should default to `docker
     pull`ing the pinned GHCR tag, which benefits from the registry's
     own layer cache automatically -- no extra configuration needed,
     the same way any other published Docker image works. This is
     where `CIBMP_<PORT>_DOCKER_IMAGE` becomes a real, documented
     *override* (build your own local image, or pin an older
     release's image) rather than the only way in.
   - **Genuinely open, not yet decided:** should there be a
     `CIBMP_DOCKER_CACHE`-style env var at all, analogous to
     `CIBW_CACHE_PATH`'s own directory, for a self-hosted runner or a
     laptop that wants pulled images to live somewhere specific (not
     Docker's own default storage driver location)? `docker`'s own
     `--data-root` / `daemon.json` already covers this at the daemon
     level, arguably making a cibuildmp-specific env var redundant --
     lean towards *not* inventing one unless a concrete need surfaces,
     but flag it explicitly here rather than silently deciding either
     way.

**Risks and open questions to resolve before or during implementation,
not after:**

- ~~Can a GitHub-hosted runner's own Docker daemon actually be reached
  from a composite action's plain shell step~~ -- **resolved, confirmed
  live on real CI, not just reasoned about:** a throwaway diagnostic
  job (`composite-action-docker-reach-check`, `usermod-dev.yml`, no
  `uses: docker` anywhere) ran a plain `docker info` and `docker run
  --rm hello-world` directly in an ordinary `run:` step on
  `ubuntu-latest`. Both worked immediately, no setup step of any kind:
  `docker info` reported a real, already-running daemon (Docker Engine
  28.0.4, `overlay2`, `runc`), and `docker run --rm hello-world`
  genuinely pulled the image from Docker Hub and printed its own real
  "Hello from Docker!" banner. Confirms the entire premise this
  migration's composite-action step depends on: GitHub-hosted runners
  really do ship a live, reachable Docker daemon with zero container
  boundary in the way, for any plain step, not just inside a Docker
  action's own container. The diagnostic job has been removed
  (`usermod-dev.yml`) now that its answer is folded in here.
- Self-hosted runners without Docker at all (mentioned nowhere in this
  session, but a real category of `cibuildmp` user going forward) lose
  the per-port image path entirely under this design. **Decided, below
  under this same decision's usermod bullet: fail loudly, no bare-host
  fallback** -- Docker is a hard requirement for usermod, not an
  optional one with a silent fallback.
- Windows/macOS runners: **D2/M2**'s own "why not docker for x86"
  reasoning, and the open question already in this document's own
  "Windows/macOS hosts" entry, both predate this plan -- a per-port
  *Linux* container obviously cannot run on a bare Windows/macOS
  runner at all, so this migration is implicitly Linux-runner-only
  unless and until that open question resolves separately.
- This is genuinely large, multi-session work -- five Dockerfiles, a
  real `action.yml` rewrite affecting three consuming repos'
  workflows, `publish.yml` extended, `dockerrun.py` mount coverage for
  four more ports, `docker`-strategy branches in four more
  `build_<port>()` functions, README's own Docker section rewritten.
  Do not attempt it in one sitting; **D26**'s own "first slice"
  precedent (one port, proven live, before committing to the rest) is
  the right shape to keep following -- `windows` is the natural next
  slice (apt-only toolchain, no large download like `esp32`'s
  ESP-IDF or `webassembly`'s emsdk, closest in shape to `unix`).

**Superseded by D33: the "cibuildmp calls `docker build` itself" default
this entry introduces is exactly what D33 later removed. Kept as the
real record of how that design was reached and load-bearing-tested, not
as the current mechanism.**

**D32 — closing D28's own "one real gap": `unix` usermod now defaults to
Docker whenever cibuildmp ships that arch's own Dockerfile, instead of
requiring an explicit override or a maintainer-registered `PORT_IMAGES`
entry first.** The user's own framing, directly: cibuildmp should call
`docker` itself and build (or reuse a local cache of) its own packaged
Dockerfile when nothing more specific is named, the same way
cibuildwheel defaults every manylinux/musllinux identifier through its
own pinned container rather than treating a container as an opt-in
fallback for a host missing packages.

`usermod/dockerrun.py`'s `image_for()` stays the pure, side-effect-free
lookup (env override, then `PORT_IMAGES`) it always was -- `arch` is now
optional there too, so a no-axis port (`qemu`/`webassembly`) can resolve
a key with no dangling `-` segment. A new `ensure_image()` wraps it with
a third fallback: if neither an override nor a registered default is
set, but cibuildmp ships this `(port, arch[, libc])`'s own Dockerfile
(`_DOCKERFILES`, mirroring the five `unix-manylinux-*` plus
`windows`/`qemu`/`webassembly` files already on disk from D28's own
migration), it builds that image and returns the tag -- relying on a
cache for "reuse if already there" rather than reinventing one, in
whichever of two shapes actually applies:

- **On a laptop**, a plain `docker build -f <packaged Dockerfile> -t
  cibuildmp-<key>:local <dockerfile's own dir>`. Docker's own local
  image/layer cache already gives "build once, instant no-op rebuild
  until the Dockerfile changes" for free -- nothing to add.
- **Inside any GitHub Actions job** (`GITHUB_ACTIONS=true`, set by the
  runner itself, not an opt-in) -- a fresh VM on every run, with no
  local layer cache persisting between them at all -- `docker buildx
  build --cache-from type=gha,scope=<dockerfile stem> --cache-to
  type=gha,mode=max,scope=<dockerfile stem> --load`, first switching to
  (creating if needed) a `docker-container`-driver builder named
  `cibuildmp`: the classic default `docker` driver does not support the
  `type=gha` cache exporter/importer at all. The scope string is
  deliberately the packaged Dockerfile's own stem (`unix-manylinux-x64`,
  not `ensure_image()`'s own `key`, which additionally folds in the
  libc segment `unix` alone carries) -- the same string
  `build-examples.yml`'s own `verify-docker-images` job already uses for
  its matrix leg, so this fallback can land in (and, on a cache hit,
  read from) the exact cache lineage that job populates, not a disjoint
  one that happens to also say `type=gha`. This is the direct answer to
  "will this work for other repos, not just this one": a consumer who
  writes nothing but a `cibuildmp.toml` and `uses: cibuildmp@vX` in
  their own workflow gets real cross-run image caching in their own CI
  too, from nothing they had to set up themselves -- matching D2's own
  framing (cibuildmp owns provisioning) rather than leaving every
  consumer to reinvent build-examples.yml's own cache wiring by hand.

Returns `None` only where cibuildmp genuinely
ships no Dockerfile at all yet (`windows/arm64`, `esp32`), which still
falls all the way through to a bare host build exactly as before.
**Stale as of the Docker-only call above (this document's own D30):**
that bare-host fallback is scheduled for removal in favour of a hard
error, not left as the permanent answer for a missing Dockerfile.
`build_unix()` now calls `ensure_image()`, not `image_for()` directly --
the only call site changed this round; `windows`/`qemu`/`webassembly`
own Dockerfiles exist and are in `_DOCKERFILES` too, but their
`build_windows()`/`build_qemu()`/`build_webassembly()` are not wired to
call `ensure_image()` yet, since none of them has a real example project
this repo's own CI exercises the way `examples/usermod-unix` does for
`unix` (**D26**'s own "one port, proven live, before the next"
precedent) -- wiring them blind, with no real build ever run through
them, is the wrong order.

**`webassembly` landed next, following exactly that precedent.**
`examples/usermod-webassembly` (a trivial `USER_C_MODULES` module,
mirroring `examples/usermod-unix`'s own `mymod`) plus a
`build-usermod-webassembly` job in `build-examples.yml`, `needs:
verify-docker-images`, same shape as `build-usermod-unix`'s own job
(env-var override pointed at the pushed `ghcr.io/.../cibuildmp-webassembly:
sha-<gitsha>` tag on a push, empty on a `pull_request` so
`ensure_image()`'s own local-build fallback runs instead). No per-arch
matrix needed -- `webassembly` has no axis at all, one combined image.
`build_webassembly()` now calls `ensure_image("webassembly")` and
`dockerrun.run()` directly, with no bare-host branch at all (unlike
`build_unix()`'s still-conditional shape): `webassembly` ships a
Dockerfile with emsdk already baked in, so `ensure_image()` never
returns `None` for it, and this decision's own Docker-only call (D30)
means there is nothing for a bare-host branch to fall back to any more.
A `docker_image is None` guard still exists, but only as the hard,
clearly-worded error this document's own "concrete follow-up" note
(under D30's usermod bullet) called for -- not a fallback path.
`emsdk.resolve_emsdk()`'s bare-host call is gone from this function
entirely: the image's own baked-in `ENV PATH` covers what `sdk.env()`
used to inject, so `usermod/emsdk.py` now only pins what the packaged
Dockerfile's own `RUN` step downloads at image-build time, verified by
running the real CLI against `examples/usermod-webassembly` in this
session's own sandbox: `--dry-run` needed no Docker at all (confirming
the earlier "scoped to an actual build only" note holds), and a real
(non-dry-run) build reached `ensure_image()` and failed with a clean,
expected `docker build ... failed with exit code 1` /
`failed to connect to the docker API` message -- this sandbox has no
reachable Docker daemon (same limitation `unix-manylinux-x64.Dockerfile`'s
own header already records), so the actual image build and `make`
invocation are proven live in this repo's own CI
(`build-usermod-webassembly`), not locally. All 253 tests pass, `ruff
check`/`ruff format --check` clean, `pyright` 0 errors.

**A real caching conflict, caught before it shipped, not after.** Naively
wiring `ensure_image()` into `build_unix()` and leaving
`build-examples.yml` untouched would have meant `build-examples.yml`'s
own `build` job -- a separate job, on a separate runner, from
`verify-docker-images` -- redoing all five `unix-manylinux-*`
`docker build`s from a cold layer cache on every single push, duplicating
work `verify-docker-images` already does *with* a real cache
(`cache-from`/`cache-to: type=gha`) and already pushes to GHCR moments
earlier in the same workflow run. Two jobs, two runners, no shared Docker
daemon: nothing about `ensure_image()`'s own plain `docker build` call
could have reached that cache by accident. Fixed by splitting
`usermod-unix` out of `build` into its own `build-usermod-unix` job
(`template`/`wasm2mpy` have nothing to do with any of this and stay
independent), `needs: verify-docker-images`, with the five
`CIBMP_UNIX_<ARCH>_MANYLINUX_DOCKER_IMAGE` env vars pointed at the exact
`ghcr.io/.../cibuildmp-unix-manylinux-<arch>:sha-<gitsha>` tags
`verify-docker-images` just built and pushed -- so `image_for()`'s own
override wins immediately and `ensure_image()`'s local-build fallback
never triggers in this repo's own CI at all, on a push. This is also,
finally, the real end-to-end proof D28's own handoff called the "one
real gap": a real `usermod-unix-x64` (and the other four arches) build
running *through* `dockerrun.run()` against one of these pushed images,
not just `docker build`/`docker push` succeeding. On a `pull_request`
run those five env vars stay unset (empty string, not absent --
`image_for()`'s own `if override:` check is truthiness-based, so this
does not repeat D28's own ninth bug where `ACTION_OUTPUT_DIR=""` read as
an explicit override), so `ensure_image()`'s local-build fallback runs
instead there -- slower, no GHA cache reachable from that job, but
correct, and exactly the path a consumer with no published image of
their own takes too.

**Two real bugs, both caught from actual CI logs, not guessed** (there is
no reachable Docker daemon in the sandbox this was written in -- `docker
info` fails to reach `/var/run/docker.sock` -- so every claim here is
checked against a real run, not local reasoning):

- The first push through this design broke 11 tests on real CI that
  passed locally. Root cause: `usermod dev`'s own "test" job runs
  `pytest` *inside a real GitHub Actions job*, where `GITHUB_ACTIONS=true`
  is genuinely set -- so any test reaching `ensure_image()`'s default path
  (no override, nothing registered) hit the real buildx+gha-cache branch,
  where `_ensure_buildx_container_builder()`'s own
  `subprocess.run(...).returncode` read broke against several
  pre-existing tests' bare `lambda *a, **k: None` stub for
  `subprocess.run` (fine before this branch existed, since nothing used
  to read a return value). Fixed with an autouse fixture
  (`tests/conftest.py`) clearing `GITHUB_ACTIONS` for every test by
  default, verified this time by running the suite locally both with and
  without `GITHUB_ACTIONS=true` set -- not just whichever one happened to
  match the sandbox's own ambient environment, which is exactly the gap
  that let this reach real CI at all.
- With that fixed, `build-usermod-unix`'s own override path (the
  `CIBMP_UNIX_*_MANYLINUX_DOCKER_IMAGE` env vars pointed at
  `verify-docker-images`'s freshly-pushed images) failed for real:
  `docker: Error response from daemon: ... unauthorized` pulling
  `ghcr.io/ballistics-lab/cibuildmp-unix-manylinux-x64:sha-<gitsha>`.
  `verify-docker-images` logs into `ghcr.io` before its own push;
  `build-usermod-unix` never did, so `dockerrun.run()`'s `docker run
  --pull missing` hit an unauthenticated pull against what GHCR treats as
  a private package by default, even for a package this same repository
  owns. Fixed by adding the same `docker/login-action@v3` step (`if:
  github.event_name == 'push'`, matching the env vars it unblocks) plus
  `permissions: packages: read` to `build-usermod-unix`.
- **A third real bug, this time a genuine link failure inside the
  actual usermod build**, not CI plumbing: `unix-aarch64` compiled
  clean but failed to link, `undefined reference to ffi_type_sint8` /
  `ffi_call` / `ffi_prep_cif` / etc. across every `modffi.c` symbol.
  Root cause: `resources/docker/unix-manylinux-aarch64.Dockerfile`
  installed only `libffi-dev:arm64`, not the plain (host/amd64)
  `libffi-dev` -- a real regression from **D26**'s own per-arch split,
  since the original combined `action.Dockerfile` always installed
  both together and nobody re-derived why. Plain `pkg-config` (no
  cross-wrapper) only searches its own build target's multiarch
  pkgconfig directory by default (`x86_64-linux-gnu` on this base
  image), never `aarch64-linux-gnu`'s -- with only the arm64 package
  present, `pkg-config --libs libffi`
  (`ports/unix/Makefile`'s own non-standalone `LIBFFI_LDFLAGS`
  resolution) silently resolved to nothing, so `-lffi` was never
  passed to the linker at all.
  - **A real self-inflicted repeat of this exact failure, caught
    immediately, not shipped twice.** The first attempt at this fix
    added a long, correct-sounding explanatory comment to the
    Dockerfile but never actually added the `libffi-dev` line the
    comment described -- pushed, and the identical CI failure
    reproduced, on the identical tag, because nothing had actually
    changed. Caught by reading the real CI logs again rather than
    assuming the fix landed because the diff looked right.
  - **Fixed for real this time, and verified live end to end in the
    sandbox before pushing again**, not just reasoned about: with
    `PKG_CONFIG_LIBDIR` pointed at nowhere (simulating "only
    `libffi-dev:arm64` installed, no host `.pc` reachable"), a real
    `aarch64-linux-gnu-gcc` compile+link reproduced the exact same
    `undefined reference to ffi_type_sint32`/`ffi_prep_cif` failure;
    with plain `pkg-config --libs libffi` resolving normally (the
    fixed state), the identical command linked clean, producing a real
    `ELF 64-bit ... ARM aarch64 ... dynamically linked` binary, and
    `readelf -d` confirmed its `NEEDED` entry is `libffi.so.8` -- the
    real, correct, arch-specific runtime dependency, not a baked-in
    host path. Fixed by actually re-adding the unqualified `libffi-dev`
    package this time: the aarch64 cross-linker's own default sysroot
    search path still finds and links the *correct* arm64 `libffi.so`
    once `-lffi` is present, regardless of which architecture's `.pc`
    file supplied the flag.
  - **A real, considered alternative, raised directly and checked
    against real source, not memory**: does `cibuildwheel` avoid this
    entire class of cross-toolchain bug? Confirmed live against a real
    `pypa/cibuildwheel` checkout (`oci_container.py`): yes -- it never
    cross-compiles from an x86_64 host at all. `docker run
    --platform=linux/arm64 <native manylinux2014_aarch64 image>`, via
    QEMU user-mode emulation (`binfmt_misc`, registered by a
    `docker/setup-qemu-action`-equivalent step, not present on a
    GitHub-hosted runner by default) runs a genuinely *native* aarch64
    container -- native `gcc`, native `libffi`, no multiarch apt
    sources, no foreign-arch packages, no `pkg-config` cross-arch
    mismatch possible at all, because nothing is cross-compiled.
    Switching `unix`'s own aarch64/armhf/mipsel images to this shape
    would very plausibly make their own Dockerfiles nearly identical to
    `unix-manylinux-x64`'s (just a different base image tag plus
    `--platform`), eliminating this entire bug category rather than
    patching each instance -- but it is a real, separate architecture
    change (QEMU setup in every workflow that runs these containers,
    including third-party consumers; `--platform` threaded through
    `dockerrun.py`'s own `run()`/`ensure_image()`; slower builds under
    emulation), not a drop-in fix for the specific failure above.
    **Deliberately not adopted now** -- raised mid-incident, while
    under real time pressure to get a concrete result rather than a
    bigger diff, and correctly deferred: swapping the architecture out
    from under five already-Dockerfiles that were otherwise working
    (four of five never even hit this bug) is a bigger, riskier change
    than the one-line fix above, and deserves its own deliberate
    decision later, not one made reactively mid-debugging. Flagged here
    precisely so a future session evaluates it as a real option rather
    than re-discovering cibuildwheel's own approach from scratch.

**D32's own end-to-end proof is now fully green, confirmed live, not
assumed**: `build-usermod-unix` succeeded for real (all 5 `unix`
arches, through `dockerrun.run()` against the exact
`ghcr.io/.../cibuildmp-unix-manylinux-<arch>:sha-<gitsha>` images
`verify-docker-images` just pushed moments earlier in the same run) --
alongside `build`, all 8 `verify-docker-images` legs, and
`usermod-dev.yml`, on the same commit. This is the actual close of
D28's own "one real gap": a real usermod build has now run *through*
the Docker path end to end, not just `docker build`/`docker push`
succeeding.

`windows`/`qemu`/`webassembly` wiring, and `PORT_IMAGES` actually being
registered (still empty -- `ensure_image()`'s local build is the thing
proving the path works at all now, registering a maintained default on
top of that is a separate, later step) remain open, same as D28 left
them.

**D29 — a real GitHub Actions job summary, the way cibuildwheel's own
action already does it: a table of what got built, visible directly on
the Action run's own page, not just buried in raw log lines. Done,
implemented while D28's own composite-action CI was running.** The
user's own explicit ask, independent of **D28**'s container-per-port
migration -- landed on its own, in parallel.

- **Implemented as designed below**, in a new standalone module,
  `src/cibuildmp/stepsummary.py` -- `write_step_summary(results,
  total_duration)`, duck-typed over a `_Result` `Protocol`
  (`identifier`/`output`/`size`, read-only properties so
  `Sequence[_Result]` stays covariant and accepts both `list[BuildResult]`
  and `list[UsermodBuildResult]` without `pyright` complaining -- the
  same list-invariance snag **D26**'s own `usermod/targets.py` comment
  already hit once). A standalone module rather than living in either
  `cli.py`, specifically to dodge a circular import: `cli.py` already
  imports `usermod.cli` for dispatch, so a shared helper defined in
  either one would need the other to import it back.
- No-ops when `$GITHUB_STEP_SUMMARY` is unset (every local run, and
  any non-GitHub CI system), otherwise appends a Markdown table to
  that path -- *appends*, not overwrites, since GitHub Actions expects
  every step in a job to add to the same running file across the
  whole job, confirmed by a dedicated test.
- Wired into both call sites exactly where designed:
  `src/cibuildmp/cli.py`'s `build()` and
  `src/cibuildmp/usermod/cli.py`'s `run()`, immediately after each
  one's own existing plain-text summary loop -- runs in addition to
  it, not instead of it.
- Tested at two levels, not just written and trusted: `stepsummary.py`
  itself (`tests/test_stepsummary.py`, 5 cases -- no-op when unset,
  correct table contents, appends rather than truncates, large sizes
  get a thousands separator, an empty result list still writes a
  header) and the real wiring through the actual CLI
  (`tests/test_cli.py::test_real_build_writes_github_step_summary_when_set`,
  a genuine `main()` call with only the toolchain/fetch/build edges
  mocked, confirmed to fail without the `write_step_summary(...)` call
  in `cli.py` before being confirmed to pass with it -- not just
  written and assumed correct). 237 tests pass project-wide.
- **Not yet verified on real GitHub Actions itself** -- unlike every
  Dockerfile fix in this session's own chain, this one genuinely
  cannot be meaningfully faked locally beyond what the tests above
  already do (there is no live `$GITHUB_STEP_SUMMARY` file to inspect
  outside a real Actions run), so the real proof is whatever the next
  `build-examples.yml` run's own Summary tab shows once this lands on
  the branch.

The original design notes below are kept for the historical record of
what was planned before implementation, not because anything in this
entry supersedes them -- the implementation matches the design as
written.

- **What cibuildwheel's own action does, precisely:** after a build,
  it writes a Markdown table into `$GITHUB_STEP_SUMMARY` -- one row
  per wheel produced, filename and size -- which GitHub renders on the
  job's own summary page (the "Summary" tab of an Actions run),
  visible without opening any log at all. `$GITHUB_STEP_SUMMARY` is a
  file path GitHub Actions itself sets as an env var on every runner;
  appending Markdown to it is the whole mechanism, no special API or
  action needed.
- **`cibuildmp` already computes exactly the data this needs, in both
  CLIs, today** -- it just only ever goes to plain stdout:
  - natmod, `src/cibuildmp/cli.py:284-287`:
    ```python
    total_duration = sum(r.duration for r in results)
    print(f"\ncibuildmp: {total} target(s) built in {total_duration:.1f}s")
    for result in results:
        print(f"  {result.identifier}: {result.output.name} ({result.size} bytes)")
    ```
  - usermod, `src/cibuildmp/usermod/cli.py:115-120`: the identical
    shape, over `UsermodBuildResult` instead of `BuildResult` --
    `identifier`, `output`, `size`, `duration` all already exist on
    both result dataclasses.
- **The design this suggests:** one small shared helper (a natural
  home: `src/cibuildmp/cli.py` or a new tiny module either CLI
  imports, since both natmod's `main()` and usermod's `run()` need
  it) -- `write_step_summary(results, *, total_duration)` or similar --
  that:
  1. No-ops immediately if `os.environ.get("GITHUB_STEP_SUMMARY")` is
     unset (every local/non-CI invocation, and any CI system that
     isn't GitHub Actions -- matches cibuildwheel's own behaviour of
     never requiring GitHub Actions specifically, and keeps this from
     ever becoming a hard dependency).
  2. Otherwise appends a Markdown table (identifier, filename, size,
     build duration) to that file path -- plain `open(path,
     "a").write(...)`, no library needed.
  3. Runs *in addition to* the existing stdout prints, not instead of
     them -- the plain-text summary is still what a local run or a
     non-GitHub CI system sees.
- **Scope check:** natmod and usermod both need this (two call sites,
  not one) but the helper itself is genuinely shared -- both result
  types already expose the same three fields (`identifier`, a way to
  get a filename, `size`), so a small `Protocol` or just duck-typing
  on those three attributes avoids writing it twice. Do not gold-plate
  this into a generic "reporting" subsystem; it is one Markdown table,
  written once, called from two places.
- Genuinely independent of **D28**: this is pure CLI/output-formatting
  work, touches no Dockerfile, no toolchain resolution, no
  `action.yml` structure at all -- a good candidate to implement
  first, quickly, before or in parallel with **D28**'s much larger
  container migration, if a new session wants an early, low-risk win.

**D30 — extending the container approach to natmod too, and a direct
answer to "Docker or QEMU" (they are not competing choices).** The
user's own follow-up to **D28**, six concrete points, addressed here
individually so a fresh session has the reasoning, not just the
conclusion.

1. **Confirmed, already the design**: `cibuildmp` stops running inside
   a container and starts launching container builds itself (**D26**'s
   own "sibling containers, not Docker-in-Docker" reasoning). No change
   from **D28**.
2. **natmod already builds cleanly through one combined Dockerfile
   today -- genuinely proven, not aspirational.** Every one of
   **D25**'s six real bugs happened inside `unix`'s own five
   architectures colliding; natmod's own arches, sharing that exact
   same combined image the whole time, never broke once across this
   entire session's CI chain. **Revised, more decisive than the first
   pass above -- the user's own direct correction:** **D3**'s own
   "works on a bare laptop, no Docker, mutates nothing" promise is
   itself now superseded, not a constraint this plan needs to route
   around. Docker becomes a **required dependency for real builds**
   going forward, not an escape hatch. The two ports genuinely differ
   though, and the plan should say so plainly rather than treat them
   identically:
   - **natmod**: `toolchains.py`'s existing host/download resolution
     stays, purely because it already works and costs nothing further
     to leave in place -- not preserved as a load-bearing design
     promise any more, just not worth deleting. Docker is the
     preferred, default path once available; the old path answers
     "Docker isn't installed" without anyone having to build or
     maintain anything new for it.
   - **usermod**: no non-Docker path is worth pursuing for any port at
     all, including `unix`. **Superseding this decision's own first
     pass** (which called `unix`'s existing host-based cross-compile
     path -- **D20/D24/D25**, real, proven, already shipping --
     "grandfathered," kept purely because ripping out working code
     costs something for no benefit): the user's own direct, later
     call is Docker-only, full stop, no exception for `unix` either.
     **The reason inverts D3's own original framing, above, not just
     overrides it:** D3 called bare-host the non-mutating option and
     Docker the heavier one. For usermod that framing is backwards --
     a bare-host build means `apt-get install`ing arch-specific
     cross-toolchains onto whatever's running the build, a real,
     persistent mutation of that host. A container is the actually
     non-mutating, deterministic, isolated option: it is built once
     from a pinned Dockerfile and discarded per run, touching nothing
     outside itself. Docker-only is the isolation-preserving choice,
     not a tradeoff against it. The real toolchain diversity across
     ports (ESP-IDF, emsdk,
     llvm-mingw, five different `unix` cross-compilers) makes a
     parallel, dual-maintained non-Docker path prohibitively expensive
     for every port, `unix` included, not just the ones added from
     here on. Every port's Docker path is mandatory, not a preferred
     default with a bare-host escape hatch. `llvmmingw.py`/`emsdk.py`/
     `espidf.py` (already written, from earlier in this session) stay
     as `docker/<port>.Dockerfile`'s own *build-time* provisioning
     mechanism -- called once when the image is built, not something a
     caller's own bare-host run falls back to. **Done (D33's own
     session): `usermod/dockerrun.py`'s `ensure_image()` no longer has
     a local-build fallback at all (build vs. pull, a separate change),
     and `build_unix()`'s own bare-host branch (the `toolchains.resolve
     ("x86")` / `shutil.which()`-plus-apt-package probe, and
     `UnixArchSettings.apt_package`, which nothing else read once that
     branch was gone) is deleted outright, not merely deprioritized.**
     `docker_image is None` is now the immediate, clearly-worded error
     this bullet called for ("no Docker image registered ... usermod
     builds are Docker-only"), matching `build_webassembly()`'s own
     shape exactly. Also closes **D32**'s own "self-hosted runners
     without Docker" question the way this bullet already predicted:
     fail loudly, never fall back. **Scoped to an actual build only, not the CLI as a whole:**
     the error belongs at the point a usermod port is actually about
     to be built (inside `build_<port>()`, once it needs a real image),
     not as a blanket check `cli.py`/`usermod/cli.py` run up front.
     natmod never touches this path at all (**D30**'s own natmod
     bullet, above -- Docker is preferred there, not required), and a
     usermod invocation that does not build anything --
     `--dry-run`, `--print-build-identifiers`, `--print-build-matrix`
     -- must keep working with no Docker installed at all, the same as
     today.
   - **A genuine, concrete payoff of this, the user's own observation:**
     adding a new port's own support becomes strictly simpler than it
     is today -- write one Dockerfile, then declare it in the resolver
     (`usermod/dockerrun.py`'s own `image_for_port()`, or whatever
     config-driven mapping replaces the current env-var-only lookup).
     No new Python resolution module to write and test (the shape
     `llvmmingw.py`/`emsdk.py`/`espidf.py` each are today), no new
     `download`/`host` probing logic, no new apt-package-list
     duplicated between a Dockerfile and a bare-host README section.
     One artifact per port, not two.
3. **Confirmed, already the design**: `usermod` gets one Dockerfile
   *per port*, not per architecture/board -- **D28**'s own "one port,
   one toolchain" framing, unchanged.
4. **A concrete, actionable addition, not yet done:** check `mpbuild`'s
   own and `cibuildwheel`'s own real Dockerfiles before writing any of
   **D28**'s five per-port images from scratch, particularly
   `esp32`/`webassembly` where the real apt/toolchain list is heavy
   and plausibly already solved correctly somewhere public. Not
   independently verified in this session at all (same "cited by the
   user, not yet checked against source" caveat **D26** already
   carries for `mpbuild`'s own container-per-port precedent) -- a
   concrete first step for whoever picks up **D28**'s implementation,
   not a claim about what those Dockerfiles actually contain.
5. **Direct consequence of point 2, same caveat:** yes, on the
   Docker-active branch, "resolve toolchain" becomes "which Dockerfile"
   for natmod exactly the way it already does for usermod's own ports
   -- conditional on Docker being the selected path, not a blanket
   replacement of `toolchains.py`.
6. **"Docker over QEMU or QEMU over Docker" -- neither; they solve
   different problems, not a build-time either/or.** **D2/M2** already
   decided, with reasoning, not to emulate for cross-compilation at
   all: real cross-compiling beats QEMU user-mode emulation for
   something as light as MicroPython's own build (the same reasoning
   **D25**'s own cibuildwheel comparison restates -- manylinux uses one
   container *per architecture* plus `qemu-user`, specifically because
   Python wheels are far more expensive to build than MicroPython is).
   Wrapping toolchains in Docker containers does not change that
   calculus at all -- the containers exist for **dependency isolation
   between ports** (**D28**'s own "why isolation is the real driver"),
   not to enable emulation as an alternative to cross-compiling. QEMU
   stays exactly where **D21** already puts it: a separate *execution*
   axis (`qemu-system`, running/testing an already-built binary under
   an emulated target), never a *build-time* one. Three orthogonal
   concerns, not a competing pair: **Docker for isolation,
   cross-compilation for building, QEMU only for execution/testing.**

- **D28's own open Docker-daemon-reachability question is now
  resolved, confirmed live, not just reasoned about** -- see **D28**'s
  own "risks and open questions" section for the real result (a
  genuine `docker info`/`docker run --rm hello-world` from a plain,
  non-Docker-action `run:` step on `ubuntu-latest`, both worked
  immediately). The diagnostic job has been removed from
  `usermod-dev.yml`.
- **`build-examples.yml` should test every available port, the same
  discipline `examples/usermod-unix` already holds `unix` to, not just
  the one port that happens to be furthest along.** The user's own
  explicit ask. Today only `unix` has an integration example at all
  (`examples/usermod-unix`) -- once **D28**'s remaining Dockerfiles
  land (migration step 3: `windows`, `qemu`, `webassembly`, `esp32`),
  each needs its own real example wired into `build-examples.yml`'s
  own `uses: ./` steps the same way, not left as a claim nobody's CI
  run actually proves. This is the same "no target claimed without a
  real CI proof" rule that caught all six of **D25**'s own bugs in the
  first place -- skipping it for the later ports would reopen exactly
  the risk this whole session's own discipline was built to close.
- **A real side benefit, the user's own observation: this also makes
  local use on Windows genuinely simpler, via Docker Desktop's own
  WSL2 backend.** The root `Dockerfile`'s own comment already
  documents running it through WSL2 (`README.md`'s "Running via
  Docker" section) -- once usermod's own port builds go through Docker
  as the required path (**D30**'s own point 2), that same WSL2 path
  covers usermod too, not just the natmod-only bare CLI it covers
  today. Does not change the "Windows/macOS *runners*" open question
  below at all (a per-port *Linux* container still cannot run on a
  bare Windows/macOS CI runner) -- this is specifically about a
  Windows *developer's own machine* running Docker locally, a genuinely
  different case from CI.

**D31 — `unix` usermod builds are glibc-only today; there is no
musllinux-equivalent, and build identifiers carry no libc axis to name
one even once it exists.** The user's own framing, directly: cibuildwheel
distinguishes `manylinux`/`musllinux` in its own wheel tags because a
compiled extension's libc linkage determines which host it actually runs
on; `cibuildmp`'s own usermod identifiers (`targets.py`'s own
`identifier` property, `{ABI}-{platform}_{arch}` shaped after
cibuildwheel's `cp311-manylinux_x86_64`) have no equivalent axis at all
-- `mpy6.3-usermod-unix-x64` says nothing about which libc the binary
inside was linked against, because today there is only ever one answer.

Verified live in this session, not assumed:

- `x64`/`x86`/`aarch64` (`usermod/build.py`'s own `UNIX_ARCH_SETTINGS`)
  build with a plain dynamic link. A real `v1.28.0` `ports/unix` build
  confirmed via `ldd`: `libc.so.6`, `libffi.so.8`, and the dynamic
  `ld-linux-x86-64.so.2` interpreter are all real runtime dependencies --
  this binary will not run at all on a musl-only host (Alpine and
  similar) with no glibc compatibility layer installed.
- `armhf`/`mipsel` already build with `MICROPY_STANDALONE=1
  LDFLAGS_EXTRA=-static` (**D20**'s own deplibs story) -- the natural
  guess is that this already makes them musl-portable, since a fully
  static ELF has no dynamic libc dependency at all. **That guess was
  checked live and is wrong for this codebase.** Rebuilding `x64` with
  the exact same static recipe still links and runs on the host
  (confirmed: `file` reports "statically linked", the binary executes),
  but the linker itself warns, for real, on this exact source:
  `modffi.c`'s `ffimod_make_new` (the `ffi` module's own `dlopen()`,
  a real, exercised usermod feature) and `modsocket.c`'s
  `mod_socket_getaddrinfo` (`getaddrinfo()`) both print "requires at
  runtime the shared libraries from the glibc version used for linking"
  -- glibc's own NSS design loads its network/name-resolution backends
  via `dlopen()` at runtime even from a "static" binary, so a fully
  static glibc build is *not* actually libc-implementation-portable the
  moment code reaches either function. `armhf`/`mipsel`'s own existing
  "static" builds inherit this same latent gap and have never been
  verified against a real musl host either -- this was not previously
  known or documented anywhere in this codebase.
- Not verified live: actually running a build under a real musl host
  (Alpine). This sandbox's `docker` CLI has no reachable daemon
  (`failed to connect to the docker API at unix:///var/run/docker.sock`)
  -- the same gap **D28**'s own "Docker-daemon-reachability" question
  hit earlier, resolved there only because a real GitHub Actions runner
  was reachable to test against. Whoever picks this up should confirm
  the `ldd`/linker-warning findings above against a real Alpine
  container before trusting them as the final word.

**The real fix is a musl toolchain, not a linker flag** -- `-static`
alone was the tempting, cheap-looking answer and it does not work, per
the live finding above. **The manylinux half of this is now done, the
musllinux half is not, and both halves live in the same mechanism.**
Following directly from this decision's own finding, the earlier
`resources/docker/unix.Dockerfile` (one image, all five arches) was
replaced with five per-arch `unix-manylinux-<arch>.Dockerfile` images
(**D26**'s own amendment above) -- the same correction the user pushed
for directly ("це херня, я думав ми наріжемо manylinux-x64
muslinux-aarch64 тощо"), and `usermod/dockerrun.py`'s own resolver now
takes an explicit `libc` parameter for exactly this reason
(`image_for(port, arch, libc=None)`, **D28** step 2). What's still
genuinely missing is only the musl side: an Alpine-based
`unix-musllinux-<arch>.Dockerfile` per arch (musl's own `gcc`, not
Ubuntu's), registered in `PORT_IMAGES` the same one-line way
(`"unix-x64-musllinux"`), no resolver changes needed at that point --
the mechanism already accepts this shape today, it just has nothing to
register yet. `targets.py`'s own `identifier` property still needs a
matching new axis alongside `arch` (`mpy6.3-usermod-unix-x64-manylinux`
/ `-x64-musllinux`, cibuildwheel-shaped, defaulting to `manylinux` so
every existing identifier stays valid unless a caller opts into
`musllinux` explicitly) -- threading this through
`UsermodOptions`/`orchestrate.py`'s own axis-override machinery
(**D20**) the same way `arch`/`board` already work is real, multi-file
work, not a one-line addition, and is explicitly **not attempted in
this session**: it needs a real musl cross-toolchain resolved per arch,
real Dockerfiles, and real verification against an actual musl host,
none of which fit alongside the resolver/image work above. Flagged
here, precisely, so a future session designs the axis once rather than
bolting it on ad hoc the way **D25**'s six bugs show what "discovered
mid-flight" costs.

- **"manylinux" here is a label, not a version pin -- a sharper version
  of a gap this decision already flagged loosely, made concrete by the
  user's own real example.** Real manylinux wheel tags carry a specific
  minimum glibc version as part of the tag itself --
  `rp2040py-0.3.1-cp314-cp314t-manylinux2014_armv7l.manylinux_2_17_armv7l.manylinux_2_31_armv7l.whl`
  names `manylinux2014`/`manylinux_2_17`/`manylinux_2_31` as three
  *specific*, independently-checkable glibc-version floors a wheel with
  that tag is guaranteed compatible with -- that guarantee is the whole
  point of the tag, not incidental to it. `cibuildmp`'s own
  `unix-manylinux-<arch>` images carry no such pin at all: "manylinux"
  today just means "whatever glibc `ubuntu:24.04` happens to ship,"
  which changes underneath every image silently whenever the base image
  itself gets rebuilt or Ubuntu patches it, with nothing recorded
  anywhere about what floor a binary built there actually needs. Not
  designed or fixed here -- raised mid-incident, correctly deferred
  alongside the QEMU/native-image question above rather than expanding
  scope further while chasing a live CI failure -- but a real, separate
  gap from the manylinux/musllinux axis itself: even a `unix` build that
  never touches musl at all still makes no claim about which glibc
  versions it actually runs on. The user's own explicit follow-up,
  directly: this isn't just "add a version number somewhere" -- it's
  "follow the actual convention" rather than reinvent a worse one.
  Real manylinux tags follow **PEP 600**, which stacks *multiple*
  compatibility floors on one artifact (`manylinux_2_17_armv7l` *and*
  `manylinux_2_31_armv7l` together in the one filename above, not a
  single flag) precisely so a checker can verify the binary's actual
  symbol versions against each floor independently, and a consumer
  picks whichever floor its own host clears; **musllinux is the same
  shape under a separate spec, PEP 656**, versioned against musl
  releases instead of glibc ones. **Decided, not just raised: a future
  session adopts this for real** -- the user's own explicit call, not
  merely "worth considering." Whoever picks this up should read both
  PEPs directly before designing anything (not re-derive the shape from
  this summary alone), and start from how `cibuildwheel` itself
  actually resolves them, checked live against a real `v4.2.0`
  checkout, not assumed: it does **not** compute a floor at all --
  `resources/defaults.toml` is a static, maintainer-curated table
  (`manylinux-x86_64-image = "manylinux_2_28"`,
  `manylinux-armv7l-image = "manylinux_2_31"`, one pinned image per
  arch from the separate `pypa/manylinux` project, trusted rather than
  verified at build time) that only decides *which base image* to
  build inside; the real, computed answer -- what glibc/musl floor a
  *just-built* binary's own symbols actually require -- comes from
  shelling out to **`auditwheel repair`** (manylinux) /
  `auditwheel repair --ldpaths` (musllinux) as the default
  `repair-wheel-command`, an external CLI cibuildwheel merely invokes
  as a subprocess inside the container, not a library it imports
  (`packaging` *is* a real cibuildwheel dependency, but only for
  `Version`/`SpecifierSet` version-range parsing -- unrelated to tag
  resolution at all). `cibuildmp`'s own equivalent, if it follows this
  precedent rather than reinventing it, is therefore two separate
  pieces, not one: (1) a maintainer-curated `PORT_IMAGES`-shaped table
  naming which base image backs each floor -- already exactly
  `dockerrun.py`'s own shape, extended with a floor segment -- and (2)
  a real post-build checker in that same spirit as `auditwheel` (built
  on `pyelftools`-style ELF symbol-version inspection, since `unix`
  produces a bare executable, not a wheel `auditwheel` itself knows how
  to repair) that verifies a `micropython` binary's own actual glibc
  symbol versions against the floor its image claims, rather than
  trusting the claim silently the way today's plain "manylinux" label
  does. **This needs zero new dependencies, checked directly against
  `pyproject.toml`**: `pyelftools`/`ar` are already real, existing
  `cibuildmp` dependencies -- today only because `tools/mpy_ld.py`
  (MicroPython's own native-`.mpy` linker, D2) is itself a Python
  script that imports them, and `make_command()`'s own
  `PYTHON=<sys.executable>` (`build.py`, D12's own mechanism) is what
  makes cibuildmp's own environment satisfy that need rather than
  requiring a separate `pip install` at build time -- not because
  `cibuildmp`'s own code does any ELF inspection of its own yet. A real
  glibc-floor checker for `unix` is therefore new *code* using an
  already-present dependency, not a new dependency to add.
  `auditwheel`'s own `elfutils.py` module (`elf_read_dt_needed`,
  `elf_find_versioned_symbols`) is worth reading directly before
  writing that code from scratch, confirmed live against a real
  `pypa/auditwheel` checkout to operate on a bare ELF `Path`, fully
  decoupled from the wheel-archive-specific code (`wheel_abi.py`,
  `repair.py`) that can't be reused as-is (`auditwheel`'s own CLI is
  hard-wired to a `.whl` file argument, not a bare executable).

- **M10** — runner/matrix integration, fan-out-by-default for usermod
  identifiers (**D20**).
- **M11** — execution axis: qemu-system, rp2040py, node, native — four of
  seven already proven working, just not owned by `cibuildmp` yet
  (**D21**).
- **M12** — adopt in the three consuming repos, mirroring **M5**.

**D33 — cibuildmp never builds a Docker image itself; it only ever
resolves a reference and pulls it, exactly like cibuildwheel's own
container runtime, checked directly rather than assumed.** The user's
own framing, directly: "я хочу окремий workflow який публікує
докерімеджі, самі докерфайли в репо-рут/docker, а cibuildmp просто
скачує готові образи" -- prompted by looking at `oci_container.py`
(cibuildwheel's own container runtime) and finding zero `docker build`/
`buildx` calls anywhere in that repo. cibuildwheel's own manylinux/
musllinux images are published to quay.io (not GHCR, not Docker Hub --
`pypa/manylinux`'s own, separate project's choice), pinned by exact
digest in `resources/pinned_docker_images.cfg`, regenerated by a rare,
out-of-band maintainer script (`bin/update_docker.py`) -- never part of
a consumer's own build. This decision brings cibuildmp's own container
story to the same shape:

- **`docker/*.Dockerfile`, repo root** -- moved out of
  `src/cibuildmp/resources/docker/` (D28's own migration step 3
  location). No longer needs to ship inside the installed wheel:
  cibuildmp itself never reads these files at runtime any more.
  `pyproject.toml`'s own `package-data` list dropped the entry.
  Mirrors `pypa/manylinux`'s own top-level `docker/` -- that repo has no
  `pyproject.toml` either, since it is pure image-building
  infrastructure, never something `pip install`s, the same reason this
  now applies to `docker/` here too.
- **`.github/workflows/publish-docker-images.yml`, a genuinely separate
  workflow** -- not a job folded into `build-examples.yml` or
  `publish.yml`. Triggers on a push to `main` that touches `docker/**`,
  or `workflow_dispatch` -- not every push to every branch, the same
  "rare, deliberate, maintainer-triggered" cadence
  `bin/update_docker.py` has. Builds and pushes every one of the eight
  images to GHCR, `:latest`-tagged for human findability only, and
  prints the real `@sha256:...` digest `docker/build-push-action`
  returns to the job summary -- what a maintainer actually copies into
  `PORT_IMAGES`, by hand, in a real PR, the same manual step
  `bin/update_docker.py`'s own output requires of a cibuildwheel
  maintainer.
- **`usermod/dockerrun.py`'s `ensure_image()` lost its entire local-build
  branch** (`_DOCKERFILES`, `_build_command()`,
  `_ensure_buildx_container_builder()`, all deleted) -- it is now a
  thin alias for `image_for()`, nothing more. `run()`'s own `--pull
  missing` is what actually fetches an image, lazily, the first time it
  is used -- the exact division of labour `oci_container.py` already
  has. `PORT_IMAGES` having nothing registered for a (port, arch[,
  libc]) is now an immediate, clear `UsermodBuildError`
  ("no Docker image registered..."), not a slow last resort that used
  to build one from scratch.
- **No `CIBMP_CACHE_PATH`-backed `docker save`/`docker load` layer was
  added either** -- floated as a way to make Docker images share
  cibuildmp's own existing `CIBMP_CACHE_PATH` cache-dir model (the same
  shape `sources.cache_root()` already gives toolchain tarballs and the
  MicroPython checkout, itself renamed this session from `CIBMP_CACHE`
  to match `CIBW_CACHE_PATH`'s own name exactly), then dropped on the
  same "check cibuildwheel's real source first" discipline: `docker
  save`/`docker load` do not appear anywhere in that repo either.
  Docker's own local image store is the only cache involved, same as
  cibuildwheel.
- **`build-examples.yml`'s own `verify-docker-images` job is build-only
  now, on every push and pull_request (fork PRs included, no registry
  credentials needed for a build that never pushes)** -- it used to
  also push every image to GHCR under a `:sha-<gitsha>` tag on a direct
  push, specifically so `build-usermod`'s own six
  `CIBMP_*_DOCKER_IMAGE` env vars could point at something real without
  waiting for a release. That whole mechanism is gone: the user's own
  call, directly -- "реальний юзер не має думати за
  CIBMP_*_DOCKER_IMAGE" -- a real end user was never going to see that
  env var, and it existed only to work around not having D28 step 5
  (a real, `PORT_IMAGES`-registered publish) done yet. `build-usermod`
  now runs with no image overrides at all, the same as any real
  consumer.
- **The bootstrap gap above closed the same session, for real, not left
  open as written.** The user triggered `publish-docker-images.yml`
  directly (`gh workflow run`, after a real merge to `main` -- GitHub
  only accepts `workflow_dispatch` for a workflow already present on the
  default branch); all eight jobs pushed successfully
  (run `32895072172`). The real `@sha256:...` digests that run printed
  are now registered in `PORT_IMAGES` for all eight (port, arch[, libc])
  keys -- copied from each job's own "Record the pinned digest" step,
  not guessed.
- **A different, real gap surfaced immediately after, checked live, not
  assumed: every one of those eight GHCR packages is private by
  default.** A plain `docker pull` of one, fully unauthenticated, came
  back `401 unauthorized` -- this is GitHub's own documented behaviour
  for a package pushed via the automatic per-job `GITHUB_TOKEN` (private
  regardless of the parent repo's own visibility), not a bug in
  `publish-docker-images.yml`. `build-usermod` no longer logs in to GHCR
  at all (this same decision removed that step), so until a repo admin
  flips each `cibuildmp-*` package to Public under `ballistics-lab`'s
  own package settings, both `build-usermod` and any real outside
  consumer fail to pull. Flagged, not fixed here: changing package
  visibility needs org-admin access this session does not have.
- **`CIBMP_TIMEOUT` / `CIBMP_<PORT>_<ARCH>_<LIBC>_TIMEOUT`, added the
  same session, prompted by a real incident, not a hypothetical.** A
  container from an unrelated earlier manual test outlived the
  killed/timed-out shell that started it -- a shell-level kill only
  reaches its immediate child, and `docker run` sits several process
  hops below that (`bash -> uv -> python -> docker CLI -> dockerd's own
  container process`), so the container itself kept running, undetected,
  burning a CPU core at 100% for over an hour. `dockerrun.run()` now
  accepts an optional `timeout` (seconds); `None` (no limit) stays the
  default, the user's own explicit call. `timeout_for()` resolves it the
  same two-tier shape `image_for()` already uses (a per-container env
  var first, `CIBMP_TIMEOUT` as the blanket fallback, `None` otherwise).
  Critically, a bare `subprocess.run(..., timeout=...)` is not enough on
  its own -- its `TimeoutExpired` only kills the `docker run` CLI
  process, not the container running under `dockerd`, which is exactly
  the gap the real incident exposed -- so `run()` now names its own
  container (`--name cibuildmp-<uuid>`) and issues a real `docker kill`
  on that name the moment the timeout fires, which is what actually
  stops it (and, via the already-present `--rm`, removes it).
- **A real, live-caught bug in `docker/webassembly.Dockerfile`, found
  the moment `PORT_IMAGES` gave it its first real exercise ever.**
  `verify-docker-images` only ever ran `docker build` (does the image's
  own layers assemble), never `docker run` (does a real `make`/`emcc`
  invocation inside it actually work) -- and `build-usermod`'s own
  webassembly leg had failed with "no Docker image registered" on
  every push until this session, meaning no real compile had ever run
  through this image before. It failed immediately once one could:
  `emcc: error: NODE_JS not set in config ..., and node not found in
  PATH`, on a bare `-E` preprocess for qstr generation -- not gated
  behind `min`/`repl`/`test`/`test_min` the way this file's own header
  comment had assumed. Root cause, confirmed live inside a real
  container: the `wasm-binaries.tar.xz` release asset this image
  downloads bundles no Node.js binary at all (only JS sources), unlike
  a full `emsdk install`/`activate` run, which this image deliberately
  bypasses for a smaller, directly-verified download (D18's own
  precedent for `llvm-mingw`). Fixed by adding Ubuntu 24.04's own
  `nodejs` package to the image -- confirmed live, the exact failing
  command re-run inside a container with `nodejs` installed passes
  `emcc`'s own sanity check. Republished (`publish-docker-images.yml`
  run `32897892176`) and re-verified end to end: a real pull of the new
  digest, a real `make` through it, a genuine `micropython.mjs`
  (217344 bytes -- byte-identical to D18's own original bare-host
  proof). `usermod/dockerrun.py`'s own `PORT_IMAGES["webassembly"]`
  entry updated to the new digest.
- **`unix`'s own bare-host fallback also removed for real this session
  (see D30's own "Concrete follow-up" bullet, now marked done there),
  prompted directly by the webassembly finding above:** the same class
  of bug -- an image that builds but was never actually run for real --
  could just as easily have been hiding in any of the five
  `unix-manylinux-<arch>` images, masked the same way, by a fallback
  nothing ever needed to fall through to once a real image existed.
  Verified live once the fallback was gone and a real `PORT_IMAGES`
  entry existed to route through: `unix-x64` built cleanly through its
  own Docker image on the first real try, no equivalent hidden bug
  found there.
- **`PORT_IMAGES` populated with real digests for all eight
  (port, arch[, libc]) keys**, copied from `publish-docker-images.yml`
  run `32895072172`'s own "Record the pinned digest" step output (and
  `32897892176` for webassembly's own re-publish above) -- not
  placeholders, the actual pins this table's own comment said would
  land "once that workflow has actually published one."
- **Every GHCR package `publish-docker-images.yml` creates is private
  by default, confirmed live** (an anonymous `docker pull` of one
  returned `401 unauthorized`) -- GitHub's own documented behaviour for
  a package pushed via the automatic per-job `GITHUB_TOKEN`, private
  regardless of the parent repo's own visibility, not a bug in the
  workflow. Fixed for all eight, by hand, via each package's own
  "Change visibility -> Public" setting (a classic OAuth token's
  `write:packages` scope, even freshly granted via `gh auth refresh`,
  turned out not to be enough for the organization-package PATCH
  endpoint specifically -- `GET` worked, `PATCH` 404'd even on an
  already-public package -- so this needs the GitHub web UI, or a
  fine-grained PAT with explicit organization Packages write
  permission, not a classic scope grant). One-time: visibility is a
  property of the package name, not each pushed version, so a future
  push to any of these same eight names stays public with no further
  action -- only a genuinely new package name (a ninth port/arch/libc
  combination) would default to private again and need this repeated.
  Reconfirmed live after the fix: an anonymous `docker pull` of the
  same digest that 401'd before now succeeds.
- **`action.Dockerfile` and the root `Dockerfile`, both deleted, along
  with `publish.yml`'s own `publish-docker` job -- the user's own call,
  the same "usermod is Docker-only, stop bundling every cross-toolchain
  in one image" principle applied to cibuildmp's own distribution
  artifacts, not just the per-port images.** `action.Dockerfile` had
  not fed `action.yml` (a composite action since D28) for a while
  already, and only existed to publish a second, standalone image
  duplicating the root `Dockerfile`'s own "docker run cibuildmp"
  purpose -- genuinely redundant once noticed, not something either
  file's own header comment had caught up to. The root `Dockerfile`
  went with it rather than being slimmed and kept (a real alternative
  considered and rejected): it bundled every usermod cross-toolchain
  (mingw-w64, aarch64/armhf/mipsel-linux-gnu, every libffi-dev/
  libc6-dev-*-cross variant) for a build path D30 already made
  Docker-only, and its own "docker run cibuildmp" story had no working
  usermod path left at all inside that container (no `docker` CLI, no
  `docker.sock` mount, to launch the sibling containers usermod builds
  now require) -- the bundled toolchains were pure dead weight, not a
  gap worth patching over removing. `uv tool install cibuildmp`/`pip
  install cibuildmp` directly is the one supported way to run
  `cibuildmp` outside CI now; README updated to match, including its
  own now-stale `examples/usermod-unix` reference (merged into
  `examples/template` earlier this same session).
- **`action.yml`'s own apt-prerequisites step slimmed the same way --
  and a real, live-caught correction to how far that slimming could
  actually go, not a clean first pass.** Every package beyond
  `build-essential`/`git`/`ca-certificates`/`curl`/`python3`/
  `gcc-13-multilib`/`linux-libc-dev:i386` existed only for usermod's
  own bare-host cross-compiles, gone since D30, and `dpkg
  --add-architecture arm64` + its own `ports.ubuntu.com` deb822 stanza
  existed only to make `libffi-dev:arm64` installable, gone with it.
  `wabt` cut too, separately -- `examples/wasm2mpy`'s own dependency
  (`wasm2c`), not cibuildmp's, moved to that example's own
  `pre-build-command` instead (the same config knob a7p's own real
  `cibuildmp.toml` already uses for its nanopb fetch).
  **`dpkg --add-architecture i386` + `linux-libc-dev:i386` do NOT go
  with arm64's own removal, though a first pass cut them too** -- the
  live check that first justified cutting them (`apt-get install
  gcc-13-multilib` alone, `gcc -m32` compiling a bare empty `main()`)
  never actually exercised what natmod's own real source needs: real
  CI (`ballistics-lab/cibuildmp` run `32900760845`) failed
  `mpy6.3-natmod-x86` with `fatal error: asm/errno.h: No such file or
  directory` the moment this landed for real -- `template.c`'s own
  `py/dynruntime.h` include chain pulls that header in, and only
  `linux-libc-dev:i386`'s own `i386-linux-gnu/asm/errno.h` satisfies it
  under `-m32` (amd64's own `/usr/include/asm/errno.h` does not).
  `linux-libc-dev:i386` is an i386-arch package, so the architecture
  registration has to come back with it -- confirmed live a second
  time, correctly this time, with a real `#include <asm/errno.h>`
  compiled under `-m32`: fails without `linux-libc-dev:i386` +
  `dpkg --add-architecture i386`, succeeds with them. i386 needs no
  `ports.ubuntu.com` stanza of its own the way arm64 did (stays on the
  default archive.ubuntu.com/security.ubuntu.com mirrors, confirmed by
  the root `Dockerfile`'s own comment before that file was deleted) --
  just the existing stanza's own `Architectures:` line gaining `i386`,
  which is what re-landed.

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
  beyond Linux, or explicitly does not. A real `windows-latest` CI run
  (`usermod-dev.yml`, added for M9's own D18 work) already surfaced two
  concrete data points either way this gets decided, both fixed on sight
  rather than left for whenever that decision happens:
  - `tests/test_build.py`'s `test_pre_build_command_runs_in_module_root`
    used `touch marker` as its example `pre-build-command` -- `touch` has
    no `cmd.exe` equivalent, so it failed there, not because
    `run_pre_build_command()` itself is Windows-broken (`subprocess.run(...,
    shell=True)` correctly uses whatever shell the host has), but because
    the test's own example command happened to be Unix-only when the
    behaviour under test (does it run in `module_root`, with the given
    `env`) doesn't require that. Fixed to `echo hi > marker`, which
    `/bin/sh -c` and `cmd.exe /c` both understand identically.
  - `usermod/build.py`'s `unix_make_command()`/`run_unix_deplibs()`/
    `qemu_make_command()`/`webassembly_make_command()` all embedded `Path`
    objects via bare `str()`, which is backslash-separated on Windows --
    real breakage, not a test artifact, since GNU Make (native or MSYS2)
    wants forward slashes regardless of host OS. This is the exact bug
    **D18** already documented for `a7p`'s own hand-written workflow
    (`$GITHUB_WORKSPACE`'s native form, mangled by MSYS2 bash's own
    escaping) -- caught here before it shipped instead of after. Fixed to
    `.as_posix()` everywhere a `Path` reaches a `make` command line.

  Partially answered since, not closed: **D18**'s own windows-usermod
  story ended up needing no Windows host at all (all three arches
  cross-compile from Linux — see **D18**'s own addenda), so `cibuildmp`
  itself running natively on Windows stopped being a real question for
  usermod specifically. `x86`'s multilib and `docker` (D3) are still
  Linux-only, unchanged. The repo's own root `Dockerfile` + README's own
  "Target support" tables are the answer for an actual Windows end user
  today: run `cibuildmp` inside Docker under WSL2, not natively on
  Windows Python — not verified with a real `docker build`/`docker run`
  in this project's own dev sandbox (Docker does not run there at all,
  the same finding **D19**'s own addendum already recorded), but every
  ingredient in it was checked directly: each `apt install` package
  live-installed and used for a real build earlier in this same session,
  and `uv tool install .` → `cibuildmp --dry-run` run for real outside
  the container.
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
- **Nothing checks whether a pinned version is stale.** Dependabot already
  watches this repo's own `uv`/Actions dependencies (the "Graph Update"/
  "github_actions ... Update" runs in Actions history), but it has no
  visibility into the pins that actually matter here: every toolchain
  version + sha256 in `resources/natmod.toml`/`resources/usermod.toml`
  (arm-none-eabi, xtensa-esp, riscv-none-elf, and now emsdk), and the
  MicroPython release tag each `examples/*/cibuildmp.toml` builds against.
  All of that goes stale on an upstream's own schedule, same as **D10**
  already says about the toolchain table specifically — but nothing here
  today notices *when*, for any of it, MicroPython tag included. Not
  designed yet: could be a periodic job that diffs each pin against
  upstream's latest release and opens an issue/PR, a documented manual
  review cadence, or something narrower per pin (e.g. a script that
  re-derives the emsdk hash for a given alias and flags drift). Flagged so
  a real staleness incident (a build that quietly stops matching upstream)
  doesn't become the way this gap gets found.

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

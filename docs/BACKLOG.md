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

**Revisited and dropped, verified live rather than assumed.** Docker does
not even run in this project's own dev sandbox (`docker run` fails outright
-- no daemon socket, not a permissions issue to work around), and the
official `git clone --recursive` + `install.sh` + `export.sh` recipe this
decision was written against works there directly, no container needed:
a real `v5.5.1` clone, `idf_tools.py install --targets=esp32` +
`install-python-env`, then `make -C ports/esp32 BOARD=ESP32_GENERIC`
produced a genuine `micropython.bin`, end to end. The "materially
stronger Docker-strategy case than x86" framing above conflated two
different things: ESP-IDF's own install being *heavy* (true, ~1.3 GiB of
toolchain + Python env, ~2 GiB more for the `--recursive` clone) is not
the same claim as it needing *isolation* the way x86's `-m32` genuinely
needs a 32-bit userland `M2`'s own host gcc doesn't ship. Every usermod
port here is still "a cross-compile (or, for `esp32`, a from-source IDF
build) that runs fine on the build host" — the same reasoning `M2`'s own
"why not docker for x86" note already used, this time holding for a
second port instead of flipping.

One real environment finding along the way, worth recording since it
looks like a Docker argument on first read and is not one: `openocd-esp32`
(part of ESP-IDF's own default toolset for a target, installed by
`install.sh esp32` regardless of what a usermod build actually needs it
for — flashing/JTAG debug, not building) failed its own post-install
check with `error while loading shared libraries: libusb-1.0.so.0`, in
this dev sandbox specifically. `apt install libusb-1.0-0` fixed it — an
ordinary Linux runtime dependency of upstream's own binary, already
present on any real dev machine or CI image (a GitHub-hosted runner
included), not something a container would have supplied any more
cheaply than `apt` already does.

What actually needed fixing was D19's own real complaint, not the
mechanism: **no caching**. Landed as `usermod/espidf.py` — `fetch_esp_idf()`
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

**D18 addendum — MSVC investigated and rejected as an alternative to MSYS2,
verified live against the real `ports/windows` build files, not assumed from
the port's own README alone.** `ports/windows/README.md` documents a fourth
build method beside MinGW-via-Makefile and MSYS2: MSVC, via
`msbuild micropython.vcxproj` (`msvc/paths.props`, `msvc/sources.props`,
`msvc/*.targets`). Simpler to orchestrate on a real `windows-latest` runner
on paper — MSVC/Build Tools ship pre-installed, no MSYS2 provisioning, no
`bash.exe`/`cygpath` indirection — so it was worth checking against the
Makefile path this project had already mostly written before committing to
either. It does not work for usermod specifically: `msvc/sources.props` is
a static `<ClCompile Include=...>` file list, fixed at project-file-authoring
time, and neither it nor `micropython.vcxproj` references `USER_C_MODULES`
or `FROZEN_MANIFEST` anywhere (confirmed by grep across the whole `msvc/`
tree and the `.vcxproj` itself — zero hits, versus real hits in `Makefile`
and `variants/dev/mpconfigvariant.mk`). The Makefile path carries both
natively: `ports/windows/Makefile`'s own `FROZEN_MANIFEST ?=
variants/manifest.py` plus `include $(TOP)/py/mkrules.mk`, which is what
actually wires `USER_C_MODULES` into the build (`py/mkrules.mk`'s own
`vpath %.c . $(TOP) $(USER_C_MODULES)` and friends). Passing a usermod's
own C sources or manifest through the MSVC path would mean hand-editing
`micropython.vcxproj` per module, defeating the point of a driver that
takes them as parameters — so MSYS2 is not a preference here, it is the
only one of MicroPython's own three Windows build methods that actually
takes a `USER_C_MODULES`/`FROZEN_MANIFEST` input at all, and it is also
what `a7p`'s own `mp-usermod.yml` already uses in production.

First landed as `usermod/msys2.py` (`find_msys2()`/`install_msys2()`/
`resolve_msys2()`, `ResolvedMsys2.run()`/`.install_packages()`/
`.to_posix_path()`) and a `build.py`'s `build_windows()` that ran through
it for all three arches — this genuinely worked: a real `windows-latest`
run of `usermod-dev.yml` produced a real `micropython.exe` with a real
usermod module linked in, catching and fixing real bugs along the way
(three in the surrounding code before any MSYS2 code even ran, then a
fourth in `ResolvedMsys2.to_posix_path()` itself — its first real
invocation on a fresh runner captured MSYS2's own one-time "Copying
skeleton files..." login-shell notice into what was supposed to be a
clean `cygpath -u` result, silently corrupting a real `USER_C_MODULES`
value fed to `make`; fixed by trusting only the last non-empty stdout
line rather than the whole captured output).

Superseded in two stages, both live-verified rather than assumed, not
one clean cutover. **Stage one:** a comparison against upstream
MicroPython's own CI (`.github/workflows/ports_windows.yml`) turned up a
fourth build method this project had not considered: `cross-build-on-linux`,
`tools/ci.sh`'s own `ci_windows_setup`/`ci_windows_build` — `apt install
gcc-mingw-w64-x86-64`/`gcc-mingw-w64-i686` plus a plain
`make -C ports/windows CROSS_COMPILE=x86_64-w64-mingw32-`/
`i686-w64-mingw32-`, no Windows host at all. Verified live in this
project's own dev sandbox exactly like `unix`/`qemu`/`webassembly`/
`esp32` already were — the one thing MSYS2 could never get — with a real
custom C module (`USER_C_MODULES` pointed at an actual `mymod.c`/
`micropython.mk`, not an empty directory): a genuine `micropython.exe`
for both `x64` (PE32+, 549376 bytes) and `x86` (PE32, 568792 bytes),
`strings` confirming the module's own `mymod`/`hello` symbols linked in.
`x64`/`x86` moved to this; `arm64` initially stayed on MSYS2 (its own
`CLANGARM64` environment, `mingw-w64-clang-aarch64-gcc-compat`/`-clang`
— no apt equivalent exists for that target), reasoned at the time to be
an acceptable gap since nothing in this project's scope appeared to need
Windows ARM64 usermod builds. That reasoning was wrong, corrected within
the same session by an explicit statement of a real requirement (a
consumer's own libraries build Windows ARM64 usermod targets today) —
recorded here as a real example of why "nothing exercises this yet" is
worth double-checking against actual consumers before it becomes a
design decision, not just a placeholder note.

**Stage two:** mingw-w64's own documentation (https://www.mingw-w64.org,
"Pre-built Toolchains") names the real fix directly: `llvm-mingw`
(`mstorsjo/llvm-mingw`) is the one toolchain that both targets ARM64
Windows and "can be run on Linux, compiling binaries for any of the 4
target Windows architectures" (its own README). Verified live, the same
standard this project holds every toolchain resolver to: downloaded a
real release tarball (`llvm-mingw-20260616-ucrt-ubuntu-22.04-x86_64.tar.xz`),
cross-compiled `ports/windows` with `CROSS_COMPILE=aarch64-w64-mingw32-`
and a real custom C module, and got a genuine PE32+ Aarch64
`micropython.exe` with that module's own symbols linked in via `strings`.
Getting there took three real, live-found compatibility fixes, not a
clean first try — worth recording since they are exactly the kind of
detail a "should be a drop-in GCC replacement" assumption would have
missed: `-Wno-double-promotion` (`py/binary.c`'s `_Float16`↔`float` union
trick reads as an implicit precision-increasing promotion to Clang
specifically), `-Wno-uninitialized` and `-Wno-default-const-init-var-unsafe`
(`shared/runtime/gchelper_generic.c`'s own `const register long x19
asm("x19")` idiom — reading a callee-saved register an asm stub already
wrote — trips two different Clang diagnostics GCC does not apply to a
bare asm-tied register declaration), and `COMPILER_TARGET=mingw-forced`/
`STRIP=`/`SIZE=true` (the same overrides MSYS2's own CLANGARM64
environment already needed — this Clang's own `-dumpmachine` doesn't
contain "mingw" either, which `ports/windows/Makefile`'s `.exe`-suffix
and post-link strip logic both grep for). None of these apply to
`x64`/`x86`'s plain GNU cross-gcc, which needs none of them.

It is the *same* `ports/windows/Makefile` in every case (MSYS2, apt-gcc,
llvm-mingw) — `USER_C_MODULES`/`FROZEN_MANIFEST` work identically
throughout; the differences are entirely in what compiler diagnostics
each toolchain enforces and how each is provisioned. Landed as `build.py`'s
current `build_windows()` (`WindowsArchSettings`, `WINDOWS_ARCH_SETTINGS`
for `x64`/`x86`/`arm64`, one function dispatching per arch the same way
`build_unix()` already dispatches its own standalone/x86 special cases)
plus `usermod/llvmmingw.py` (pinned in `resources/usermod.toml`'s own
`[llvm-mingw]` table, same `cached_dir`/`download_file`/`verify_sha256`
shape `emsdk.py` already uses). `usermod/msys2.py` and its own
`usermod-dev.yml` `windows`/`windows-live-build`/`windows-arm64-live-build`
jobs were deleted outright, twice, not kept as a fallback: a second
working path to the same Makefile is not a hedge, it is surface area
nothing exercises. `windows` needs no `windows-latest` runner at all now,
for any of its three arches — relevant to **D20** below, which had
assumed one for all of them.

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
entirely) surfaced four genuine, non-obvious apt/gcc problems no amount
of reading package lists would have caught -- one of them (the
`i386-linux-gnu` symlink) initially "fixed" wrong and only caught by a
later, unrelated real build failure.** `examples/usermod-unix`
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
- All four fixes are Dockerfile-only, not `cibuildmp` itself: none
  affect a bare `ubuntu-latest` runner running the CLI directly
  (**M9b**'s own live verification, and every `build-examples.yml` run
  before this one, already exercised `gcc -m32` successfully outside
  Docker) -- only these two custom images, which now need
  `gcc-13-multilib`, `libffi-dev`, `pkg-config`, and the real
  `:i386` packages (not a symlink) to combine x86 multilib support with
  the cross-compilers in one filesystem. README's own bare-metal
  install instructions get the same fixes, at the point a reader would
  actually hit them.
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

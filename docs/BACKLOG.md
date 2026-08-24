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
discipline **M4** applies to the `package.json` schema):

- `Port`/`Board`/`Variant` plus the `ports/*/boards/*/board.json` scan,
- `check_board_json`.

Do **not** take the port → Docker-image map or command construction: that
layer is exactly what **D3** wants `cibuildmp` to resolve itself, and it is
coupled to mpbuild's own CLI.

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

No separate float/precision field. Precision is already encoded in the arch
itself (`MP_NATIVE_ARCH_ARMV7EMSP` vs `…ARMV7EMDP` are distinct values, and
`MPY_FEATURE_ARCH` is selected from `__ARM_FP` at compile time). bclibc's
`MP_BCLIBC_PRECISION` / `_sp` / `_dp` suffixes are a *project-level source
define and module-naming convention*, not part of the `.mpy` ABI — they
belong in that project's own Makefile and, where CI must set them, in an
`extra-make-args` override.

Glob-friendly in both directions: `mpy6.3-*`, `*-armv7em*`, `*-x64`.

Usermod identifiers, when that phase lands, take the same shape with the
MicroPython release tag in the first slot, since a firmware image's identity
*is* its MicroPython version: `v1.28.0-usermod-esp32_ESP32_GENERIC`.

## Config schema (phase 1)

```toml
# cibuildmp.toml — repo root

micropython = "v1.28.0"       # release tag(s) to build against -- also
                              # accepts a list (D13): ["v1.22.0", "v1.28.0"]
output-dir = "mpyhouse"       # where built .mpy files land
build = "*"                   # glob(s) over identifiers, space-separated
skip = ""

[natmod]
archs = ["x64", "x86", "armv6m", "armv7m", "armv7emsp", "armv7emdp",
         "rv32imc", "rv64imc", "xtensa", "xtensawin"]
module-dir = "natmod"         # dir containing the Makefile
make-target = "dist"
extra-make-args = []
pre-build-command = ""        # run in module-dir after mpy-cross, before make
                              # (a7p: "make fetch-nanopb")

[[overrides]]
select = "*-armv7emsp"
extra-make-args = ["MP_BCLIBC_PRECISION=single"]
```

Every option is overridable by environment variable, `CIBMP_`-prefixed and
screaming-snake-cased: `CIBMP_BUILD`, `CIBMP_SKIP`, `CIBMP_MICROPYTHON`,
`CIBMP_OUTPUT_DIR`, `CIBMP_EXTRA_MAKE_ARGS`, … Precedence, lowest to highest:
defaults → config file → `[[overrides]]` matching the identifier →
environment → CLI flags.

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
Finding `gcc` on `PATH` proves nothing there, so the resolver compiles an
empty translation unit with `-m32` (a `probe-args` entry in the resource
file) and, on failure, errors naming `gcc-multilib` rather than letting the
build fail later with a confusing compiler diagnostic.

### M3 — the build itself — **done**

`src/cibuildmp/build.py`. Checked against cibuildwheel's own
`platforms/linux.py` rather than assumed: it is fail-fast per identifier too
(a `subprocess.CalledProcessError` from one platform config aborts the whole
invocation, no per-target continue-and-report), and its
`BuildProducedNoWheelError`/`RepairStepProducedMultipleWheelsError`/
`AlreadyBuiltWheelError` are the shape `collect_output()`/`verify_output()`/
the `seen_names` check below copy.

- [x] Run `pre-build-command` in `module-dir` (`shell=True`, matching what
      `build-natmod`'s own `pre_build_command` input already does).
- [x] Invoke `make -C <module-dir> ARCH=<arch> MPY_DIR=<…>
      PYTHON=<sys.executable> <extra-make-args> <make-target>` — `mpy_ld.py`
      resolves `pyelftools`/`ar` from `cibuildmp`'s own dependencies
      (**D12**), verified for real against a live `make dist` run, not just
      by inspection.
- [x] Collect the produced `.mpy` into `output-dir`, named unambiguously:
      `<module-stem>-<identifier>.mpy`, found by globbing
      `<module-dir>/build/<arch>*/*.mpy` — the layout `build-natmod`'s own
      artifact-upload step already assumes. Zero or more-than-one match is a
      `BuildError` naming what was found, cibuildwheel's
      `BuildProducedNoWheelError`/`RepairStepProducedMultipleWheelsError`
      shape. Two targets landing on the same output name within one
      invocation is also a `BuildError` (`AlreadyBuiltWheelError`'s
      equivalent), tracked in a `seen_names` set threaded through the loop.
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

### M4 — publish

- [ ] `cibuildmp publish` — absorb bclibc's `tools/build_release_assets.py`:
      emit flat, uniquely named assets plus a `package.json` using the
      per-entry native compat tag schema from
      [micropython#19532](https://github.com/micropython/micropython/pull/19532)
      / [micropython-lib#1144](https://github.com/micropython/micropython-lib/pull/1144).
- [ ] Keep relative `urls` (resolved by `mip` against wherever it fetched
      `package.json`), with `--repo` for absolute ones.
- [ ] **Isolate this behind one module.** The upstream schema is still a
      proposal; if it changes, exactly one file should need rewriting.

### M5 — adopt in the three repos

- [ ] `micropython-bclibc`, `a7p`, `micropython-wasm3`: repin every
      `uses:` path from `micropython-native-ci@v0.2.0` to
      `cibuildmp@v0.3.0` (**D11**) — mechanical, no behaviour change, and
      independent of everything else here, so it can go first.
- [ ] Archive `ballistics-lab/micropython-native-ci` once all three have
      repinned.
- [ ] The same three repos: replace the natmod
      matrix with `cibuildmp`. a7p is the interesting one — non-default
      `module-dir` (`micropython/natmod`) and a `pre-build-command`.
- [ ] Reduce `build-natmod` to a wrapper over `cibuildmp --only <id>` so
      there is one implementation of the toolchain logic, not two. Do not let
      the two coexist for long.

### Later — usermod

Not scheduled. Built on board data vendored from `mpbuild` (**D7**):
`cibuildmp` resolves the port → Docker-image map and build command itself
for `rp2`/`esp32`/`stm32`/etc., keeps the existing composite actions for the
ports mpbuild does not cover (`unix`, `windows`, `webassembly`), and treats
firmware as a verification output rather than a published artifact by
default.

### Later — tests

Not scheduled (**D6**). When it lands, the design is an explicit runner axis:
`native`, `qemu-user`, `qemu-system`, `node`, `rp2040py`, `mpremote`, `none`.
`mpremote` — tests on real hardware attached to a self-hosted runner — is the
one with no cibuildwheel analogue and the most value for embedded.

## Open questions

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

- Being a general MicroPython firmware builder — that is `mpbuild`.
- Compiling anything itself. `dynruntime.mk` and the project's Makefile own
  that (**D2**).
- Replacing `mpremote`/`mip` on the install side.

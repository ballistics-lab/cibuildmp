# cibuildmp — implementation backlog

`cibuildmp` is a `cibuildwheel`-shaped build driver for MicroPython native C
extensions: one declarative config in the module's own repo drives the whole
target matrix, resolves each target's toolchain itself, and runs identically
on a developer laptop and on CI.

This file is the plan. It records the decisions that are already locked, the
scheme they imply, and the order of work. It is not a changelog — see
`CHANGELOG.md` for what actually shipped.

## Positioning

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
- installing `mpy_ld.py`'s host deps (`pyelftools`, `ar`),
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

**D7 — usermod will be built on `mpbuild`, not reimplemented.**
[`mattytrentini/mpbuild`](https://github.com/mattytrentini/mpbuild) (PyPI
`mpbuild`, 1.2.0) already builds any port/board in per-port Docker images and
carries a board database. Verified constraints: it requires a MicroPython
*git checkout* (its `board_database` scans `ports/*/boards`), it is
Docker-only, and it has no natmod support whatsoever. So it is complementary,
not competing — `cibuildmp` owns the natmod path mpbuild does not have, and
drives mpbuild for firmware.

**D8 — distribution of the tool itself is deferred.**
The PyPI name `cibuildmp` is currently free (404 on the JSON API) but is not
reserved yet. Until it is, `action.yml` installs from the action's own ref:
`uv tool install git+https://…@<ref>` or `uv tool install .`. The current
`uv tool install cibuildmp` line in `action.yml` is a placeholder and must be
changed before the action is usable.

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

micropython = "v1.28.0"       # release tag to build against
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

## Phases

### M0 — skeleton

- [ ] Replace the `main()` stub with a real CLI: `cibuildmp [--config-file]
      [--output-dir] [--only ID] [--print-build-identifiers] [--platform]`.
- [ ] Config loader: `cibuildmp.toml` → `pyproject.toml [tool.cibuildmp]`
      fallback; env-var layer; `[[overrides]]` resolution.
- [ ] Identifier generation + `build`/`skip` glob filtering.
- [ ] `--print-build-identifiers` emitting JSON, suitable for
      `strategy.matrix` via `fromJSON`.
- [ ] Fix `action.yml`'s install line per **D8**.

`--print-build-identifiers` alone removes the duplicated matrix from all
three repos. It is worth releasing on its own, before any build logic exists.

### M1 — MicroPython + mpy-cross provisioning

- [ ] Fetch MicroPython at the configured tag. Tarball by default (it vendors
      every port's `lib/`, so no submodule init — same reasoning as
      `fetch-micropython`); shallow clone as an option. No `wget` dependency:
      use `urllib` so it works on any host.
- [ ] Cache the checkout under `~/.cache/cibuildmp/micropython/<tag>/`, keyed
      and reused across targets — currently every matrix leg refetches.
- [ ] Build `mpy-cross` once per checkout, cached alongside it.
- [ ] Read `MPY_VERSION`/`MPY_SUB_VERSION` out of `py/persistentcode.h` to
      derive the ABI slot of the identifier.

### M2 — toolchain resolver

- [ ] Resolver interface: given an identifier, return an environment
      (`CROSS_COMPILE`, `PATH` additions) or raise a clear "not available
      here" error.
- [ ] Strategies in priority order: `host` (already on `PATH` — always tried
      first, and the whole story for `x64`), `download` (tarball into
      `~/.cache/cibuildmp/toolchains/<name>/<version>/`), `docker` (opt-in).
- [ ] `--toolchain=host|download|docker` to force one.
- [ ] arm-none-eabi tarball source + pinned version.
- [ ] riscv tarball source + pinned version, **picolibc verified**.
- [ ] xtensa-lx106 tarball (port the URL from `build-natmod`).
- [ ] xtensa-esp32 standalone tarball (see the ESP-IDF finding above).
- [ ] Checksum verification for every download.

### M3 — the build itself

- [ ] Install `mpy_ld.py`'s host deps (`pyelftools`, `ar`) into an isolated
      env, not the system interpreter.
- [ ] Run `pre-build-command` in `module-dir`.
- [ ] Invoke `make -C <module-dir> ARCH=<arch> MPY_DIR=<…> <extra-make-args>
      <make-target>`.
- [ ] Collect the produced `.mpy` into `output-dir`, named unambiguously.
      Every arch's build otherwise emits the same basename — flatten using
      the file's own header, not the build-dir name (the approach already
      proven in bclibc's `tools/build_release_assets.py`).
- [ ] Verify each output's header arch against the requested identifier and
      fail loudly on mismatch. This is `cibuildmp`'s equivalent of
      `auditwheel`: cheap, and it catches a whole class of "built the wrong
      thing into the right directory" bugs.
- [ ] Readable per-target logging and a summary table.

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

- [ ] `micropython-bclibc`, `a7p`, `micropython-wasm3`: replace the natmod
      matrix with `cibuildmp`. a7p is the interesting one — non-default
      `module-dir` (`micropython/natmod`) and a `pre-build-command`.
- [ ] Reduce `build-natmod` to a wrapper over `cibuildmp --only <id>` so
      there is one implementation of the toolchain logic, not two. Do not let
      the two coexist for long.

### Later — usermod

Not scheduled. Built on `mpbuild` (**D7**): drive it for `rp2`/`esp32`/
`stm32`/etc., keep the existing composite actions for the ports mpbuild does
not cover (`unix`, `windows`, `webassembly`), and treat firmware as a
verification output rather than a published artifact by default.

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
- **`micropython` as a list.** The draft config has `mpy_tags` as an array.
  Building one module against several MicroPython tags is a real use case
  only when they span an ABI boundary; otherwise it produces identical
  output. Start with a single tag; revisit when a second ABI is in play.
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

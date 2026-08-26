# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Every usermod identifier now carries the MicroPython release, and
  natmod's `mpy-abi` can name the ABI axis directly.**
  `unix-manylinux_2_28_x86_64` becomes
  `v1.29.0-unix-manylinux_2_28_x86_64`. Before this, usermod's
  `micropython` was silently truncated to its first entry whenever more
  than one was configured -- the only thing standing between a two-tag
  config and one release's output silently overwriting the other's,
  since nothing distinguished them: not the identifier, not the output
  filename, not the directory. `micropython` is a real list now, and a
  second tag gets its own output. natmod gets the same axis from the
  other direction: `mpy-abi = ["6.3", "6.2"]` states the ABIs to build
  directly, each resolved to its own newest known MicroPython tag,
  rather than only being derivable by supplying tags and letting the ABI
  fall out (still supported, unchanged). `select()`/`matches()`/
  `parse_selector()`, previously hand-duplicated between the two modes,
  now live once in `cibuildmp/selector.py`, which also gained brace
  expansion (`cp{36,37}-*`-style globs), matching upstream. Record 0051
  (partial -- moving `--platform` to mean the port landed later the same
  day; see below).
- **usermod gained its own `[[usermod.overrides]]`, and both modes gained
  opt-in groups (`--enable`/`enable`).** `[[usermod.overrides]]` layers
  `module-dir`/`manifest`/`extra-make-args` per target
  (`file -> matching override -> environment`), nested under `[usermod]`
  rather than shared with natmod's own top-level `[[overrides]]`, since
  the two modes' override tables take different keys. Opt-in groups
  (upstream's own `EnableGroup`): a target matching an unenabled group is
  excluded before `build`/`skip` is even checked, and `--enable
  <name>`/`enable = [...]` is what reaches it -- naming it in `build`
  alone cannot. The concrete first group,
  `unix-emulated-everywhere` (`ppc64le`/`s390x`/`riscv64`, both libcs),
  answers this file's own "stay opt-in" line above properly: those three
  cells are in the `unix` axis now (`default_axis_values("unix")` is the
  full fifteen), not held out of it, and it is the group -- reachable
  without editing a config's own `archs` -- that keeps a bare `build =
  "*"` at nine cells by default, same as before. One narrow, deliberate
  behaviour change: `--archs all` alone no longer reaches those three
  archs, matching upstream's own precedent (`CIBW_ARCHS=all` does not
  alone build `pypy` either). Record 0051.
- **`--platform` names a platform, not a build mode, and `[usermod]` is
  gone.** `[usermod.<port>]` becomes `[<port>]` -- `[unix]`, `[windows]`,
  `[qemu]`, `[webassembly]`, `[esp32]` -- a top-level table sibling to
  `[natmod]`, exactly like `[natmod]`'s own shape; `ports = [...]` no
  longer exists as a concept, a port's own table presence is what selects
  it. **Breaking**: any config still using `[usermod]` now fails loudly,
  naming the exact migration, with no deprecation window (`examples/template`,
  this repo's own included, migrated in the same commit); the old
  single-mode spelling `--platform usermod` is rejected the same way any
  other unknown platform name is (`--platform natmod` still works, since
  `natmod` is a real platform name now). The headline new capability:
  **more than one platform can build in a single invocation**, with no
  `--platform` needed at all -- unlike cibuildwheel's own platforms
  (bound to host OS), cibuildmp's six are just Docker images on one host,
  so nothing forces one platform per invocation. `--platform`/
  `CIBMP_PLATFORM` becomes an optional, comma- or space-separated filter
  over the six platform names instead. `module-dir`/`manifest`/
  `extra-make-args` (natmod also `make-target`/`pre-build-command`) are
  genuinely shared-with-per-platform-override now, resolved through
  `cibuildmp/options.py`'s cascade; `[[usermod.overrides]]` is renamed to
  a top-level `[[usermod-overrides]]` (still not merged with natmod's own
  `[[overrides]]` -- that unification is record 0051's own next phase).
  Record 0051 (Phase F).
- **One shared `[[overrides]]` list, and `inherit`.** Natmod's own
  `[[overrides]]` and `[[usermod-overrides]]` (above) merge into one
  top-level `[[overrides]]`, shared by every platform. `inherit =
  {extra-make-args = "append"|"prepend"|"none"}` is real now (default
  `"none"`, unchanged behaviour for every override written before this):
  the one option genuinely list-shaped across every platform's own
  override surface can compose onto the running value instead of always
  replacing it outright. An override's own key is validated twice --
  loosely (is it valid for *any* platform) when the config loads, and
  strictly (is it valid for the platform the matched identifier actually
  belongs to) once a target resolves -- so a `natmod`-only key inside an
  override that only ever matches a `unix` identifier is still a loud,
  specific error, not silently ignored. `natmod.targets.Target` gained a
  `.port` property (always `"natmod"`) to make the strict check possible
  for natmod too. Record 0051 (Phase G).
- **natmod builds in a container, and there is no bare-host path.** It used to
  resolve a toolchain onto the invoking machine -- an apt probe, a pinned
  tarball, or the host gcc's own 32-bit multilib -- and run `make` there. One
  `linux/amd64` image now carries all ten `dynruntime.mk` toolchains under
  exactly the prefixes it expects. The visible consequence: **`x86` builds on an
  arm64 runner**, which it could not before, because inside the image the host
  is amd64 by construction. Record 0050.
- **The default MicroPython release is `v1.29.0`** (was `v1.28.0`). Its `.mpy`
  ABI is 6.3, unchanged, so no identifier moves. v1.29.0 also changed
  `dynruntime.mk`'s `x86` from `-m32` to `CROSS = i686-linux-gnu-`; the image
  carries both spellings, since `micropython` accepts a list of tags that can
  span the change.
- **`pre-build-command` runs inside the build's own container**, the shape
  cibuildwheel's `before-all` has. It therefore runs unprivileged and cannot
  install system packages -- a project that needs a tool should fetch it, as
  `examples/wasm2mpy` now does for `wabt`.
- **`esp32` is no longer in the default port set.** It is the one port with no
  Dockerfile and no pinned image, so it is also the one that cannot satisfy the
  Docker-only rule; its build provisions ESP-IDF onto the host. Still a real
  identifier, still reachable with `--only`, still built by a config that names
  it.
- `qemu` runs in its published image like every other port (record 0032, closed
  by 0050).

### Removed

- **`--toolchain`, and the toolchain resolver behind it.** Every question it
  answered -- is a compiler for this arch here, where is one fetched from, does
  its prefix match what `dynruntime.mk` hardcodes -- is answered by the natmod
  image. `resources/natmod.toml`'s `[[toolchain]]` table went with it; those
  pins live in `docker/natmod.Dockerfile` now, and are sha256-checked at image
  build, which the table's own hashes had stopped protecting anything.
- **Matrix generation.** `--print-build-matrix`, `Target.default_runner` /
  `UsermodTarget.default_runner`, natmod's `runs-on` config key and the
  `.github/actions/cibuildmp-matrix` composite action are gone. cibuildwheel
  has no equivalent of any of them: it emits no matrix and holds no opinion
  about which host a target should run on, because `runs-on` is the
  consumer's own workflow's business. cibuildmp had grown the opposite --
  a tool that routed targets to hosts -- and that routing was also why CI
  had never once exercised a build on a host it was not native to. See
  record 0049.

### Added

- **`--archs auto` / `native` / `all` for usermod**, and an `archs:` input on
  the root action. This is what replaces matrix generation, and it is
  upstream's own mechanism for spreading work across runners: give each job
  in your own matrix a `runs-on` and `archs: auto`, and each one builds what
  it is native to. `native` is the runner's own architecture, `auto` adds
  the 32-bit sibling it can execute directly, `all` is every cell. Keywords
  work in `[usermod.<port>] archs` too, and can be mixed with explicit
  names.

  Nothing is unbuildable on the "wrong" runner: every build runs in a
  container with an explicit `--platform`, so a non-native cell builds under
  emulation wherever it lands. `archs` is a choice about time, not about
  capability.
- `verify_windows_output()` — reads the COFF `Machine` out of the produced
  `micropython.exe` and rejects a binary that is not the architecture its
  identifier names. `windows` previously checked only that the file existed.
- **The four native `musllinux` cells are in the default `unix` axis**
  (`x86_64`, `i686`, `aarch64`, `armv7l`), so a bare `ports = ["unix"]` is nine
  cells rather than five. They are the musl cells with a runner they are native
  to; the other three are emulated everywhere and stay opt-in.
- `windows` joined `examples/template`'s own `ports` and is verified on every
  push.
- A `workflow_dispatch` input on `publish-docker-images.yml` to republish one
  image instead of all nineteen.

## [0.3.0] - 2026-08-24

First release where `cibuildmp` actually builds a module — `v0.3.0a1` could
only plan the target matrix. Validated against three real consuming repos
(`micropython-bclibc`, `a7p`, `micropython-wasm3`), all natmod and usermod
workflows green on every arch, including the RISC-V toolchain fix below.

### Added

- **`cibuildmp` can now actually build natmod targets**, not just plan them:
  `cli.build()` runs each target's `pre-build-command`, invokes
  `make -C <module-dir> ARCH=<arch> MPY_DIR=<…> PYTHON=<sys.executable>
  <extra-make-args> <make-target>`, collects the produced `.mpy` from
  `<module-dir>/build/<arch>*/`, and verifies its header's native-arch code
  (and, for `rv32imc`, its arch-flags — **D15**) against the requested
  identifier — `cibuildmp`'s `auditwheel` equivalent. Ends with a
  per-target `done in Ns` line and a summary table. See
  [`docs/BACKLOG.md`](docs/BACKLOG.md) M3 and **D12**.
- **Every target gets its own `output-dir/<identifier>/` directory and,
  once `version` is set, a `package.json` mip can install straight from**
  (**D14**) — no separate `cibuildmp publish` command; `cli.build()`
  writes it as part of the normal build, the same way cibuildwheel has no
  publish step and `wheelhouse/*` is immediately `twine upload`-able.
  `[publish] extra-files` copies a facade or any other file meant to
  install regardless of target arch into every identifier's directory too
  (found via `../micropython-bclibc`'s `ffimod/`). `package.json`'s `urls`
  install the file under its own clean name (e.g. `template.mpy`, what
  `import template` needs on-device) from the identifier-qualified,
  collision-safe filename actually sitting next to it
  (`template-mpy6.3-natmod-x64.mpy`).
- `pyelftools`/`ar` are now `cibuildmp`'s own dependencies (**D12** in
  `docs/BACKLOG.md`) rather than something installed at build time: both are
  pure-Python packages `tools/mpy_ld.py` itself needs, and `PYTHON=` on the
  `make` command line points it at the interpreter that already has them.
- **`micropython` accepts a list, not just a string** (**D13**), to cover
  more than one `.mpy` ABI from one config: `micropython = ["v1.22.0",
  "v1.28.0"]`. Tags are deduped by the ABI they resolve to, keeping
  whichever came first — building against two tags only produces different
  output when they cross an ABI boundary, otherwise it's the same native
  `.mpy` twice. `cli.build()` fetches MicroPython and builds `mpy-cross`
  once per distinct ABI group rather than once per invocation.
- **`rv32imc`'s `ARCH_FLAGS=` is now part of the identifier** (**D15**):
  `arch-flags = "zba,zcmp"` (or a numeric string, matching `mpy_ld.py`'s
  own `validate_arch_flags()`) produces `mpy6.3-natmod-rv32imc+0x3`.
  Verified live against a real `riscv-none-elf-gcc` build, not just a
  synthetic header: the produced `.mpy`'s own arch-flags round-trip
  through `verify_output()` correctly. Also accepts a list --
  `arch-flags = ["", "zba", "zba,zcmp"]` builds every variant as its own
  `rv32imc` identifier in one invocation, the same "build every X" shape
  `archs`/`micropython` already have.
- `examples/template` and `examples/wasm2mpy` — real natmod modules, both
  built by this repo's own `action.yml` in
  `.github/workflows/build-examples.yml` on every push and PR.
  `wasm2mpy`'s native source is WebAssembly (vendored from
  [`vshymanskyy/wasm2mpy`](https://github.com/vshymanskyy/wasm2mpy), MIT,
  see `examples/wasm2mpy/NOTICE`), compiled to C via `wasm2c` before the
  same `dynruntime.mk` flow every other natmod uses takes over — proof the
  natmod contract (**D2**) is genuinely source-language-agnostic, not just
  validated against a plain-C example. Builds for 7 of its 8 documented
  arches; `xtensa` (ESP8266) is left out with a comment in
  `examples/wasm2mpy/cibuildmp.toml` explaining why (a real symbol clash
  between the vendored `esp8266-rom.S` and `LINK_RUNTIME=1`, not a
  `cibuildmp` bug). cibuildmp's own integration test: green here means the
  real build path (M3) works end to end, not just that `--dry-run` prints
  a plausible plan.

### Changed

- `docs/BACKLOG.md` **D7** — usermod now vendors `mpbuild`'s board-database
  module rather than depending on the `mpbuild` package, which would have
  pulled `rich`/`textual`/`typer` and Python ≥3.12 onto a build driver that
  has stayed standard-library-only otherwise.

### Fixed

- `run_make()` passed both `-C <module-dir>` in the command *and*
  `cwd=<module-dir>` to `subprocess.run` — redundant when `module-dir` is
  absolute, broken when it's relative (the common case: `package_dir`
  defaults to `.`), since the process would chdir there and then `-C`
  would look for `<module-dir>` nested inside itself. Found by actually
  running `cibuildmp` against `examples/template`, not just by unit tests
  that mocked `subprocess.run` entirely.
- `.gitignore` had a blanket `**/*.c`, left over from before this repo had
  any real C source of its own — it silently excluded
  `examples/template/natmod/template.c`. Narrowed to natmod's own build
  byproducts (`**/build`, `*.mpy`, `.mpy_ld_cache`) instead.
- `dynruntime.mk` defaults `BUILD ?= build`, not scoped by `$(ARCH)` — a
  real problem only under `cibuildmp`'s own default (`--only`-less)
  invocation, which runs every target sequentially in one `natmod/` tree
  (**D9**): a second `ARCH=` found the first arch's own object files "up
  to date" and skipped rebuilding, so the merged `.mpy` silently stayed
  the first arch's binary. Not a `cibuildmp` code fix (the consuming
  Makefile owns `BUILD`), but real enough to need documenting as a
  requirement: `examples/template/natmod/Makefile` now sets
  `BUILD = .obj/$(ARCH)`, and README.md's "Conventions this repo assumes"
  says so for every other natmod Makefile too.
- The `x86` toolchain probe compiled an *empty* translation unit, which
  `-m32` always accepts even with the 32-bit glibc headers/libs entirely
  missing — so it reported `x86` buildable on a bare `ubuntu-latest`
  runner, and the real build then failed deep inside `dynruntime.mk`
  with `bits/wordsize.h: No such file or directory` instead of the clear
  "install gcc-multilib" error this probe exists to give. Now compiles
  and links `#include <stdio.h>\nint main(void) { return 0; }`, which
  actually exercises the missing header chain.
- `.mpy` header arch decoding was an unmasked `header[2] >> 2` —
  `py/persistentcode.h`'s own `MPY_FEATURE_DECODE_ARCH` masks with
  `0x2F` after the shift to exclude the arch-flags marker bit (bit 6).
  Without the mask, `rv32imc` (native-code 11) with that bit set decoded
  as 27. Latent until **D15** added a real way to set that bit; caught
  while implementing it, before it ever affected a real build.
- The `BUILD=` scoping fix noted above (`BUILD = .obj/$(ARCH)`) only
  accounted for `$(ARCH)`, not `$(ARCH_FLAGS)` — building **D15**'s
  `arch-flags` list back to back in one invocation reused the first
  variant's cached `.o`/`.mpy` for every later one, since `$(ARCH)` never
  changes across those targets and `rv32imc`'s own object file doesn't
  depend on `ARCH_FLAGS` at all. Same bug, second axis; found the same
  way, by actually running the variant list rather than trusting the
  single-value case already worked.
  `examples/template/natmod/Makefile` now scopes
  `BUILD = .obj/$(ARCH)$(if $(ARCH_FLAGS),+$(ARCH_FLAGS))`.
- `riscv-none-elf` was the one toolchain in `resources/natmod.toml` with no
  pinned `sha256` — it relied on fetching xpack's own `<asset>.sha` sidecar
  at runtime instead, unlike `arm-none-eabi`/`xtensa-lx106-elf`/
  `xtensa-esp-elf`, which all pin literally. A real CI run (a cold-cache
  `rv64imc` build in `ballistics-lab/micropython-bclibc`'s own natmod.yml)
  hit `riscv-none-elf: no pinned sha256 and its .sha sidecar is unavailable
  (HTTP Error 500: Internal Server Error)` — a transient GitHub
  release-asset failure with nothing here to retry it, and every other
  arch in the same job matrix went green regardless, since none of them
  depend on that second live network call. Pinned literally now too
  (cross-checked: the sidecar's own published digest against a fresh
  `sha256sum` of the tarball itself, not copied blind), removing the
  runtime fetch entirely rather than adding a retry around it.

## [0.3.0a1] - 2026-08-24

First alpha. Ships the composite actions unchanged and the first working
slice of the `cibuildmp` CLI; the CLI cannot build a module yet, so the
actions remain the supported path for every target.

### Changed

- **This project moved to `ballistics-lab/cibuildmp` and absorbed
  `ballistics-lab/micropython-native-ci` entirely.** Every composite action
  is here now, unchanged in behaviour, inputs and outputs — only the repo in
  the `uses:` path differs. The old repository is deprecated and will be
  archived once its consumers have repinned; the version line continues
  rather than restarting, so this release's actions are `v0.2.0`'s, moved.

  ```diff
  - uses: ballistics-lab/micropython-native-ci/.github/actions/build-natmod@v0.2.0
  + uses: ballistics-lab/cibuildmp/.github/actions/build-natmod@v0.3.0
  ```

### Added

- **`cibuildmp`, a CLI** that builds a module's whole natmod target matrix
  from one `cibuildmp.toml`, on CI and locally alike — `cibuildwheel` for
  MicroPython. See [`docs/BACKLOG.md`](docs/BACKLOG.md) for the design
  decisions behind it. Implemented so far:
  - Target selection: build identifiers shaped `mpy6.3-natmod-armv7emsp`
    ({.mpy ABI}-{mode}-{arch}), `build`/`skip` globs, a single
    `[[overrides]]` mechanism, `CIBMP_*` environment overrides, and
    `pyproject.toml [tool.cibuildmp]` as a fallback config location.
  - MicroPython and `mpy-cross` provisioning, cached under
    `~/.cache/cibuildmp/`. Uses the release *asset* tarball (which vendors
    every `lib/` submodule) with a shallow-clone fallback for refs that
    publish none, and `urllib` rather than `wget` — which is what made
    `fetch-micropython` unusable on a Windows runner outside MSYS2.
  - Cross-toolchain resolution: already on `PATH` first, then a pinned,
    checksummed tarball into the cache. **`xtensawin` no longer needs
    ESP-IDF** — `dynruntime.mk` only ever wanted `xtensa-esp32-elf-` on
    `PATH`, so the toolchain is fetched straight from
    `espressif/crosstool-NG` releases instead of cloning IDF to run its
    installer.
  - `--print-build-identifiers`, `--print-build-matrix`, `--dry-run`,
    `--only`, `--archs`, `--toolchain`, `--clean-cache`, `--allow-empty`,
    `--debug-traceback`.
- `action.yml` at the repo root — installs and runs `cibuildmp`.
- `.github/actions/cibuildmp-matrix` — resolves a config into a
  `strategy.matrix` of `{only, os}` entries. Optional: the default layout is
  one job looping over every target, since all ten natmod arches
  cross-compile on the same runner.

### Not yet implemented

- Running the per-target build and collecting the `.mpy` files. Until that
  lands, the composite actions remain the supported path for every target.


## [0.2.0] - 2026-08-24

### Added

- `variant` input on `build-usermod-unix` (default `standard`) — needed so
  `o-murphy/a7p`'s `usermod-cross` job could use the action (it originally
  built `VARIANT=coverage`; later switched to `standard` for consistency
  with every other unix row, but the input stays for whatever future
  caller genuinely needs a non-default variant).
- `build-usermod-windows` — the `ports/windows` usermod build (MSYS2
  setup and the MicroPython tarball fetch stay caller-side, since a
  composite action's own `shell: bash` steps can't bootstrap MSYS2 for
  themselves and have no `wget`). Carries the four CLANGARM64-only
  overrides (`LDFLAGS_ARCH`, `COMPILER_TARGET`, `STRIP`/`SIZE`) needed
  for `windows-11-arm`, transplanted from a proven `o-murphy/a7p` /
  `o-murphy/micropython-wasm3` recipe. Also gained a `variant` input
  (default `''`, omitted from the command line unless set) for the same
  forward-compatibility reason as `build-usermod-unix`'s.
- `build-usermod-webassembly` — the `ports/webassembly` usermod build:
  installs emsdk, builds `mpy-cross`, runs the port build. Adds
  `emsdk_ref` (default `latest`, matching every caller and upstream's own
  `tools/ci.sh`). Deliberately does **not** combine `FROZEN_MANIFEST`
  with the port's own default (`variants/<variant>/manifest.py`) itself
  — see its own header for why that has to stay a caller-side step.
- `build-usermod-rp2040` — the `ports/rp2` usermod build. Adds
  `extra_cmake_args`, absent from the sibling actions: `ports/rp2`'s own
  Makefile builds `CMAKE_ARGS` with `+=`, so a define passed on the
  `make` command line replaces the whole accumulated set instead of
  adding to it. `o-murphy/micropython-wasm3`'s own rp2 row needs exactly
  this (`-DMICROPY_C_HEAP_SIZE=131072`) via a two-step configure,
  generalized here so that row could wire onto this action too.
- `build-usermod-armv7m` — the `ports/qemu` usermod build (default
  `BOARD=MPS2_AN385`, a Cortex-M3). QEMU itself is deliberately **not**
  installed here — it's a runtime emulator for testing the resulting
  `firmware.elf`, not a build dependency, same split `build-usermod-rp2040`
  already uses for the rp2040py emulator.
- `build-usermod-esp32` — the `ports/esp32` usermod build: installs
  ESP-IDF, builds `mpy-cross`, runs the port build. `idf_target` and
  `board` are separate inputs, not derived from one another (`install.sh`'s
  argument is the chip family, `BOARD=` is the actual MicroPython board
  definition — more than one board can exist per chip family). Folds in a
  "Dump the IDF build logs on failure" diagnostic universally (idf.py's
  own console output swallows the real compiler error on a failing
  build — found on `o-murphy/micropython-wasm3`'s own job first).
- Full Markdown input/output reference tables for every action in
  `README.md`, replacing the previous prose-only coverage.

### Changed

- Dropped the `-arch` suffix from every action whose name carried it:
  `build-natmod-arch` → `build-natmod`, `build-usermod-unix-arch` →
  `build-usermod-unix`, `build-usermod-windows-arch` →
  `build-usermod-windows`, `build-usermod-webassembly-arch` →
  `build-usermod-webassembly`. `arch:` as an input already signals
  per-architecture dispatch on its own (`build-natmod`,
  `build-usermod-unix` both still take one) — the suffix added nothing
  there, and on actions with no `arch:` input at all it was never
  anything but copied naming. Consumers still pinned to the `v0.1.0` tag
  (an immutable point that predates this rename) keep using the old
  `-arch`-suffixed names for `build-natmod-arch` until they repin to
  `v0.2.0` or later.
- `build-usermod-qemu-armv7m` (the name it launched under) renamed again,
  almost immediately, to `build-usermod-armv7m`: QEMU is a runtime test
  mechanism this action never installs or touches (see its own entry
  above), so it shouldn't be part of the action's identity either — the
  same reasoning that already kept rp2040py out of
  `build-usermod-rp2040`'s name.

### Fixed

- `build-usermod-esp32`: dropped its `build_dir` input entirely after a
  real CI failure on `ballistics-lab/micropython-bclibc`'s first run —
  passing `BUILD=` explicitly on the `make` command line, even set to
  the exact value the port already defaults to (`build-$(BOARD)`), made
  esp32's *internal* CMake-driven `mpy-cross` sub-build (a separate copy
  from the top-level `$MPY_DIR/mpy-cross` this action pre-builds) pick
  up `FROZEN_MANIFEST` through `MAKEFLAGS` and fail with `undefined
  reference to mp_qstr_frozen_const_pool`. The usual pre-build-mpy-cross-first
  fix (used successfully by every other action here) doesn't reach this:
  it prevents `py/mkrules.mk`'s own auto-build rule from firing, but
  esp32's copy is CMake's, a different mechanism entirely. Every real
  caller already wanted the port's own default anyway, so the lost
  override capability costs nothing in practice.

## [0.1.0] - 2026-08-23

### Added

- `fetch-micropython` / `clone-micropython` — get a MicroPython release
  ready and export `MPY_DIR`.
- `build-natmod-arch` — install whatever toolchain a `dynruntime.mk` ARCH
  needs and build its natmod `.mpy`.
- `build-usermod-unix-arch` — the unix-port cross-compile matrix
  (x64/x86/aarch64/armhf/mipsel) for a `USER_C_MODULES` usermod.

Composite GitHub Actions extracted from `ballistics-lab/micropython-bclibc`,
`o-murphy/a7p` and `o-murphy/micropython-wasm3`, which had each
hand-copied and then independently drifted on the same
toolchain-install and MicroPython-checkout logic. Verified against real
CI on all three consuming repos before this squash: bclibc (natmod +
usermod), a7p (natmod), micropython-wasm3 (natmod + usermod) all green.

<!-- Comparison links. v0.1.0 and v0.2.0 were cut in
ballistics-lab/micropython-native-ci, but both tags exist here too, so every
link resolves inside this repository -- the version line continues rather
than restarting (see the 0.3.0a1 entry). -->

[Unreleased]: https://github.com/ballistics-lab/cibuildmp/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/ballistics-lab/cibuildmp/compare/v0.3.0a1...v0.3.0
[0.3.0a1]: https://github.com/ballistics-lab/cibuildmp/compare/v0.2.0...v0.3.0a1
[0.2.0]: https://github.com/ballistics-lab/cibuildmp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ballistics-lab/cibuildmp/releases/tag/v0.1.0

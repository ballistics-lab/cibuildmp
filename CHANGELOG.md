# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **`docs/reference/*.md` audited claim by claim against the source**, which
  found six things no mechanical check can catch. `design.md` still carried the
  false `a7p unix-mipsel` claim record 0076 corrected in three other files; it
  stated the per-target precedence chain two different ways, both wrong, in one
  file; it documented `arch-flags` as a string when it is a list (and an axis —
  each entry is its own target); it counted usermod's override keys as three
  when there are four; and its toolchain map gave `x64`/`x86` no `CROSS` prefix,
  true up to v1.28.0 and false from v1.29.0. `open-questions.md`'s first entry
  asked how MSYS2/ESP-IDF fit a toolchain-strategy shape record 0050 deleted,
  and its second cited a workflow that no longer exists. The toolchain map is
  generated now, since it is a per-tag fact no single hand-written table can
  state correctly. Record 0077.
- **`bin/refresh_docs.py` generates the doc tables that are pure functions of
  the resource files** — README's identifier-shape table and
  `docs/reference/vendored-images.md`'s port/arch → image-group mapping, each
  between a `<!-- generated: … -->` marker pair. `tests/test_docs.py` fails the
  build if either is out of date, so these cannot drift rather than merely being
  checked for drift. Every identifier example is now picked from a real row at
  that port's own newest stable tag instead of composed from the format string:
  a composed example can be well-formed and still name nothing, which is exactly
  what `design.md` had shipped. The mapping is also exhaustive now (all fifteen
  usermod ports, not the subset kept up by hand), and a group no published image
  backs is marked inline. Record 0077.
  - One more stale number, removed rather than refreshed: README claimed
    `test-all-platforms.yml` covers "83 real `esp32` identifiers and 74 real
    `rp2` ones". That was a two-tag slice; the totals are now 442 and 374,
    because each new MicroPython tag adds a whole board set. The matrix already
    says "every row", which is the durable statement.
- **Docs drift now fails the build.** `tests/test_docs.py` checks the living
  docs (`README.md`, `docs/ACTIONS.md`, `docs/reference/*.md`) against the
  source they describe: identifiers must exist in `build-platforms.toml`,
  README's own option table must equal `FAMILIES`' `OPTION_KEYS` in both
  directions, `CIBMP_*` names must be read by something, repo paths must exist,
  image groups must be in `pinned_docker_images.toml`, and record links must
  resolve. It runs in the existing pytest job — no new workflow step.
  `docs/records/` is deliberately excluded: a record is correct as history even
  when the state it describes is long gone. Record 0077.
  - Found on its first run, both fixed here: `docs/reference/design.md` claimed
    a usermod identifier is `{tag}-{port}`/`{tag}-{port}-{axis}` and gave
    `v1.29.0-unix-manylinux_2_28_x86_64` and `v1.29.0-webassembly` as examples —
    neither exists, since `unix`/`windows`/`webassembly` all use a bare
    `{tag}-{arch}` with no port segment and only board ports carry one; and
    fifteen record numbers across `docs/ACTIONS.md`, `docs/reference/design.md`,
    `CHANGELOG.md` and `CLAUDE.md` were cited with no link definition, rendering
    as literal `[0043]`.

- **`README.md` now documents how to actually configure the thing**: a
  `Configuration` section covering where the config file is looked for and in
  what order, the flat key/`[override]`/`[publish]` shape, a table of all
  fourteen option keys with defaults and which family reads each, the full
  `CIBMP_*` environment surface (option forms, the per-platform
  `CIBMP_BUILD_<PLATFORM>` form, and the machinery variables that have no
  config-file counterpart), and — the part nothing stated anywhere before —
  the two distinct precedence chains. Invocation-wide options resolve
  `default → file → env → CLI`; per-target options resolve
  `default → file → matching [override] → env`, so an environment variable
  beats an `[override]` while a CLI flag beats an environment variable. Every
  claim in the section was checked by running it, not read off the source:
  that is how the `CIBMP_BUILD_<PLATFORM>` behaviour got documented correctly
  — it does not replace the global selection, it scopes one platform's own
  alongside it.
- Every record number cited in `README.md` is now a working link. They were
  bare bracketed text with no reference definition, rendering as a literal
  `[0043]`.

- **An unrecognised scalar key at the top level of `cibuildmp.toml` is now an
  error**, with a close-match suggestion — `buidl = "..."` answers "Perhaps you
  meant `build`?". Previously only unknown *tables* were caught; an unknown
  scalar key (`micropython =`, retired back in record 0052, or any typo) was
  read as simply absent, its default silently applying, and the build succeeded
  having ignored the line you wrote. Every family module now declares its own
  `OPTION_KEYS` and the CLI unions them across `FAMILIES`, so no key list lives
  in `cli.py`. `[[name]]` array-of-tables syntax is now recognised as a table by
  the sibling table check too, rather than falling through to this one. Record
  0075.

### Fixed

- **Docs: the reason given for keeping the legacy composite actions named the
  wrong repository.** Record 0073's rewrite of `README.md`/`docs/ACTIONS.md`
  said `a7p`'s own `unix-mipsel` cell was the one remaining dependency on
  `.github/actions/*`, citing record 0067. `a7p` uses no composite action at
  all, 0067 is about something else entirely, and the claim was already untrue
  when written. The real `build-usermod-unix` holdouts are `micropython-bclibc`
  and `micropython-wasm3`, both of which also use `fetch-micropython` far more
  widely than the mipsel story suggested. No code change. Record 0076.

### Removed

- **`[usermod]`, the shared-defaults table for every usermod port at once.** No real
  config in this project's own examples ever actually wrote it (checked directly, not
  assumed) — the family-tier cascade layer it alone populated is deleted from
  `cibuildmp.options.Options` entirely, not just left empty. `user-c-modules`/
  `manifest`/`extra-make-args` are plain top-level keys now; narrow one port at a time
  through `[override."<glob>"]` instead. A stray `[usermod]` table is now an ordinary
  "unknown table(s) at the top level" error, the same as any other unrecognised name.
  Record 0074.
- **The dedicated "no longer exists, move X here instead" error message for
  `[natmod]`/`[unix]`/`[windows]`/`[qemu]`/`[webassembly]`/`[esp32]`.** These six tables
  are still rejected — as ordinary unknown top-level tables — but no longer explain what
  replaced them individually; `build`/`skip`/`[override."<glob>"]` has been the only real
  mechanism since record 0052, and all three consuming repos have long since migrated
  onto it. Record 0074.

## [0.4.2] - 2026-08-31

### Added

- **`{micropython}` — a placeholder in `user-c-modules` for a path inside the pinned
  MicroPython checkout**, substituted with the real, already-fetched `mpy_dir` before any
  Docker/mount step, uniformly for every usermod port. Closes the gap [0069] named and
  deliberately left open ("no `{checkout}`-style template today"). Record 0071.
- **The same `{micropython}` placeholder, and a real upstream-`examples/natmod` CI slice
  covering all eleven upstream modules, for natmod.** `module-dir` can now name a path
  inside the pinned checkout directly (`{micropython}/examples/natmod/<module>`), and
  `collect_output()` gained a fallback for `py/dynruntime.mk`'s own `all` target, which —
  unlike this project's own `dist` convention — leaves the merged `.mpy` sitting in
  module-dir itself rather than under `build/<arch>*/`. `test-upstream-natmod.yml` builds
  `features0` for two real arches (`x64`, `armv7emsp`) in one invocation — the multi-target
  collision scenario record 0055's own guard survey was about — plus the other ten modules
  (`features1`-`4`, `btree`, `deflate`, `framebuf`, `heapq`, `random`, `re`) each for `x64`.
  Closes record 0055: neither of the two risks its own survey flagged (`btree`'s git
  submodule, an rv32imc arch-flags collision) turned out to be a real blocker. Record 0072.
- **The `[0054]`/`[0069]` upstream-`examples/usercmodule` fixture now covers all six usermod
  ports**, not just `unix`/`rp2`: `esp32`, `windows`, `webassembly` and `qemu` all build
  `cppexample`/`cexample`/`subpackage` in CI now too. `examples/usercmodule/cibuildmp.toml`
  carries the whole thing — a `[override."*-manylinux* *-win* *-qemu-* *-wasm32"]` pointing
  the four Make ports' `user-c-modules` straight at `{micropython}/examples/usercmodule`
  (no vendoring, no wrapper file), the two CMake ports (`rp2`/`esp32`) reading `MICROPY_DIR`
  directly inside `examples/usercmodule/micropython.cmake`. No job in
  `test-upstream-usermodule.yml` resolves the checkout itself or sets
  `CIBMP_USER_C_MODULES`/`CIBMP_EXTRA_MAKE_ARGS`/`CIBMP_EXTRA_CMAKE_ARGS` any more — a bare
  `cibuildmp examples/usercmodule --build <identifier>` run, CI or local, now resolves
  identically to what a job here does.

### Changed

- **`test-all-platforms.yml` no longer runs on `pull_request`** — the full real matrix
  (200+ identifiers, bucketed across up to 20 concurrent jobs) took too long to gate every
  PR's own turnaround time for how rarely its answer actually changes. Now `schedule`
  (weekly) plus `workflow_dispatch` for an on-demand run; `push`/`pull_request` CI still
  covers every change through `tests.yml`'s unit suite and `build-examples.yml`'s narrower
  matrix. The `if: github.actor != 'dependabot[bot]'` guard record 0068 added specifically
  for the now-gone `pull_request` trigger came out too, moot rather than just redundant.

### Fixed

- **`docker/windows.Dockerfile` installed only the C mingw-w64 cross-compilers
  (`gcc-mingw-w64-*`), never the C++ ones (`g++-mingw-w64-*`)** — mingw-w64 fully supports
  C++, this was a real gap in the image, not a port limitation. A C++ user module on
  `windows` failed with "cannot execute `cc1plus`" (the C++ compiler backend didn't exist
  at all) until this fixed it; republished, repinned in `pinned_docker_images.toml`.
- **`ports/webassembly/Makefile` never overrides `CXX` from its own default (`g++`, the
  host's real compiler), only `CC`/`LD` (to `emcc`)** — a C++ user module's real `.cpp`
  compile was silently running through the wrong compiler entirely (confirmed live: the
  failure's own `cc1plus` and "unrecognized command-line option" for a clang-only flag name
  are exactly what a host `g++` invocation looks like, not `emcc`'s). Worked around through
  `extra-make-args` (`CXX=em++`, emsdk's own C++ driver, already baked into the image) —
  an upstream Makefile bug this project can reach without vendoring upstream's own file.
- **Upstream's own `ports/webassembly/mpconfigport.h` unconditionally `#define _GNU_SOURCE`,
  conflicting with emcc/clang's own built-in definition in C++ mode** (`-std=c++11`),
  tripping `-Werror -Wmacro-redefined` once the `CXX` fix above let the right compiler run
  at all. Reached through `py/mkrules.mk`'s own `CXXFLAGS_MOD` hook ("Add default C++
  compiler flags based on CFLAGS. For use with C++ user modules" — that comment's own
  words), via `extra-make-args`, with nothing to clobber (unlike [0066]'s own
  `CMAKE_ARGS`/`IDFPY_FLAGS` trap): nothing in the tree ever assigns `CXXFLAGS_MOD` first.

## [0.4.1] - 2026-08-30

### Added

- **A real, narrow CI slice testing upstream's own `examples/usercmodule/`**, not just a
  module cibuildmp wrote for itself the way `examples/template` is.
  `.github/workflows/test-upstream-usermodule.yml` resolves the pinned MicroPython
  checkout via `sources.fetch_micropython()` and builds `cexample`/`cppexample`/
  `subpackage` on one Make port (`unix`) and one CMake port (`rp2`) — no vendoring, no new
  config surface. `examples/usercmodule/micropython.cmake` is this repo's own three-line
  shim adding the `subpackage` `include()` upstream's own CMake aggregator omits (a real
  gap, confirmed against a v1.29.0 checkout, not assumed). `unix` also gets a real smoke
  test (`examples/usercmodule/smoke_test.py`), run under the built binary, not just a
  build-succeeded check. Confirmed green (run 33330364394), `cppexample`'s `-lstdc++`
  linking on `rp2`'s own bare-metal toolchain included. Records 0054/0069.

### Fixed

- **A collected `unix` usermod binary that needed `libffi` shipped without the `lib/`
  directory its own rpath depends on, and could not actually run from where cibuildmp
  says its output lives.** `repair_unix_binary()` vendors `libffi.so.<N>` beside the
  built binary and points it there with `patchelf --set-rpath '$ORIGIN/lib'` for exactly
  this reason; `orchestrate.py`'s `build_one()` only ever copied the binary itself into
  `mpyhouse/<identifier>/`, silently defeating that portability contract for every
  dynamically-linked glibc cell. Invisible until now: nothing in this project's own CI
  had ever executed a collected `unix` artifact, only listed it — `examples/usercmodule/
  smoke_test.py` (above) is the first thing that did, and failed with "error while
  loading shared libraries: libffi.so.6: cannot open shared object file" on its very
  first real run. `build_one()` now copies the `lib/` sidecar alongside the binary too,
  whenever `repair_unix_binary()` created one; a no-op for every other target and port.
  Record 0070.

## [0.4.0] - 2026-08-29

Extensive, still-unreleased rework of the config surface and natmod's own
container story. Written as the current, final state rather than as a
phase-by-phase account -- several intermediate mechanisms below were
designed, shipped inside this same Unreleased section, and then retracted
again before ever reaching a release; the full journey (including what was
tried and rejected) lives in `docs/records/`, not here.

### Changed

- **Config is purely `build`/`skip` glob-matching a real identifier, plus
  `[override]` -- no per-platform tables, no `--platform`, no opt-in
  keywords.** `[natmod]`/`[unix]`/`[windows]`/`[qemu]`/`[webassembly]`/
  `[esp32]` do not exist as config tables at all: every platform is
  always in scope, on every invocation, and `build`/`skip` (config,
  `CIBMP_BUILD`/`CIBMP_SKIP`, or `--build`/`--skip` on the CLI)
  glob-matching each platform's own real identifier is the only thing
  that decides what actually gets built. **Breaking, and deliberate: an
  unconfigured `build` selects nothing at all, from any platform** -- a
  config states what it wants, explicitly, via a glob, or nothing
  builds. `--platform`/`CIBMP_PLATFORM`/`--only`/`--toolchain`/`--archs`
  and `--enable`/`enable`/`GROUPS` are all gone from the CLI and every
  config surface; more than one platform can build in a single
  invocation, with no flag needed at all, since cibuildmp's platforms are
  just Docker images on one host rather than being bound to it the way
  cibuildwheel's own are. `[usermod]` is unaffected -- it was never a
  selector, only a shared-defaults tier for usermod's own ports (see
  below), and stays exactly that. See the README's own "Identifiers and
  selectors" section for the full real identifier list and glob syntax.
  Record 0052.
- **Every real `(port, tag, arch/board)` row `resources/build-platforms.toml`
  has verified is a candidate, always, for both natmod and usermod.**
  Selection narrows that real-row domain; nothing computes an axis
  product any more. Fixed a real, previously-silent bug along the way:
  `unix`/`windows`/`webassembly` identifiers never actually carried the
  port name at all (`v1.29.0-manylinux_2_28_x86_64`, not
  `v1.29.0-unix-manylinux_2_28_x86_64`), which every earlier build of
  this identifier had gotten wrong. A tag or arch/board this file has
  never verified is a loud, specific error at resolution time, naming
  `bin/refresh_natmod_archs.py`/`bin/refresh_usermod_boards.py` as the
  fix, not a silent guess. Record 0052, Track C.
- **`unix` builds run inside a native image per target instead of
  cross-compiling from one shared image.** Identifiers are the real PEP
  600/656 platform tag (`unix-manylinux_2_28_x86_64`,
  `unix-musllinux_1_2_aarch64`, `unix-manylinux_2_39_mipsel`), not a bare
  arch name -- **breaking: every existing `unix` identifier changes**
  (`x64` → `x86_64`, `x86` → `i686`, `armhf` → `armv7l`). Base images are
  a thin layer over pypa's own manylinux/musllinux images; nine of
  fifteen cells need no cibuildmp-published layer at all and resolve
  straight to pypa's own digest. `docker run --platform=<target>` picks
  the image the same way cibuildwheel's `OCIContainer` does, so an arm64
  runner now runs `aarch64`/`armv7l` natively instead of under QEMU: a
  real `manylinux_2_28_aarch64` build measured 88.8s native against
  1041s emulated on the same machine (~12x), and `manylinux_2_31_armv7l`
  built in 59.5s -- faster than the native `aarch64` leg on the same
  runner class, confirming GitHub's own `ubuntu-24.04-arm` really does
  run AArch32-at-EL0 natively too. All six default targets green on CI
  (runs 32958683512/32959019090); the musllinux column (4 of 7 cells --
  `x86_64`/`i686`/`aarch64`/`armv7l`; `ppc64le`/`s390x`/`riscv64` stay
  declared but unbuilt) went green on run 32960761641. Records 0031,
  0043, 0044.
- **`mpy-cross` now builds inside the target container for every `unix`
  build, not on the host.** A host-built binary only worked by
  coincidence of matching the image's own glibc -- against a real
  `manylinux_2_28` (AlmaLinux 8) image it failed outright with
  `mpy-cross: /lib64/libc.so.6: version 'GLIBC_2.34' not found`, and
  cannot run at all inside a foreign-architecture container regardless
  of libc. `windows`/`qemu`/`webassembly` already build it in-container
  for the same reason on an arm64 host. Two real compiler findings from
  running gcc 14 against AlmaLinux 8/Alpine 3.22/Rocky 10 for the first
  time, both fixed with a targeted `CFLAGS_EXTRA` rather than a global
  suppression: `-Wno-error=cpp` for every `musllinux_*` cell (musl's own
  `<sys/cdefs.h>` is a bare `#warning`), `-Wno-error=array-bounds` for
  every `aarch64` cell (gcc 14's bounds analysis false-positives
  identically on `mbedtls_xor` across both a glibc and a musl base).
  Records 0043, 0044.
- **`windows` builds inside a container too**, closing the last of
  usermod's Docker-only ports still using a bare-host toolchain --
  deletes both host-side resolvers it depended on (an apt
  `gcc-mingw-w64` probe for `x64`/`x86`, a ~600MB `llvm-mingw` tarball
  fetched onto the host per cache miss for `arm64`).
  `docker/windows.Dockerfile` bakes llvm-mingw as a pinned layer
  instead. **Breaking for anyone relying on `apt install
  gcc-mingw-w64-*` on the runner** -- that path no longer exists. Found
  live: llvm-mingw's own `bin/` ships `x86_64-w64-mingw32-gcc`/
  `i686-w64-mingw32-gcc` wrapper names too, both really Clang --
  prepending its directory onto `PATH` would have silently swapped
  `x64`/`x86` from the real MinGW GCC (the toolchain upstream
  MicroPython's own CI uses) onto Clang. Fixed by appending rather than
  prepending, each ordering checked with a real `command -v` inside a
  container rather than assumed. Verified against the published,
  anonymously-pulled image, all three arches producing a genuinely
  linked (not stock) `.exe`: `x64` → `PE32+ … x86-64`, `x86` → `PE32 …
  Intel i386`, `arm64` → `PE32+ … ARM64`. Record 0042.
- **natmod's identifier is `mpy{abi}-{tag}-{arch}[+0x{flags}]`, read
  directly off its own verified row rather than reassembled** (matching
  cibuildwheel's own `PythonConfiguration.identifier`, a literal field,
  never computed) **-- tag included**, so two MicroPython releases
  sharing one `.mpy` ABI never collapse onto the same identifier
  (`mpy5-x86` alone spans seven distinct tags, `v1.12`-`v1.18`). A
  `build`/`skip` glob that never names a tag narrows to the single
  newest one per arch automatically, preferring a stable release over a
  newer preview sharing the same ABI; a glob that does name a specific
  tag is trusted as-is. `micropython`/`mpy-abi` no longer exist as
  natmod config keys -- the ABI/tag domain is read from
  `resources/build-platforms.toml` instead of pinned by hand. Record
  0052.
- **`[[overrides]]` is `[override]`, one shared list keyed by its own
  glob directly** (`[override."*-armv7emsp"]`, no separate `select =`
  field) rather than upstream's own `[[tool.cibuildwheel.overrides]]`
  array-of-tables shape -- this project's overrides have always been
  "one glob, some options," so the glob can simply be the table's own
  name. `inherit = {extra-make-args = "append"|"prepend"|"none"}`
  (default `"none"`, i.e. replace) lets the one option genuinely
  list-shaped across every platform's own override surface compose onto
  the running value instead of always replacing it outright. An
  override's own key is validated twice -- loosely (valid for *any*
  platform) when the config loads, and strictly (valid for the platform
  the matched identifier actually belongs to) once a target resolves --
  so a `natmod`-only key inside an override that only ever matches a
  `unix` identifier is still a loud, specific error, not silently
  ignored. Precedence is declaration order, which a TOML table's own
  keys already preserve: a narrower glob written further down the file
  still wins over a broader one above it. Record 0052.
- **New `name`/`version` config keys give built artifacts real project
  identity**, read from the top level for every platform. Setting `name`
  replaces natmod's `mpy_path.stem`-derived filename prefix and
  usermod's literal `"micropython"`/`"micropython.exe"` stem with
  `{name}-{version}-{identifier}` (`mylib-1.2.0-mpy6.3-v1.29.0-x64.mpy`,
  `mylib-1.2.0-v1.29.0-unix-manylinux_2_28_x86_64`) -- two different
  projects' usermod firmware used to be indistinguishable by filename
  alone. Leaving `name` unset keeps exactly today's filename. Record
  0052, Track A.
- **usermod's `module-dir` is renamed `user-c-modules`** (the literal
  Makefile variable it feeds; natmod's own, differently-meaning
  `module-dir` is untouched), **its default changes from `"usermod"` to
  `"."`, and `[usermod]` is a real shared-defaults tier again** -- a
  top-level table, sibling to every platform table, holding
  `user-c-modules`/`manifest`/`extra-make-args` defaults for every
  active usermod port at once
  (`default → global → family → platform → env → CLI` cascade). It does
  **not** gate which ports are active -- a port's own table presence
  does that, same as `[natmod]`'s presence always has. **Breaking**: any
  config still writing `module-dir` under a usermod port table needs to
  rename it. Record 0051.
- **natmod builds in a container, with no bare-host path at all**, and
  its own `mpy-cross` builds inside that same image rather than on the
  host (`py/dynruntime.mk` hardcodes the path it invokes, so a host-built
  binary only ever worked by the coincidence of matching the image's own
  glibc -- the same bug class already fixed for `unix`/`windows`/
  `webassembly`). One `linux/amd64` image carries all ten
  `dynruntime.mk` toolchains under exactly the prefixes it expects.
  Visible consequence: **`x86` builds on an arm64 runner**, which it
  could not before. `docker/natmod.Dockerfile`'s own apt/toolchain
  layers are ordered minimal-apt → toolchains → the rest of apt, so a
  package addition to the volatile half no longer invalidates the
  3.38GB toolchain layer. `build-essential` stays in `action.yml`'s apt
  step regardless: `qemu` still builds its own `mpy-cross` on the host,
  unrelated to any of this -- `esp32` no longer does (see the esp32
  bullet above). Records 0050, 0052.
- **`pre-build-command` runs inside the build's own container**, the shape
  cibuildwheel's `before-all` has. It therefore runs unprivileged and cannot
  install system packages -- a project that needs a tool should fetch it, as
  `examples/wasm2mpy` now does for `wabt`.
- **`esp32` now builds in a container too, closing the one remaining
  exception to the Docker-only rule.** `build_esp32()` runs entirely
  inside `esp_idf_base`; only ESP-IDF's own `git clone` stays host-side
  (source, not a binary, the same reasoning `mpy_dir` mounts straight
  into every image already relies on). `idf_version`/`idf_target` are
  now resolved from each target's own real `build-platforms.toml` row
  rather than a fixed default, so a RISC-V board (`esp32c2`/`c3`/`c6`)
  installs the right toolchain, not Xtensa's. Records 0028, 0058.

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

- **`rp2` usermod builds, live-verified.** `build_rp2()` closes [0022]'s own
  last unstarted item ("no Pico SDK resolver, no live verification") --
  config and the `arm_embedded` Docker image were already in place, only
  the driver itself was missing. No provisioning step runs inside the
  container: the Pico SDK and everything under it it needs
  (`lib/pico-sdk`/`lib/tinyusb`/`lib/lwip`/`lib/btstack`/`lib/cyw43-driver`)
  are plain git submodules of the MicroPython checkout, already vendored
  for free by the release tarball `sources.fetch_micropython()` prefers --
  running `ports/rp2`'s own `make ... submodules` target instead was tried
  first and failed live against a real tarball checkout ("fatal: not a
  git repository"), since it is a bare `git submodule update` and a
  release tarball is not a git checkout at all. Confirmed live: a real
  `examples/template` build against `v1.29.0-rp2-RPI_PICO` producing a
  genuine 681984-byte `firmware.uf2` with the fixture's own C module
  linked in. Record 0060.
- `verify_windows_output()` — reads the COFF `Machine` out of the produced
  `micropython.exe` and rejects a binary that is not the architecture its
  identifier names. `windows` previously checked only that the file existed.
- **`ppc64le`/`s390x`/`riscv64` (both libc columns) are now real, nameable
  `unix` targets** — a pinned digest and a real identifier, reachable via
  `build`/`skip` — but carry no CI leg: native to no runner GitHub offers,
  and no consumer has asked for one (Alpine's own `community/micropython`
  doesn't build for `ppc64le`/`s390x` at all). README marks them ⚠️ with a
  footnote that no real build has ever run. Records 0043, 0044.
- A `workflow_dispatch` input on `publish-docker-images.yml` to republish one
  image instead of all nineteen.
- **`qemu` actually exercised in CI for the first time.** `build_qemu()` was
  wired to `ensure_image()` back in record 0032, and
  `resources/pinned_docker_images.toml` already carried a real published
  digest for it, but no build had ever run through that path — here or by
  hand, per the tracker's own [0032] row. `build-examples.yml`'s
  `build-usermod` job now carries a dedicated `v1.29.0-qemu-MPS2_AN385`
  matrix leg, deliberately its own job rather than folded into the nine
  already-green cells sharing the amd64 batch: `usermod.orchestrate.build()`
  has no per-target try/except, so one failing target aborts the whole
  invocation, and a never-proven cell has no business risking nine settled
  ones. Confirmed live, not assumed: `build-examples.yml` run 33156958747
  produced a real `firmware-v1.29.0-qemu-MPS2_AN385.elf` (330404 bytes) in
  40 seconds.

### Fixed

- **`windows` rejected every real identifier with `unknown windows arch
  'win32'`.** `WINDOWS_ARCH_SETTINGS` was still keyed by the old bare
  `x64`/`x86`/`arm64` tokens from before the identifier scheme moved onto
  the Python/PEP wheel-tag vocabulary (`win32`/`win_amd64`/`win_arm64`,
  `resources/build-platforms.toml`'s own arch column) the rest of the
  scheme uses — `build_windows()` reads `target.arch` straight off the
  identifier, so every real `windows` build failed this lookup outright.
  Caught live: `build-examples.yml` run 33150753588 failed on
  `v1.29.0-win32` with exit code 2. Renamed the dict's three keys to
  match; no other caller keys off the old names (`dockerrun.image_for()`
  shares one pinned image across all three regardless of the value
  passed).

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

### Added

- **`extra-cmake-args`, the cmake-side `extra-make-args`.** `rp2`/`esp32`
  accumulate their own cmake arguments with a plain `+=`
  (`CMAKE_ARGS`/`IDFPY_FLAGS`), and GNU Make's own precedence means a
  command-line assignment of that name *replaces* the makefile's own
  `-DMICROPY_BOARD=`/`-DUSER_C_MODULES=` entirely rather than adding to
  it, whatever operator the command line itself uses — verified live,
  twice. Delivered as a container environment variable instead, which
  sits one precedence tier below the makefile's own assignment so its
  `+=` still appends correctly on top of it. The four Make-only ports
  never read it, same as `extra-make-args` is meaningless to a port that
  never reads whatever name a caller passes it. Surfaced migrating
  `micropython-wasm3` to the unified CLI ([0038], M5). Record 0066.

### Fixed

- **`resolve_user_c_modules()` silently built zero user modules for a
  flat, single-module `usermod/` layout.** `py/py.mk` globs
  `<USER_C_MODULES>/*/micropython.mk` for make ports, one directory
  level *above* the module itself — a `user-c-modules` value pointing
  straight at a directory that already contains `micropython.mk`
  (rather than a directory *of* module subdirectories) made that glob
  match nothing, with no error anywhere: the port built and linked
  clean, just without any of the user's own code in it. Now detects a
  `micropython.mk` directly inside the given directory and resolves to
  its own parent for make ports only; the pre-existing multi-module
  shape (module subdirectories, one `*/micropython.mk` per module) and
  every cmake-port resolution are unaffected, confirmed live against
  two real consuming repos' own directories. Live-caught migrating
  `micropython-wasm3` to the unified CLI ([0038], M5) — its own build
  reported success throughout, and only its test step surfaced the
  missing module, by accident, through an unrelated `except ImportError`
  fallback. Record 0067, addendum to record 0056.
- `build_qemu.py`/`build_webassembly.py`/`build_windows.py` had
  pre-existing `ruff format` drift (a wrapped `usermod_mounts()` call
  each) that blocked this branch's own `Tests` workflow at the
  format-check step, which skips `pyright`/`pytest` entirely on
  failure — nothing behind it was actually running until this was
  fixed. A `pyelftools`-typing false positive in `build_unix.py`'s own
  `DynamicTag.needed` access did the same to `pyright` right after;
  silenced with a documented `pyright: ignore`, since `DynamicTag`
  really does set that attribute at runtime (a `setattr()` in its own
  `__init__`, for `DT_NEEDED` specifically), just never as a declared
  attribute pyright's static analysis can see.

## [0.3.0] - 2026-08-24

First release where `cibuildmp` actually builds a module — `v0.3.0a1` could
only plan the target matrix. Validated against three real consuming repos
(`micropython-bclibc`, `a7p`, `micropython-wasm3`), all natmod and usermod
workflows green on every arch, including a RISC-V toolchain fix. Its own
detailed entry was lost in the `#9` squash-merge that later folded into the
[0.4.0] rewrite; restored here as this short summary rather than the full
original list, since most of what it described was itself superseded before
[0.4.0] shipped — see `docs/records/` for that history.

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

[Unreleased]: https://github.com/ballistics-lab/cibuildmp/compare/v0.4.2...HEAD
[0.4.2]: https://github.com/ballistics-lab/cibuildmp/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/ballistics-lab/cibuildmp/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/ballistics-lab/cibuildmp/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/ballistics-lab/cibuildmp/compare/v0.3.0a1...v0.3.0
[0.3.0a1]: https://github.com/ballistics-lab/cibuildmp/compare/v0.2.0...v0.3.0a1
[0.2.0]: https://github.com/ballistics-lab/cibuildmp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ballistics-lab/cibuildmp/releases/tag/v0.1.0

[0022]: docs/records/0022-zephyr-third-selector-axis.md
[0032]: docs/records/0032-unix-docker-default-and-webassembly-wiring.md
[0038]: docs/records/0038-m5-adopt-in-three-repos.md
[0043]: docs/records/0043-unix-adopts-cibuildwheel-native-image-model.md
[0054]: docs/records/0054-usermod-example-from-upstream-usercmodule.md
[0066]: docs/records/0066-extra-cmake-args.md
[0069]: docs/records/0069-upstream-usercmodule-narrow-ci-slice.md

# cibuildmp

Build MicroPython native C extensions for every target they support, from
one declarative config -- on CI and on your own machine. `cibuildwheel`, for
MicroPython.

Covers **natmod** (dynamically loadable native `.mpy` modules, built against
`py/dynruntime.mk`) and **usermod** (`USER_C_MODULES`, compiled straight
into a port's own firmware build) C extensions.

> **This repository supersedes
> [`ballistics-lab/micropython-native-ci`](https://github.com/ballistics-lab/micropython-native-ci).**
> Every composite action that lived there now lives here, unchanged in
> behaviour but on new paths -- see [Migrating](#migrating) below. The old
> repository is deprecated and will be archived once its consumers have
> repinned; nothing new lands there.

## Two layers

**`cibuildmp`, the CLI.** One `cibuildmp.toml` in a module's own repo
describes its whole target matrix. The tool resolves it into build
identifiers, fetches MicroPython, builds `mpy-cross`, provisions each
target's cross toolchain, and runs the build -- the same way locally as on a
runner. This is the direction the project is going, and the intended
primary way to use it going forward -- run directly, via the root
[`Dockerfile`](Dockerfile) (Linux and, through WSL2/Docker Desktop,
Windows too -- see [Target support](#target-support) below for why no
target needs a native Windows or macOS host), or in CI via this repo's
own root `action.yml` (`uses: ballistics-lab/cibuildmp@<tag>`) -- a
Docker action, not composite, built from
[`action.Dockerfile`](action.Dockerfile)
(a separate image from the standalone `Dockerfile` above -- see that
file's own header for why they can't share one). See
[`docs/BACKLOG.md`](docs/BACKLOG.md) for the design decisions and what is
implemented so far.

```console
$ cibuildmp --dry-run
cibuildmp: 10 target(s) against MicroPython v1.28.0
  [ 1/10] mpy6.3-natmod-x86            CROSS=(host)                 make -C natmod ARCH=x86 dist
  [ 2/10] mpy6.3-natmod-x64            CROSS=(host)                 make -C natmod ARCH=x64 dist
  ...
```

Drop `--dry-run` and it builds for real: each target lands in its own
`output-dir/<identifier>/` directory (`mpyhouse/mpy6.3-natmod-x64/`, …)
alongside a `package.json` once `version` is set — see
[`examples/template`](examples/template) and
[`examples/wasm2mpy`](examples/wasm2mpy) (native source is WebAssembly,
compiled through `wasm2c` — the natmod contract doesn't care what
produced the C).

**The composite actions.** The original building blocks, and still the
supported path for CI wanting each usermod target built as its own job
today. `cibuildmp` is absorbing them one at a time (natmod first); until
it does, they remain fully supported, but are no longer where new work
starts -- see [Composite actions](#composite-actions-githubactions)
further down.

## Why this exists

MicroPython itself already defines two standard, unrelated build
mechanisms for a native C extension:

- **natmod** -- `natmod/Makefile` includes MicroPython's own
  `py/dynruntime.mk` and is parameterised by `ARCH=`. It produces a
  runtime-loadable `.mpy` per target architecture. See MicroPython's own
  `examples/natmod/`.
- **usermod** -- `usermod/micropython.cmake` + `usermod/micropython.mk`,
  pointed at via `USER_C_MODULES=` on a port's own build. Compiled into the
  firmware image itself. See MicroPython's
  [`docs/develop/cmodules.rst`](https://docs.micropython.org/en/latest/develop/cmodules.html).

[`ballistics-lab/micropython-bclibc`](https://github.com/ballistics-lab/micropython-bclibc),
[`o-murphy/micropython-wasm3`](https://github.com/o-murphy/micropython-wasm3)
and [`o-murphy/a7p`](https://github.com/o-murphy/a7p) each already follow
that same `natmod/` + `usermod/` layout -- that part was never the problem.
What diverged was the CI *around* it: each repo's GitHub Actions workflow
was hand-copied into the next and then evolved independently, so the same
~10-architecture build matrix, the same toolchain-install steps and the
same real-ARM-Linux test trick ended up as three separate, slowly drifting
copies (different `actions/checkout` versions, different path filters, one
bug fixed in one repo and not the other two).

This repo is the shared home for the parts that are genuinely identical
across all three -- so a fix or an improvement lands once, and every
consuming repo picks it up deliberately by bumping the tag it's pinned to,
instead of by hand-patching three YAML files that have already started to
disagree with each other.

The composite actions solved that for the *steps*. They could not solve it
for everything around them: the arch matrix itself still had to be spelled
out in each repo, a composite action structurally cannot choose its own
`runs-on:`, artifact globs stayed caller-side, and none of it could be run
on a laptop. That is what `cibuildmp` is for.

## Migrating

Action paths change repo, nothing else. Behaviour, inputs and outputs are
identical:

```diff
- uses: ballistics-lab/micropython-native-ci/.github/actions/build-natmod@v0.2.0
+ uses: ballistics-lab/cibuildmp/.github/actions/build-natmod@v0.3.0
```

Pin a tag, as before -- not `@main`, not a commit SHA.

## Conventions this repo assumes

A module following the natmod/usermod layout looks like:

```
natmod/
  Makefile              # includes py/dynruntime.mk, dispatches on ARCH=
usermod/
  micropython.cmake
  micropython.mk
  manifest.py
```

`build-natmod` only assumes `natmod/Makefile` (or whatever
`natmod_dir` points at) accepts `ARCH=` and `MPY_DIR=` and has a `dist`
target that drops the built `.mpy` under `build/<arch>*/`. Nothing here
assumes a specific module name, precision scheme, or test framework --
those stay in the consuming repo.

**One more requirement for the `cibuildmp` CLI specifically** (not
`build-natmod`, which gives every arch its own job and checkout): scope
`dynruntime.mk`'s `BUILD` variable by `$(ARCH)` --
`BUILD = .obj/$(ARCH)` before the `include`, kept outside `build/` so it
does not collide with the `dist` output the CLI globs for (see
`examples/template/natmod/Makefile`). `cibuildmp` with no `--only` runs
every target sequentially in one `natmod/` tree (**D9**), and
`dynruntime.mk` defaults `BUILD ?= build` unscoped, so without this a
second `ARCH=` in the same invocation finds the previous arch's own
object files "up to date" (same path, source unchanged) and skips
rebuilding -- the merged `$(MOD).mpy` silently stays the *first* arch's
binary. `cibuildmp` catches this itself (the header-arch verification
that is its `auditwheel` equivalent fails loudly instead), but scoping
`BUILD` avoids paying for the failed build at all.

If the module also uses `rv32imc`'s `arch-flags` (**D15**), `BUILD` needs
`$(ARCH_FLAGS)` folded in too --
`BUILD = .obj/$(ARCH)$(if $(ARCH_FLAGS),+$(ARCH_FLAGS))`. Same bug, second
axis: `rv32imc`'s own object file does not depend on `ARCH_FLAGS` at all,
so building several arch-flags variants back to back in one invocation
(`arch-flags = ["", "zba", "zba,zcmp"]`) reuses the first variant's cached
`.o`/`.mpy` for every later one just as silently, even though `$(ARCH)`
never changed. Found the same way as the `$(ARCH)` case: by actually
running the whole variant list, not by inspection.

None of this cares what produced the `.c` files `SRC` lists --
[`examples/wasm2mpy`](examples/wasm2mpy) compiles WebAssembly to C via
`wasm2c` in a Makefile rule before the same `dynruntime.mk` flow takes
over, and needs nothing from `cibuildmp` beyond `module-dir = "."` and an
`extra-make-args` entry for its own `APP=` variable.

## Target support

### Natmod support per arch

All ten `ARCH=` values `py/dynruntime.mk` accepts (`docs/BACKLOG.md`'s
own **M0**–**M5**), each self-provisioning its own toolchain (**D3**) —
adopted in all three consuming repos and verified on real CI, arch by
arch, not just `--dry-run`.

| Arch        | Toolchain              | Provisioning         |
|-------------|-------------------------|-----------------------|
| `x64`       | host gcc                | none needed           |
| `x86`       | host gcc (`-m32`)       | apt only[^apt-x86]    |
| `armv6m`    | `arm-none-eabi-`        | self-downloaded, cached |
| `armv7m`    | `arm-none-eabi-`        | self-downloaded, cached |
| `armv7emsp` | `arm-none-eabi-`        | self-downloaded, cached |
| `armv7emdp` | `arm-none-eabi-`        | self-downloaded, cached |
| `xtensa`    | `xtensa-lx106-elf-`     | self-downloaded, cached |
| `xtensawin` | `xtensa-esp32-elf-`     | self-downloaded, cached |
| `rv32imc`   | `riscv64-unknown-elf-`  | self-downloaded, cached |
| `rv64imc`   | `riscv64-unknown-elf-`  | self-downloaded, cached |

[^apt-x86]: `apt install gcc-multilib` — no downloadable tarball exists for this one; **D3**'s own "why not docker for x86" note.

### Usermod support per port/arch

Upstream MicroPython has 20 ports (`ports/*` in a real checkout); every
one of them is listed below for orientation, not just the ones this
project covers. This is `usermod/build.py`'s own build-driver layer
(`docs/BACKLOG.md`'s **M6**–**M9**) — live-verified against a real
MicroPython checkout, including a real custom `USER_C_MODULES` module
for every ✅ row. **Not yet wired into the `cibuildmp` CLI or
`action.yml`** — that's a real, separate, still-open gap (no
`--mode usermod` entrypoint exists yet). Until it lands, the composite
actions above (`build-usermod-*`) remain the supported, production path
for the six ports they cover.

| Port          | Target                    | Provisioning                    | Status |
|---------------|----------------------------|-----------------------------------|--------|
| `unix`        | `x64`                      | host gcc                          | ✅ |
| `unix`        | `x86`                      | apt only[^apt-x86]                | ✅ |
| `unix`        | `aarch64`                  | `apt install gcc-aarch64-linux-gnu libffi-dev:arm64`[^ports-mirror] | ✅ |
| `unix`        | `armhf`                    | `arm-linux-gnueabihf-`             | ❌[^no-toolchain] |
| `unix`        | `mipsel`                   | `mipsel-linux-gnu-`                | ❌[^no-toolchain] |
| `qemu`        | `MPS2_AN385` (Cortex-M3)   | `arm-none-eabi-`[^qemu-shared]     | ✅ |
| `qemu`        | RISC-V boards               | `riscv64-unknown-elf-`             | ❌[^not-attempted] |
| `webassembly` | `pyscript` variant          | `emsdk`[^linux-x64-only]           | ✅ |
| `esp32`       | `ESP32_GENERIC`             | ESP-IDF v5.5.1, self-cloned + installed | ✅ |
| `esp32`       | other ESP32-family boards   | same ESP-IDF resolver              | ⚠️[^esp32-other] |
| `windows`     | `x64`                       | `apt install gcc-mingw-w64-x86-64` | ✅ |
| `windows`     | `x86`                       | `apt install gcc-mingw-w64-i686`   | ✅ |
| `windows`     | `arm64`                     | `llvm-mingw`[^linux-x64-only]      | ✅ |
| `rp2`         | any board                   | Pico SDK                          | ❌[^rp2-gap] |
| `stm32`       | STM32 MCUs                 | —                                  | ❌[^out-of-scope] |
| `esp8266`     | Espressif ESP8266           | —                                  | ❌[^out-of-scope] |
| `samd`        | Microchip SAMD21/SAMD51     | —                                  | ❌[^out-of-scope] |
| `nrf`         | Nordic nRF51/52             | —                                  | ❌[^out-of-scope] |
| `mimxrt`      | NXP i.MX RT 10xx             | —                                  | ❌[^out-of-scope] |
| `renesas-ra`  | Renesas RA family            | —                                  | ❌[^out-of-scope] |
| `cc3200`      | TI CC3200 (Wi-Fi SoC)         | —                                  | ❌[^out-of-scope] |
| `alif`        | Alif Ensemble MCUs           | —                                  | ❌[^out-of-scope] |
| `pic16bit`    | Microchip PIC24/dsPIC33       | —                                  | ❌[^out-of-scope] |
| `powerpc`     | PowerPC (Microwatt/qemu)      | —                                  | ❌[^out-of-scope] |
| `zephyr`      | Zephyr RTOS (any board)       | —                                  | ❌[^zephyr-gap] |
| `bare-arm`    | minimal bare-metal reference — not a real target | — | ❌[^out-of-scope] |
| `minimal`     | minimal reference port — not a real target | —          | ❌[^out-of-scope] |
| `embed`       | embeddable library, not a flashable target | —          | ❌[^out-of-scope] |

[^ports-mirror]: Cross-compiles cleanly from an x86_64 host — verified live, a real linked `ARM aarch64` ELF with a custom C module built in. `libffi-dev:arm64` needs `dpkg --add-architecture arm64`'s apt sources pointed at `ports.ubuntu.com` first: Ubuntu's default `archive.ubuntu.com`/`security.ubuntu.com` mirrors only carry `amd64`/`i386`. Real for any Ubuntu host, not sandbox-specific.
[^no-toolchain]: Not buildable yet — pinned settings exist, but no toolchain resolver for this cross target is implemented.
[^qemu-shared]: Shared with natmod's own `armv7m` toolchain — resolved once, reused, not pinned a second time.
[^not-attempted]: `ports/qemu` also has RISC-V boards; a real, cheap-to-add extension later, not attempted since nothing here exercises it yet.
[^linux-x64-only]: Self-downloaded and cached; the pinned release is `linux-x64`-hosted only today.
[^esp32-other]: Selectable via the same `Esp32BuildOptions`, not itself live-verified — only `ESP32_GENERIC` was actually built and checked.
[^rp2-gap]: `resources/usermod.toml` already pins its manifest path and `cmake` build-system (target selection is ready), but `usermod/build.py` has no `build_rp2()` driver at all yet — no Pico SDK resolver, no live verification, not started.
[^out-of-scope]: Out of scope, not started: no reference CI recipe to build this against and no pinned data at all -- `a7p`'s own `mp-usermod.yml` (the real production reference this project's usermod support is built from) doesn't cover it either. Scoped in only when a real consumer needs it, the same way `windows`/arm64 was (see **D18**'s own addenda).
[^zephyr-gap]: Also out of scope, for a second, structural reason beyond "no reference workflow": `zephyr` doesn't fit this project's own board-selection model at all -- **D22**, confirmed directly against upstream: no `board.json` anywhere in `ports/zephyr/boards/`, board selection is a `<board>.conf`/`<board>.overlay` pair instead, a shape the vendored `boards.py` scanner has nothing to match.

No Windows or macOS host is needed for any of the seven ✅/⚠️ usermod
targets above, `windows`'s own three arches included — every toolchain
there is either already on a Linux host or downloads/apt-installs onto
one.

## Roadmap

`cibuildmp` is the roadmap. [`docs/BACKLOG.md`](docs/BACKLOG.md) is the
plan of record: the decisions taken (and why), what is implemented, and
what is deliberately deferred.

Where it stands: target selection, MicroPython and `mpy-cross`
provisioning, cross-toolchain resolution, and the natmod build itself
(running `make`, collecting the `.mpy`, verifying its header) are done.
There is no separate publish step -- `cibuildmp` writes each identifier's
own `package.json` as part of the normal build once `version` is set, the
same way cibuildwheel has no publish step either. Adopted in all three
consuming repos' natmod workflows and verified green on real CI, arch by
arch (`micropython-bclibc`, `a7p`, `micropython-wasm3`) -- not just
`--dry-run`. usermod's own build drivers exist too (see
[Target support](#target-support) above) but aren't wired into the CLI's
own `--mode` yet -- that's the next real milestone, not the composite
actions below.

Until usermod is wired into the CLI and verified against real CI in a
consuming repo the way natmod now is, the composite actions below stay
the supported path for it -- natmod's own composite actions
(`fetch-micropython`, `build-natmod`) are still here too, unchanged, for
anything that hasn't repinned to the `cibuildmp` CLI yet.

## Composite actions (`.github/actions/`)

The pre-CLI building blocks -- one GitHub Action per build step, still
fully supported for CI, but no longer where new work starts (see
[Two layers](#two-layers) above). New usermod ports and arches land in
the `cibuildmp` CLI's own `usermod/build.py` first; these actions absorb
the CLI's work once it's wired up, not the other way around.

Every table below is the action's complete input surface -- if it isn't
listed here, the action doesn't accept it. `MPY_DIR` in a "Requires"
line means `fetch-micropython` or `clone-micropython` (this repo's own)
must have already run in the same job; a composite action step can't set
an env var that steps *before* it will see, only ones after.

### `fetch-micropython`

Downloads and extracts a MicroPython release tarball, exports `MPY_DIR`.
Use for a plain natmod build or a unix-port build; the tarball already
vendors every port's `lib/` submodules, so no submodule init is needed.
Not usable on a Windows runner outside MSYS2 -- it shells out to `wget`,
which plain Git Bash doesn't have (see `build-usermod-windows` below
for why the Windows actions never call it either).

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `mpy_tag` | yes | -- | MicroPython release tag, e.g. `v1.28.0` |

No outputs; exports `MPY_DIR` to `$GITHUB_ENV` as a side effect.

### `clone-micropython`

Shallow git-clones a MicroPython release branch instead of fetching a
tarball, with a chosen set of submodules initialised, and exports
`MPY_DIR`. Use this when the build needs a submodule the release tarball
doesn't vendor (`lib/pico-sdk` for an rp2 firmware build, for instance) --
or, as a7p and now bclibc/wasm3's own webassembly/rp2040/windows-adjacent
jobs use it, any time the caller needs `MPY_DIR` set without dragging in
`fetch-micropython`'s `wget` dependency.

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `mpy_tag` | yes | -- | MicroPython release tag |
| `submodules` | no | `''` | Space-separated submodules to `git submodule update --init` (empty = skip) |
| `pico_sdk_submodules` | no | `'false'` | Also run `git -C lib/pico-sdk submodule update --init` (rp2040 builds) |
| `path` | no | `'micropython'` | Clone destination, relative to the workspace root -- override when the caller's own repo already has a top-level directory of that name (a7p passes `path: mpy`, since its own MicroPython subtree already lives at `micropython/`) |

No outputs; exports `MPY_DIR` to `$GITHUB_ENV` as a side effect.

### `build-natmod`

Installs whatever toolchain a single `dynruntime.mk` `ARCH` needs (plain
apt package, the `xtensa-lx106` tarball, or esp-idf -- dispatched per
arch, matching `dynruntime.mk`'s own `CROSS` choices), builds `mpy-cross`,
then runs `make ARCH=<arch> dist` in the natmod directory.

Requires: `MPY_DIR` (see above) and the calling repo already checked out,
submodules included if the natmod Makefile needs any.

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `arch` | yes | -- | `x64`, `x86`, `armv6m`, `armv7m`, `armv7emsp`, `armv7emdp`, `rv32imc`, `rv64imc`, `xtensa`, or `xtensawin` (no `aarch64` -- `dynruntime.mk` has none as of MicroPython ≤ v1.28; build that via a usermod instead) |
| `natmod_dir` | no | `natmod` | Path to the directory containing `natmod/Makefile`, relative to the workspace root (a7p passes `micropython/natmod`) |
| `esp_idf_ver` | no | `v5.4` | esp-idf tag to install for the `xtensawin` toolchain |
| `extra_pip` | no | `''` | Extra space-separated pip packages, alongside `pyelftools`/`ar` (always installed -- `mpy_ld.py` needs them for every ARCH) |
| `pre_build_command` | no | `''` | Shell command run once inside `natmod_dir`, after `mpy-cross` and before `make dist` (a7p uses `make fetch-nanopb`) |

No outputs.

### `build-usermod-unix`

The unix-port cross-compile matrix for a `USER_C_MODULES` usermod: `x64`,
`x86` (32-bit), `aarch64`, `armhf`, or `mipsel`. Installs the arch's
toolchain (apt package, qemu-user-static for the emulated ones, a
from-source libffi for the statically-linked ones), builds `mpy-cross`,
then runs the port build.

Requires: `MPY_DIR` and checkout, same as `build-natmod`. The
caller's own matrix still has to choose `runs-on:` per arch
(`ubuntu-24.04-arm` for `aarch64`/`armhf` -- both execute natively there,
not under an emulator; `ubuntu-latest` for the rest, `mipsel` included --
it stays under `qemu-user-static`, since GitHub has no mips runner) -- a
composite action can't pick its own runner.

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `arch` | yes | -- | `x64`, `x86`, `aarch64`, `armhf`, or `mipsel` |
| `user_c_modules` | no | `''` → `$GITHUB_WORKSPACE` | Value for `USER_C_MODULES=` |
| `frozen_manifest` | no | `''` → `$GITHUB_WORKSPACE/usermod/manifest.py` | Value for `FROZEN_MANIFEST=` |
| `extra_make_args` | no | `''` | Extra space-separated `VAR=value` pairs appended to the build command (e.g. bclibc's `MP_BCLIBC_PRECISION=double`) |
| `build_dir` | no | `''` → `$GITHUB_WORKSPACE/usermod/build/<arch>` | Value for `BUILD=`. A bare relative value (no leading `/`, e.g. `build-wasm3`) resolves against `$MPY_DIR/ports/unix` instead, the same way a bare `BUILD=` on the command line always did |
| `variant` | no | `standard` | Value for `VARIANT=`. A caller building against upstream's own `VARIANT=coverage` recipe (a7p's armhf/mipsel qemu legs used to) overrides this |

| Output | Description |
| --- | --- |
| `build_dir` | The `BUILD=` directory actually used (resolved default included), so the caller can find the built binary without recomputing it |

### `build-usermod-windows`

The `ports/windows` half of the same usermod build, run inside an MSYS2
shell (every step is `shell: msys2 {0}`): builds `mpy-cross` then the
port itself, including the four CLANGARM64-only overrides every
consuming repo's Windows row needed (`LDFLAGS_ARCH`/`COMPILER_TARGET`
because CLANGARM64 links via clang+lld rather than GNU ld/gcc,
`STRIP=""`/`SIZE="true"` because that toolchain ships neither binary).

Deliberately narrower than `build-usermod-unix`: fetching MicroPython
and setting up MSYS2 both stay the caller's own job. Requires:

- `MPY_DIR`, exported to a **POSIX-style path** (no backslashes -- MSYS2
  bash's own escape character eats them on any unquoted command line built
  from a native `D:\a\...` value, a real failure documented in every
  caller this was extracted from). Neither `fetch-micropython` nor
  `clone-micropython` is safe to use for this on a Windows runner as-is:
  the former shells out to `wget`, which plain Git Bash doesn't have, and
  the latter's own `$GITHUB_WORKSPACE`-derived `MPY_DIR` is the native
  backslash form. Every caller this was extracted from sets `MPY_DIR`
  itself with an inline `curl`+`$(pwd)` step instead.
- `msys2/setup-msys2` already run in the calling job, with the target
  `msystem`. This action's own steps can't do it for themselves --
  they're composite-action steps, so their `shell:` is fixed at
  `msys2 {0}` regardless of what ran before them in the *calling* job,
  and that shell wrapper only exists on `PATH` once `setup-msys2` has
  put it there.

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `user_c_modules` | no | `$(pwd)` | Value for `USER_C_MODULES=` |
| `frozen_manifest` | no | `$(pwd)/usermod/manifest.py` | Value for `FROZEN_MANIFEST=` |
| `extra_make_args` | no | `''` | Extra space-separated `VAR=value` pairs, e.g. a custom `PROG=` (wasm3 uses `PROG=micropython-wasm3.exe`) |
| `build_dir` | no | `build-standard` | Value for `BUILD=` -- a bare relative value, resolving against `$MPY_DIR/ports/windows` |
| `cflags_extra` | no | `''` | Value for `CFLAGS_EXTRA=` on the main build only (not `mpy-cross`), e.g. `-Wno-error` for CLANGARM64 |
| `variant` | no | `''` | Value for `VARIANT=` on the main build only, omitted from the command line entirely when empty. None of the three current callers ever pass this -- `ports/windows` has no `variants/<name>/` split in any of them, unlike the unix port -- it's here for a future caller whose own fork of the port does define one |

Every path input defaults to a `$(pwd)`-relative value, never an absolute
one, for the same backslash reason `MPY_DIR` has to be POSIX-style.

| Output | Description |
| --- | --- |
| `build_dir` | The `BUILD=` directory actually used (the input, verbatim) |

### `build-usermod-webassembly`

The `ports/webassembly` usermod build: installs emsdk, builds `mpy-cross`,
then runs the port build under it, producing a `micropython.mjs` +
`micropython.wasm` pair.

Requires: `MPY_DIR` and checkout, same as `build-usermod-unix`.
Combining `FROZEN_MANIFEST` with the port's own default
(`variants/<variant>/manifest.py`) is deliberately **not** done here --
every one of `usermod/manifest.py`'s own `try`/`except` tricks in the
three repos this was extracted from only ever probed
`$(PORT_DIR)/boards/manifest.py`, which doesn't exist for this port (it
has `variants/`, not `boards/`) -- so passing that file straight through
as `FROZEN_MANIFEST` silently dropped the variant's own default (for
`pyscript`: `asyncio`, backed by a custom JS-runtime scheduler, plus a
`require()` list of 24 stdlib/utility modules). That was a real gap, not
a stylistic one -- the `.mjs`/`.wasm` these jobs upload is a build
artifact real code can import against, not just a test fixture, and
`tests/`-only coverage never exercises it. Every consuming repo now
writes its own combined manifest first and passes that as
`frozen_manifest`.

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `variant` | no | `pyscript` | Value for `VARIANT=`. `standard`'s `-s ASYNCIFY` is broken against modern emsdk in multiple ways (tracked upstream at [micropython/micropython#19380](https://github.com/micropython/micropython/issues/19380)); `pyscript` is upstream's own recommended workaround, since it doesn't use `ASYNCIFY` at all |
| `emsdk_ref` | no | `latest` | emsdk install/activate ref. `latest` matches every caller today and upstream's own `tools/ci.sh` (`ci_webassembly_setup`) -- a moving target, since some future emsdk release could break a build with no change on either side of this action. Override to pin once that actually happens |
| `user_c_modules` | no | `''` → `$GITHUB_WORKSPACE` | Value for `USER_C_MODULES=` |
| `frozen_manifest` | no | `''` → `$GITHUB_WORKSPACE/usermod/manifest.py` | Value for `FROZEN_MANIFEST=` -- pass a combined manifest (see the note above) unless the module genuinely needs nothing from the variant's own default |
| `extra_make_args` | no | `''` | Extra space-separated `VAR=value` pairs, e.g. a module's own precision define or a custom `PROG=` |
| `build_dir` | no | `''` → `$GITHUB_WORKSPACE/usermod/build/wasm` | Value for `BUILD=`. A bare relative value (no leading `/`) resolves against `$MPY_DIR/ports/webassembly` instead, same as a bare `BUILD=` on the command line always did |

| Output | Description |
| --- | --- |
| `build_dir` | The `BUILD=` directory actually used (resolved default included), so the caller can find `micropython.mjs`/`.wasm` without recomputing it |

### `build-usermod-rp2040`

The `ports/rp2` usermod build: installs the arm-none-eabi + CMake toolchain,
builds `mpy-cross`, then runs the port build under it, producing a
`firmware.uf2`.

Requires: `MPY_DIR` and checkout, same as `build-usermod-unix`. Plain
`fetch-micropython` is sufficient here, no `clone-micropython` +
submodules needed: `ports/rp2/CMakeLists.txt` redirects
`PICO_TINYUSB_PATH`/`PICO_LWIP_PATH`/`PICO_BTSTACK_PATH`/
`PICO_CYW43_DRIVER_PATH` at `${MICROPY_DIR}/lib/<name>` -- MicroPython's
own top-level submodules, which the release tarball already vendors --
rather than at pico-sdk's own nested vendored copies, so pico-sdk's
internal submodule tree is never actually touched by this build.

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `board` | no | `RPI_PICO` | Value for `BOARD=` |
| `user_c_modules` | no | `''` → `$GITHUB_WORKSPACE/usermod/micropython.cmake` | Value for `USER_C_MODULES=` -- a *file*, unlike `build-usermod-unix`/`build-usermod-webassembly`'s own `user_c_modules`: CMake's `USER_C_MODULES` takes a single `.cmake` entry point, not a directory to glob |
| `frozen_manifest` | no | `''` → `$GITHUB_WORKSPACE/usermod/manifest.py` | Value for `FROZEN_MANIFEST=` |
| `extra_make_args` | no | `''` | Extra space-separated `VAR=value` pairs appended to the build command |
| `extra_cmake_args` | no | `''` | Extra arguments for a direct `cmake -S . -B <build_dir>` reconfigure step run after the port's own first configure. Left empty, the build runs in one `make` invocation. `ports/rp2/Makefile` builds its own cmake arguments with `CMAKE_ARGS +=`, so a define passed straight on the `make` command line replaces the whole accumulated set (including `MICROPY_BOARD`/`USER_C_MODULES`/`MICROPY_FROZEN_MANIFEST`) instead of adding to it -- pass one when the module needs its own CMake define, e.g. `-DMICROPY_C_HEAP_SIZE=131072` |
| `build_dir` | no | `''` → `$GITHUB_WORKSPACE/usermod/build/rp2040` | Value for `BUILD=`. A bare relative value (no leading `/`) resolves against `$MPY_DIR/ports/rp2` instead, same as a bare `BUILD=` on the command line always did |

| Output | Description |
| --- | --- |
| `build_dir` | The `BUILD=` directory actually used (resolved default included), so the caller can find `firmware.uf2` without recomputing it |

### `build-usermod-armv7m`

The `ports/qemu` usermod build: installs the arm-none-eabi toolchain, builds
`mpy-cross`, then runs the port build under it, producing a `firmware.elf`.

QEMU itself is deliberately **not** installed here -- it's a runtime
emulator for testing the resulting `firmware.elf`, not a build dependency,
same split `build-usermod-rp2040` uses for the rp2040py emulator. Install
`qemu-system-arm` (and whatever your own test harness needs, e.g.
`pyserial`) as a caller-side step, alongside your own `run_qemu.py`-equivalent.

Requires: `MPY_DIR` and checkout, same as `build-usermod-unix`.

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `board` | no | `MPS2_AN385` | Value for `BOARD=`. The stock target: a Cortex-M3, no FPU |
| `user_c_modules` | no | `''` → `$GITHUB_WORKSPACE` | Value for `USER_C_MODULES=` |
| `frozen_manifest` | no | `''` → `$GITHUB_WORKSPACE/usermod/manifest.py` | Value for `FROZEN_MANIFEST=`. `ports/qemu` ships no `boards/manifest.py` of its own, so there's no port default to combine with here, unlike unix/rp2/esp32 |
| `extra_make_args` | no | `''` | Extra space-separated `VAR=value` pairs appended to the build command, e.g. a module's own precision define |
| `build_dir` | no | `''` → `$GITHUB_WORKSPACE/usermod/build/armv7m` | Value for `BUILD=`. A bare relative value (no leading `/`) resolves against `$MPY_DIR/ports/qemu` instead, same as a bare `BUILD=` on the command line always did -- pass one to get the port's own `build-$(BOARD)` default |

| Output | Description |
| --- | --- |
| `build_dir` | The `BUILD=` directory actually used (resolved default included), so the caller can find `firmware.elf` without recomputing it |

### `build-usermod-esp32`

The `ports/esp32` usermod build: installs ESP-IDF, builds `mpy-cross`,
then runs the port build under it, producing `micropython.bin`/`firmware.bin`.
Dumps IDF's own build logs and re-runs `ninja -v` on failure -- idf.py's
own console output swallows the actual compiler diagnostic on a failing
build, printing only "ninja failed with exit code 1".

No caching yet -- every consumer's original recipe had none either, so
this preserves behavior exactly rather than mixing an extraction with a
new capability. A real follow-up, not forgotten: ESP-IDF's own `--recursive`
clone is the heaviest single step across every action in this repo.

No `build_dir` input, unlike the sibling actions: a real CI failure showed
that passing `BUILD=` explicitly on the `make` command line -- regardless
of the value, even the port's own default -- makes esp32's internal
CMake-driven `mpy-cross` sub-build (a separate copy from the top-level one
this action already pre-builds) pick up `FROZEN_MANIFEST` through
`MAKEFLAGS` and fail with `undefined reference to mp_qstr_frozen_const_pool`.
The port's own `build-$(BOARD)` default is always used instead.

Requires: `MPY_DIR` and checkout, same as `build-usermod-unix`.

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `board` | no | `ESP32_GENERIC` | Value for `BOARD=` |
| `idf_target` | no | `esp32` | Chip family passed to `install.sh` (e.g. `esp32`, `esp32s3`). Deliberately separate from `board`, not derived from it -- more than one board can exist per chip family |
| `idf_ver` | no | `v5.5.1` | ESP-IDF version tag to clone |
| `user_c_modules` | no | `''` → `$GITHUB_WORKSPACE/usermod/micropython.cmake` | Value for `USER_C_MODULES=` -- a *file*, like `build-usermod-rp2040`'s own `user_c_modules` |
| `frozen_manifest` | no | `''` → `$GITHUB_WORKSPACE/usermod/manifest.py` | Value for `FROZEN_MANIFEST=` |
| `extra_make_args` | no | `''` | Extra space-separated `VAR=value` pairs appended to the build command |

| Output | Description |
| --- | --- |
| `build_dir` | The port's own default `build-$(BOARD)` directory (relative to `$MPY_DIR/ports/esp32`), so the caller can find `micropython.bin`/`firmware.bin` without recomputing it |

### Usage example

```yaml
jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        arch: [x64, x86, armv6m, armv7m, armv7emsp, armv7emdp, rv32imc, rv64imc, xtensa, xtensawin]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          submodules: recursive

      - uses: ballistics-lab/cibuildmp/.github/actions/fetch-micropython@v0.3.0
        with:
          mpy_tag: v1.28.0

      - uses: ballistics-lab/cibuildmp/.github/actions/build-natmod@v0.3.0
        with:
          arch: ${{ matrix.arch }}
          # natmod_dir: natmod              # default; a7p passes micropython/natmod
          # pre_build_command: make fetch-nanopb   # a7p-only, runs before `make dist`

      - uses: actions/upload-artifact@v7
        with:
          name: my-module-${{ matrix.arch }}
          path: natmod/build/${{ matrix.arch }}*/
          if-no-files-found: error
```

That replaces roughly 70 lines of per-arch toolchain-install boilerplate
(apt package selection, the xtensa tarball fetch, the esp-idf install +
the esp-idf-venv-shadows-system-pip fix) with one `uses:` block per matrix
leg, identical across every consuming repo.

Artifact upload is left to the caller on purpose -- artifact names and the
exact glob under `natmod/build/` differ per repo/module and aren't part of
the shared contract.

## Versioning

Pin consumers to a tag, not `@main` and not a commit SHA. Bumping the tag
a consumer references is a deliberate, visible edit in that repo, same as
bumping any other CI dependency -- a change here never silently changes
what three other repos' builds do.

`v0.3.0` is the first tag where the `cibuildmp` CLI actually builds a
module, not just plans it -- `v0.3.0a1` (this repository's first tag)
shipped the composite actions and the CLI's target-resolution half only.
Both continue `micropython-native-ci`'s version line rather than
restarting it: the composite actions are `v0.2.0`'s, moved. Consumers
pinned to `micropython-native-ci@v0.2.0` keep working until they repin --
that repository is deprecated, not deleted.

Older tags, on the old repository: `v0.2.0` added `build-usermod-windows`,
`-webassembly`, `-rp2040`, `-armv7m` and `-esp32`, and dropped the `-arch`
name suffix (`build-natmod-arch` → `build-natmod`). `v0.1.0` had only
`fetch-micropython`, `clone-micropython`, `build-natmod-arch` and
`build-usermod-unix-arch`.

The `cibuildmp` package and the actions share one version. The package is
not on PyPI yet, so every action installs it from its own checkout --
`cibuildmp-matrix` still does this directly
(`uv tool install ${{ github.action_path }}`), and the root `action.yml`
does the same thing one layer down, inside `action.Dockerfile`'s
own `COPY . /opt/cibuildmp` + `uv tool install` (a Docker action now, not
composite -- see that action's own comment for why: cibuildmp's toolchain
provisioning needs real apt packages baked into an image, not re-installed
on every job). Either way, the tool that runs is exactly the ref you
pinned, with no index to keep in sync. The root `Dockerfile` (the
standalone/WSL2 one, not the action's) pins the same way, just explicitly
instead of implicitly: `uv tool install git+https://github.com/ballistics-lab/cibuildmp.git@${CIBUILDMP_REF}`,
`CIBUILDMP_REF` defaulting to the latest tag at the time the Dockerfile
was last touched -- override it with `--build-arg CIBUILDMP_REF=vX.Y.Z`
for a different one, the same "pin a tag, not `@main`" rule as everywhere
else on this page.

`publish.yml`'s own `publish-docker` job builds and pushes
`action.Dockerfile` to
`ghcr.io/ballistics-lab/cibuildmp:<tag>` on every real release tag --
infrastructure for a pre-built, pulled-not-built action image, not yet
wired into `action.yml` itself. Switching `runs.image` over to
`docker://ghcr.io/ballistics-lab/cibuildmp:vX.Y.Z` has to be a deliberate
step in cutting the *next* release, not automatic: build-from-source and
a published image are both correct today, but a published one can only
be referenced by the exact tag that already has a matching image behind
it (`action.yml`'s own Docker-action syntax takes a literal string, not
an expression, so it cannot compute "whatever tag this is" at resolve
time) -- bump that reference, commit it, *then* tag the release, so the
image `publish-docker` builds from that same tag push is the one
`action.yml` (as committed at that tag) already points at.

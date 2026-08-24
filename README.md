# micropython-native-ci

Shared GitHub Actions building blocks for building and testing MicroPython
**natmod** (dynamically loadable native `.mpy` modules, built against
`py/dynruntime.mk`) and **usermod** (`USER_C_MODULES`, compiled straight
into a port's own firmware build) C extensions.

## Why this repo exists

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

## What's here

### Composite actions (`.github/actions/`)

Every table below is the action's complete input surface -- if it isn't
listed here, the action doesn't accept it. `MPY_DIR` in a "Requires"
line means `fetch-micropython` or `clone-micropython` (this repo's own)
must have already run in the same job; a composite action step can't set
an env var that steps *before* it will see, only ones after.

#### `fetch-micropython`

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

#### `clone-micropython`

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

#### `build-natmod`

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

#### `build-usermod-unix`

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

#### `build-usermod-windows`

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

#### `build-usermod-webassembly`

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

#### `build-usermod-rp2040`

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

#### `build-usermod-armv7m`

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

#### `build-usermod-esp32`

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

      - uses: ballistics-lab/micropython-native-ci/.github/actions/fetch-micropython@v0.1.0
        with:
          mpy_tag: v1.28.0

      - uses: ballistics-lab/micropython-native-ci/.github/actions/build-natmod-arch@v0.1.0
        # Still -arch here: the v0.1.0 tag predates the -arch suffix drop
        # (see CHANGELOG.md's [Unreleased] Changed section) -- build-natmod
        # (no suffix) only exists past that tag, e.g. pinned to a branch ref.
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

## Roadmap

Not done yet, deliberately -- each of these needs to be verified against
real CI in the consuming repo, not just written and trusted:

- A reusable `workflow_call` for the full natmod build+test matrix
  (build-natmod already covers the highest-drift part of it).
- A reusable `workflow_call` for the "armv7emsp / armv7emdp on real ARM
  Linux" test job -- currently near-identical hand-copied YAML in all
  three source repos.
- A small scaffolding script to generate a new `natmod/` + `usermod/`
  skeleton for a fresh module, wired to the actions above.

## Versioning

Pin consumers to a tag, not `@main` and not a commit SHA. Bumping the tag
a consumer references is a deliberate, visible edit in that repo, same as
bumping any other CI dependency -- a change here never silently changes
what three other repos' builds do.

`v0.1.0` is the only tag cut so far (`fetch-micropython`,
`clone-micropython`, `build-natmod-arch`, `build-usermod-unix-arch` --
each still under their pre-rename `-arch`-suffixed names at that point).
Every action added since (`build-usermod-windows`, `-webassembly`,
`-rp2040`, `-armv7m`, `-esp32`, plus the `-arch` suffix drop itself) only
exists past that tag -- consuming repos currently reach these by pinning
to this development branch instead
(`@claude/usermod-shared-action-kwulzv`), deliberately, while each new
action is still being proven against real CI one consumer at a time. A
`v0.2.0` tag, and repinning every consumer's `natmod.yml`/`usermod.yml`
off the branch ref onto it, is queued but not yet cut.

# cibuildmp

[![SWUbanner]][SWUBadge]
[![license]][license-url]
![natmod-abi]
![usermod-tag]
[![pypi version]][PyPiUrl]
[![python versions]][PyPiUrl]
[![pre-commit]][pre-commit-workflow]
[![coverage]][CodecovUrl]

> [!WARNING]
> Pre-1.0.0 and still alpha software — the config schema and CLI can change
> between releases without a deprecation cycle. Pin an exact `@vX.Y.Z` tag,
> never a branch.

Build MicroPython native C extensions for every target they support, from
one declarative config — on CI and on your own machine. `cibuildwheel`, for
MicroPython.

Covers **natmod** (dynamically loadable native `.mpy` modules, built against
`py/dynruntime.mk`) and **usermod** (`USER_C_MODULES`, compiled straight
into a port's own firmware build) C extensions.

The two halves reach different distances back: **natmod** builds every
release from `v1.12` on (ABI 5 through 6.3), **usermod** every port from
`v1.20.0` on (`qemu` from `v1.24.0`). Both run to the newest preview release
the pinned tag table knows.

## Why

MicroPython gives a native C extension two standard, unrelated build paths:

- **natmod** — `natmod/Makefile` includes MicroPython's own
  `py/dynruntime.mk`, parameterised by `ARCH=`. Produces a runtime-loadable
  `.mpy` per target architecture. See MicroPython's own `examples/natmod/`.
- **usermod** — `usermod/micropython.cmake` + `usermod/micropython.mk`,
  pointed at via `USER_C_MODULES=` on a port's own build. Compiled straight
  into the firmware image. See MicroPython's
  [`docs/develop/cmodules.rst`](https://docs.micropython.org/en/latest/develop/cmodules.html).

[`ballistics-lab/micropython-bclibc`](https://github.com/ballistics-lab/micropython-bclibc),
[`o-murphy/micropython-wasm3`](https://github.com/o-murphy/micropython-wasm3)
and [`o-murphy/a7p`](https://github.com/o-murphy/a7p) each already follow
that layout — that part was never the problem. What diverged was the CI
*around* it: each repo's own GitHub Actions workflow was hand-copied into
the next and then evolved independently, so the same ~10-architecture
build matrix and the same toolchain-install steps ended up as three
separate, slowly drifting copies. `cibuildmp` is the shared home for the
parts that are genuinely identical across all three, resolving each
target's cross-toolchain itself instead of leaving it hand-written per
repo, the same way locally and on CI.

## Quick start

Install it from PyPI and point it at a module with a `cibuildmp.toml`:

```console
$ uv tool install cibuildmp
$ cibuildmp --build "mpy6.3-*" --dry-run
cibuildmp: 10 target(s) against MicroPython v1.29.0
  [ 1/10] mpy6.3-v1.29.0-x86           make -C natmod ARCH=x86 dist
  [ 2/10] mpy6.3-v1.29.0-x64           make -C natmod ARCH=x64 dist
  ...
```

An unconfigured `build` matches nothing at all, from any platform — see
[Identifiers and selectors](#identifiers-and-selectors) below for the full
identifier list and glob syntax. Drop `--dry-run` and it builds for real:
each target lands in its own `output-dir/<identifier>/` directory
(`mpyhouse/mpy6.3-v1.29.0-x64/`, …), with a `package.json` mip can install from
once `version` is set.

**Host prerequisites, in full:** Docker (below), `git` — needed only for a
preview tag, which publishes no release tarball and is therefore cloned —
and a C compiler for the one `qemu` usermod cell. natmod additionally
bind-mounts *cibuildmp's own installed* `pyelftools`/`ar` into every
container rather than baking them into six images, so those come from your
`cibuildmp` install, not from the image and not from your system Python.

**`cibuildmp` needs a reachable Docker daemon on whatever host runs it —
one that shares this machine's filesystem.** Every path is bind-mounted
into the container at its identical host path, so a remote or
VM-isolated daemon that cannot see your working tree will not work.
It never builds an image itself — it pulls pre-built, pinned images (most
are pypa's own `quay.io/pypa/<target>` directly; the handful cibuildmp
adds a thin layer to publish as `ghcr.io/ballistics-lab/<target>`) and
launches sibling containers, one per target, the same way cibuildwheel's
own container runtime does. That
covers natmod (four of the five toolchain-group images cover all ten
arches — see [`docs/reference/vendored-images.md`](docs/reference/vendored-images.md))
and every usermod port, `esp32` included — only the ESP-IDF `git clone` itself
stays on the host (source, not a binary, the same reasoning `mpy_dir`
mounts straight in everywhere else); installing ESP-IDF's own tools and
building both run inside `esp_idf_base`. There is no
"run `cibuildmp` itself inside Docker" story any more — a previous root
`Dockerfile` offered that and was deleted once usermod needed to launch
sibling containers of its own (Docker-in-Docker was ruled out); `uv tool
install cibuildmp`/`pip install cibuildmp` directly is the one supported
way to run it outside CI.

**A container build looks exactly like a host build in the log.** Every
path is bind-mounted at its identical host path, so `make` prints the same
directory names it would locally, and a digest-pinned image shows as
`<none>` in `docker images`. Nothing has escaped the container; there is
just no visible difference to escape into.

A non-native target (anything other than your own machine's architecture)
also needs an emulator registered: `docker/setup-qemu-action@v4` on CI, or
once per machine locally, `docker run --privileged --rm tonistiigi/binfmt
--install all`. `cibuildmp` names the missing emulator up front rather
than letting the build fail with `exec format error`.

On CI, use the action instead of installing the CLI yourself — it already
runs on a bare runner with the runner's own Docker daemon reachable:

```yaml
- uses: ballistics-lab/cibuildmp@v0.6.2
  with:
    build: "mpy6.3-* v1.29.0-manylinux_2_28_x86_64"
```

The action takes seven inputs, all optional — every one overrides the
config file rather than replacing it:

| Input         | Default    | What it does                                                                                      |
| ------------- | ---------- | ------------------------------------------------------------------------------------------------- |
| `package-dir` | `.`        | Directory holding the module and its config                                                       |
| `config-file` | —          | Config to use instead of `<package-dir>/cibuildmp.toml`                                           |
| `build`       | —          | Override the config's own `build` selector                                                        |
| `skip`        | —          | Override the config's own `skip` selector                                                         |
| `output-dir`  | `mpyhouse` | Where to collect output. **natmod only** — usermod reads it from the config or `CIBMP_OUTPUT_DIR` |
| `keep-going`  | —          | Any non-empty value: build every selected target even after one fails                             |
| `extras`      | —          | **Leave empty.** There are no extras today; a non-empty value fails the install                   |

Anything without an input has an environment form instead — see
[Configuration](#configuration).

**An empty `CIBMP_*` environment variable is a value, not an absence.** Only
an *unset* variable is skipped; `CIBMP_VERSION=""` overrides a
`version = "1.0.0"` in your config with the empty string, which silently
disables `package.json` and `[publish] extra-files`. This matters on Actions
specifically, because the usual conditional-env idiom sets the variable
either way:

```yaml
env:
  CIBMP_VERSION: ${{ startsWith(github.ref, 'refs/tags/v') && github.ref_name || '' }}   # WRONG
```

Write the variable only when you mean it:

```yaml
- if: startsWith(github.ref, 'refs/tags/v')
  run: echo "CIBMP_VERSION=${GITHUB_REF_NAME}" >> "$GITHUB_ENV"
```

### A complete workflow

Every natmod arch cross-compiles inside a `linux/amd64` container, so this
needs **no matrix and no `docker/setup-qemu-action`** — one job builds all
ten:

```yaml
name: build
on: [push, pull_request]

jobs:
  natmod:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: ballistics-lab/cibuildmp@v0.6.2
        with:
          build: "mpy6.3-v1.29.0-*"
      - uses: actions/upload-artifact@v4
        with:
          name: mpy
          path: mpyhouse/
```

usermod is the case that *does* need a matrix, because some of its
identifiers are native to a non-amd64 runner (`*_aarch64`, `*_armv7l` →
`ubuntu-24.04-arm`) and the rest are emulated — add
`docker/setup-qemu-action` to any job building an emulated cell. See
[`.github/workflows/build-examples.yml`](.github/workflows/build-examples.yml)
for a worked multi-runner version.

See [`examples/template`](examples/template) for a minimal natmod module
and its `cibuildmp.toml`, and [`examples/wasm2mpy`](examples/wasm2mpy) for
one whose native source is WebAssembly, compiled through `wasm2c` — the
natmod contract doesn't care what produced the C. `cibuildmp --help` lists
every flag, and [Configuration](#configuration) below covers the config
file, every option key, the `CIBMP_*` environment forms and the order they
all resolve in.

## Your first module

Empty directory to a working `.mpy`, in three files. Every command and every
output below is from a real run, not an illustration.

**1. `natmod/mymod.c`** — the module itself:

```c
#include "py/dynruntime.h"

static mp_obj_t add(mp_obj_t a_obj, mp_obj_t b_obj) {
    return mp_obj_new_int(mp_obj_get_int(a_obj) + mp_obj_get_int(b_obj));
}
static MP_DEFINE_CONST_FUN_OBJ_2(add_obj, add);

mp_obj_t mpy_init(mp_obj_fun_bc_t *self, size_t n_args, size_t n_kw, mp_obj_t *args) {
    MP_DYNRUNTIME_INIT_ENTRY
    mp_store_global(MP_QSTR_add, MP_OBJ_FROM_PTR(&add_obj));
    MP_DYNRUNTIME_INIT_EXIT
}
```

`py/dynruntime.h` in the pinned checkout is the whole API a natmod may
use — `mp_obj_get_int`, `mp_obj_new_int`, `mp_get_buffer_raise` and the
rest. Read it when you need something this example does not show.

**2. `natmod/Makefile`** — `MPY_DIR` and `ARCH` arrive on the command line;
don't hardcode them. **`BUILD` and the `dist` output must be different
directories**: `cibuildmp` globs `build/<arch>*/*.mpy` for the finished
file, so leaving make's own intermediates there gives it two `.mpy` files
and the `ambiguous output` error below:

```make
MOD = mymod
SRC = mymod.c

# Keep make's own object files out of build/, and scope them per MicroPython
# release and per arch -- an object file depends on neither, so anything
# shared here gets silently reused across both.
BUILD = .obj/$(notdir $(patsubst %/,%,$(MPY_DIR)))/$(ARCH)

include $(MPY_DIR)/py/dynruntime.mk

# cibuildmp looks for the finished .mpy in build/<arch>*/
dist:
	rm -f $(MOD).mpy
	$(MAKE) all
	mkdir -p build/$(ARCH)
	cp $(MOD).mpy build/$(ARCH)/
```

**3. `cibuildmp.toml`** — what to build. Start with one target:

```toml
build = "mpy6.3-v1.29.0-x64"
```

Then run it:

```console
$ cibuildmp
cibuildmp: 1 target(s) against MicroPython v1.29.0
  [1/1] mpy6.3-v1.29.0-x64        make -C natmod ARCH=x64 dist
...
cibuildmp: 1 target(s) built in 0.7s
  mpy6.3-v1.29.0-x64: mymod-mpy6.3-v1.29.0-x64.mpy (210 bytes)
```

The result is in `mpyhouse/mpy6.3-v1.29.0-x64/`. That is the whole loop —
the same command, with a wider `build`, is what CI runs.

### Widening it

Change one line to build every arch instead of one:

```toml
build = "mpy6.3-v1.29.0-*"
```

`cibuildmp --print-build-identifiers` lists exactly what a glob selects
before you build it, and `--dry-run` shows the `make` command line each
target will get. Neither builds anything, so both are safe to run
repeatedly while you get the glob right.

### Using what you built

The `.mpy` is a normal MicroPython native module. On a board:

```console
$ mpremote cp mpyhouse/mpy6.3-v1.29.0-armv6m/mymod-*.mpy :mymod.mpy
$ mpremote exec "import mymod; print(mymod.add(2, 3))"
5
```

The filename carries its identifier so several arches can sit side by side;
rename it to plain `mymod.mpy` on the device, because `import mymod` looks
for exactly that name.

**Ask the device which arch it wants** rather than guessing from the board:

```python
>>> import sys; print(sys.implementation._mpy >> 10)
```

That number is the `MP_NATIVE_ARCH_*` index — 1 `x86`, 2 `x64`, 4 `armv6m`,
5 `armv7m`, 7 `armv7emsp`, 8 `armv7emdp`, 9 `xtensa`, 10 `xtensawin`,
11 `rv32imc`, 12 `rv64imc`.

**For `mip install`**, set `version` in your config. `cibuildmp` then writes
a `package.json` beside each `.mpy` naming the ABI and arch it is
compatible with, which is what lets one release serve every device:

```toml
name = "mymod"
version = "1.0.0"
```

**What each port produces**, since it is not a `.mpy` for any of them:

| Port          | Artifact                                         |
| ------------- | ------------------------------------------------ |
| `unix`        | `micropython` — plus a `lib/` sidecar, see below |
| `windows`     | `micropython.exe`                                |
| `webassembly` | `micropython.mjs` (with its `.wasm` beside it)   |
| `qemu`        | `firmware.elf`                                   |
| `esp32`       | `micropython.bin`                                |
| `rp2`         | `firmware.uf2`                                   |

Flashing or running those is your own port's normal procedure —
`cibuildmp` collects them and stops.

**A `usermod` build is not one file.** `unix` in particular produces the
binary *plus* a `lib/` directory beside it: `cibuildmp` copies every
non-baseline shared library the binary needs into it and sets an
`$ORIGIN/lib` rpath, so the binary runs outside the container it was built
in. Upload or copy the whole identifier directory, not just the file in it.

The `urls` entries in that `package.json` are **relative** — an on-device
basename paired with the identifier-qualified filename sitting beside it —
so `mip` resolves them against wherever it fetched the `package.json` from:

```console
$ mpremote mip install https://example.com/releases/v1.0.0/package.json
```

Publishing that directory — a GitHub Release, or anywhere else — stays your
own CI step. `cibuildmp` assembles the tree and stops there, the same line
cibuildwheel draws at `wheelhouse/`.

### When you outgrow three files

Two more example trees exist and are built by CI on every push:
[`examples/natmod`](examples/natmod) and
[`examples/usercmodule`](examples/usercmodule) are MicroPython's *own*
upstream examples, built through `cibuildmp` unmodified — proof the tool
works on modules it did not shape, and the closest thing here to a
compatibility suite.

The Makefile above is the **minimum for one arch at a time**.
[`examples/template`](examples/template)'s own differs deliberately and is
what a full matrix needs: `BUILD` folds in `$(ARCH_FLAGS)` (so two
`rv32imc` variants do not share objects), carries an extra directory level
(so a `../src/` source stays arch-scoped), and `dist` deletes `$(MOD).mpy`
before rebuilding (so a second run in the same tree cannot collect the
previous arch's file). Each of those is a real silent-wrong-binary bug
its comments record.

[`examples/template`](examples/template) is the same module with everything
a real project ends up needing: a shared `src/` core compiled by both the
natmod and the usermod path, a `usermod/` half, and a `Makefile` whose
comments record three separate ways a shared `BUILD` directory silently
produces the *wrong* arch's binary. Read it when your own build starts
doing something strange, not before.

## Identifiers and selectors

Every buildable thing — one natmod arch, one usermod port/board/arch cell —
has a real, stable **identifier**, read straight from
`resources/build-platforms.toml` (never guessed or reconstructed from a
format string). `build`/`skip` (config, `CIBMP_BUILD`/`CIBMP_SKIP` env
vars, or `--build`/`--skip` on the CLI) are space-separated glob patterns
matched against these identifiers, `skip` applied after `build`; an
`[override."<glob>"]` table applies option overrides to whichever
identifiers match its own glob. There's no other selection mechanism — no
per-platform table, no `--platform`/`--only` flag, no `auto`/`native`/`all`
keyword vocabulary. **An unconfigured `build` selects nothing, from any
platform.**

Identifier shapes, one per platform:

<!-- generated: identifier-shapes -- bin/refresh_docs.py, do not edit by hand -->
| Platform              | Shape                   | Example                               |
| --------------------- | ----------------------- | ------------------------------------- |
| natmod                | `mpy{abi}-{tag}-{arch}` | `mpy6.3-v1.29.0-armv6m`               |
| usermod `esp32`       | `{tag}-esp32-{board}`   | `v1.29.0-esp32-ARDUINO_NANO_ESP32`    |
| usermod `qemu`        | `{tag}-qemu-{board}`    | `v1.29.0-qemu-MICROBIT`               |
| usermod `rp2`         | `{tag}-rp2-{board}`     | `v1.29.0-rp2-ADAFRUIT_FEATHER_RP2040` |
| usermod `unix`        | `{tag}-{arch}`          | `v1.29.0-manylinux_2_28_aarch64`      |
| usermod `webassembly` | `{tag}-{arch}`          | `v1.29.0-wasm32`                      |
| usermod `windows`     | `{tag}-{arch}`          | `v1.29.0-win32`                       |
<!-- /generated: identifier-shapes -->

The shape genuinely differs per usermod port — `unix`/`windows`/
`webassembly` carry no port name at all in the identifier, only `qemu`/
`esp32`/`rp2` do. `--print-build-identifiers --json` against a broad `build`
glob is the fastest way to see the real list for yourself rather than
guessing one by hand:

```console
$ cibuildmp --build "mpy6.3-* v1.29.0-manylinux* v1.29.0-esp32-*" \
    --print-build-identifiers
```

```toml
build = "mpy6.3-*"                        # every arch, one natmod ABI, newest verified tag
build = "mpy6.2-* mpy6.3-*"                # two ABIs in one invocation
build = "v1.29.0-manylinux*"               # every native unix cell, one tag
skip  = "*_ppc64le *_s390x *_riscv64"      # drop the emulated-everywhere cells
build = "v1.29.0-esp32-ESP32_GENERIC"      # exactly one board

[override."*-armv7emsp"]
extra-make-args = ["MP_BCLIBC_PRECISION=single"]
```

`{...,...}` brace expansion works inside a pattern (`build =
"*-{x64,armv6m}"`), matching shell glob syntax. A `build`/`skip` pattern
that can never match any real identifier is a load-time error, not a
silent no-op.

When a `build` glob names no specific MicroPython tag, natmod narrows the
match to the newest tag this project has verified as *stable* for that
ABI — name one explicitly (`mpy6.3-v1.29.0-*`) to pin it yourself. Usermod
has no equivalent narrowing: every real `(port, tag, arch/board)` row
already carries its own explicit tag.

### `--keep-going` and the JSON build report

The default is fail-fast: the first target to fail stops the whole
invocation, and nothing selected after it is even attempted — the same
behaviour `cibuildwheel` itself has, unconditionally, with no keep-going
concept of its own. `--keep-going` (record 0063) is a deliberate cibuildmp
divergence for the opposite case — a `--build` glob wide enough to span a
real coverage sweep, where the point is to find out *every* target's own
outcome rather than stop at the first one that fails.

Every attempted target — success or failure, `--keep-going` or not — is
written to a JSON report, one file per invocation, under
`<output-dir>/reports/` by default — `mpyhouse/reports/`, beside the
artifacts of the same run (`CIBMP_REPORT_PATH` to redirect it). Each entry
carries the identifier, how long it took, and either the built artifact's
directory/size/file listing or the error that stopped it:

```json
{
  "generated_at": "2026-08-29T12:00:00+00:00",
  "total_duration": 12.4,
  "built": 1,
  "failed": 1,
  "results": [
    {
      "identifier": "v1.29.0-manylinux_2_28_x86_64",
      "duration": 9.1,
      "error": null,
      "output_dir": "mpyhouse/v1.29.0-manylinux_2_28_x86_64",
      "size": 1048576,
      "files": ["micropython-v1.29.0-manylinux_2_28_x86_64"]
    },
    {
      "identifier": "v1.29.0-qemu-POWERNV9",
      "duration": 3.3,
      "error": "make: *** [firmware.elf] Error 1",
      "output_dir": null,
      "size": null,
      "files": []
    }
  ]
}
```

## Configuration

### Where config lives

`cibuildmp` reads exactly one config source, resolved in this order:

1. `--config-file <path>`, if given (a missing file is an error, not a
   fallback).
2. `<package-dir>/cibuildmp.toml`.
3. `[tool.cibuildmp]` in `<package-dir>/pyproject.toml`.
4. Nothing. Every option has a default, so this is legitimate — but
   `build` defaults to empty, and an empty `build` selects nothing, so a
   config-less run builds nothing rather than everything.

`<package-dir>` is the CLI's positional argument (`cibuildmp micropython/`)
or the action's `package-dir` input, defaulting to `.`. Only the first
source that exists is read — the three are alternatives, not layers.

### The shape

One flat table of scalar keys, plus two real sub-tables. There are no
per-platform config tables: `[natmod]`, `[unix]`, `[esp32]`, `[usermod]`
and friends were all retired ([0052]/[0074]) and writing one now is a
plain "unknown table" error. Anything a per-platform table used to say, a
sufficiently-scoped glob already says — every identifier carries its own
platform marker.

```toml
# ── invocation-wide ───────────────────────────────────────────────────
build = "mpy6.3-v1.29.0-* v1.29.0-manylinux_2_28_x86_64"
skip  = "*-armv6m"
name    = "mymod"          # .mpy/package.json naming; defaults to empty
version = "1.2.0"
output-dir = "mpyhouse"

# ── defaults for every target, of either family ───────────────────────
module-dir     = "natmod"      # natmod: where its Makefile lives
user-c-modules = "usermod"     # usermod: the USER_C_MODULES path
manifest       = "usermod/manifest.py"
extra-make-args = ["LDFLAGS_EXTRA=-static"]

# ── narrowed to the identifiers a glob matches ────────────────────────
[override."*-manylinux_2_31_armv7l"]
extra-make-args = ["LDFLAGS_EXTRA=-static"]

[override."*-wasm32"]
extra-make-args = ["VARIANT=pyscript"]
inherit = { extra-make-args = "append" }   # or "prepend"; default replaces

# ── natmod only: files copied beside every built .mpy ─────────────────
[publish]
extra-files = ["../src/mymod.py"]
```

`[override]` is keyed **directly by its own glob** — `[override."<glob>"]`,
deliberately unlike cibuildwheel's `[[tool.cibuildwheel.overrides]]` with a
`select =` field inside. (Writing `select = "…"` *inside* an entry is an
error, not a second spelling.) The table name takes the full selector
syntax, so one entry can cover several globs:
`[override."*-manylinux* *-win* *-wasm32"]`. Entries are matched in file order and every
matching one applies, so two globs that both match one identifier layer
onto each other rather than the first winning.

### Every key

| Key                      | Read by | Default                |                      Also in `[override]`?                       |
| ------------------------ | ------- | ---------------------- | :--------------------------------------------------------------: |
| `build`                  | both    | `""` (selects nothing) |                                ✗                                 |
| `skip`                   | both    | `""`                   |                                ✗                                 |
| `output-dir`             | both    | `"mpyhouse"`           |                                ✗                                 |
| `name`                   | both    | `""`                   |                                ✗                                 |
| `version`                | both    | `""`                   |                                ✗                                 |
| `arch-flags`             | natmod  | `[]`                   | ✗ — resolved once for the whole config, before any target exists |
| `micropython-submodules` | natmod  | `[]`                   |                                ✗                                 |
| `module-dir`             | natmod  | `"natmod"`             |                                ✓                                 |
| `make-target`            | natmod  | `"dist"`               |                                ✓                                 |
| `pre-build-command`      | natmod  | `""`                   |                                ✓                                 |
| `extra-make-args`        | both    | `[]`                   |                                ✓                                 |
| `user-c-modules`         | usermod | `"."`                  |                                ✓                                 |
| `manifest`               | usermod | `""`                   |                                ✓                                 |
| `extra-cmake-args`       | usermod | `[]`                   |                                ✓                                 |

Every list-valued key also accepts a plain string, split the way a shell
would: `extra-make-args = "CXX=em++ CXXFLAGS_MOD=-Wno-macro-redefined"` is
the same as the two-element list.

A key a family does not read is accepted and ignored, so
`pre-build-command` in a usermod-only config is silently inert — usermod has
no pre-build hook at all. The "Read by" column is the one to check.

Two more keys live in tables rather than at the top level, so they are not
in the list above: `[publish] extra-files` (natmod — files copied beside
every built `.mpy`) and `inherit` inside an `[override]` entry.

**`name` and `version` do different things per family.** For natmod they
name the artifact *and* gate `package.json`; for usermod they only replace
the output filename's stem — there is no manifest for a firmware image.

**`version` gates more than the version string.** For natmod, with `version` unset,
`cibuildmp` writes no `package.json` *and copies no `[publish] extra-files`*
— the identifier directory holds the built artifact alone. Set `name` and
`version` as soon as you want either.

Every key is valid at the top level whatever family reads it — the global
layer is just every platform's own default, so a natmod-only key in a
usermod-only project is accepted and ignored, not rejected. A key **no**
family recognises is an error, with a close-match suggestion ([0075]):

```console
$ cibuildmp
cibuildmp: error: cibuildmp.toml: unknown key `buidl`. Perhaps you meant `build`?
```

Two notes on individual keys:

- `user-c-modules` is **rewritten to its parent** for a Make port when the
  directory you name contains `micropython.mk` itself. MicroPython's own
  `py/py.mk` globs `<USER_C_MODULES>/*/micropython.mk`, one level *below*
  the path it is given, so a flat single-module layout would otherwise link
  nothing and still succeed. `cibuildmp` detects that shape and adjusts;
  you do not need to point one level up yourself.
- `module-dir` and `user-c-modules` accept a literal `{micropython}`
  placeholder, substituted with the pinned checkout cibuildmp itself
  fetched ([0071]/[0072]) — `module-dir = "{micropython}/examples/natmod/btree"`
  builds a module living inside MicroPython's own tree, with nothing
  vendored into your repo.
- `arch-flags` is a *list*, and each entry produces its own target: it is an
  axis, not a flag. That is why it cannot live in `[override]` — an override
  is matched against an identifier that arch-flags itself helped create.
  The extra entries get a `+0x<hex>` suffix, which the generated shape table
  above cannot express because it is built from `identifier_format`:

  ```console
  $ cibuildmp --print-build-identifiers   # arch-flags = ["", "zba,zcmp"]
  mpy6.3-v1.29.0-rv32imc
  mpy6.3-v1.29.0-rv32imc+0x3
  ```

  So an override for the flagged variant is `[override."*rv32imc+0x3"]`, and
  a plain `skip = "*-rv32imc"` will *not* match it — `*-rv32imc*` does.

### Environment variables

Every option key above has an environment form: `CIBMP_` + the key in
`SCREAMING_SNAKE_CASE` (`extra-make-args` → `CIBMP_EXTRA_MAKE_ARGS`), the
same shape cibuildwheel's own `CIBW_*` uses. `build` and `skip` also take a
per-platform form, `CIBMP_BUILD_<PLATFORM>`/`CIBMP_SKIP_<PLATFORM>` —
`CIBMP_BUILD_NATMOD`, `CIBMP_BUILD_UNIX`, `CIBMP_SKIP_ESP32`, … — and
natmod's `arch-flags` takes `CIBMP_ARCH_FLAGS_NATMOD`.

**The per-platform form does not replace the global selection — it scopes
one platform's own, alongside it.** This surprises people, so it is worth
seeing:

```console
$ CIBMP_BUILD_UNIX=v1.29.0-manylinux_2_28_x86_64 \
  cibuildmp --build v1.29.0-win_amd64 --print-build-identifiers
v1.29.0-manylinux_2_28_x86_64
v1.29.0-win_amd64
```

`unix` used its own env-scoped selector; every other platform kept the
global one. Use it to widen one platform in one CI job without touching the
config file — not to narrow the run as a whole.

A second group of variables configures the machinery rather than the build,
and has no config-file counterpart at all. **What `<TARGET>` is depends on
the port**, because it is that port's own build axis:

| `<PORT>`                      | `<TARGET>`       | example                                         |
| ----------------------------- | ---------------- | ----------------------------------------------- |
| `unix`                        | the platform tag | `CIBMP_UNIX_MANYLINUX_2_28_X86_64_DOCKER_IMAGE` |
| `windows`                     | the arch         | `CIBMP_WINDOWS_WIN_AMD64_DOCKER_IMAGE`          |
| `qemu`                        | the board        | `CIBMP_QEMU_MPS2_AN385_DOCKER_IMAGE`            |
| `natmod`                      | the arch         | `CIBMP_NATMOD_ARMV7EMSP_DOCKER_IMAGE`           |
| `esp32`, `rp2`, `webassembly` | *none*           | `CIBMP_WEBASSEMBLY_DOCKER_IMAGE`                |


| Variable                                | Effect                                                                                                                                                                                                                            |
| --------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `CIBMP_CACHE_PATH`                      | Where fetched MicroPython checkouts and ESP-IDF are cached. Defaults to `$XDG_CACHE_HOME/cibuildmp`, or `~/.cache/cibuildmp`. Pin it in CI when a later step needs the checkout by path — `<CIBMP_CACHE_PATH>/micropython/<tag>` |
| `CIBMP_SCRATCH_PATH`                    | Read, but currently redirects nothing: every usermod port's compiled build state now lives inside its own container and never reaches the host (record 0095's own addendum 13). Left as a documented knob rather than removed outright |
| `CIBMP_REPORT_PATH`                     | Where the JSON build report is written                                                                                                                                                                                            |
| `CIBMP_TIMEOUT`                         | Seconds before a build container is killed (`docker kill`, not just the CLI). No limit by default. **usermod only** -- natmod's own container call does not consult it                                                            |
| `CIBMP_<PORT>_<TARGET>_TIMEOUT`         | The same, for one container — `CIBMP_UNIX_MANYLINUX_2_28_X86_64_TIMEOUT`                                                                                                                                                          |
| `CIBMP_<PORT>_<TARGET>_DOCKER_IMAGE`    | Run this (port, target) in a different image — a locally built one, or a fork's. Wins over the pinned default. Omit the `<TARGET>` segment for a port with no per-build image axis (`CIBMP_WEBASSEMBLY_DOCKER_IMAGE`)             |
| `CIBMP_<PORT>_<TARGET>_DOCKER_PLATFORM` | Same shape, for the container's `--platform`                                                                                                                                                                                      |
| `CIBMP_DEBUG_TRACEBACK`                 | Print a full traceback instead of a one-line error (same as `--debug-traceback`)                                                                                                                                                  |
| `CIBMP_DISABLE_GITHUB_STEP_SUMMARY`     | Suppress the step-summary table on GitHub Actions                                                                                                                                                                                 |

### Precedence

There are two chains, because two kinds of option resolve at two different
times, and they do **not** order env and `[override]` the same way.

**Invocation-wide options** — `build`, `skip`, `output-dir`, `name`,
`version`, `arch-flags`, `micropython-submodules` — resolve once, before any
target exists. Later wins:

```
built-in default  →  config file  →  CIBMP_<KEY>  →  CLI flag
```

with `CIBMP_BUILD_<PLATFORM>`/`CIBMP_SKIP_<PLATFORM>` applying *per
platform* on top of whatever that chain produced, as shown above.

Only three of these have a CLI flag at all — `--build`, `--skip` and
`--output-dir` — and `--output-dir` is **natmod-only**: usermod's own
`output-dir` comes from the config file or `CIBMP_OUTPUT_DIR`, and passing
the flag does not move its collected files. Everything else is config file
or environment.

**Per-target options** — `module-dir`, `make-target`, `pre-build-command`,
`extra-make-args`, `user-c-modules`, `manifest`, `extra-cmake-args` —
resolve once per identifier, after selection. Later wins:

```
built-in default  →  config file (top level)  →  matching [override] entries  →  CIBMP_<KEY>
```

So an `[override]` beats the top-level default for the identifiers it
matches, and an environment variable beats **everything**, override
included — a one-off CI override stays a one-off, and cannot be
accidentally re-narrowed by a glob in the config file. Matching
`[override]` entries apply in file order, each replacing the running value
unless its own `inherit` rule says otherwise:

```toml
extra-make-args = ["A=1"]

[override."*-x64"]
extra-make-args = ["B=2"]
inherit = { extra-make-args = "append" }  # -> A=1 B=2   ("prepend" -> B=2 A=1)
                                          # without inherit -> B=2
```
`inherit` only applies to list-valued options — `extra-make-args` is the one
option genuinely list-shaped across every platform's own override surface;
naming a scalar option in `inherit` is a config error, not a silent no-op.

<!-- Every record this file cites, defined once. Reference definitions are
     document-wide, so the numbers used in other sections resolve too --
     they were bare bracketed text before, which rendered as literal
     "[0043]" with nothing behind it. -->

[0038]: docs/records/0038-m5-adopt-in-three-repos.md
[0043]: docs/records/0043-unix-adopts-cibuildwheel-native-image-model.md
[0052]: docs/records/0052-config-is-a-tree-not-a-selector-matrix.md
[0058]: docs/records/0058-image-groups-are-toolchains-not-ports.md
[0071]: docs/records/0071-micropython-placeholder-in-user-c-modules.md
[0072]: docs/records/0072-natmod-micropython-placeholder-and-upstream-natmod-ci.md
[0074]: docs/records/0074-usermod-family-table-and-retired-table-messages-removed.md
[0075]: docs/records/0075-top-level-scalar-keys-are-validated.md
[0076]: docs/records/0076-the-mipsel-holdout-is-bclibc-and-wasm3-not-a7p.md
[0077]: docs/records/0077-docs-drift-is-a-failing-test-not-a-discipline-problem.md

## When a build fails

Every heading below is the message `cibuildmp` actually prints, minus the
`cibuildmp: error: ` prefix every error carries — so searching this page for
the text in your terminal finds it. Find yours, read the cause, apply the
fix.

### no targets selected. Pass --allow-empty if that is expected.

Your `build` glob matched nothing. This is the normal first-run result,
because an unset `build` selects **nothing at all** — there is no "build
everything" default.

Check what you asked for against what exists:

```console
$ cibuildmp --print-build-identifiers        # what your config selects
$ cibuildmp --build "*" --print-build-identifiers | head   # what exists
```

A glob that matches nothing is usually a tag that has no rows (`v1.28.1`
is not a MicroPython release) or a port spelled as a port when the
identifier has no port segment — `unix`, `windows` and `webassembly`
identifiers are `{tag}-{arch}`, with no `unix-` in them.

### unknown key &#96;buidl&#96;. Perhaps you meant &#96;build&#96;?

A typo, or a key from a config schema older than v0.6.0. The suggestion is
usually right. See [Configuration](#configuration) for every key that
exists.

### unknown table(s) at the top level: [natmod].

Per-platform tables (`[natmod]`, `[unix]`, `[esp32]`, `[usermod]`, …) were
removed in v0.6.0. Everything lives at the top level now, narrowed with
`[override."<glob>"]`. Move the keys up and delete the table.

### `docker run against image '…' was requested but the docker CLI itself is not on PATH`

`cibuildmp` builds in containers, with **one exception**: a `qemu` usermod
build compiles `mpy-cross` on the host first (`_HOST_MPY_CROSS_PORTS` in
`usermod/orchestrate.py`), so that one port needs a working host C
compiler as well as Docker. Everything else — natmod included — has no
bare-host path
for any target. Install Docker and make sure `docker info` works as the
user running the build.

### `… cannot run as linux/arm64 on this host (x86_64): the kernel has no binfmt handler registered`

You asked for a target that is not your machine's architecture. `cibuildmp`
does not install emulation itself:

```console
$ docker run --privileged --rm tonistiigi/binfmt --install all   # locally, once
```

On CI, add `docker/setup-qemu-action` to the job before the build step.

### `ambiguous output -- found 2 .mpy files under natmod/build/x64*: mymod.mpy, mymod_x64.mpy`

Your `dist` target left an intermediate file next to the one it produced.
This bites when a MicroPython bump renames that intermediate — v1.29.0
renamed `$(BUILD)/$(MOD).native.mpy` to `$(BUILD)/$(MOD).mpy`, so a `dist`
cleaning up only the old name suddenly leaves the new one behind. Remove
both:

```make
dist: all
	mv $(MOD).mpy $(BUILD)/mymod.mpy
	rm -f $(BUILD)/$(MOD).native.mpy $(BUILD)/$(MOD).mpy
```

### `'dist' produced no .mpy under natmod/build/x64*/ or directly in natmod`

Either `module-dir` points at the wrong directory, or your `make-target`
does not put its output where `cibuildmp` looks. It looks in
`<module-dir>/build/<arch>*/` first, then in `<module-dir>` itself.

### `mymod.mpy's header encodes native arch code 2, expected 4 (armv6m)`

Two arches shared one build directory, so the second one reused the first
one's object files and the `.mpy` is the *first* arch's binary.
`cibuildmp` catches this rather than shipping it. Scope `BUILD` in your
Makefile, before the `include`:

```make
BUILD = .obj/$(notdir $(patsubst %/,%,$(MPY_DIR)))/$(ARCH)
```

(MicroPython v1.29.0 and later already default to `build-$(ARCH)`, so the
`$(ARCH)` half only matters on older tags or if you set `BUILD` yourself.)

**The `$(MPY_DIR)` half is the same bug across MicroPython releases, and
that one produces no error at all.** An object file depends on the tag no
more than it depends on the arch, so two tags built back to back in one
tree link the first tag's objects against the second's `py/` — and the
arch header the check above reads is *correct* in that case, so nothing
fails. It surfaces as a `LinkError` about an undefined symbol when the two
releases straddle a `py/` change, and as a quietly mislabelled `.mpy` when
they do not. No default in any `dynruntime.mk` scopes by tag; only your own
`BUILD` can.

### `no image registered for …` / `… is not published for linux/…`

The image that target needs is not in
`resources/pinned_docker_images.toml`, or the pinned reference does not
cover your platform. If you are testing a locally built image, point at it
directly — `CIBMP_UNIX_MANYLINUX_2_28_X86_64_DOCKER_IMAGE=my-image:local`
and the equivalent for other ports. Otherwise this is a bug here: please
open an issue.

### `config file not found: …`

`--config-file` was given a path that does not exist. Without that flag,
`cibuildmp` looks for `<package-dir>/cibuildmp.toml`, then
`[tool.cibuildmp]` in `<package-dir>/pyproject.toml`.

### Disk, and clearing it

The first run downloads a MicroPython release tarball, builds `mpy-cross`,
and pulls a toolchain image — so it is minutes and gigabytes, not the
sub-second rebuilds shown above. A cache with a few tags and an ESP-IDF in
it runs to several GB. `cibuildmp --clean-cache` deletes the lot
(`$XDG_CACHE_HOME/cibuildmp`, or wherever `CIBMP_CACHE_PATH` points);
Docker images are Docker's own to prune.

The JSON build reports are **not** in there — they live beside the
artifacts, under `<output-dir>/reports/`, so `--clean-cache` never takes
them with it. They are one file per invocation and never overwritten, so
they accumulate in the output directory instead; set `CIBMP_REPORT_PATH`
if you want them somewhere else.

Nor is the build state: every usermod port builds inside a container's own
overlay now (a `:ro` bind of the checkout plus a writable view on top), so
object files, per-identifier `build-<identifier>/` trees and the
container-built `mpy-cross` binaries never touch the host at all — they die
with the container. `CIBMP_SCRATCH_PATH` is still read but currently has
nothing to redirect, since nothing writes to the path it names any more;
kept for now as a documented knob rather than removed outright (see record
0095's own addendum 13 for the reasoning).

### Still stuck

`--dry-run` prints what would be built, without building — with the `make`
command line for natmod targets, and identifiers alone for usermod ones
(each port's own driver composes its command far too late for a preview). It prints a `{micropython}` placeholder
literally rather than resolved — the checkout it would point at is not
fetched during a dry run, so `make -C {micropython}/examples/natmod/btree`
in that output is correct, not a broken config. `--debug-traceback` turns a
one-line error
into a full traceback. Both are the fastest way to turn "it failed" into a
specific question.

## Target support

### Natmod, per arch

All ten `ARCH=` values `py/dynruntime.mk` accepts, each running inside a
pulled `linux/amd64` image — natmod builds no bare-host toolchain of any
kind any more, `x86`'s 32-bit multilib included, which is exactly what makes
it buildable on an arm64 runner too. There is no single `natmod` image any
more either: four of the five toolchain-group images cover all ten arches
(`embedded_base`, `xtensa_lx106`, `xtensa_esp`, `natmod_host`), and two of
those four are shared with several usermod ports too, keyed by toolchain
rather than by port — see
[`docs/reference/vendored-images.md`](docs/reference/vendored-images.md) for
the full group model. Adopted in all three consuming repos and verified on
real CI, arch by arch, not just `--dry-run`.

<table>
<thead>
<tr>
  <th>Arch</th>
  <th>Toolchain</th>
  <th>Status</th>
</tr>
</thead>
<tbody>
<tr>
  <td>
    <code>x64</code><br>
  </td>
  <td>host gcc</td>
  <td>✅</td>
</tr>
<tr>
  <td>
    <code>x86</code><br>
  </td>
  <td>host gcc (<code>-m32</code>)</td>
  <td>✅</td>
</tr>
<tr>
  <td>
    <code>armv6m</code><br>
    <code>armv7m</code><br>
    <code>armv7emsp</code><br>
    <code>armv7emdp</code><br>
  </td>
  <td>
    <code>arm-none-eabi-</code><br>
  </td>
  <td>✅</td>
</tr>
<tr>
  <td>
    <code>xtensa</code><br>
  </td>
  <td>
    <code>xtensa-lx106-elf-</code><br>
  </td>
  <td>✅</td>
</tr>
<tr>
  <td>
    <code>xtensawin</code><br>
  </td>
  <td>
    <code>xtensa-esp32-elf-</code><br>
  </td>
  <td>✅</td>
</tr>
<tr>
  <td>
    <code>rv32imc</code><br>
    <code>rv64imc</code><br>
  </td>
  <td>
    <code>riscv64-unknown-elf-</code><br>
  </td>
  <td>✅</td>
</tr>
</tbody>
</table>

### Usermod, per port/arch

Upstream MicroPython has 20 ports (`ports/*` in a real checkout); every one
is listed below for orientation, not just the ones this project covers.
`resources/build-platforms.toml` carries independently-verified
`(tag, arch/board)` rows for 15 of them; only 6 (`unix`, `windows`, `qemu`,
`webassembly`, `esp32`, `rp2`) have a real build driver wired into the CLI
at all — the other 9 have verified facts a config can already *name*, but
nothing yet to actually build them. Every ✅ row below is live-verified
against a real MicroPython checkout, including a real custom
`USER_C_MODULES` module, Docker-only. `unix`, `windows`, `webassembly` and
`qemu` are exercised through `build-examples.yml`'s own small integration
smoke test on every push, producing genuine linked binaries with their
executable bit intact (`unix`: one native image per arch/libc;
`windows`/`webassembly`/`qemu`: one image each — `qemu`'s own
`v1.29.0-qemu-MPS2_AN385` runs in its own matrix leg rather than sharing a
job with already-proven cells, since it was the first build ever run
through that path). `esp32` and `rp2` are not in that smoke test, but not
because either is unproven -- both are exercised far more broadly, on a
weekly schedule (or manual dispatch any time sooner), through
`test-all-platforms.yml`'s own real matrix
(`bin/plan_test_matrix.py`, record 0065): every board/tag row
`resources/build-platforms.toml` carries for either port, not a spot check.
(No count here on purpose. It used to say "83 real `esp32` identifiers and
74 real `rp2` ones" — a two-tag slice that was accurate when written and is
now off by five times, since each new MicroPython tag adds a full board set.
The rows are the fact; their number is a snapshot.) **Both build through the exact same `cibuildmp`
CLI/action every other ✅ row does** -- `esp32`'s own composite action
(tracker item [0038]) was only ever needed while `build_esp32()` still
provisioned onto the bare host; record 0028 moved it fully into
`esp_idf_base` (Docker) on 2026-08-28, and nothing in this project still
depends on that composite action's own toolchain-install path. `rp2`'s
own driver landed the next day (record 0060), live-verified against
`examples/template` first and now carrying its own share of every
scheduled `test-all-platforms.yml` run since.

<table>
<thead>
<tr>
  <th>Port</th>
  <th>Target</th>
  <th>Provisioning</th>
  <th>Status</th>
</tr>
</thead>
<tbody>
<tr>
  <td><code>unix / manylinux</code></td>
  <td>
    <code>manylinux_2_28_x86_64</code><br>
    <code>manylinux_2_28_i686</code><br>
    <code>manylinux_2_28_aarch64</code><br>
    <code>manylinux_2_31_armv7l</code><br>
    <code>manylinux_2_41_mipsel</code>
  </td>
  <td>

  native image[^native]<br>
  native image[^native]<br>
  native image[^native]<br>
  native image[^native]<br>
  cross image[^cross]

  </td>
  <td>✅</td>
</tr>
<tr>
  <td><code>unix / musllinux</code></td>
  <td>
    <code>musllinux_1_2_x86_64</code><br>
    <code>musllinux_1_2_i686</code><br>
    <code>musllinux_1_2_aarch64</code><br>
    <code>musllinux_1_2_armv7l</code>
  </td>
  <td>

  native image[^native]

  </td>
  <td>✅</td>
</tr>
<tr>
  <td><code>unix / manylinux</code></td>
  <td>
    <code>manylinux_2_28_ppc64le</code><br>
    <code>manylinux_2_28_s390x</code><br>
    <code>manylinux_2_39_riscv64</code>
  </td>
  <td>

  native image[^native]

  </td>
  <td>

  ✅[^emulatedci]<br>
  ✅[^emulatedci]<br>
  ✅[^emulatedci]

  </td>
</tr>
<tr>
  <td><code>unix / musllinux</code></td>
  <td>
    <code>musllinux_1_2_ppc64le</code><br>
    <code>musllinux_1_2_s390x</code><br>
    <code>musllinux_1_2_riscv64</code>
  </td>
  <td>

  native image[^native]

  </td>
  <td>

  ⚠️[^ppc64lerelocation]<br>
  ✅[^emulatedci]<br>
  ✅[^emulatedci]

  </td>
</tr>
<tr>
  <td><code>qemu</code></td>
  <td>
    <code>MPS2_AN385</code><br>
    <code>MICROBIT</code><br>
    <code>MPS2_AN500</code><br>
    <code>MPS3_AN547</code><br>
    <code>NETDUINO2</code><br>
    <code>SABRELITE</code>
  </td>
  <td>
    <code>arm-none-eabi-</code></td>
  <td>✅</td>
</tr>
<tr>
  <td><code>qemu</code></td>
  <td>
    <code>VIRT_RV32</code><br>
    <code>VIRT_RV64</code><br>
  </td>
  <td>
    <code>riscv64-unknown-elf-</code></td>
  <td>✅</td>
</tr>
<tr>
  <td><code>qemu</code></td>
  <td>
    <code>POWERNV9</code> (PowerPC)
  </td>
  <td><code>powerpc64le-linux-gnu-</code></td>
  <td>✅</td>
</tr>
<tr>
  <td><code>webassembly</code></td>
  <td>
    <code>pyscript</code> variant
  </td>
  <td><code>emsdk</code> (Linux x64 host only)</td>
  <td>✅</td>
</tr>
<tr>
  <td><code>esp32</code></td>
  <td>
    every board across <code>v1.28.0</code>/<code>v1.29.0</code>[^esp32ci]
  </td>
  <td><code>esp_idf_base</code> (Docker) -- ESP-IDF cloned on the host, installed in-container, per-board <code>idf_target</code>/<code>idf_version</code></td>
  <td>✅</td>
</tr>
<tr>
  <td><code>windows</code></td>
  <td>
    <code>x64</code><br>
    <code>x86</code><br>
    <code>arm64</code>
  </td>
  <td>

  `windows` image (Docker)[^windowsimg]

  </td>
  <td>✅</td>
</tr>
<tr>
  <td><code>rp2</code></td>
  <td>
    every board across <code>v1.20.0</code>-<code>v1.30.0-preview</code>
  </td>
  <td><code>embedded_base</code> (Docker) -- Pico SDK + every <code>lib/</code> it needs are vendored by the MicroPython release tarball itself[^rp2ci]</td>
  <td>✅</td>
</tr>
<tr>
  <td>
    <code>mimxrt</code><br>
    <code>samd</code><br>
    <code>stm32</code><br>
    <code>psoc-edge</code><br>
    <code>alif</code><br>
    <code>esp8266</code><br>
    <code>cc3200</code><br>
    <code>renesas-ra</code><br>
    <code>nrf</code>
  </td>
  <td>

  verified `(tag, board)` rows exist[^nodriver]

  </td>
  <td>—</td>
  <td>❌ no build driver yet</td>
</tr>
<tr>
  <td>
    <code>zephyr</code>
  </td>
  <td>Zephyr RTOS (any board)</td>
  <td>—</td>
  <td>❌ no build driver yet</td>
</tr>
<tr>
  <td>
    <code>pic16bit</code><br>
    <code>powerpc</code> (as a standalone port)<br>
    <code>bare-arm</code><br>
    <code>minimal</code><br>
    <code>embed</code>
  </td>
  <td>no verified rows at all — reference builds or CPU families with no matching natmod/usermod facts</td>
  <td>—</td>
  <td>❌ out of scope</td>
</tr>
</tbody>
</table>

[^native]: Nothing to provision. The image is pypa's own `quay.io/pypa/<target>` directly (the same images cibuildwheel builds wheels in), no cibuildmp layer at all — a build never needed the `libffi-devel` that used to be the one thing added on top, once `MICROPY_STANDALONE=1`/vendored `libffi` went universal for every `unix` cell. Carries a native compiler for that architecture; non-native targets run emulated. The binary is checked against its target's real platform tag after every build. Green across every one of the 11 latest-patch MicroPython releases, not one — `test-all-platforms.yml`'s own native sweep, record 0084's own 2026-09-02 addendum.

[^cross]: The one target that still cross-compiles: pypa publishes no mipsel image and there's no Docker official image for 32-bit mipsel, so there's nothing to be native to. Its toolchain is a pinned Bootlin tarball (`mips32el--glibc--stable-2025.08-1`, gcc 14.3.0, glibc 2.41-70, URL + sha256), not an apt cross-compiler: Debian 13 "Trixie" dropped the mipsel port and Ubuntu's archive lost `gcc-mipsel-linux-gnu`/`libc6-dev-mipsel-cross` with it. That is also why this cell is `manylinux_2_41_mipsel` and was `manylinux_2_39_mipsel` until 2026-09-01 — `2_39` was apt's cross-glibc version, and a real PEP 600 tag must not keep claiming a floor its image no longer has (record 0068). Its own real bug, found the same full-history sweep as the emulated cells' own: the live gcc-diagnostic probe checked the image's bare `gcc`, not the `mipsel-linux-gnu-gcc` (14.3.0, older) the build actually uses — a false-positive verdict let a gcc-15-only flag back into a gcc-14 compile on every pre-`v1.26.0` tag. Fixed by probing the actual compiler each build step uses; record 0084's own 2026-09-02 addendum.

[^emulatedci]: `ppc64le`/`s390x`/`riscv64`, both libcs — native to no runner GitHub offers, so still QEMU-emulated, but no longer untested: `test-all-platforms.yml`'s own `unix-emulated` entry gives all six a real `test-emulated` CI leg on its weekly schedule (or manual dispatch) now, and its own bucket planner (`bin/plan_test_matrix.py`) partitions them into a dedicated `emulated` job set rather than sharing a runner with the fast native cells. Green across every one of the 11 latest-patch MicroPython releases now, not spot-checked against one — a full historical sweep (record 0084's own 2026-09-02 addendum) is what found and fixed the real bugs the narrower checks this footnote used to cite never reached: a `riscv64` `lib/libffi` fork with no `riscv*` support at all on pre-`v1.24.0` tags, a `deplibs` symlink fixup that only checked one hardcoded multiarch path, and the real `s390x`/`riscv64` `-Werror=clobbered` diagnostic this footnote's own ⚠️ row named until 2026-09-02. The one remaining ⚠️ row below (musllinux `ppc64le`) is unrelated to any of that — a real QEMU relocation gap, not a compile-time bug. Point `CIBMP_UNIX_<TARGET>_DOCKER_IMAGE` at a locally-built image, or an emulated one, to work on one of these locally. Record 0044's own 2026-08-29 addendum.

[^ppc64lerelocation]: Both tags. `mpy-cross` builds cleanly inside the image; it fails when QEMU actually *executes* it to freeze `argparse.py`: `Error relocating .../mpy-cross: unsupported relocation type 4/5`. A real gap in QEMU's own ppc64le user-mode emulation of this PIE binary's relocations, not a cibuildmp or MicroPython bug — the `manylinux_2_28_ppc64le` cell above, same emulator, is unaffected. Skipped by glob (`*musllinux_1_2_ppc64le`) in `test-all-platforms.yml` until fixed. Record 0044's own 2026-08-29 addendum.

[^nodriver]: `resources/build-platforms.toml` has real, independently-verified rows for each of these ports (walked against a real MicroPython checkout the same way every ✅ row above was); a config can name their identifiers today. What's missing is a `build_<port>()` driver (`platforms/usermod/build_<port>.py`) to actually run one — not a scope decision, just not built yet.
[^rp2ci]: `build_rp2()` runs no provisioning step inside the container at all — the Pico SDK and everything it needs (`lib/pico-sdk`/`lib/tinyusb`/`lib/lwip`/`lib/btstack`/`lib/cyw43-driver`) are plain git submodules of the MicroPython checkout, already vendored as real files by the release tarball this project prefers. Running the port's own `make ... submodules` target was tried first and failed live against a real tarball checkout ("fatal: not a git repository", since a release tarball is not a git checkout at all); those submodules are threaded into `sources.fetch_micropython()` instead, reached only on its clone path (a preview tag with no tarball). Live-verified: a real `examples/template` build against `v1.29.0-rp2-RPI_PICO` producing a genuine 681984-byte `firmware.uf2` with the project's own C module linked in. Record 0060.

[^esp32ci]: `build_esp32()` went Docker 2026-08-28 (`esp_idf_base`, [0058]), closing the venv conflict that made every real esp32 build fail on the bare host; `idf_version`/`idf_target` are threaded from each board's own real row rather than a fixed default, and `HOME` is exported explicitly for the same reason `esp32`'s own `ports/esp32` needs a real per-user cache dir that `dockerrun.run()`'s `--user <uid>:<gid>` doesn't otherwise give it (unmapped on GitHub's own runners specifically, live-caught on real CI). `test-all-platforms.yml`'s own broad sweep is what actually proves this across the whole board matrix, not a spot check — Xtensa and RISC-V both, both MicroPython tags this project currently tracks.

[^windowsimg]: One combined `docker/windows.Dockerfile` image (`ghcr.io/ballistics-lab/windows`) for all three arches, not split per arch like `unix`'s own five images — there is no second Windows libc a binary could be built against, so the isolation argument that drives `unix`'s split doesn't apply here. `x64`/`x86` are plain apt-installed `gcc-mingw-w64-x86-64`/`gcc-mingw-w64-i686` inside the image; `arm64` is a pinned `llvm-mingw` tarball baked into the same image (no Debian/Ubuntu package targets `aarch64-w64-mingw32` at all). None of this runs on the CI runner itself any more — `apt install gcc-mingw-w64-*` on the bare host was removed as part of Record 0042's own container migration.

No Windows or macOS host is needed for any of the ✅/⚠️ usermod targets
above, `windows`'s own three arches included — every toolchain there is
either already on a Linux host or downloads/apt-installs onto one.

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

`cibuildmp` only assumes `natmod/Makefile` (or whatever `module-dir`
points at) accepts `ARCH=` and `MPY_DIR=` and has a `dist` target that
drops the built `.mpy` under `build/<arch>*/`. Nothing here assumes a
specific module name, precision scheme, or test framework — those stay in
the consuming repo.

**One more requirement for the `cibuildmp` CLI specifically:** scope
`dynruntime.mk`'s `BUILD` variable by the MicroPython release *and* the
arch — `BUILD = .obj/$(notdir $(patsubst %/,%,$(MPY_DIR)))/$(ARCH)` before
the `include`, kept outside `build/` so it does not collide with the `dist`
output the CLI globs for (see `examples/template/natmod/Makefile`).
`cibuildmp` runs every selected target sequentially in one `natmod/` tree,
and an object file depends on neither the arch nor the tag, so anything
those targets share in `BUILD` gets silently reused across them.

**The arch axis is caught; the tag axis is not.** A `BUILD` shared across
arches makes a second `ARCH=` in the same invocation find the previous
arch's object files "up to date" and skip rebuilding — the merged `.mpy`
silently stays the *first* arch's binary, and `cibuildmp`'s own header-arch
verification fails loudly rather than shipping it, so scoping `$(ARCH)`
only saves you the failed build. A `BUILD` shared across *tags* produces an
artifact whose arch header is perfectly correct and whose `py/` is the
wrong release's, so nothing fails: it shows up as a `LinkError` about an
undefined symbol when the two releases straddle a `py/` change, and as a
quietly mislabelled `.mpy` when they do not.

**No `dynruntime.mk` default covers either axis fully**, which this
paragraph did not used to say: `BUILD` defaulted to an unscoped `build` up
to v1.28.0 and to `build-$(ARCH)` from v1.29.0 — arch-scoped from that tag
on, tag-scoped in no release at all, since `MPY_DIR` is the only thing that
knows which release is being built. So on v1.29.0 and later the arch
collision cannot happen by default; the tag one still can, and only your
own `BUILD` prevents it.

If the module also builds `rv32imc` with more than one `arch-flags` value
in the same invocation, `BUILD` needs `$(ARCH_FLAGS)` folded in too —
`BUILD = .obj/$(notdir $(patsubst %/,%,$(MPY_DIR)))/$(ARCH)$(if $(ARCH_FLAGS),+$(ARCH_FLAGS))`,
for the same reason on a third axis.

None of this cares what produced the `.c` files `SRC` lists —
[`examples/wasm2mpy`](examples/wasm2mpy) compiles WebAssembly to C via
`wasm2c` in a Makefile rule before the same `dynruntime.mk` flow takes
over.

## Roadmap

[`docs/0000-TRACKER.md`](docs/0000-TRACKER.md) is the plan of record: the
decisions taken and why (in [`docs/records/`](docs/records/)), what's
implemented, what's deliberately deferred. `docs/BACKLOG.md` is now just a
short redirect into that scheme, not itself the plan.

Natmod is done end to end — target selection, MicroPython/`mpy-cross`
provisioning, and the build itself, all ten arches now running inside pulled
toolchain-group images rather than a host-side toolchain resolver (that
resolver, and its own `--toolchain` flag, are deleted) — verified on real CI
in all three consuming repos, not just `--dry-run`. Usermod's own build
drivers are wired into the CLI too (see [Target support](#target-support)
above), covering every port with a real driver, not just three.

How far each consuming repo has migrated onto the unified CLI/action is
**not stated here** — that is a claim about another repository's CI, which
nothing in this repo can verify. The tracker's own [0038] row carries it,
dated; [0077] has why this document no longer tries.

The container/image model itself — which build pulls what, and why — is
[`docs/reference/vendored-images.md`](docs/reference/vendored-images.md),
kept current the same way [`docs/reference/design.md`](docs/reference/design.md)
is, not by memory.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the dev loop, and
[`CLAUDE.md`](CLAUDE.md) before touching anything with a `cibuildwheel`
counterpart — selectors, identifiers, options, container invocation.

## Legacy composite actions (not a way to use `cibuildmp`)

`.github/actions/{fetch-micropython,clone-micropython,build-natmod,
build-usermod-unix/-windows/-webassembly/-rp2040/-armv7m/-esp32}` predate
the CLI and don't invoke `cibuildmp` at all — each is its own bare-host
toolchain-install-then-`make`/`idf.py` implementation, one GitHub Action
per build step. They are **not** a second supported way to use this
project; `action.yml` above (wrapping the real CLI) is the only current
path for a new integration.

That list is the whole of this layer, not the whole of the directory:
`.github/actions/` also holds internal CI plumbing (`run-with-wine`, which
runs an already-built `.exe` against a script under wine) that builds
nothing and is not part of the legacy story.

This layer is a deliberate fallback, not something being absorbed into the
CLI over time — folding `build-natmod` into a thin `cibuildmp --build`
wrapper was proposed and explicitly rejected (tracker [0038], see
"Rejected"). It stays because consuming repos still call it — a
`unix-mipsel` cross-compile has no native runner, and [0043]'s vendored
`MICROPY_STANDALONE=1`/`deplibs` static path was kept for exactly that
cell. **Which repos, and how much of each, is in the tracker's own [0038]
row rather than here**, dated: this paragraph named the wrong repo for a
week and was copied to four other files before anyone checked ([0076],
[0077]). Read [`docs/ACTIONS.md`](docs/ACTIONS.md) if you are maintaining
or migrating off a holdout like that — not as a starting point for a new
module.

## Versioning

Pin consumers to a tag, not `@main` and not a commit SHA — bumping the tag
a consumer references is a deliberate, visible edit in that repo, same as
bumping any other CI dependency.

The `cibuildmp` package and the actions share one version. **Which tag is
current is not restated here** — [`CHANGELOG.md`](CHANGELOG.md)'s own
newest released heading is that, and `tests/test_docs.py` checks every
`@vX.Y.Z` example in this file against it. (This paragraph named `v0.6.0`
as current, and as "the one every example in this README targets", for two
releases after that stopped being true.) `v0.6.0` is worth knowing as
history: it is the breaking one — config surface rewritten, `unix`
identifiers renamed, see `CHANGELOG.md`'s own `[0.4.0]` entry. `v0.3.0` was the first tag
where the CLI actually built a module at all, not just planned it, and
the line continues `micropython-native-ci`'s own version numbering rather
than restarting it, since this repo absorbed that one (its consumers have
since repinned; the old repo is now archived). See
[`CHANGELOG.md`](CHANGELOG.md) for the full history.

The root `action.yml` installs `cibuildmp` from its own checkout rather
than from PyPI (`uv tool install "$GITHUB_ACTION_PATH"`, already the
pinned ref's own source, checked out by GitHub Actions before any step
runs), so the tool that runs on CI is always exactly the ref you pinned,
with no index to keep in sync. Running it yourself with `uv tool install
cibuildmp`/`pip install cibuildmp` instead pulls whatever's newest on
PyPI unless you pin a version there too.

<!-- REUSABLE LINKS -->

[natmod-abi]:
https://img.shields.io/badge/mpy_v5%2B-orange?logo=micropython&label=natmod

[usermod-tag]:
https://img.shields.io/badge/v1.20%2B-orange?logo=micropython&label=usermod

[license]:
https://img.shields.io/github/license/ballistics-lab/cibuildmp

[license-url]:
https://opensource.org/licenses/MIT

[pypi version]:
https://img.shields.io/pypi/v/cibuildmp?logo=pypi

[python versions]:
https://img.shields.io/pypi/pyversions/cibuildmp?logo=python

[PyPiUrl]:
https://pypi.org/project/cibuildmp/

[pre-commit]:
https://github.com/ballistics-lab/cibuildmp/actions/workflows/pre-commit.yml/badge.svg

[pre-commit-workflow]:
https://github.com/ballistics-lab/cibuildmp/actions/workflows/pre-commit.yml

[coverage]:
https://codecov.io/gh/ballistics-lab/cibuildmp/graph/badge.svg

[CodecovUrl]:
https://codecov.io/gh/ballistics-lab/cibuildmp

[SWUbanner]:
    https://img.shields.io/badge/made_in-Ukraine-ffd700.svg?labelColor=0057b7&style=flat-square
[SWUBadge]: https://stand-with-ukraine.pp.ua

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

- **`fetch-micropython`** -- downloads and extracts a MicroPython release
  tarball, exports `MPY_DIR`. Use this for a plain natmod build or a unix
  port build; the tarball already vendors every port's `lib/` submodules.
- **`clone-micropython`** -- shallow git-clones a MicroPython release
  branch instead, with a chosen set of submodules initialised (e.g.
  `lib/pico-sdk` for an rp2 firmware build) and exports `MPY_DIR`. Clones
  into `micropython/` by default; pass `path:` if the calling repo already
  has a top-level directory of that name (a7p does -- its own MicroPython
  subtree lives at `micropython/`, so its jobs pass `path: mpy`).
- **`build-natmod-arch`** -- installs whatever toolchain a single
  `dynruntime.mk` `ARCH` needs (plain apt package, the `xtensa-lx106`
  tarball, or esp-idf -- dispatched per arch, exactly matching what each of
  the three source repos already did by hand), builds `mpy-cross`, then
  runs `make ARCH=<arch> dist` in the natmod directory. `natmod_dir`
  defaults to `natmod` (a7p passes `micropython/natmod`); an optional
  `pre_build_command` runs first (a7p uses this for `make fetch-nanopb`).
  Requires `MPY_DIR` to already be set (i.e. run `fetch-micropython` or
  `clone-micropython` first) and the calling repo already checked out.
- **`build-usermod-unix-arch`** -- the unix-port cross-compile matrix for a
  `USER_C_MODULES` usermod: `x64`, `x86` (32-bit), `aarch64`, `armhf`, or
  `mipsel`. Installs the arch's toolchain (apt package, qemu-user-static
  for the emulated ones, a from-source libffi for the statically-linked
  ones), builds `mpy-cross`, then runs the port build with
  `USER_C_MODULES=`/`FROZEN_MANIFEST=` pointed at the caller's own
  `usermod/`. `extra_make_args` carries a module's own defines (e.g.
  bclibc's `MP_BCLIBC_PRECISION=double`). Same `MPY_DIR` + checkout
  prerequisite as `build-natmod-arch`; the caller's own matrix still
  chooses `runs-on:` per arch (`ubuntu-24.04-arm` for aarch64/armhf,
  `ubuntu-latest` otherwise) -- a composite action can't pick its own
  runner.

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

`build-natmod-arch` only assumes `natmod/Makefile` (or whatever
`natmod_dir` points at) accepts `ARCH=` and `MPY_DIR=` and has a `dist`
target that drops the built `.mpy` under `build/<arch>*/`. Nothing here
assumes a specific module name, precision scheme, or test framework --
those stay in the consuming repo.

## Roadmap

Not done yet, deliberately -- each of these needs to be verified against
real CI in the consuming repo, not just written and trusted:

- A reusable `workflow_call` for the full natmod build+test matrix
  (build-natmod-arch already covers the highest-drift part of it).
- A reusable `workflow_call` for the "armv7emsp / armv7emdp on real ARM
  Linux" test job -- currently near-identical hand-copied YAML in all
  three source repos.
- A small scaffolding script to generate a new `natmod/` + `usermod/`
  skeleton for a fresh module, wired to the actions above.

## Versioning

Pin consumers to a tag (`@v0.1.0`), not `@main` and not a commit SHA.
Bumping the tag a consumer references is a deliberate, visible edit in
that repo, same as bumping any other CI dependency -- a change here never
silently changes what three other repos' builds do. `v0.1.0` is the
current tag; each of bclibc, a7p and micropython-wasm3 pin to it.

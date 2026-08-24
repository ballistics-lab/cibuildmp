# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
  anything but copied naming. Consumers pinned to the `v0.1.0` tag (an
  immutable point that predates this rename) keep using the old
  `-arch`-suffixed names until a new tag is cut; only branch-ref
  consumers (`@<this-branch>`) see the new names.
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

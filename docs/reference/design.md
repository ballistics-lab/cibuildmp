# cibuildmp — design reference

Living reference for the current design: positioning, the identifier scheme,
the phase-1 config schema, the toolchain map, and what "local use" means.
This is not a decision history — see [docs/0000-TRACKER.md](../0000-TRACKER.md)
and [docs/records/](../records/) for that. When this file and a numbered
record disagree, the record is the historical account of *why*; this file
should be kept current with *what is true today*.

<!-- migrated verbatim from docs/BACKLOG.md lines 12-33 (Positioning) -->

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

<!-- migrated verbatim from docs/BACKLOG.md lines 433-476 (Identifier scheme) -->

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
`VARIANT=` (see [0039](../records/0039-usermod-composite-actions-status.md)),
so theirs is `v1.28.0-usermod-unix_standard` — same shape, the last slot
names whichever axis that port actually selects on. (In practice, usermod's
shipped identifier scheme ended up simpler than this — see [0023]; no ABI
axis, no `package.json`.)

**What is actually true today**, since this is a living document rather than
a decision record: a usermod identifier is `{port}` or `{port}-{axis value}`
([0023]), and for `unix` that axis value is a **PEP 600 / PEP 656 platform
tag** — `unix-manylinux_2_28_x86_64`, `unix-musllinux_1_2_aarch64`,
`unix-manylinux_2_39_mipsel`. Records [0043]/[0044] put the libc floor and
pypa's own architecture spelling into the name deliberately, so the
identifier states a compatibility claim the build then verifies against the
finished ELF, rather than labelling one. The floor is *inside* the
identifier here, unlike cibuildwheel's own `cp313-manylinux_x86_64`, because
cibuildmp curates exactly one floor per architecture and offers no knob to
choose another.

[0043]: ../records/0043-unix-adopts-cibuildwheel-native-image-model.md
[0044]: ../records/0044-unix-native-images-landed.md

<!-- migrated verbatim from docs/BACKLOG.md lines 477-518 (Config schema) -->

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

**Where a key goes is part of the schema, and getting it wrong is an
error** ([0048]). The keys above the first table header — `micropython`,
`output-dir`, `build`, `skip`, `version`, `mpy-abi`,
`micropython-submodules` — are invocation-wide and are read **only** from
the top level, in both build modes. Writing one inside `[natmod]` or
`[usermod]` fails with a message naming where it belongs; so does any key
a mode table does not read at all (a typo, or an `arch-flags` inside
`[[overrides]]`). Until [0048] every one of those was silently ignored,
which meant a misplaced `skip` produced a successful build of something
you had asked not to build. `archs`/`arch-flags` remain the one deliberate
exception: natmod reads them from the top level *or* `[natmod]`, and both
work, so neither is silent.

[0048]: ../records/0048-build-skip-live-in-opposite-tables.md

Usermod's own `[usermod]` / `[usermod.<port>]` config shape is documented in
[0023] rather than transcribed here — it is a genuinely different shape
(no ABI axis, per-port sub-tables), not a variant of the table above.

<!-- migrated verbatim from docs/BACKLOG.md lines 519-546 (Toolchain map) -->

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

(Resolved and shipped as of [0036] — see that record for what actually
landed, including the prefix-reconciliation and picolibc details.)

<!-- migrated verbatim from docs/BACKLOG.md lines 547-570 (Local use) -->

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
an open question — see [docs/reference/open-questions.md](open-questions.md).

Nothing about this is CI-specific: the cache directory, the toolchain
resolver and the build loop are the same code path in both places. The only
thing a runner adds is that its cache starts empty.

**Note (as of [0030]/[0033]):** for usermod, this "no Docker, no host
mutation" story was later superseded — usermod builds are Docker-only, and
`cibuildmp` itself never builds an image, only pulls a published one. natmod
keeps the host/download story above as its preferred path, with Docker as an
additional, not required, option. See [0030] and [0033] for the full
reasoning.

<!-- migrated verbatim from docs/BACKLOG.md lines 3649-3666 (Non-goals) -->

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

[0006]: ../records/0006-no-test-runners-phase1.md
[0007]: ../records/0007-usermod-vendors-mpbuild-board-db.md
[0011]: ../records/0011-one-repo-absorbs-micropython-native-ci.md
[0013]: ../records/0013-micropython-list-dedup-by-abi.md
[0014]: ../records/0014-mip-package-per-identifier.md
[0015]: ../records/0015-rv32imc-arch-flags-identifier.md
[0023]: ../records/0023-usermod-identifier-scheme-config-output.md
[0030]: ../records/0030-container-approach-natmod-and-docker-vs-qemu.md
[0033]: ../records/0033-cibuildmp-never-builds-docker-image-itself.md
[0036]: ../records/0036-m2-toolchain-resolver.md

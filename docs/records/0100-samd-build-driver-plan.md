# 0100 — samd build driver: implementation plan, chosen over the other eight [0053] ports

Status: In progress — `build_samd.py` written and live-verified against two real identifiers
(`v1.29.0-samd-SEEED_XIAO_SAMD21`, `v1.20.0-samd-ADAFRUIT_FEATHER_M0_EXPRESS`); a full sweep of
all 211 rows is running to confirm every board/tag. See the addendum below.
Related: [0053], [0060], [0058], [0087], [0093], [0094], [0096], [0099]

## Why `samd`, not the other eight

[0053] lists nine usermod ports with verified `build-platforms.toml` rows and no
`build_<port>()` driver: `mimxrt`, `samd`, `stm32`, `psoc-edge`, `alif`, `esp8266`, `cc3200`,
`renesas-ra`, `nrf`. Picked by elimination, against real facts in this repo rather than a
guess at which "sounds simplest":

- **`esp8266`, `cc3200`, `renesas-ra`, `nrf`** all carry rows below `v1.20.0` — exactly the
  four ports [0093] names as sitting in the tag range where `usermod/build_common.py`'s
  `container_mpy_cross()` has a known, unfixed two-candidate fallback that resolves to the
  wrong path (`find_mpy_cross()`'s pre-`v1.20.0` naming). [0093] says outright: "whichever
  record gives one of them a driver has to solve it properly". Not this record's problem to
  take on as a prerequisite.
- **`alif`** looks trivial by row count (6 rows, 1 board, `ALIF_ENSEMBLE`), but its own rows
  carry `toolchain_version = "13.3.Rel1"` — a field `bin/refresh_toolchain_pins.py`'s
  `current_row_pin()` never reads (it reads `row.get("gcc")` only; alif rows have no `gcc`
  key at all), and a value that does not appear anywhere in `pinned_toolchains.toml`'s own
  `["arm-none-eabi-"]` table (which holds `15.2.1-1.1`/`14.2.1-1.1`/`12.3.1-1.2`, xpack's own
  version spelling — `"13.3.Rel1"` is Arm's own `gitlab.arm.com` naming, [0094]'s subject).
  So alif's one real fact has never been checked by the pin-staleness tooling and does not
  resolve through `toolchain_fetch.resolve_toolchain()` today. A real gap, not a config edit.
- **`psoc-edge`** has 2 rows, 1 board, but carries neither `gcc` nor `toolchain_version` at
  all, and is the only one of the nine whose `[usermod.psoc-edge]` table has its own
  `pre_checkout = "sudo apt-get install gcc-arm-none-eabi libnewlib-arm-none-eabi"` — every
  other `embedded_base`-image port needs no such step, which is a live hint that the shared
  image was not (yet) confirmed to cover it. Only two tags exist upstream
  (`v1.29.0`/`v1.30.0-preview`) — the newest, least-obtained port in the whole table.
- **`mimxrt`** (189 rows / 14 boards) and **`stm32`** (1016 rows / 76 boards) both have real,
  checked `gcc` facts (`refresh_toolchain_pins.py --check` passes for both, per [0094]'s own
  2026-09-04 addendum table), but carry the largest board surfaces of the nine, and `stm32`
  additionally needs a genuine two-sided floor/ceiling split by tag ([0094]'s own subject —
  `<15.1` before `v1.26.0`, `>=14.3` from it) where every other `embedded_base` port (`samd`
  included) needs only the ordinary single-boundary xpack split.
- **`samd`** (211 rows / 18 boards) has a real, `--check`-passing `gcc` fact, the same plain
  single-boundary split every other `embedded_base` port already has (`14.2.1-1.1` for
  `v1.20.0`–`v1.25.0`, `15.2.1-1.1` from `v1.26.0` on — verified directly against every row,
  not sampled), no nonstandard `pre_checkout`, and no ports/mimxrt- or stm32-scale board
  surface to worry a first live build with.

## What's already in place (the same "everything but the driver" shape [0060] found for `rp2`)

- `build-platforms.toml`'s own `[usermod.samd]` table: `image = "embedded_base"`,
  `post_checkout = "make -C mpy-cross && make -C ports/samd BOARD={board} submodules"`, 211
  real `(tag, board)` rows spanning `v1.20.0`..`v1.30.0-preview`, each carrying `cross =
  "arm-none-eabi-"` and a real `gcc` value.
- `embedded_base` (the `arm_embedded`/`riscv_embedded` merge, [0096]) is already built,
  published, and digest-pinned.
- `toolchain_fetch.resolve_toolchain("arm-none-eabi-", version)` already has both real
  versions this port's rows ever ask for (`pinned_toolchains.toml`'s `["arm-none-eabi-"]`
  table) — nothing new to fetch or pin.
- `refresh_toolchain_pins.py --check` already treats every `samd` row as passing (`gcc`
  inside its own window), per [0094]'s own addendum.

What's missing is exactly two things: `portinfo.py`'s own `build-system`/`default-manifest`
fact for `samd` (`known_ports()` does not include it yet — presence of those two keys in
`[usermod.samd]` is the only signal that module reads), and the driver code itself.

## Verified directly against `ports/samd/Makefile` at `v1.29.0`, not assumed

Fetched and read live this session (the exact discipline CLAUDE.md's opening rule asks for —
checked here against MicroPython's own port, not cibuildwheel, but the same principle):

- **Plain GNU Make, no CMake anywhere.** `include ../../py/mkenv.mk`, `$(TOP)/py/py.mk`,
  `$(TOP)/extmod/extmod.mk`, `$(TOP)/py/mkrules.mk` — zero references to `cmake`,
  `CMAKE_ARGS`, `add_subdirectory`, or `idf.py`. Confirms the standing suspicion from the
  earlier esp8266 conversation: `build_common.cmake_extra_args_env()`'s own docstring names
  exactly two usermod ports whose Makefile wraps `cmake`/`idf.py` — `rp2` and `esp32`. `samd`
  is not one of them, checked directly rather than inferred from that docstring's silence.
- **`FROZEN_MANIFEST ?= boards/manifest.py`** — the same real, port-level default `rp2` has
  ([0060]: `default-manifest = "boards/manifest.py"`). Not an overridden variant the way
  `unix`/`webassembly`'s own entries are (`portinfo.default_manifest()`'s own docstring
  distinction) — `samd`'s value is what its own Makefile already resolves to unmodified.
- **`BUILD` is conditional**: `ifneq ($(BOARD_VARIANT),) BUILD ?= build-$(BOARD)-$(BOARD_VARIANT)
  else BUILD ?= build-$(BOARD)`. Still safe to override unconditionally from the make command
  line the way `unix_make_command()`'s own `BUILD=` does: a `?=` inside the port's own
  Makefile only ever fires when the variable is *unset* by the time that line runs, and an
  explicit `BUILD=<dir>` on the invoking command line always wins regardless of which branch
  of the `ifneq` would otherwise have applied. This is exactly the case `esp32`/`rp2` cannot
  make (their own comments: passing `BUILD=` *at all* leaks `FROZEN_MANIFEST` into an
  internal CMake sub-build via `MAKEFLAGS`) — `samd` has no such internal CMake sub-build to
  leak into, confirmed above.
- **No dedicated `submodules` target visible in this Makefile**, but a `GIT_SUBMODULES`
  variable is — the generic top-level plumbing (`py/mkenv.mk`'s own rule) that
  `build-platforms.toml`'s own `post_checkout` already assumes resolves
  (`make -C ports/samd BOARD=... submodules`). This is the same shape [0060] already built
  the reusable half of (`sources.fetch_micropython(tag, submodules=...)`, exercised for
  `rp2`'s own five `lib/` paths) — the actual path list for `samd` needs reading off a real
  tag checkout, not guessed here.
- `USER_C_MODULES`/`MICROPY_MPYCROSS` did not show up in the fetched excerpt — both are
  standard `py/mkenv.mk`/`py/py.mk`-level names every Make port (`unix` included) already
  gets for free, not something `ports/samd/Makefile` itself would restate.

## Implementation plan

1. Add `build-system = "make"` and `default-manifest = "boards/manifest.py"` to
   `[usermod.samd]`'s own table in `build-platforms.toml` — the same shape `rp2`'s own table
   already carries for the `cmake` branch, here for the `make` branch instead.
2. `targets.py`: add `samd_toolchain(tag)`, mirroring `rp2_toolchain(tag)` exactly — read
   `row["gcc"]` off `_USERMOD_ROWS["samd"]`, return
   `(TOOLCHAIN_CROSS_PREFIX["arm_embedded"], version)`. No new toolchain-fetch mechanism;
   this reuses [0087]'s existing one verbatim.
3. Write `platforms/usermod/build_samd.py`: a `SamdBuildOptions` dataclass mirroring
   `Rp2BuildOptions` minus `extra_cmake_args` (a make port needs no `cmake_extra_args_env()`
   call at all — nothing to append into), and `samd_make_command()` shaped like
   `unix_make_command()`'s flat, unconditional style rather than `rp2_make_command()`'s
   CMake-avoidance one: `make -C ports/samd BOARD=<board> CROSS_COMPILE=arm-none-eabi-
   USER_C_MODULES=... FROZEN_MANIFEST=... BUILD=<build_dir>
   MICROPY_MPYCROSS=<container mpy-cross>`, plus `CFLAGS_EXTRA` from
   `build_common.tag_cflags(tag)` and `extra_make_args`. `build_samd()` itself follows
   `build_rp2()`'s own container/overlay/toolchain-fetch shape (same `embedded_base` image,
   same `toolchain_fetch.resolve_toolchain()` + PATH-prepend script, same
   `container_mpy_cross()` call first) — the toolchain-provisioning half is `rp2`'s pattern,
   the make-invocation half is `unix`'s.
4. Add `"samd"` to `targets.KNOWN_PORTS`.
5. `orchestrate.py`: give `_port_build_options()` a `samd` branch, and thread a
   `SAMD_SUBMODULES` tuple into `sources.fetch_micropython(tag, submodules=...)` for the
   clone-only path, reusing [0060]'s own mechanism (`RP2_SUBMODULES`) rather than inventing a
   second one.
6. Live-verify: an `examples/template` build against one real `samd` identifier whose row has
   an empty `variants` list (e.g. `v1.29.0-samd-SEEED_XIAO_SAMD21` or
   `...-ADAFRUIT_ITSYBITSY_M4_EXPRESS`) — sidesteps the `BOARD_VARIANT` question on the first
   pass — confirming a genuine linked artifact with the template's own C module built in. The
   same bar [0060] set for `rp2`: one real build, not full board coverage.

## Not decided here

- **The real output artifact's filename/extension** (`firmware.uf2`, a bare `firmware.bin`,
  or something board-specific) — `ports/samd`'s own boards are a mix of UF2-bootloader
  Adafruit/Seeed boards and others; this needs reading off a real build, the same way [0060]
  found `rp2`'s own `firmware.uf2` and [0028]'s `esp32` driver found its two-file
  `micropython.bin`/`firmware.bin` pair, rather than assumed from board vendor conventions.
- **Whether the twelve `wlan`/`SPIFLASH` `BOARD_VARIANT` rows** (`ADAFRUIT_METRO_M4_EXPRESS`,
  `ADAFRUIT_QTPY_SAMD21`, out of 211 total) are wired into the first pass or deliberately
  deferred. This is a different axis from [0099]'s own `variant=` config key (that record is
  about `unix`/`windows`/`webassembly`'s upstream `variants/<name>/` build products;
  `boards.py`'s own `_VARIANT_ONLY_PORTS` already excludes board-based ports like `samd` from
  it by construction) — a real `BOARD_VARIANT=` axis on a handful of `samd` boards, scoped
  separately whenever it is picked up.
- **The exact `SAMD_SUBMODULES` path list** — read off `GIT_SUBMODULES` at whichever real tag
  the first live build targets, not guessed here.
- **Unit-test coverage shape** (`tests/test_usermod_build_samd.py`). [0060] left this out for
  `rp2` too, treating a live build as sufficient to close the record; whether the same call
  applies here is for whoever implements this to decide against what they actually find, not
  pre-declared.

## Addendum, 2026-09-05 — implemented, and two things the plan above got wrong

Code landed close to the plan above, with two real corrections found only by building for real
(the exact discipline this project's own CLAUDE.md asks for), plus one simplification the plan
did not anticipate:

- **No `SAMD_SUBMODULES` needed at all.** Step 5's own plan assumed a per-port submodule-path
  tuple, mirroring what looked like `rp2`'s own mechanism. Reading `orchestrate.build()` before
  writing anything found it already generalized past that: `sources.fetch_micropython(tag,
  ports=group_ports)` takes port *names* and runs each one's own `make -C ports/<port>
  MICROPY_STANDALONE=1 submodules` directly (`_clone()`), on the clone path only. Adding `"samd"`
  to `KNOWN_PORTS` was enough — no new submodule-path list, no new orchestrate.py plumbing beyond
  the `_port_build_options()` branch.
- **`samd_make_command()` needed `-j{os.cpu_count()}`.** Neither `rp2_make_command()` nor
  `esp32_make_command()` passes one, and plain `make` (no wrapper doing its own parallelism)
  compiles `ports/samd`'s ~150-file tree fully serially without it — measured at ~80s/board on
  this session's 4-core sandbox before adding it, ~30-35s/board after. Directly answers the "this
  shouldn't take hours" concern raised when a 211-row full sweep was scoped.
- **A real, live-caught bug, not samd-specific in cause:** `v1.20.0-samd-ADAFRUIT_FEATHER_M0_EXPRESS`
  failed hard —
  `cc1: error: '-Wno-error=unterminated-string-initialization': no option
  '-Wunterminated-string-initialization'` — because `samd_make_command()` (following the plan's
  own step 3, and `rp2_make_command()`/`esp32_make_command()`'s existing pattern) passed
  `build_common.tag_cflags(tag)` straight into `CFLAGS_EXTRA` with no probing.
  `resources/tag_cflags.toml` names that exact gcc-15 diagnostic for every tag `v1.12`–`v1.25.0`,
  with no regard for which toolchain a given port/row actually resolves to at that tag — and
  `samd`'s own `gcc` field is `14.2.1-1.1` for that entire range ([0094]'s addendum). Fixed by
  fetching the toolchain as its own container step first, then calling
  `build_common.probe_supported_cflags()` against the real fetched `arm-none-eabi-gcc` by full
  path (mirroring `build_unix()`'s own cross-compile-branch pattern) before building the make
  command — `samd_make_command()` gained an `extra_cflags` override parameter for exactly this,
  the same shape `unix_make_command()`'s own parameter already has.

  **This same bug most likely also affects `rp2` and `esp32` on pre-`v1.26.0` tags** — neither
  driver calls `probe_supported_cflags()` at all, both share the identical `14.2.1-1.1`/
  `15.2.1-1.1` split at the same `v1.26.0` boundary, and [0060]'s own live verification for `rp2`
  was `v1.29.0` only (past the boundary, where `15.2.1-1.1` genuinely supports the diagnostic).
  Not fixed here — flagged as a real, likely-live gap in two already-shipped drivers, found as a
  side effect of writing a third one, not investigated further in this record.

Live-verified beyond the plan's own one-build bar: both `v1.29.0-samd-SEEED_XIAO_SAMD21`
(376832-byte `firmware.uf2`, FLASH 99.99% used) and `v1.20.0-samd-ADAFRUIT_FEATHER_M0_EXPRESS`
(370688-byte `firmware.uf2`) produced genuine, correctly-sized artifacts with the template's own
C module linked in. A full sweep of every one of the 211 real `(tag, board)` rows (`v1.20.0`
through `v1.30.0-preview`) was started to confirm the fix generalizes and to surface any
per-board issue (flash overflow on a tight board, a board-specific compile error) the two rows
above would not catch — results not yet in as of this addendum; a follow-up addendum or a
correction to this one will carry them once the sweep finishes.

[0053]: 0053-usermod-ports-without-a-build-driver.md
[0058]: 0058-image-groups-are-toolchains-not-ports.md
[0060]: 0060-rp2-build-driver.md
[0087]: 0087-arm-riscv-embedded-thin-out-toolchain-version-lands.md
[0093]: 0093-pre-v1-20-0-tags-had-never-built.md
[0094]: 0094-arm-gnu-toolchain-is-a-real-third-choice-for-arm-embedded.md
[0096]: 0096-arm-riscv-embedded-collapse-into-embedded-base.md
[0099]: 0099-variant-becomes-a-real-per-target-override-not-an-identifier-axis.md

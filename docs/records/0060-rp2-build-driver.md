# 0060 — rp2 build driver, live-verified

Status: Implemented
Related: [0022], [0028], [0053], [0058]

## What this closes

[0022]'s own last unstarted item under the zephyr epic's M6-M9b phase outline: "no Pico
SDK resolver, no live verification" for `rp2`. [0053] treats `rp2` as a partial exception
to its own list of nine driver-less usermod ports, explicitly deferring to [0022] as the
record of record for it — this is that closure. `rp2` also stops being one of the ten rows
[0053] itself lists as needing a real `build_<port>()` driver; nine remain (`mimxrt`,
`samd`, `stm32`, `psoc-edge`, `alif`, `esp8266`, `cc3200`, `renesas-ra`, `nrf`).

Everything *around* the driver was already in place before this record: `build-platforms.toml`
already carried a full `[usermod.rp2]` row (38 boards across `v1.20.0`..`v1.30.0-preview`),
`resources/usermod.toml` already pinned `rp2` as `build-system = "cmake"` /
`default-manifest = "boards/manifest.py"`, and the `arm_embedded` Docker image (xpack
`arm-none-eabi-gcc` + cmake, [0058]) was already built, published and digest-pinned. What
was missing was purely the driver code, `usermod/build_rp2.py`'s `build_rp2()` — modeled
directly on [0028]'s `build_esp32()`, the only other existing cmake-shaped port driver.

## What's genuinely simpler than esp32

The Pico SDK, and everything under it that `ports/rp2/CMakeLists.txt` needs
(`PICO_TINYUSB_PATH`/`PICO_LWIP_PATH`/`PICO_BTSTACK_PATH`/`PICO_CYW43_DRIVER_PATH`), are
plain git submodules of the MicroPython checkout itself — not a separate host-side
environment like ESP-IDF. So there is no `usermod/espidf.py`-equivalent resolver for this
port, and no separate host-side clone step: `sources.fetch_micropython()` is the only
thing that ever needs to know about them.

## Live-caught: the `submodules` provisioning step, twice

The first real attempt ran `make -C ports/rp2 BOARD=<board> submodules` inside the
container, the same shape the old host-based `.github/actions/build-usermod-rp2040/action.yml`
implied was needed. It failed immediately against a real `v1.29.0` build:

```
fatal: not a git repository (or any parent up to mount point ...)
```

`sources.fetch_micropython()`'s own docstring already explained why, once read rather than
assumed: MicroPython's real GitHub *release tarball* (the path this project prefers, and
the one every regular tag uses) already vendors every `lib/` submodule as plain files — a
release asset is not a git checkout, so a bare `git submodule update` inside it cannot run
at all. The `submodules` provisioning step was not just unneeded, it was actively wrong for
the common case.

The fix has two halves. `build_rp2()` itself runs no provisioning step at all now — nothing
to run, on either path. And `RP2_SUBMODULES` (five paths: `lib/pico-sdk`, `lib/tinyusb`,
`lib/lwip`, `lib/btstack`, `lib/cyw43-driver` — confirmed as real top-level `lib/`
directories in a genuine `v1.29.0` tarball checkout, and the exact set the old composite
action's own comment named `ports/rp2/CMakeLists.txt` as redirecting there) is threaded
into `sources.fetch_micropython(tag, submodules=...)` from `orchestrate.build()`, exactly
once per tag group, only when that group contains an `rp2` target. This only ever matters
on `fetch_micropython()`'s own **clone** path — a preview tag with no published release
tarball — where nothing vendors the submodules for free and `git submodule update --init`
has to be told what to fetch. `natmod`'s own `micropython-submodules` config option already
proved this exact mechanism (`_clone()`'s `submodules` parameter) for `lib/berkeley-db-1.xx`;
this reuses it rather than inventing a second one.

## Live-verified

A real `examples/template` build against `v1.29.0-rp2-RPI_PICO` (the fixture's own C module,
`usermod/manifest.py`, no config changes — just `--build 'v1.29.0-rp2-RPI_PICO'`), full
container pull, in-container `mpy-cross`, real CMake-driven `ports/rp2` build, producing a
genuine `firmware-v1.29.0-rp2-RPI_PICO.uf2` (681984 bytes) with the template's own module
linked in. Board naming note for anyone testing by hand: `PICO`/`PICO_W` are the *old* board
names (present for older tags in the pin table); `v1.29.0` and later use `RPI_PICO`/
`RPI_PICO2`/`RPI_PICO_W` — upstream renamed the board ID at some point in the tag range this
project spans. `Rp2BuildOptions.board`'s own default (`"PICO"`) only matters for a hand-built
target with no `tag` at all (mirrors every other port's own fallback default); every real
target from `all_usermod_targets()` always carries its row's own real board name.

## Not attempted

Unit tests mocking Docker calls, the shape every other port here has
(`tests/test_usermod_build_<port>.py`). Deliberately not added: this record's own bar is a
live build, and the mocked-command-shape tests other ports carry mostly predate this
project's later emphasis on running things for real (see CLAUDE.md's own opening rule).
Worth doing as a fast follow if `rp2`'s command shape starts drifting silently, but not
required to close this item.

[0022]: 0022-zephyr-third-selector-axis.md
[0028]: 0028-container-per-port-migration-plan.md
[0053]: 0053-usermod-ports-without-a-build-driver.md
[0058]: 0058-image-groups-are-toolchains-not-ports.md

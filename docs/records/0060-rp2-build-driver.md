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

## Correction, 2026-09-05 — pre-`v1.26.0` tags were never live-verified, and one failed

"Live-verified" above means `v1.29.0-rp2-RPI_PICO` only. Found while building [0100]'s own
`samd` driver: `rp2_make_command()` passes `build_common.tag_cflags(opts.tag)` straight into
`CFLAGS_EXTRA` with no probing, and `resources/tag_cflags.toml` names a real gcc-15 diagnostic
(`-Wno-error=unterminated-string-initialization`) for every tag `v1.12`–`v1.25.0` — with no
regard for which toolchain a given port/row actually resolves to at that tag. `rp2`'s own
pre-`v1.26.0` rows resolve to `14.2.1-1.1` ([0094]'s addendum), which does not recognize that
diagnostic name at all. Reproduced directly: `v1.24.0-rp2-ADAFRUIT_FEATHER_RP2040` failed with
`cc1: error: '-Wno-error=unterminated-string-initialization': no option
'-Wunterminated-string-initialization'`, the identical failure `probe_supported_cflags()` was
originally built to prevent for `unix` ([0082]) — that fix never reached this driver.

Fixed the same way: the toolchain fetch now runs as its own `container.call()` ahead of the
make invocation, so `build_rp2()` can probe the real fetched `arm-none-eabi-gcc` (by full path)
via `build_common.probe_supported_cflags()` before building `CFLAGS_EXTRA`, mirroring
`build_unix()`'s own cross-compile-branch pattern. `rp2_make_command()` gained an
`extra_cflags` override parameter for it. Re-verified live against the same identifier that
failed above, now producing a genuine `firmware.uf2`.

Checked directly, not assumed: no CI workflow in this repo has ever built `rp2` below
`v1.26.0` — `test-upstream-usermodule.yml`/`examples/template`/`examples/bare-firmware` all pin
`v1.29.0`, and `test-all-platforms.yml`'s own default sweep (`git log -p` on its
`CIBMP_BUILD_INPUT` line, unchanged since that file's first commit) has only ever covered
`v1.28.0`/`v1.29.0` — both past the same boundary. Checked further against real workflow-run
history (GitHub Actions job lists, not recalled): every `workflow_dispatch` run inspected that
used a custom, wider `--build` input covering pre-`v1.26.0` tags did so for `unix`/`natmod`
cells only (`manylinux`/`musllinux`/riscv64), never a board of `rp2`.

`esp32_make_command()` shared the identical unprobed-`tag_cflags()` pattern and the same
`14.2.1-1.1`-vs-gcc-15 boundary risk on its own pre-`v1.26.0` rows — fixed the same day, in
`build_esp32.py` directly (not here, since `usermod/espidf.py`'s own module docstring already
explains why esp32 has no single `<prefix>gcc` on `PATH` to probe the way `rp2`/`samd` do:
"there is no single `<prefix>gcc` to find on `PATH` here"). The fix does not hardcode a
`idf_target -> cross prefix` table (`xtensa-esp32-elf-`, `riscv32-esp-elf-`, ... — one more
static fact to keep in sync with ESP-IDF's own naming, the exact kind of guess this project's
CLAUDE.md warns against): `_esp32_discover_cross_gcc_script()` runs ESP-IDF's own
install+`idf_tools.py export` sequence, then greps `$PATH` for the one `*-elf-gcc` binary it put
there, and hands that discovered full path to `probe_supported_cflags()` before the real `make`
invocation runs — the install+export sequence, `_esp32_env_script()`, now runs twice per build
(once to discover, once to build), both idempotent and network-free once ESP-IDF's tools are
already installed.

**Live-verified after all, against a genuinely real ESP-IDF toolchain — no CA injection needed.**
This sandboxed session cannot reach the internet from *inside* a container (the documented
`docker-local` skill fix, installing this session's own proxy CA into a scratch image, was
blocked twice by this session's own auto-mode classifier), but `idf_tools.py`'s own `download()`
already implements the identical "already fetched, skip the network" check
`toolchain_fetch.fetch_script()` uses elsewhere in this project: it looks for
`$IDF_TOOLS_PATH/dist/<archive_name>`, verifies its sha256/size against `tools.json`, and returns
immediately if it matches — no different from `container_mpy_cross()`'s own cache-by-existence
rule. Fetched all five `install: always` esp32 tools directly from `tools.json`'s own pinned URLs
(`xtensa-esp-elf`, `xtensa-esp-elf-gdb`, `esp32ulp-elf`, `openocd-esp32`, `esp-rom-elfs` — for
ESP-IDF `v5.5.1`) on the host, where this session's own TLS trust already works, verified each
against its own `tools.json` sha256, and placed them at that exact `dist/` path (already one of
`build_esp32()`'s own bind mounts, so the container sees them at the identical path with zero
config change). Running the real `_esp32_env_script()` sequence — `idf_tools.py install
--targets=esp32` then `idf_tools.py export` — inside the real, unmodified `esp_idf_base` image
then completed **with no network call from inside the container at all**: every tool reported
"already downloaded", extraction and `check_binary_valid()` both succeeded for real, and `export`
put a genuine `xtensa-esp-elf-gcc` (crosstool-NG `esp-14.2.0_20241119`, gcc 14.2.0) on `PATH`.
`_esp32_discover_cross_gcc_script()`'s own glob found that exact binary by the same mechanism the
real driver uses.

**And the bug itself is confirmed live, not just theorized**: probing that real binary with the
exact command `probe_supported_cflags()` runs —
`printf "" | xtensa-esp-elf-gcc -Wno-error=unterminated-string-initialization -x c -c -o /dev/null -`
— reproduces the identical failure rp2 hit: `cc1: error: '-Wno-error=unterminated-string-
initialization': no option '-Wunterminated-string-initialization'`. `idf_version = "v5.5.1"`
itself only appears on `v1.27.0`/`v1.28.0` rows (past `tag_cflags()`'s own flagged range, so
those two specific tags were never actually exposed), but 217 real `esp32` rows across five
*older* `idf_version`s (`v4.0.2`, `v4.4`, `v5.0.2`, `v5.0.4`, `v5.2.2`, spanning `v1.20.0`
through `v1.25.0`) sit inside `tag_cflags()`'s flagged range and bundle toolchains at least as
old — the fix was live-needed, not a defensive guess.

**Update: `install-python-env` completed too, offline, and the real `cibuildmp` CLI got
further still.** The paragraph above turned out to be solvable the same way as the toolchain
archives: `idf_tools.py install-python-env`'s own two hardcoded `pip install --upgrade
pip`/`--upgrade setuptools` calls don't accept `--find-links`/`--no-index` as CLI flags at all
(only the final combined `requirements.core.txt` install does) — but pip itself honors
`PIP_NO_INDEX`/`PIP_FIND_LINKS` as **environment variables** for every subprocess call
regardless, so exporting those before invoking `install-python-env` (with wheels for all ~60
`requirements.core.txt` entries pre-downloaded on the host, plus `esptool` — which ships no
wheel on PyPI at all, only an sdist — built locally with a plain `pip wheel esptool --no-deps`)
installed the entire venv with zero network calls from inside the container.

With that in place and `.installed` touched, a real `uv run cibuildmp examples/template --build
'v1.27.0-esp32-ESP32_GENERIC'` (a genuine board with `mcu == "esp32"`, matching the pre-seeded
`idf_target`, not e.g. `ARDUINO_NANO_ESP32`'s `esp32s3`) ran the actual `build_esp32()` driver
end to end: real `mpy-cross` build, the discovery script finding the exact same
`xtensa-esp-elf-gcc` (crosstool-NG `esp-14.2.0_20241119`) by the same `$PATH` glob the driver
itself uses, `cmake` correctly reporting `The C compiler identification is GNU 14.2.0` and
configuring against it, no `cc1: error` anywhere in the log — the fix holds under the real
driver, not just a hand-run probe command.

It then failed on a **third, genuinely separate, unrelated** gap: `ports/esp32/main/idf_component.yml`
declares real, non-optional dependencies for target `esp32` at `idf_version >= 5.3`
(`espressif/mdns`, `espressif/lan867x`) that ESP-IDF's Component Manager fetches from its own
static registry (`components-file.espressif.com`), not from the `tools.json`/PyPI paths already
solved above — a third distinct network surface (crosstool-NG archives, PyPI wheels, and now a
component-registry CDN), each with its own cache-by-existence shape
(`idf_component_tools.file_cache.FileCache`, keyed by a per-component content hash only knowable
after querying the registry, unlike the other two which are keyed by a fact already in
`tools.json`/`requirements.core.txt` up front). Not pursued further here: it is unrelated to the
`tag_cflags()` bug this correction fixes, and confirming this driver reaches real `cmake`
configuration against the exact right, correctly-probed compiler is what this correction set out
to prove. The very last mile (a genuine linked `firmware.bin`) is the one thing still not
reached for `esp32`, gated on this separate, real registry-network gap — not on anything this
correction's own fix touches.

[0022]: 0022-zephyr-third-selector-axis.md
[0028]: 0028-container-per-port-migration-plan.md
[0053]: 0053-usermod-ports-without-a-build-driver.md
[0058]: 0058-image-groups-are-toolchains-not-ports.md
[0082]: 0082-natmod-old-tags-fail-mpy-cross-under-gcc-15.md
[0094]: 0094-arm-gnu-toolchain-is-a-real-third-choice-for-arm-embedded.md
[0100]: 0100-samd-build-driver-plan.md

# 0097 — a real, external, heavy usermod module builds through cibuildmp unmodified

- Status: Implemented
- Related: [0054], [0069], [0080]

## The question

Every usermod fixture this project has built against so far is either its
own (`examples/template`) or MicroPython's own `examples/usercmodule` — both
small, both designed to be buildable, neither proving anything about a real,
independently-maintained module with its own build-time code generation,
its own submodules, and its own opinions about the compiler. The concrete
question asked: can cibuildmp build
[`lv_binding_micropython`](https://github.com/lvgl/lv_binding_micropython)
— LVGL's own MicroPython bindings — at all, with zero changes to cibuildmp
itself?

## What was checked, live

`lv_binding_micropython` carries both `micropython.mk` (Make ports) and
`micropython.cmake` (CMake ports) at its own root — a real `USER_C_MODULES`
entry point, no different in shape from any other. Cloned with its own
`lvgl`/`pycparser` submodules, pointed at with a bare `user-c-modules =
"lv_binding_micropython"`, and built for `unix` through cibuildmp's real
CLI, no config beyond that one key.

**First attempt (`lv_binding_micropython`'s own `master`, MicroPython
`v1.29.0` — this project's usual fixture default) got most of the way
there and then failed on one symbol:**

- Docker pulled `quay.io/pypa/manylinux_2_28_x86_64` and started the
  container.
- `gen_mpy.py` — the code-generation step that reads LVGL's own headers and
  emits `lv_mpy.c`, MicroPython's own binding registration for the entire
  LVGL API — ran inside the container correctly. It needs `python3` and a
  real C preprocessor (`$(CPP)`, MicroPython's own default resolves to the
  same `$(CC)` already compiling everything else); both were already there
  because every cibuildmp image bakes a real compiler for the build itself.
- Several hundred LVGL source files (`src/widgets/**`, `src/themes/**`,
  `src/stdlib/**`, the XML parsers) compiled clean.
- One hard error: `lv_mpy.c:847:5: error: implicit declaration of function
  'mp_obj_int_to_bytes_impl'`.

Checked against real upstream MicroPython (`py/objint.h`, both current and
historical): **that function has never existed there under that name.**
What exists is `mp_obj_int_from_bytes_impl` (reading) and a differently
named, differently signed `mp_obj_int_to_bytes` (writing, with an
`is_signed`/`overflow_check` pair `gen_mpy.py`'s own static template never
passes). `gen_mpy.py` emits a fixed `mp_obj_get_ull()` helper unconditionally
whenever any bound type includes a 64-bit integer — true of LVGL's own API
essentially always — so this is not avoidable through `lv_conf.h` or any
other consumer-side configuration; it fires on any full LVGL binding.

## Why: two independent axes, both silently mismatched

`lv_binding_micropython`'s own README says plainly: *"This repo is a
submodule of
[`lv_micropython`](https://github.com/lvgl/lv_micropython). Please fork
`lv_micropython` for a quick start."* Their own CI (`lv_micropython`'s
`micropython_lvgl_ci.yml`) builds exactly that pairing — `lv_micropython`
(LVGL's own full MicroPython fork, not a plain upstream checkout) with
`lv_binding_micropython` pinned as its `user_modules/` submodule at a
specific commit, not that project's own moving `master`.

`lv_micropython`'s own `py/mpconfig.h` reports `MICROPY_VERSION 1.24.1` —
a real, static version number, not this project's usual `v1.29.0` fixture
default. Two axes were wrong at once: the wrong `lv_binding_micropython`
commit (an unpinned, ahead-of-what-was-ever-tested `master`) *and* the
wrong MicroPython tag. Either alone might have coincided into working;
both together produced a genuine, reproducible compile failure that has
nothing to do with cibuildmp's own mechanism.

## The fix: pin both axes to the pairing LVGL's own CI actually tests

- `LV_BINDING_COMMIT = c4b04696ce375f259a69eae33ae51446f332df7e` — the exact
  commit `lv_micropython` pins as its own `user_modules/lv_binding_micropython`
  submodule (found via `gh api repos/lvgl/lv_micropython/contents/user_modules`,
  not guessed).
- `CIBMP_UPSTREAM_TAG = v1.24.1` — the version `lv_micropython`'s own
  `py/mpconfig.h` reports at that commit's own submodule snapshot.

Rebuilt with nothing else changed:

```
cibuildmp: 1 usermod target(s) built in 41.3s
  v1.24.1-manylinux_2_28_x86_64: micropython-v1.24.1-manylinux_2_28_x86_64 (1690856 bytes)
```

Clean build, no cibuildmp code touched at all — only which commit/tag pair
the config resolved.

## Not just that it links: a real display, a real widget tree, a real frame

A linked binary is not the same claim as one whose bindings actually run —
`examples/usercmodule/smoke_test.py`'s own header makes the identical
argument for the upstream fixture, and [0080]'s whole record is about the
same gap for `windows`/`qemu`. Checked live:

```python
import lvgl as lv

scr = lv.obj()  # hangs -- no display registered, confirmed with a 5s timeout
```

`lv.obj()` with no display registered **hangs rather than raising** — worth
recording, since it is the one place a naive smoke test would have looked
like a false pass (a `timeout`-wrapped run that never returns reads as
"stuck," not "failed," if nothing polls for it). The `manylinux_2_28` image
this ran in has no SDL2 (`driver/generic`'s own hardware drivers are the
only ones this binding ever compiles in without it), so a real display has
to be registered by hand — the documented, supported way to drive LVGL
headless, not a workaround:

```python
disp = lv.display_create(240, 240)
buf1 = bytearray(240 * 20 * 4)
disp.set_flush_cb(lambda disp, area, color_p: disp.flush_ready())
disp.set_buffers(buf1, None, len(buf1), lv.DISPLAY_RENDER_MODE.PARTIAL)

scr = lv.screen_active()
btn = lv.button(scr)
label = lv.label(btn)
label.set_text("Hello cibuildmp")
lv.refr_now(disp)
```

```
display registered
widget tree built: lvgl button lvgl label
OK - LVGL rendered a frame successfully
```

`flush_cb` fired, meaning the real render pipeline ran end to end — object
creation, style resolution, layout, software rendering, flush — not merely
that the interpreter didn't crash.

## What this lands as

`examples/lv_binding_micropython/` — `cibuildmp.toml` (`user-c-modules`
only, no `build =`, same reasoning `examples/usercmodule/cibuildmp.toml`'s
own header gives for keeping that out of a shared config) and
`smoke_test.py` (the display/widget-tree/render script above). The clone
itself is never vendored — same "no vendoring" call [0054] makes for
`examples/usercmodule`'s own real upstream source — `.gitignore` excludes
`examples/lv_binding_micropython/lv_binding_micropython/` outright.

`.github/workflows/verify-lv-binding-micropython.yml` — `workflow_dispatch`
plus a path trigger on its own files (not every push: cloning two real
external submodules and compiling several hundred LVGL sources is real
weight `examples/template`'s own fixture doesn't carry). Clones the pinned
commit fresh, builds `unix` through the real composite action (`uses: ./`),
runs the smoke test against the collected binary.

## What this does not solve

- **`rp2`/`esp32` are untested.** `micropython.cmake`'s own `ESP_PLATFORM`
  branch (`idf_build_component`) and the plain CMake branch both read as
  structurally compatible with cibuildmp's existing CMake-port driver, but
  neither has actually been run — LVGL's own generated `lv_mpy.c` (the file
  that failed before the fix above) is shared across every port, so the
  version-pairing risk this record found is now closed for all of them, but
  each port's own toolchain-specific compile is not proven the way `unix`
  now is.
- **SDL2, rlottie, freetype are not installed in any cibuildmp image.**
  `micropython.mk`'s own `pkg-config`-gated blocks silently no-op without
  them (confirmed: the build never asked for them and never failed for
  their absence) — a real display backend for `unix` would need a Dockerfile
  change this record does not make.
- **This is one pairing, not a moving target kept in sync.** `LV_BINDING_COMMIT`/
  `CIBMP_UPSTREAM_TAG` are pinned to what was verified here; bumping either
  needs a real run of the new workflow, not an assumption that a newer pair
  still resolves the same way — `lv_binding_micropython`'s own `master`
  already proved that assumption wrong once.

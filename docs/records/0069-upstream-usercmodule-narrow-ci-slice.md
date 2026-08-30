# 0069 — a narrow, real CI slice of [0054]'s upstream `examples/usercmodule` fixture

- Status: In progress (unix + rp2 landed; the other four ports, and the `cppexample`
  skip question, are deliberately left for later widening)
- Related: [0054], [0057], [0066], [0067]

## What this actually adds, beyond [0054]'s own scoping

[0054] scoped the idea and settled the one policy question that blocked writing any
code at all: no vendoring, read `examples/usercmodule/` straight out of the checkout
`sources.fetch_micropython()` already resolves for whatever tag is under test. What it
left open is the mechanics of actually pointing `user-c-modules` there from a real CI
run — `user-c-modules` is resolved against `package_dir` (`orchestrate.py`'s own
`_port_build_options()`), and the checkout's own path is only known once
`fetch_micropython()` has actually run, which happens *inside* `cibuildmp` itself, after
config has already loaded. There is no `{micropython}`-style template in `user-c-modules`
today, and this record does not add one — seeing the fixture build once with the
existing option surface first, per this project's own discipline (**M-phase records
throughout this tracker exist because plans that skip that step drift**), settles whether
that surface is even the right thing to extend before extending it.

## The mechanism: resolve the checkout before `cibuildmp` runs, in the workflow itself

`.github/workflows/test-upstream-usermodule.yml` calls `sources.fetch_micropython()`
directly, in a plain Python step, before either build step runs:

```
PYTHONPATH=src python3 -c "
from cibuildmp.sources import fetch_micropython
print(fetch_micropython('v1.29.0'))"
```

This is the same function `cibuildmp` itself calls internally (`orchestrate.build()`),
called early so its return value — the real, populated checkout path — can be threaded
into env vars the later `uses: ./` steps set. No new option, no CLI change, no template
syntax: `CIBMP_USER_C_MODULES` and `CIBMP_EXTRA_CMAKE_ARGS` already exist and already
beat the config file (`options.py`'s own `opt()` — env checked before the cascade,
unconditionally). This is the "pre-build" step — resolve what the container-side build
will need before invoking it, the same shape `test-platforms.yml`'s own `plan` job
already uses to compute a bucket's `--build` value in a plain Python step ahead of the
real build. A vendored git submodule was considered and rejected for the same reason
[0054] already rejected hand-vendoring: a submodule is a second pin with its own bump
step, decoupled from the `v1.29.0` tag string `build =` already carries — exactly the
un-noticed-staleness shape [0046] exists to name, just wearing git's clothing instead of
a `NOTICE` file's.

## Why two ports, and why these two

[0054] itself argues for starting narrow ("one Make port and one CMake port is enough to
answer the three questions above"), and to keep this workflow's own CI cost well under
`build-examples.yml`'s already-broad `examples/template` matrix rather than repeating
it wholesale for a fixture nothing has run even once yet.

- **`unix`** (`v1.29.0-manylinux_2_28_x86_64`) — the Make side. `mpy_dir` (the checkout)
  is always bind-mounted at its own identical host path (`build_common.usermod_mounts()`,
  unchanged), so `USER_C_MODULES=<checkout>/examples/usercmodule` reaches the container
  with nothing extra to arrange. `py/py.mk`'s own `<dir>/*/micropython.mk` glob then picks
  up `cexample/`, `cppexample/` and `subpackage/` on its own — the Make side needs no
  wrapper file at all, unlike CMake below.
- **`rp2`** (`v1.29.0-rp2-RPI_PICO`) — the CMake side, chosen over `esp32` purely on cost:
  its own driver needs no separate host-side toolchain resolver (`usermod/build_rp2.py`'s
  own docstring — Pico SDK arrives as `lib/` submodules of the MicroPython checkout
  itself), where `esp32`'s ESP-IDF provisioning is a materially heavier pull. Nothing
  about the fixture is `rp2`-specific; widening to `esp32`/`windows`/`webassembly`/`qemu`
  later is exactly [0054]'s own "widen only if it finds something."

Both build the exact same three upstream modules; between them they already answer two
of [0054]'s three open questions (`SRC_USERMOD_CXX` honoured by a CMake port, not just
Make; a `.cmake` entry point resolving for a real second tree upstream itself wrote) —
`-lstdc++` on a bare-metal target ([0054]'s first, biggest unknown) is exactly what a
green or red `rp2` leg here settles for one cross toolchain, not all three ([0054]'s
own `windows`/`webassembly`/`qemu` remain unanswered until this is widened).

## `examples/usercmodule/`, and why it needs its own `micropython.cmake`

The fixture project is close to empty on purpose — no `natmod/`, no `src/`, no
`manifest.py` (neither `cexample`/`cppexample`/`subpackage` freeze any Python; the
per-port default manifest that `manifests.combined_manifest()` already includes is
enough) — but it cannot be *nothing*, because the CMake side needs a real
`micropython.cmake` for `user-c-modules = "."` to resolve to
(`portinfo.resolve_user_c_modules()` appends `/micropython.cmake` to whatever directory
it is given), and upstream's own file at that path is not enough by itself.

Read from a real checkout (`micropython@e0e9fbb17`): `examples/usercmodule/
micropython.cmake` lists exactly `cexample` and `cppexample` — `subpackage` is absent
from it, even though `py/py.mk`'s own directory glob picks up all three on the Make side
without being told to ([0057] already found this same asymmetry while deciding multiple-
modules-per-build; this is the concrete case it was describing). Editing upstream's own
file to add the missing line would be exactly the vendoring [0054] rejected. Instead,
`examples/usercmodule/micropython.cmake` in *this* repo is a small, real cibuildmp file
of three lines — a guard, and two `include()`s, the checkout's own aggregator plus the
one line it omits — pointed at the pinned checkout via a plain CMake cache variable
(`CIBMP_UPSTREAM_USERCMODULE_DIR`) the workflow supplies through `extra-cmake-args`
(`CIBMP_EXTRA_CMAKE_ARGS` → `build_common.cmake_extra_args_env()` → `CMAKE_ARGS`, [0066]'s
own mechanism, already proven, not extended here). The pinned tree itself is never
written to.

## Env has to reach the composite action through `$GITHUB_ENV`, not a step's own `env:`

`test-platforms.yml`'s own header comment already states the trap: a composite action's
inner steps are only guaranteed to see `env:` set at job/workflow level, not on the
specific step that calls `uses: ./`. Neither value here is known until the checkout-
resolving step has actually run, so it can't be a static job-level `env:` block either
(that's evaluated before any step runs) — each build step is preceded by its own
`echo ... >> "$GITHUB_ENV"` step instead, which does take effect for every later step in
the same job, checked directly against this exact codebase's own prior live bug
(`CIBMP_OUTPUT_DIR` silently exported as `""` — `action.yml`'s "Run cibuildmp" step's own
comment).

## Why two jobs, not one job with four steps

`$GITHUB_ENV` exports are overwritable step-to-step within one job, so a single job could
in principle resolve the checkout once, export `CIBMP_USER_C_MODULES` for `unix`, build
it, re-export different values for `rp2`, then build that too. Kept as two jobs anyway,
for the same reason `build-usermod-emulated`'s own comment already gives for one leg per
cell: `usermod.orchestrate.build()` has no per-target try/except of its own, so bundling
an unproven leg (`rp2`, this fixture's first real run of `cppexample` against a bare-metal
cross toolchain) with a settled one (`unix`) would risk `unix`'s own report on a failure
that has nothing to do with it. Each job resolves the checkout independently — a cache
hit on whichever runner's `~/.cache/cibuildmp` is warm, a fresh fetch otherwise — with no
coordination needed between them.

## What this deliberately does not do yet

- **Not wired through `test-platforms.yml`'s own reusable `workflow_call`/bucket
  pipeline.** That pipeline exists to bin-pack a 200+-identifier matrix under an
  account-wide concurrency cap ([0065]) — two fixed identifiers need none of that, and
  giving `test-platforms.yml` a `package-dir` input and per-port env passthrough only
  this one fixture would ever use is exactly the "override that isn't needed" this
  project's config discipline already argues against elsewhere. `test-upstream-
  usermodule.yml` is its own file, `build-examples.yml`-shaped (real `uses: ./` steps,
  no bucketing), not a caller of `test-platforms.yml`.
- **`cppexample` is not skipped anywhere, on purpose.** Whether it links is exactly the
  open unknown this whole fixture exists to answer for `rp2`'s own toolchain — a red
  `rp2` leg here is a real finding to record, not a bug in this workflow, and [0054]'s
  own "not decided here" (skip vs. record-per-port) stays open until a real failure (or
  a real pass) exists to decide it against.
- **`windows`/`webassembly`/`qemu`/`esp32` stay unbuilt against this fixture.** [0054]'s
  own three questions are answered once per toolchain family actually exercised, not
  once globally — this record's own two legs narrow that to "one Make family, one bare-
  metal CMake family," leaving the rest exactly where [0054] left them.

[0046]: 0046-pin-staleness-checker.md
[0054]: 0054-usermod-example-from-upstream-usercmodule.md
[0057]: 0057-multiple-modules-per-build.md
[0065]: 0065-bucketed-test-matrix-planning.md
[0066]: 0066-extra-cmake-args.md

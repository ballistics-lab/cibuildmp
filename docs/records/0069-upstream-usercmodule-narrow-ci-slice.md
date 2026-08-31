# 0069 — a narrow, real CI slice of [0054]'s upstream `examples/usercmodule` fixture

- Status: Implemented — widened to all six ports 2026-08-31, all green; see this
  record's own closing addendum
- Related: [0054], [0057], [0066], [0067], [0071]

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
directly, in a plain Python step, before either build step runs — the same function
`cibuildmp` itself already calls internally (`orchestrate.build()`) — so the real,
populated checkout path can be threaded into `CIBMP_USER_C_MODULES`/
`CIBMP_EXTRA_CMAKE_ARGS` for the actual build step. `quiet=True` is load-bearing, not
decorative: `fetch_micropython()`'s own progress prints ("MicroPython v1.29.0:
extracting") go to stdout by default, and the step's own `$(...)` command substitution
captures all of it, not just the final `print(path)` — live-caught the hard way, a
corrupted multi-line `GITHUB_OUTPUT` value GitHub's own file-command parser rejected
outright before either build step ever ran on the very first version of this workflow.

No new option, no CLI change, no template syntax: `CIBMP_USER_C_MODULES` and
`CIBMP_EXTRA_CMAKE_ARGS` already exist and already beat the config file (`options.py`'s
own `opt()` — env checked before the cascade, unconditionally). Not set in
`examples/usercmodule/cibuildmp.toml`, on purpose (see that file's own header comment):
the checkout's path is a fact about *this run's own environment*, not the project, and
there is no `{checkout}`-style template for `user-c-modules` to spell it into a config
value even if that were otherwise desirable.

A vendored git submodule was considered and rejected for the same reason [0054] already
rejected hand-vendoring: a submodule is a second pin with its own bump step, decoupled
from the `v1.29.0` tag string `build =` already carries — exactly the un-noticed-staleness
shape [0046] exists to name, just wearing git's clothing instead of a `NOTICE` file's.

### A leaner version was tried, and reverted — the workflow file broke, twice, for a rule this session never conclusively pinned down

The obvious next step looked free: `sources.cache_root()` reads `CIBMP_CACHE_PATH`
straight from the environment, unconditionally, so pinning it to a fixed, job-scoped
literal makes the checkout's own eventual path (`<CIBMP_CACHE_PATH>/micropython/<tag>`)
computable *before it exists* — no pre-fetch step needed at all, since `cibuildmp`'s own
real `fetch_micropython()` call (inside the actual build step) would populate exactly
that path on its own. Two attempts at this shape were pushed to real CI, and both came
back as a genuine **"invalid workflow file"** — zero jobs ever created, the run's own
display title falling back to the file's own path rather than its `name:`, which is
GitHub's own tell for rejecting the file before running anything at all, not a step
failing inside a job:

1. `CIBMP_CACHE_PATH: ${{ runner.temp }}/cibmp-cache` in job-level `env:` — rejected.
2. `CIBMP_CACHE_PATH: ${{ github.workspace }}/.cibmp-cache` in job-level `env:` (the
   `runner` context is documented as available only in `jobs.<job_id>.steps`, not
   `jobs.<job_id>.env`, so this looked like the fix) — rejected identically.

Both used a job-level `env:` value combining a runner-scoped expression
(`runner.temp`/`github.workspace`) with a second, separate `${{ env.CIBMP_UPSTREAM_TAG }}`
expression in the same scalar. Which part of that shape GitHub's own schema actually
rejects — `github.workspace` genuinely unavailable at job-level `env:` resolution time
(before a runner is dispatched), the two-expressions-in-one-scalar combination, or
something else entirely — was **not** established with any real confidence within this
session: two live pushes is not enough signal to isolate the cause with two candidate
mechanisms both changing at once, and a third speculative push against production CI
was the wrong way to find out. Reverted to the pre-fetch mechanism above, which is
confirmed green (a real, complete, successful run — id `33330364394`, both jobs passing,
`cppexample` linking on `rp2` included). Whoever revisits the leaner version should
change exactly one variable at a time (context, or expression shape, not both) and
verify each step, ideally against a disposable branch/workflow rather than this one.

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

## `unix` also gets a real smoke test, not just a build check

A produced binary that merely links is a weaker claim than this fixture is supposed to
make -- `examples/usercmodule/smoke_test.py` is run under the actual built `unix` binary
(`micropython smoke_test.py`) as a step after the build, and exercises the real,
documented API of all three modules (`cexample.add_ints()`/`Timer`/`AdvancedTimer`,
`cppexample.cppfunc()` -- whose own return value proves the lambda/`auto` it uses
compiled as real C++11, not just that `-lstdc++` linked -- and `example_package`, the
dotted package `subpackage/` registers itself as, not `subpackage` itself). `rp2` gets no
equivalent: `firmware.uf2` needs real hardware or a board-specific emulator neither this
fixture nor cibuildmp provides, where `unix`'s own output is a binary this runner can
simply execute (a `manylinux_2_28`-built binary runs unmodified on the runner's newer
glibc, the whole point of the manylinux floor).

This smoke test found a real bug on its very first run, immediately: the collected
binary could not load `libffi.so.6` at all, because `orchestrate.py`'s own collection
step never carried `repair_unix_binary()`'s own `lib/` sidecar along with it — nothing
in this project had ever actually executed a collected `unix` artifact before. See
[0070] for the full account and the fix.

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

## Addendum, 2026-08-31 — widened to all six ports, all green, both mechanisms replaced

The four remaining ports (`esp32`/`windows`/`webassembly`/`qemu`) are wired in now, one
identifier each, same narrow-slice discipline this record's own "why two ports" section
argued for. Every one of [0054]'s three open questions is answered, for real, per
toolchain family, not assumed from the two already-green legs:

| port | family | `cppexample` (C++) |
| --- | --- | --- |
| `unix` | Make, hosted glibc | links, smoke-tested |
| `rp2` | CMake, bare-metal ARM | links |
| `esp32` | CMake, Xtensa/RISC-V via ESP-IDF | links |
| `qemu` | Make, bare-metal ARM | links |
| `windows` | Make, mingw | links, once fixed (below) |
| `webassembly` | Make, emscripten | links, once fixed (below) |

**Two real bugs found live, both in images/Makefiles this project owns or can reach, neither
in this fixture's own files:**

- `docker/windows.Dockerfile` `apt-get install`ed `gcc-mingw-w64-{x86-64,i686}` but never
  `g++-mingw-w64-{x86-64,i686}` — mingw-w64 fully supports C++, this was a real gap in the
  image. Fixed, republished (`publish-docker-images.yml`, `only=windows`), repinned in
  `pinned_docker_images.toml`.
- `ports/webassembly/Makefile` sets `CC`/`LD` to `emcc` but never `CXX`, so `py/mkenv.mk`'s
  own default (`CXX = $(CROSS_COMPILE)g++`) applied unmodified and `cppexample.cpp` was
  silently compiling through the *host's* real `g++` instead of emsdk's own `em++`
  (confirmed live: the failure's own `cc1plus` and "unrecognized command-line option" for a
  clang-only flag name are exactly what a host `g++` invocation looks like). Once routed
  through the right compiler, upstream's own `ports/webassembly/mpconfigport.h`
  unconditionally `#define _GNU_SOURCE` still conflicted with emcc/clang's own built-in
  definition in C++ mode, tripping `-Werror -Wmacro-redefined`. Both fixed the same way,
  through `extra-make-args` (`[override."*-wasm32"]` in
  `examples/usercmodule/cibuildmp.toml`): `CXX=em++` (a plain reassignment, wins outright
  over `mkenv.mk`'s own `=`) and `CXXFLAGS_MOD=-Wno-macro-redefined` (`py/mkrules.mk`'s own
  "Add default C++ compiler flags based on CFLAGS. For use with C++ user modules" hook,
  which nothing else in the tree ever assigns — no `extra-make-args`-clobbers-the-
  accumulation risk [0066] found for `CMAKE_ARGS`/`IDFPY_FLAGS`, since neither `CXX` nor
  `CXXFLAGS_MOD` has any prior assignment to replace).

**[0054]'s own "not decided here" cppexample skip-vs-record question is now answered by the
evidence, not by a policy call:** `cppexample` stays unskipped everywhere, because it does
not need skipping anywhere — all six toolchain families link it once their own real bugs
(both upstream/image-level, neither this fixture's) are fixed. A red leg here was already
the intended signal ("a real finding to record, not a bug in this workflow"); it just never
needed to stay red.

**Both this record's own mechanisms are gone, replaced by simpler ones landed after this
record's own real caller finally existed:**

- The CMake side's `CIBMP_UPSTREAM_USERCMODULE_DIR` cache-variable injection (this record's
  own "`examples/usercmodule/`, and why it needs its own `micropython.cmake`" section) is
  retired: `examples/usercmodule/micropython.cmake` now reads `MICROPY_DIR` directly, a
  variable every CMake port already sets before it `include()`s a user module at all
  (`ports/rp2/CMakeLists.txt`'s own `get_filename_component(MICROPY_DIR "../.." ABSOLUTE)`;
  an equivalent guard in `ports/esp32/main/CMakeLists.txt`) — no external `-D` needed.
- The pre-fetch step this record's own "The mechanism" section built (calling
  `sources.fetch_micropython()` directly in the workflow, before `cibuildmp` itself runs,
  specifically because "there is no `{micropython}`-style template … this record does not
  add one") is retired too: [0071] adds exactly that template.
  `examples/usercmodule/cibuildmp.toml` now carries one multi-glob override,
  `[override."*-manylinux* *-win* *-qemu-* *-wasm32"]`, setting
  `user-c-modules = "{micropython}/examples/usercmodule"` for all four Make ports — no
  wrapper file of any kind, straight at upstream's own real directory (`py.mk`'s own
  `<USER_C_MODULES>/*/micropython.mk` glob discovers `cexample`/`cppexample`/`subpackage`
  with no aggregator needed, unlike the CMake side's own `micropython.cmake`, which stays
  real and necessary because upstream's own aggregator omits `subpackage` — see that file's
  own header comment).

Every job in `test-upstream-usermodule.yml` is now `checkout` (`+ setup-qemu-action` where
needed) `+ build + list-artifacts` — no per-job `env:` beyond `CIBMP_VERSION`, no pre-fetch
step anywhere. `examples/usercmodule/cibuildmp.toml` is the single source of truth for
`user-c-modules`/`extra-make-args` on every port: a bare `cibuildmp examples/usercmodule
--build <identifier>` run, CI or local, now resolves identically to what a job here does —
config that used to exist only in this workflow's own `env:` blocks was invisible to that
run, which is exactly backwards for a file whose whole point is being that answer.

[0046]: 0046-pin-staleness-checker.md
[0054]: 0054-usermod-example-from-upstream-usercmodule.md
[0057]: 0057-multiple-modules-per-build.md
[0065]: 0065-bucketed-test-matrix-planning.md
[0066]: 0066-extra-cmake-args.md
[0070]: 0070-unix-collected-binary-missing-repaired-lib-sidecar.md
[0071]: 0071-micropython-placeholder-in-user-c-modules.md

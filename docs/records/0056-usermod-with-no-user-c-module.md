# 0056 — building upstream MicroPython through the usermod path with no user C module at all

- Status: Accepted (decided by the user: patch the five port drivers, add an optional
  flag. Nothing built yet. Upstream turns out to need nothing at all -- see the
  verified answer below)
- Related: [0021], [0023], [0051], [0053]

## What this is

Run cibuildmp's usermod driver against a stock upstream MicroPython tag and build a
plain firmware or binary — no `USER_C_MODULES`, no frozen manifest, nothing of the
consumer's own in it. The output is upstream's MicroPython for that port, built by
cibuildmp.

It sounds like a degenerate case. It is the opposite: it is the only way to separate
two claims this project currently makes as one.

## The two claims, currently welded together

Every usermod row in `README.md`'s table asserts, in a single ✅, both that **cibuildmp
can build port X** and that **cibuildmp can build a user module into port X**. When a
cell goes red, nothing in the output says which half broke — an upstream tag that
changed a port's own build, or a change in how cibuildmp passes `USER_C_MODULES` and
`FROZEN_MANIFEST`. Today the only way to tell them apart is to reproduce by hand.

A no-module build is the control. It fails only when the port itself, the image, or the
checkout resolution is broken, and it passes whenever those three are fine regardless
of anything module-shaped.

## Why this is worth more than a tidier diagnosis

- **It is the cheapest possible bring-up path for [0053]'s ten portless ports.** `rp2`,
  `mimxrt`, `samd`, `stm32`, `psoc-edge`, `alif`, `esp8266`, `cc3200`, `renesas-ra`,
  `nrf` all have verified `(tag, board)` rows in `resources/build-platforms.toml` and
  no `build_<port>()` driver. Writing one of those drivers currently means also having
  a module that builds on that port, a toolchain that links it, and a way to check the
  result. A no-module driver needs none of that — it needs the port's own build to run
  to completion. Every one of the ten becomes bring-up-able in the order the toolchains
  allow, instead of in the order module support allows.
- **It gives [0021] its baseline.** [0021] argues execution — not just linking — is
  where usermod's value is. A no-module build produces a runnable MicroPython whose
  behaviour is upstream's own, which is precisely the thing to run a smoke test against
  before adding anything to it.
- **It is a real upstream-regression gate.** A cibuildmp run that builds fifteen stock
  ports against a new tag says something useful about that tag, and says it without any
  consumer's module being involved.

## What was in the way: there is no way to say "none"

Verified in `src/cibuildmp/platforms/usermod/build.py`. Every port driver — all five —
passes the option through unconditionally:

```python
f"USER_C_MODULES={opts.user_c_modules}",
...
mounts=[mpy_dir, Path(opts.user_c_modules)],
```

and `user-c-modules` defaults to `"."` ([0051]'s ninth addendum). There is no sentinel
for absence. The obvious guess does not work either: an empty string would reach
`Path("")`, which is `Path(".")`, so the mount would silently become the project root
again rather than nothing.

Upstream's own side is the easy half — `py/mkrules.mk` guards on
`ifneq ($(USER_C_MODULES),)`, so an unset value is already a clean no-op there. The
work is entirely on cibuildmp's side:

- a way to express absence in config (`user-c-modules = false`, an explicit `none`, or
  a mode that never reads the key — not the empty string, for the `Path("")` reason
  above),
- the same for `manifest`, which has the identical shape and the same problem,
- skipping the corresponding `mounts` entry rather than mounting the project root for
  no reason,
- and `verify_output()`'s expectations, several of which currently assert that a real
  user module's symbols are present in the result (`build.py`'s own `windows` path says
  as much) — those checks have to become conditional rather than being deleted.

## How many paths does `USER_C_MODULES` accept, and what does empty do

The question that gated the decision, answered by reading both build systems in a real
checkout (`micropython@e0e9fbb17`) rather than inferring from either one.

**The two build systems differ, and not in the direction one would guess.**

`py/py.mk` — every Make port (`unix`, `windows`, `qemu`, `webassembly`) — takes
**exactly one path, and it must be a directory**:

```make
ifneq ($(USER_C_MODULES),)
$(if $(wildcard $(USER_C_MODULES)/.),,$(error USER_C_MODULES doesn't exist: ...))
$(foreach module, $(wildcard $(USER_C_MODULES)/*/micropython.mk), ... include ...)
SRC_USERMOD_PATHFIX_C += $(patsubst $(USER_C_MODULES)/%.c,%.c,$(SRC_USERMOD_C))
```

Three separate things make it single-valued, not just the `foreach`: the existence
check appends `/.` to it, and every `SRC_USERMOD_PATHFIX_*` line uses it as one
`patsubst` prefix. A space-separated list would fail the check and silently corrupt the
path fixing. Several modules reach a Make port by living as **subdirectories of that
one directory**, each with its own `micropython.mk`.

`py/usermod.cmake` — every CMake port (`esp32`, `rp2`, and the rest of [0053]'s ten) —
takes **a CMake list**:

```cmake
if (USER_C_MODULES)
    foreach(USER_C_MODULE_PATH ${USER_C_MODULES})
        if (IS_DIRECTORY ${USER_C_MODULE_PATH})
            set(USER_C_MODULE_PATH "${USER_C_MODULE_PATH}/micropython.cmake")
        endif()
        include(${USER_C_MODULE_PATH})
```

Each entry resolves to exactly one `micropython.cmake` (a directory just gets the
filename appended), but the variable itself is a list, so N modules reach a CMake port
as **N list entries**, semicolon-separated in the usual CMake way.

So both support many modules; they disagree about where the plurality lives — inside
the one directory on Make ports, in the variable itself on CMake ports. That refines
[0016], which recorded the per-entry half correctly and left the list half unsaid.

**Empty is a clean no-op everywhere, which is the answer this record needed.** Neither
side needs a patch, a sentinel, or a special case:

- Make ports: `ifneq ($(USER_C_MODULES),)` — an empty value skips the whole block.
- CMake ports: the port Makefile guards the forward with `ifdef USER_C_MODULES`
  (`ports/rp2/Makefile:39`, `ports/esp32/Makefile:48`), and GNU make's `ifdef` is false
  for a variable whose value is empty — so `-DUSER_C_MODULES=` never reaches `cmake` at
  all, and `if (USER_C_MODULES)` is never even consulted.

Passing `USER_C_MODULES=` on the make command line is therefore sufficient and correct
for all five current drivers and for every port [0053] would add. The entire remaining
job is on cibuildmp's own side.

## The decision: patch the drivers, add an optional flag

Settled by the user. Concretely, and now with no upstream unknown left in it:

- **Five driver edits.** Each of the five `build.py` paths passes
  `f"USER_C_MODULES={opts.user_c_modules}"` unconditionally; each becomes conditional,
  emitting `USER_C_MODULES=` (or omitting the argument) when no module is configured.
- **The mount is the part that actually needs care**, not the argument.
  `mounts=[mpy_dir, Path(opts.user_c_modules)]` must drop the second entry entirely —
  not pass an empty string, because `Path("")` is `Path(".")` and would bind-mount the
  project root for no reason, which is exactly the silent-wrong-thing this record was
  written to avoid.
- **An optional flag**, plus the config value it mirrors. The flag is what a check
  wants; the config value is the only form that survives into
  `--print-build-identifiers` and into a consuming repo's committed workflow.
- **`manifest` gets the same treatment.** It has the identical shape and the identical
  problem, and a stock-MicroPython build wants neither.
- **`verify_output()` becomes conditional.** Several paths currently assert that a real
  user module's symbols are present in the result — `build.py`'s own `windows` path says
  so directly. Those checks stay for a with-module build and are skipped, not deleted,
  for a stock one.

## The awkward question this raises about identifiers

[0023] settled that a usermod identifier is `{tag}-{arch}` or `{tag}-{port}-{board}` —
it names what was built, and the module is implied by the config that produced it. A
no-module build produces an artifact at the same identifier as a with-module build,
from the same tag and target, and the two are not interchangeable. Nothing in the
identifier, the output path, or the `package.json` would distinguish them.

Whether that matters depends on whether no-module builds are ever *published* or only
ever run as a check. If it is only ever a check — which is the assumption this record
starts from — the collision is harmless and needs no identifier change. If a stock
firmware is ever a deliverable, it needs its own answer, and that answer should not be
invented in a hurry when someone first wants one.

## Not decided here

- The exact spelling of the flag and of the config value it mirrors. Both, not one --
  see the decision above.
- Whether it should run in `build-examples.yml` across every port on every push, or on
  the schedule leg only. It is the cheapest build in the project per port and the
  broadest in coverage, which argues for often.

[0016]: 0016-usermod-user-c-modules-dir-vs-cmake.md
[0021]: 0021-usermod-execution-central-value.md
[0023]: 0023-usermod-identifier-scheme-config-output.md
[0051]: 0051-usermod-identifiers-have-no-version-axis.md
[0053]: 0053-usermod-ports-without-a-build-driver.md

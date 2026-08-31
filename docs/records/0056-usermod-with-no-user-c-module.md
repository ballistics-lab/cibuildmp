# 0056 — building upstream MicroPython through the usermod path with no user C module at all

- Status: Accepted in intent, open in shape. Wanted, and the driver work is settled:
  the five port drivers stop passing `USER_C_MODULES=` unconditionally, the mount list
  is rebuilt rather than shortened, `verify_output()`'s module-symbol assertions become
  conditional. **Undecided: how absence is expressed** — two options below, both from
  the user, neither chosen. Nothing built yet. Upstream needs nothing either way
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

- a way to express absence in config — not the empty string, for the `Path("")` reason
  above (settled below as `no-user-c-modules = true`),
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

## Option A — `no-user-c-modules`, mutually exclusive, an error when combined

The user's first proposal. The spelling would be `no-user-c-modules = true` — kebab-case,
matching every other key in this config (`user-c-modules`, `extra-make-args`,
`pre-build-command`) rather than the snake_case it was first sketched in. It would follow
the same three-form pattern every option here has: the TOML key, a `--no-user-c-modules`
CLI flag, and the `CIBMP_NO_USER_C_MODULES` env override `Options.get()` already builds
for free.

**It would be mutually exclusive with `user-c-modules`, and giving both a load-time
error**, not a precedence rule. That is the part worth arguing rather than transcribing.

A precedence rule has to pick a winner, and either choice is silently wrong for somebody:
`no-user-c-modules` winning means an explicitly written `user-c-modules` is ignored;
`user-c-modules` winning means an explicitly written `no-user-c-modules` is. Both are the
shape of bug this project keeps catching the hard way — [0048] is an entire record about
a misplaced key being silently ignored, and [0044]'s own "a declared cell with an empty
value is a real target" paragraph is the same argument about a different table. An error
cannot be silently wrong. There is also no sensible reading of "build with no modules,
using these modules", so nothing is lost by refusing it.

### The check has to test *explicitly set*, not *has a value*

The trap in implementing it: `user-c-modules` always has a value, because it defaults to
`"."` ([0051]'s ninth addendum). A naive `if user_c_modules and no_user_c_modules: error`
would fire on every single use of the flag.

`Options.get()` already gives the distinction, because `default=` is just the bottom
layer of its `default -> global -> family -> env -> env(platform) -> extra_layers`
cascade: calling it **without** a `default=` returns `None` when the key is set at no
layer at all. So the rule is

```python
# not opt("user-c-modules", DEFAULT_USER_C_MODULES) -- that can never be None
if opt("no-user-c-modules") and opt("user-c-modules") is not None:
    raise UsermodConfigError(...)
```

and it belongs at load time with the rest of the config validation, not in a driver.

### `manifest` does *not* need the same treatment

The neighbouring key looks like it has the identical problem and does not. `manifest` is
already `str(opt("manifest", ""))`, so its default *is* absence: `FROZEN_MANIFEST=` goes
out empty on every build that does not set one, and that already works. Nothing to
express, no second flag.

The asymmetry is entirely about the default — `"."` versus `""` — and saying so is the
clearest way to explain why one key needs a flag and its neighbour does not.

It also means **a stock MicroPython build with a frozen Python manifest is a legitimate
combination**, not a contradiction: no C modules, some pure-Python ones.
`no-user-c-modules` must not imply `manifest = ""`.

### Which surfaces a mount that only works by accident today

`mounts=[mpy_dir, Path(opts.user_c_modules)]` is the whole mount list. **The manifest file
is not in it.** It reaches the container only because `user-c-modules` defaults to `"."`,
so the project root gets bind-mounted and the manifest happens to be underneath.

Drop that mount for a stock build and `FROZEN_MANIFEST=usermod/manifest.py` names a path
that does not exist inside the image — the legitimate combination above breaks on the
first port that tries it. So the driver change is not "drop the second mount" but "mount
what is actually needed": the module directory when there is one, the manifest's own
directory when there is a manifest, and `mpy_dir` always.

### The driver work, which is the same under either option

- **Five driver edits.** Each of the five `build.py` paths passes
  `f"USER_C_MODULES={opts.user_c_modules}"` unconditionally; each becomes conditional,
  emitting `USER_C_MODULES=` (or omitting the argument) when no module is configured —
  whichever of the two options above ends up defining "not configured".
- **Never `Path("")`.** It is `Path(".")`, which would bind-mount the project root for no
  reason — exactly the silent-wrong-thing this record exists to avoid.
- **`verify_output()` becomes conditional.** Several paths currently assert that a real
  user module's symbols are present in the result — `build.py`'s own `windows` path says
  so directly. Those checks stay for a with-module build and are skipped, not deleted,
  for a stock one.


## Option B — drop the default instead of negating it

Raised by the user straight after the first proposal, and it deserves the space
because measuring its cost changed what the cost is. The proposal: make
`user-c-modules` genuinely optional — no `DEFAULT_USER_C_MODULES = "."` — so **unset
means no user C modules**, and no flag exists at all. Nothing to be mutually exclusive
with, no validation rule, one key with one meaning.

### The consistency argument is the strong one

`manifest` already works exactly this way: `str(opt("manifest", ""))`, unset is absence,
and it has never needed a flag. Two neighbouring keys of the same shape currently behave
differently for no reason a reader could derive — one defaults to a real value, the other
to absence. Dropping the default makes them the same key twice, which is the outcome that
needs no documentation at all.

Against the flag: `no-user-c-modules` is a boolean whose entire job is to negate a default
that could simply not exist. That is a real smell, and the record should say so rather
than defend the decision it happens to have reached first.

### The blast radius, measured rather than assumed

The obvious objection is that dropping a default silently changes behaviour for every
config relying on it. Counting who that actually is:

- **`examples/template/cibuildmp.toml`** — this repo's own, and its comment says so in as
  many words: "No `[usermod]` table here, deliberately … `user-c-modules` defaults to `.`
  … the whole project root, which is exactly what every port below already wants".
- **`a7p/micropython/cibuildmp.toml`** — sets neither key, but is natmod-only
  (`module-dir = "natmod"`), so `user-c-modules` never applies to it.
- **`micropython-bclibc`, `micropython-wasm3`** — no root `cibuildmp.toml` at all. Their
  usermod builds still go through the `build-usermod-*` composite actions.
- **The `build-usermod-*` composite actions themselves** — they never reach
  `usermod/options.py`. Each calls `make USER_C_MODULES=…` directly from its own input,
  with its own separately-documented default ("Defaults to the workspace root",
  "Defaults to `usermod/micropython.cmake`"). `DEFAULT_USER_C_MODULES` is invisible to
  them.

So exactly **one** config in existence depends on this default, and it is in this
repository. That is not the migration the objection assumes; it is a one-line edit
(`user-c-modules = "."`) to a file that already explains why it wants that value.

Worth noting in passing: those composite-action defaults are a second, independent
implementation of the same convention, documented separately and drifting on their own —
the same two-implementations shape [0038] records for `build-natmod`.

### The one real risk, and what to do about it

A config that relied on the default would, after the change, build stock MicroPython and
*succeed*. `verify_output()` catches this on at least some ports — `build.py`'s own
`windows` path asserts a real user module's symbols are present — but "at least some" is
not a guarantee, and a green build that quietly contains none of the user's code is worse
than any error.

So if this route is taken, **absence should be a load-time error for one release**, with
a message naming both ways forward, rather than silently meaning "none" from day one.
After that the error can be dropped and absence can simply mean absence. With a blast
radius of one file the transition is nearly free, and [0038]'s repin — which has to touch
those repos anyway — is the natural moment.

### What survives either way

[0051]'s ninth addendum chose `"."` for a real reason: `src/` is a sibling of `usermod/`,
so `USER_C_MODULES` has to reach one level above `usermod/` to see the shared core at all.
That reasoning is untouched. It stops being an implicit default and becomes a line
`examples/template` writes down — which arguably documents the layout better than a
default ever did.

### Where this record's own guess lands, which is not a decision

**No choice has been made — the user has explicitly left this open, and both options above
are on record precisely so it can be made later on the evidence rather than on whichever
was written first.**

For what it is worth, the reading here leans to Option B: it removes a key and a
validation rule instead of adding them, it makes `user-c-modules` and `manifest` behave
identically, and the migration it was assumed to require turns out to be one line in this
repository. The counter-case for Option A is that it changes nothing for anyone and needs
no transition at all, which is worth real money if the counting above ever turns out to
have missed a config.

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

- **Option A or Option B** — how absence is expressed. Explicitly left open by the user;
  both are written up above with their evidence so the choice can be made on that rather
  than on which was proposed first.
- Whether this runs in `build-examples.yml` across every port on every push, or on the
  schedule leg only. It is the cheapest build in the project per port and the broadest
  in coverage, which argues for often.

---

## Addendum, 2026-08-29 — the core claim confirmed live, by accident

**"Empty is a clean no-op everywhere" was a claim read off upstream source. [0067]
watched it happen for real, unintentionally**, migrating `micropython-wasm3`
([0038], M5): a wrong-but-non-empty `user-c-modules` value made `py/py.mk`'s own
`$(wildcard $(USER_C_MODULES)/*/micropython.mk)` resolve to an empty list, and the
`foreach` over that empty list did exactly what this record's own upstream reading
said an empty `USER_C_MODULES` would do — nothing, silently, leaving a stock port
build that reported success. Not the scenario this record analysed (that was a
genuinely empty/absent value, not a non-empty one whose glob happens to match
nothing), but the same mechanism and the same observable result: a real, unplanned
live data point for the premise Option A and Option B both rest on, not a decision
between them.

It is also the sharpest illustration yet of this record's own closing worry — "a
green build that quietly contains none of the user's code is worse than any
error". [0067] closes the *specific* trap that produced it (a flat single-module
`usermod/` resolving to the wrong make-side value), not the general one this record
describes (no configured value at all); Option A/Option B are still both open, and
still worth deciding on the evidence above rather than on whichever gets written
first.

[0016]: 0016-usermod-user-c-modules-dir-vs-cmake.md
[0021]: 0021-usermod-execution-central-value.md
[0023]: 0023-usermod-identifier-scheme-config-output.md
[0038]: 0038-m5-adopt-in-three-repos.md
[0044]: 0044-unix-native-images-landed.md
[0048]: 0048-build-skip-live-in-opposite-tables.md
[0051]: 0051-usermod-identifiers-have-no-version-axis.md
[0053]: 0053-usermod-ports-without-a-build-driver.md
[0067]: 0067-user-c-modules-flat-shape-autodetect.md

## Correction, 2026-08-31 — "five port drivers" in one file is two records old

The opening paragraph says "the five port drivers" and cites
`usermod/build.py`. There are **six** drivers and that file no longer exists:
[0061] split it into one `usermod/build_<port>.py` per port, and [0060] added
`rp2` as the sixth. The substantive claim is unchanged and was re-checked
against each of the six — all pass `USER_C_MODULES=` unconditionally, which is
what this record is about.

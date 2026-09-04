# 0057 — more than one module per build, in both modes

- Status: Implemented (closed 2026-09-04 — see addendum). Both halves decided by the
  user. natmod: one config per module. usermod: `user-c-modules` stays a single path,
  and a consumer expresses N modules in their own layout — subdirectories on Make
  ports, an aggregating `micropython.cmake` that `include()`s the others on CMake
  ports. Documentation in both cases; no new mechanism in either

## It has come up twice before, never as its own decision

Worth stating first, because the answer is partly already on record:

- **[0016] settled the upstream mechanism, precisely, against a real `v1.28.0`
  checkout.** On the make side `py/py.mk` globs
  `$(wildcard $(USER_C_MODULES)/*/micropython.mk)` — **one directory already holds
  several modules side by side**, one per subdirectory. On the CMake side
  `py/usermod.cmake` resolves one entry to exactly one `micropython.cmake` (appending
  `/micropython.cmake` when handed a directory). That record's own words: the real
  difference "is not file-vs-directory, it's *how many modules one entry can resolve
  to*".
- **[0056] then found the half [0016] left unsaid**, reading both files again for its
  own question: `USER_C_MODULES` is *itself a CMake list* —
  `foreach(USER_C_MODULE_PATH ${USER_C_MODULES})` — so a CMake port is not
  structurally single at all. It is single *per entry*, and takes N entries. The make
  side is the genuinely single-valued one: its existence check appends `/.` and every
  `SRC_USERMOD_PATHFIX_*` line uses the value as one `patsubst` prefix, so it cannot
  be a list even in principle.
- **[0014] found a real second module in the wild** while designing per-identifier
  packages: `micropython-bclibc`'s own `ffimod/`, which builds a native `.so` plus
  facade `.py` files alongside the `natmod/` module that repo already publishes. It is
  not published today, which is why the shape was designed against
  `examples/template` instead.

So multi-module is neither hypothetical nor unexplored. What has never been decided is
what *cibuildmp* does about it.

## The two modes are not asking the same question

This is the thing to get right before designing anything, because a single "support
multiple modules" feature would be two features wearing one name.

**usermod is N modules → 1 artifact.** Every module links into the same firmware or
binary. There is one output per identifier no matter how many modules went in, so
nothing about identifiers, output layout or `package.json` is disturbed. The whole
question is *how a config names more than one*, and upstream has already answered it
twice over, differently in each build system: point at a parent directory and let
`py/py.mk` glob its subdirectories (Make ports), or pass a list — `USER_C_MODULES`
is a CMake list, per [0056]'s own reading — and optionally let one entry's
`micropython.cmake` `include()` the others (CMake ports). Upstream's own
`examples/usercmodule/micropython.cmake` is exactly that aggregator, which is why
[0054]'s fixture runs straight into this record.

**natmod is N modules → N artifacts, per architecture.** Each module is its own `.mpy`.
This collides with invariants that are load-bearing:

- `collect_output()` looks for exactly one `.mpy` under `build/<arch>*/` and
  **deliberately refuses an ambiguous two-`.mpy` result** — [0038] records that refusal
  firing correctly for real, against `micropython-wasm3`'s own `dist:` leaving an
  intermediate behind.
- The identifier grammar `mpy{abi}-{tag}-{arch}` has no module axis at all.
- [0014]'s per-identifier `package.json` assumes one artifact plus arch-independent
  companions.

Note what is *not* a problem on the natmod side: a module built from several source
files, including mixed `.c` and `.py`, is already handled entirely by
`dynruntime.mk`'s own `SRC`/`SRC_MPY` merge — [0014] says so explicitly, and [0002]
puts it out of cibuildmp's scope on purpose. "Multiple modules" here means multiple
*outputs*, not multiple inputs.

## The natmod decision: one config per module, and documentation

**Decided by the user, directly: natmod's N-modules question is resolved by
documentation and by splitting into a config per module.** No new mechanism, no change
to the identifier grammar, no change to `collect_output()`.

Concretely, a project with two natmod modules gives each one its own directory with its
own config, and runs cibuildmp once per module -- the `package-dir` input
`build-examples.yml` already passes for `examples/template` and `examples/wasm2mpy` is
exactly this knob, and those two are already a working demonstration of it: two modules,
two configs, two invocations, two independent `mpyhouse/` trees, in one repo. What was
missing was never the mechanism. It was anyone saying this is the supported answer
rather than a workaround.

Three things follow, and all three are improvements rather than costs:

- **`collect_output()`'s refusal of an ambiguous two-`.mpy` result stops being a
  limitation and becomes the guard for this decision.** A config that finds two modules
  is a mis-scoped config, and [0038] records that refusal already firing correctly for
  real against `micropython-wasm3`'s own leftover intermediate. Nothing to relax.
- **It fits [0014] exactly as designed.** Per-identifier packages make the *URL* the
  selector; one module per config means one `mpyhouse/` tree per module, so a consumer
  installs each module by its own URL. Two modules were never one package in that
  scheme, and now they are not one config either.
- **The identifier grammar stays three-axis.** [0051] and [0052] both spent real effort
  flattening it; a `<module>` axis would have been a fourth, multiplying identifier
  count by module count for a distinction the directory layout already carries.

### What the documentation actually has to say

This is the whole remaining work on the natmod side, and it is prose, not code:

- One natmod module per config, one config per directory -- stated positively, in
  `README.md`, not inferred from the absence of a multi-module feature.
- `module-dir` is **not** the mechanism for this. It names where one module's Makefile
  lives, and pointing it at a parent of several is the mis-scoping the guard above
  catches.
- Output is per module by construction: N modules produce N `mpyhouse/` trees, and
  composing or publishing them is the consumer's own workflow, the same way running
  cibuildmp N times is.
- The one thing genuinely given up: nothing ties the N results together into a single
  artifact set. `micropython-bclibc`'s own `ffimod/` ([0014]) is the real case on
  record, and it wants a `.so` beside a `.mpy` -- two different things, which two
  configs describe better than one ever would.

### The two options this rejects

- **A module axis in the identifier** (`mpy6.3-v1.29.0-x64-<module>`) -- rejected for
  the flattening reason above. It would have been defensible: [0015] put `ARCH_FLAGS`
  in the identifier for the same "real distinctions belong in the name" argument. The
  difference is that `ARCH_FLAGS` distinguishes two builds of *one* module, which
  nothing else in the layout records, whereas the module is already the directory.
- **One identifier, several artifacts** -- rejected outright. It is the smallest
  identifier change and the largest output-contract change, and it gives up the "one
  identifier, one artifact" property that makes [0014]'s scheme simple to reason about.

## The usermod decision: the same answer, reached through CMake `include`

**Also decided by the user, and it is the same shape as the natmod half: documentation,
not mechanism.** `user-c-modules` stays exactly one path. A consumer with N modules
expresses the N in their own layout, and both build systems already have a way:

- **Make ports** — point at the parent directory. `py/py.mk` globs
  `$(wildcard $(USER_C_MODULES)/*/micropython.mk)` and includes every subdirectory that
  has one. Nothing to write; the layout *is* the mechanism.
- **CMake ports** — point at an aggregating `micropython.cmake` that `include()`s the
  others. Upstream ships the reference implementation of exactly this file:
  `examples/usercmodule/micropython.cmake`, sitting above `cexample`, `cppexample` and
  `subpackage`.

This closes the question [0056]'s reading had reopened — whether `user-c-modules` should
become a list, since `USER_C_MODULES` is itself a CMake list. It should not, and the
reason is the better one:

- **The aggregator is the consumer's own build file, not one cibuildmp writes.** That is
  the line [0002] draws and the whole reason a list looked expensive in the first place.
  Reaching the same result through a file the consumer already controls costs cibuildmp
  nothing and keeps the delegation intact.
- **One config key keeps one meaning.** A list would have worked on CMake ports and been
  rejected on Make ports, so the key would mean different things per build system — the
  exact divergence [0052] spent a whole record removing from the config surface.
- **Upstream documents both forms already.** cibuildmp does not have to invent a
  convention, only point at one, which is what makes this a documentation task.

### What the documentation has to say

- `user-c-modules` is one path, always. It is a directory on Make ports and a directory
  or a `micropython.cmake` on CMake ports — [0016]'s own distinction, now with a reason
  a reader can act on.
- N modules on a Make port: put them side by side under that directory, one
  `micropython.mk` each. Upstream's glob does the rest.
- N modules on a CMake port: write one `micropython.cmake` that `include()`s the others
  and name it. Point at `examples/usercmodule/micropython.cmake` as the worked example.
- The asymmetry is upstream's, not cibuildmp's, and saying so is part of the job — a
  reader who hits it otherwise assumes cibuildmp imposed it.

### How it gets tested, and the trap the two forms hide

Both forms are exercised by the same tree — upstream's own `examples/usercmodule`, which
is [0054]'s fixture. Reading the two files side by side turns up something the
documentation has to say out loud, because it will bite otherwise.

**The CMake side is an explicit list, and upstream's own aggregator is incomplete.**
`examples/usercmodule/micropython.cmake` is, in full, two `include()` lines:

```cmake
include(${CMAKE_CURRENT_LIST_DIR}/cexample/micropython.cmake)
include(${CMAKE_CURRENT_LIST_DIR}/cppexample/micropython.cmake)
```

`subpackage` has its own `micropython.cmake` and **is not in that list**. Pointing a
CMake port at this file builds two of the three modules.

**The Make side is a glob, and there is no top-level `micropython.mk` at all** — there is
nothing for one to do. `py/py.mk` globs `*/micropython.mk` under the directory it is
given, so pointing a Make port at `examples/usercmodule/` builds **all three**,
`subpackage` included, with no file listing them anywhere.

So the same directory, named the same way in the same config, yields a different module
set per build system: three on Make ports, two on CMake ports. That is not a bug in
either build system — opt-out-by-glob and opt-in-by-list are both defensible — but it is
exactly the kind of asymmetry a consumer will read as a cibuildmp inconsistency. The
documentation has to name it, and [0054]'s fixture is what proves the description is
accurate rather than plausible.

It also settles a detail [0054] left open: if that fixture is to build the same three
modules everywhere, the vendored copy needs a third `include()` line added to the
aggregator — a one-line, clearly-marked local change to a vendored file, which is its own
small argument for vendoring rather than reaching into the resolved checkout.

**Neither form has ever been tested by this project** — `examples/template` has exactly
one usermod module, so nothing here has ever run.

`manifest` needs nothing: [0017] already merges several frozen manifests into one
`FROZEN_MANIFEST`, so the Python side of multi-module was built long before the C side
had an answer.

## Not decided here

Nothing. Both halves are decided above; what remains in each is prose and, for the
usermod half, [0054]'s fixture to prove the worked example actually builds.

## Addendum, 2026-09-04: both remaining items closed

Both items this record's own "Not decided here" section named as outstanding are done:

- **The usermod fixture builds, for real, across all six ports.** [0069], written
  independently to give [0054]'s scoping a real CI slice, turned out to be this
  record's own proof: `examples/usercmodule/micropython.cmake` is not a one-line patch
  to a vendored copy as this record originally proposed — [0054]'s own "no vendoring"
  call still holds — it is a fixture-owned file that `include()`s upstream's aggregator
  unmodified and adds the one line for `subpackage`, resolved against the checkout
  `sources.fetch_micropython()` already fetches. `examples/usercmodule/smoke_test.py`
  then imports and calls into all three modules for real. [0069]'s own status line:
  "Implemented — widened to all six ports 2026-08-31, all green."
- **Both documentation sections landed in `README.md`**, under "More than one module":
  natmod's one-module-per-config rule (pointing at
  [`examples/template`](../../examples/template) and
  [`examples/wasm2mpy`](../../examples/wasm2mpy) as the two-modules-two-configs
  demonstration this record already named), and usermod's Make-glob-vs-CMake-`include()`
  convention (pointing at `examples/usercmodule/micropython.cmake` above), including the
  asymmetry paragraph this record's own "trap" section said had to be named out loud.

[0002]: 0002-delegate-compile-own-environment.md
[0014]: 0014-mip-package-per-identifier.md
[0015]: 0015-rv32imc-arch-flags-identifier.md
[0016]: 0016-usermod-user-c-modules-dir-vs-cmake.md
[0017]: 0017-usermod-frozen-manifest-merge.md
[0023]: 0023-usermod-identifier-scheme-config-output.md
[0038]: 0038-m5-adopt-in-three-repos.md
[0051]: 0051-usermod-identifiers-have-no-version-axis.md
[0052]: 0052-config-is-a-tree-not-a-selector-matrix.md
[0054]: 0054-usermod-example-from-upstream-usercmodule.md
[0056]: 0056-usermod-with-no-user-c-module.md
[0069]: 0069-upstream-usercmodule-narrow-ci-slice.md

# 0072 — a `{micropython}` placeholder for natmod, and a real `examples/natmod` slice

- Status: Implemented (one module, two arches -- not the full eleven-module survey [0055] scoped)
- Related: [0054], [0055], [0069], [0071]

## What this closes, and what it deliberately does not

[0055] found that cibuildmp's natmod contract (`make ... dist`, output collected from
`build/<arch>*/*.mpy`) does not fit upstream's own `examples/natmod/*` modules
(`py/dynruntime.mk` only ever defines `all`, which drops `$(MOD).mpy` straight into
module-dir with no arch-scoped subdirectory at all) -- confirmed there directly against a
real checkout, not assumed. It named three ways to close that gap and picked none of
them. This record picks **option 2** ("`make-target = "all"` plus a fallback in
`collect_output()`") for exactly one module, `features0` -- [0055]'s own "deliberately
minimal ... would prove the contract" pick -- and wires a real, narrow CI slice around
it, the natmod mirror of [0069]'s own usermod slice. The other ten upstream modules,
`btree`'s own submodule requirement, and the arch-flags variant risk named below all stay
open -- widen only if this slice finds something, [0054]'s own rule.

## The mechanism: two small core changes, everything else in the fixture's own config

**`{micropython}` in `module-dir`** (`platforms/natmod/__init__.py`, `build_all()`'s own
per-target loop) -- the exact mirror of [0071]'s `user-c-modules` placeholder, substituted
with `mpy_dir.as_posix()` at the one point in the loop `mpy_dir` is already real and
fetched. Lets `module-dir` name a path *inside the pinned checkout* directly --
`{micropython}/examples/natmod/features0` -- with no vendored copy of upstream's own file,
the same "no vendoring" argument [0054] made and [0071] mechanised for usermod.

Two things this substitution does **not** reach, both left this way on purpose, matching
[0071]'s own scope note: `build_all()`'s own pre-loop `build/` cleanup (its docstring:
"One rmtree per distinct module_root, before anything builds") runs before any tag is
fetched, so a `{micropython}`-templated `module-dir` is still the literal, unresolved
placeholder string at that point -- the rmtree targets a path that cannot exist and is a
silent no-op (`ignore_errors=True`). And `--dry-run`'s own `_plan_line()` print shows the
raw placeholder too, for the same reason: no real checkout to substitute with during a
preview. Neither is a bug; both are consequences of `mpy_dir` only being knowable once a
real build actually starts.

**A fallback in `collect_output()`** (`platforms/natmod/build.py`): once the arch-scoped
`build/<arch>*/*.mpy` glob comes up empty, try a flat `module_root.glob("*.mpy")` instead.
Exactly one candidate either way is still required -- an upstream module compiling `.py`
sources too would drop intermediate `.mpy` files under `$(BUILD)/`, not module_root
itself, so the flat glob only ever sees the one real merged artifact. A project already
using this project's own `dist` contract sees the exact same behaviour and the exact same
error text it always did; the fallback is only ever tried second.

## The one real, verified correction to [0055]'s own citation

[0055] cited a checkout at `micropython@e0e9fbb17` (v1.28.0) for `BUILD ?= build`, "one
shared path for every architecture" -- accurate for that checkout, confirmed by walking
back through a real clone's full history, not re-quoted from the record. It is no longer
accurate for the newest pinned tag: `531c80dc0` ("tools/mpy_ld.py: Do not share build
directory across architectures"), landed between `e0e9fbb17` (2026-04-06) and `v1.29.0`
(`0fd6c573e`, 2026-08-24) -- confirmed `git merge-base --is-ancestor` both ways, and by
reading `v1.29.0`'s own `py/dynruntime.mk` directly -- changed the default to
`BUILD ?= build-$(ARCH)`. Built and verified locally against that real tag (no Docker
available in this session; mpy-cross and `features0` for `x64` built on the bare host,
`elftools`/`ar` from cibuildmp's own venv on `PYTHONPATH`): `all` drops `features0.mpy` in
module-dir exactly as described, `build-x64/` is genuinely arch-scoped, and
`collect_output()`'s new fallback plus `verify_output()` both pass against the real,
unmodified output -- no synthetic fixture involved for this part.

That fix does not reach every axis [0055] named, though: `BUILD` is scoped by `$(ARCH)`
only, never by `$(ARCH_FLAGS)` -- confirmed by reading the same file -- so two rv32imc
arch-flags variants (`arch-flags = ["", "zba,zcmp"]`) still share one `build-rv32imc/`
directory on every tag, `v1.29.0` included. Traced through the make DAG by hand (no
riscv toolchain in this session to build it for real): `CFLAGS_ARCH` for rv32imc does not
vary with `ARCH_FLAGS` at all -- only the final `mpy_ld.py --arch-flags` link step does --
so the `.o` never goes stale, but `$(BUILD)/$(MOD).mpy`'s own link rule can see its
prerequisite unchanged and skip relinking for the second variant entirely, silently
keeping the first variant's header. `verify_output()` (already run on every real build,
`build.py`) is the actual backstop here: it checks `actual_flags != target.arch_flags`
and fails loudly rather than shipping the mismatch. `features0` carries no `arch-flags`
config, so this fixture does not exercise it -- named here so whoever widens this fixture
to rv32imc does not have to re-derive it.

## Why `pre-build-command`, not a third core-code change

`examples/natmod/cibuildmp.toml` sets `pre-build-command = "rm -rf features0.mpy build
build-*"`, run inside the image before every single arch's `make`. Not needed for the
specific pair this CI slice builds (`x64`+`armv7emsp`, both real, distinct arches, on
`v1.29.0` -- the fix above already isolates them by directory name) -- kept anyway because
the fixture's own `module-dir`/`make-target` are general config, not scoped to one tag,
and every tag before `531c80dc0` (`v1.20.0` through `v1.28.0`, all still in
`build-platforms.toml`'s own pinned range) still shares one unscoped `build/` across every
arch the way [0055] originally described. Kept in the fixture's own config, not a third
`natmod/build.py` change, for the same reason [0054]'s wasm32 override carries its own
`CXX=em++` fix rather than teaching `usermod/build.py` about emsdk: an upstream quirk's
workaround belongs with the fixture that depends on it, not the generic contract every
other project's config also goes through.

## The CI slice

`.github/workflows/test-upstream-natmod.yml` -- one job, building **two** arches
(`x64`, `armv7emsp`) for the same tag in the same invocation, deliberately not two
single-arch jobs: a job that only ever builds one arch at a time would never exercise the
exact risk this whole record is about. No `docker/setup-qemu-action` needed, unlike
[0069]'s rp2/esp32/qemu legs: `dockerrun.platform_for()` resolves every non-`unix` port,
natmod included, to a flat `linux/amd64` -- confirmed directly against that function's own
source -- so every natmod toolchain image already runs native on an `ubuntu-latest`
runner regardless of which arch's cross-compiler it carries.

## Still open

- The other ten upstream modules. `btree` needs `sources.py` to initialise a git
  submodule cibuildmp's own checkout resolution does not touch today -- [0055]'s own
  "Two examples worth calling out" section has the detail, unchanged by this record.
- rv32imc arch-flags variants against this same fixture -- would exercise the
  `verify_output()` backstop described above for real, but `features0` alone does not
  need it and this record does not add it speculatively.
- Whether `build_all()`'s own pre-loop `build/` cleanup should learn to resolve
  `{micropython}` itself (fetching the newest selected tag early, before any group loop)
  -- would let it actually clean a templated `module-dir` between whole invocations too,
  not just between arches within one. Not needed for this fixture (`pre-build-command`
  already covers the within-invocation case entirely); left for whoever hits the
  cross-invocation gap for real, the same way [0071] left an equivalent natmod gap for
  this record to eventually pick up.

[0054]: 0054-usermod-example-from-upstream-usercmodule.md
[0055]: 0055-natmod-example-from-upstream-natmod.md
[0069]: 0069-upstream-usercmodule-narrow-ci-slice.md
[0071]: 0071-micropython-placeholder-in-user-c-modules.md

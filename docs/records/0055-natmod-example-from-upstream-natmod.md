# 0055 — an `examples/` natmod fixture built on upstream's own `examples/natmod`

- Status: Implemented ([0072] implemented option 2 for all eleven modules; see this
  record's own second addendum for the two named risks below that turned out not to be
  real gaps)
- Related: [0002], [0014], [0049], [0072]

## The idea, and what checking it immediately turned up

MicroPython ships eleven natmod modules of its own — read from a real checkout
(`micropython@e0e9fbb17`), `examples/natmod/` is `btree`, `deflate`, `features0`
through `features4`, `framebuf`, `heapq`, `random`, `re`. Pointing cibuildmp at them
looks like the cheapest possible breadth: eleven real modules, written by the people
who wrote `py/dynruntime.mk`, versus the one module this project wrote for itself.

It is not cheap, and the reason is worth recording even if the fixture never gets
built. **cibuildmp's natmod contract does not fit upstream's own natmod modules.**

`py/dynruntime.mk` declares exactly two targets:

```make
.PHONY: all clean
all: $(MOD).mpy
```

and defaults `BUILD ?= build`. A stock example Makefile (`features0/Makefile`, in full)
sets `MOD`, `SRC`, `ARCH` and includes it — nothing else.

cibuildmp runs `make -C <module-dir> ARCH=<arch> MPY_DIR=<dir> PYTHON=python3
<make-target>` with `make-target` defaulting to `dist`, and then
`collect_output()` globs `build/<arch>*/*.mpy` for exactly one result. Upstream's
examples satisfy neither half: there is no `dist` target to call, and `all` leaves
`$(MOD).mpy` in the module directory while `BUILD ?= build` is one shared path for
every architecture.

So the `dist`-target-plus-`build/<arch>*/` convention that
`src/cibuildmp/platforms/natmod/build.py` calls "every natmod Makefile in the wild" is
in fact a **downstream** convention. It came from `micropython-native-ci`'s own
workflow (`path: natmod/build/${{ matrix.arch }}*/`) and is shared by this project's
consumers because they were all written against that action. Upstream has never used
it. That is a real, if narrow, correction to [0002]'s framing.

## What a matrix-safe natmod Makefile actually needs

`examples/template/natmod/Makefile` is the evidence, and it is not short. Every guard
in it was added in response to a bug found by running the whole matrix in one tree —
which [0049] made the *normal* way to build natmod when it put the builds in a
container:

- `BUILD = .obj/$(ARCH)$(if $(ARCH_FLAGS),+$(ARCH_FLAGS))/o` — scoped by arch *and* by
  arch-flags. Without the first half, a second `make ARCH=<other>` sees the first
  arch's objects as up to date and silently ships the first arch's binary. Without the
  second, [0015]'s `rv32imc` arch-flags variants do the same to each other.
- The trailing `/o` — so a `SRC` entry containing `..` (`../src/template_core.c`)
  still lands under `$(ARCH)`, instead of `..` eating the arch component and producing
  one shared object linked into every arch. That one surfaced as
  `LinkError: incompatible arch`.
- A `dist` target that `rm -f $(MOD).mpy` before recursing into `all` — because
  `$(MOD).mpy` is one fixed filename that dynruntime.mk does not scope by arch at all,
  so a stale one from a previous arch reads as up to date.

Upstream's examples carry none of these guards, and do not need to: they are built one
arch at a time, by hand, from a checkout, which is what their `ARCH ?= x64` default is
for. The guards are a consequence of cibuildmp's own model, not of anything wrong
upstream.

## Three ways to actually do it, and what each one costs

1. **A shim Makefile per example** that sets a scoped `BUILD`, adds a `dist` target and
   includes upstream's. Cheapest to write, and the fixture then tests cibuildmp's real
   contract honestly — but it means the vendored module is no longer upstream's file,
   which is most of the point of vendoring it.
2. **`make-target = "all"` plus a fallback in `collect_output()`** — accept
   `$(MOD).mpy` at module root when nothing matches `build/<arch>*/`. The `make-target`
   half already exists as a config key; the collect half has no knob. This makes
   cibuildmp fit upstream rather than the other way round, and it is the option that
   would let a stock module build unmodified. It also inherits every stale-artifact
   bug the template Makefile documents, so it would need the matrix serialised or the
   tree cleaned between arches.
3. **Document the contract as requiring `dist`** and treat upstream's examples as out
   of scope. Honest, cheap, and gives up the breadth entirely.

This record does not choose. It exists so the choice is made deliberately rather than
discovered halfway through vendoring eleven Makefiles.

## Two examples worth calling out before anyone starts

- **`btree` needs a submodule.** Its Makefile pulls sources from
  `$(MPY_DIR)/lib/berkeley-db-1.xx`, which is a git submodule of the MicroPython
  checkout, not part of a plain clone. cibuildmp's own checkout resolution
  (`sources.py`) would have to initialise it, or `btree` gets skipped.
- **`btree` also names its module `btree_$(ARCH)`**, so the output filename varies with
  the architecture. Harmless for `collect_output()`'s one-`.mpy` glob, but it breaks the
  assumption that an identifier's artifact name is arch-independent — which
  [0014]'s per-identifier `package.json` and `[publish] extra-files` both lean on.

## Not decided here

- Whether the eleven are vendored or built from the resolved MicroPython checkout.
  [0054] argues for vendoring on the grounds that a fixture whose content moves with
  the tag under test cannot distinguish upstream drift from a cibuildmp regression;
  the same argument applies here and is stronger, because these Makefiles are exactly
  the thing under test. **Stale as of [0054]'s own later flip — see this record's own
  addendum.**
- Whether all eleven, or a chosen few. `features0`–`features4` are deliberately
  minimal and would prove the contract; `btree`/`deflate`/`framebuf`/`re` drag in real
  MicroPython internals and would prove considerably more.

## Addendum, 2026-08-31 — the vendoring citation above is stale, and a real mechanism now exists for option 2

[0054] later reconsidered and flipped its own vendoring call (its own "Vendoring policy —
reconsidered, flipped" section): reaching straight into the checkout `sources.
fetch_micropython()` already resolves is *more* pinned than a hand-vendored copy, not less
— a vendored tree is a second, independent pin nothing watches, exactly the staleness shape
[0046] exists to name. The bullet above cites [0054]'s original, superseded position; left
as written per this project's own append-only convention, corrected here rather than
edited in place.

That flip, plus [0071] (a `{micropython}` placeholder in `user-c-modules`, substituted with
the pinned checkout's own real path before any build step runs — landed for usermod's own
identical fixture, [0069]), directly serves this record's own **option 2**
("`make-target = "all"` plus a fallback in `collect_output()`", "the option that would let a
stock module build unmodified"): a natmod equivalent of the same placeholder in `module-dir`
would let `examples/natmod`-style config point at `{micropython}/examples/natmod/<module>`
directly, no vendoring, the same way the four Make-port usermod overrides now do. Not
implemented here — [0071] is deliberately scoped to `usermod/orchestrate.py` alone (natmod's
own `options.py`/`build.py` are independent modules by design, "natmod must never import
usermod"), and this record's own three-way choice (shim Makefile / fit-upstream fallback /
document-and-descope) is still not made. Worth knowing before whoever picks this up reasons
from the now-stale vendoring citation above.

## Addendum, 2026-08-31 (second) — option 2 implemented, for all eleven modules

[0072] picked option 2 and landed it: a `{micropython}` placeholder for `module-dir`
(the natmod mirror of [0071]'s `user-c-modules` one) plus a fallback in
`collect_output()` for `py/dynruntime.mk`'s own `all` target. Wired around all eleven
upstream modules, not just `features0` -- `examples/natmod/cibuildmp.toml` defaults to
`features0`, `.github/workflows/test-upstream-natmod.yml`'s own `build-upstream-natmod`
matrix job overrides `CIBMP_MODULE_DIR` per module for the other ten -- with a real CI
slice covering every one, plus a dedicated multi-arch job (`x64`+`armv7emsp` for
`features0` in one invocation) exercising the exact collision scenario this record's own
guard survey was about. [0072]'s own addendum has the detail on all of it.

[0072] also corrects two things this record got wrong, not just optimistic. First, the
`BUILD ?= build` citation: upstream's `531c80dc0` scoped it to `BUILD ?= build-$(ARCH)`
between the checkout this record cited and the currently pinned `v1.29.0` -- real for the
tag this record checked, no longer true for the newest one. Second, `btree`'s own
submodule requirement was never actually a blocker for any tag this project's default
target selection can reach: `sources.fetch_micropython()` prefers the release tarball,
which already vendors `lib/berkeley-db-1.xx`, and only the tarball-less clone path (never
`natmod`'s own default) genuinely needs `micropython-submodules`. The rv32imc arch-flags
collision this record's own guard survey named is closed structurally, not just
backstopped, by the same `pre-build-command` that makes `all` safe to run across several
targets in one checkout at all -- see [0072]'s own addendum for why deleting the whole
build tree before every target removes the possibility outright rather than only
detecting it after the fact.

[0002]: 0002-delegate-compile-own-environment.md
[0014]: 0014-mip-package-per-identifier.md
[0015]: 0015-rv32imc-arch-flags-identifier.md
[0046]: 0046-pin-staleness-checker.md
[0049]: 0049-no-matrix-generation-archs-vocabulary.md
[0054]: 0054-usermod-example-from-upstream-usercmodule.md
[0069]: 0069-upstream-usercmodule-narrow-ci-slice.md
[0071]: 0071-micropython-placeholder-in-user-c-modules.md
[0072]: 0072-natmod-micropython-placeholder-and-upstream-natmod-ci.md

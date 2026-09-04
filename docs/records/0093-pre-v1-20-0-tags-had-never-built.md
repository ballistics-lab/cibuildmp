# 0093 — the nine ABI 5/6 tags had never built, and none of the three reasons was the gcc 15 diagnostic

Status: Implemented — all three fixed and live-verified the same session, `v1.12`/`v1.18`/`v1.19.1`
building end to end on both `natmod_host` and `arm_embedded` for the first time. One observation
left open at the bottom, and one thing this record explicitly does not claim.
Related: [0010], [0013], [0045], [0049], [0053], [0072], [0082], [0084], [0091]

## How this was found

[0082]'s own closing addendum corrected its scope from 9 affected tags to 18: the nine ABI 5/6 tags
(`v1.12`-`v1.19.1`) are real `natmod` rows in `build-platforms.toml`, and they are on the failing
side of the gcc 15 boundary it bisected, not outside it. Adding their `tag_cflags.toml` entries was
supposed to be a data diff. It was not: with `mpy-cross` finally compiling, the build reached three
further failures in a row, each one a *pre-`v1.20.0` upstream layout fact this project had
hardcoded the modern shape of*.

None of them is a regression, and none was introduced by [0084]/[0091]. They are the reason these
nine identifiers had never produced an artifact — including before gcc 15 existed. `--check`-style
machinery could not have caught them either: every one is a shape difference in a checkout that
only appears once a build actually runs.

## The three, in the order the build hit them

**1. `mpy-cross`'s own output path is a fact about the tag.** `py/mkrules.mk` links `all: $(PROG)`
— `mpy-cross/mpy-cross` — through `v1.19.1`, and `all: $(BUILD)/$(PROG)` —
`mpy-cross/build/mpy-cross` — from `v1.20.0` on. `py/dynruntime.mk`'s own hardcoded `MPY_CROSS =`
moves in the same release, so the two always agree with each other; what disagreed was
`sources.build_mpy_cross()` and `natmod/build.py`'s own `build_mpy_cross()`, both naming
`mpy-cross/build/mpy-cross` as a constant. The symptom is not a compile error but

```
cibuildmp: error: mpy-cross build reported success but .../mpy-cross/build/mpy-cross is missing
```

*after a clean, successful `LINK mpy-cross`* — the most confusing possible shape, since the build
genuinely did succeed. `natmod/build.py`'s own docstring was the source of the assumption and said
so honestly: "confirmed directly against v1.29.0's own dynruntime.mk, not assumed." It was right
about `v1.29.0` and wrong as a constant. Fixed with `sources.find_mpy_cross()` /
`mpy_cross_candidates()`, which take the first layout that exists rather than comparing tags — the
two candidates are disjoint in practice, a tag produces one or the other and never both.

**2. `MPY_SUB_VERSION` is a `v1.20.0`-and-later define.** `read_mpy_abi()` required both
`MPY_VERSION` and `MPY_SUB_VERSION` out of `py/persistentcode.h` and raised
`could not find MPY_VERSION/MPY_SUB_VERSION` otherwise. Upstream added the sub-version in the same
release that introduced ABI 6.1; before it the header carries `MPY_VERSION` alone, and the bare
`"5"`/`"6"` that yields is a real ABI — exactly what `build-platforms.toml`'s own `mpy` column
already records for those nine tags. **A test asserted the wrong behaviour**
(`test_read_mpy_abi_incomplete_header`, calling a `MPY_VERSION`-only header "incomplete"), which is
the [0045] pattern again: a test passing vacuously because nothing had ever exercised the input it
was wrong about. It is now two tests — one for the pre-`v1.20.0` shape, one for a header with no
`MPY_VERSION` at all, which is still an error.

**3. The example Makefile's object cache is scoped by arch, not by tag.**
`examples/template/natmod/Makefile` sets `BUILD = .obj/$(ARCH)…/o`, and its own header comment
already documents three separate instances of the bug that scoping exists to prevent (arch,
arch-flags, and the `..` that escaped the arch component). The tag is a fourth axis, and the one
that needs no manual meddling at all to hit: an object file depends on neither `MPY_DIR` nor the
tag, so **a single `--build 'mpy*-armv7emsp'` — five ABIs, one arch, one tree — silently links
every tag after the first against the first tag's objects**. It surfaces as

```
LinkError: .obj/armv7emsp/o/template.o: undefined symbol: mp_native_qstr_val_table
```

when the tags straddle a `py/` change, and as a quietly mislabelled `.mpy` when they do not. This
is precisely the invocation shape [0049] made normal, and precisely what [0091]'s own CI run did —
it went unnoticed there only because every pre-`v1.26.0` tag in that run failed at `mpy-cross`
before reaching the link step. `BUILD` now carries `$(notdir $(patsubst %/,%,$(MPY_DIR)))`.

## What was verified, live

`examples/template`, local Docker, `ghcr.io/ballistics-lab/arm_embedded`:

| identifier | result |
| --- | --- |
| `mpy5-v1.12-armv7emsp` | `.mpy`, 166 bytes — oldest tag the project knows |
| `mpy5-v1.18-armv7emsp` | `.mpy`, 166 bytes |
| `mpy6-v1.19.1-armv7emsp` | `.mpy`, 209 bytes |
| `mpy6.3-v1.29.0-armv7emsp` | `.mpy`, 177 bytes — regression check |

Run back to back **in one tree with no clean between them**, which is the case fix 3 exists for;
and each also from a clean tree, to be sure the first result was not itself a stale-object
artifact.

**Both image families, not just one**, since fixes 1 and 2 are `sources.py`-level and would have
been just as easy to get right for `arm_embedded` alone: `mpy5-v1.12-x64` and `mpy5-v1.18-x86`
build on `natmod_host` (the image [0082] originally bisected against), and `mpy6-v1.19.1-armv6m`
on `arm_embedded` beside the `armv7emsp` rows above. 592 tests, ruff, pyright and
`bin/refresh_docs.py --check` clean afterward.

## What `README.md` was telling people to do, and why it mattered more than the badge

Two separate corrections, both per CLAUDE.md's standing rule about narrative docs surviving the
record that obsoletes them:

**The blanket `micropython v1.20.0+` badge was false the moment this landed.** It now reads
`v1.12+`, with one sentence next to the natmod/usermod split saying what each half reaches: natmod
from `v1.12`, usermod from `v1.20.0`, `qemu` from `v1.24.0`. The per-port table's own
`v1.20.0`-`v1.30.0-preview` rows were already right and are untouched.

**More seriously, README was handing every downstream repo the bug.** `BUILD = .obj/$(ARCH)`
appears three times — the quickstart Makefile people copy verbatim, the `header encodes native arch
code` troubleshooting entry, and "Conventions this repo assumes" — and every one of them is the
arch-only form fix 3 replaces. Worse, the surrounding prose made two claims that read as *coverage*:

- *"`cibuildmp` catches this rather than shipping it"* / *"a header-arch verification step fails
  loudly instead."* True for the arch axis, and the reason the tag axis is dangerous: the header
  that check reads is correct on a tag-contaminated artifact, so nothing fails. The
  `examples/wasm2mpy` measurement above is exactly that case — `verify_output()` passed on the
  wrong binary.
- *"On v1.29.0 and later the collision cannot happen by default."* Checked against upstream rather
  than left standing: `dynruntime.mk`'s `BUILD` default is an unscoped `build` through `v1.28.0`
  and `build-$(ARCH)` from `v1.29.0` — arch-scoped from that tag on, **tag-scoped in no release at
  all**, since `MPY_DIR` is the only thing that knows which release is being built. So the sentence
  is true of the arch collision and false of the tag one, which is the collision no default can
  ever cover.

All three snippets now carry the release component, the two claims are scoped to the axis they are
actually true of, and the tag axis is spelled out as the one that produces no error. The
`patsubst` guard is in the README form too, and was checked against a real `make` invocation with
and without a trailing `MPY_DIR` slash rather than assumed to expand.

## Every other example, surveyed rather than assumed

Fix 3 is in a file this project ships as the thing downstream repos copy, so the same question was
asked of every other example in the tree rather than left to whoever hits it next:

- **`examples/wasm2mpy/Makefile` had the identical bug and is fixed the same way.** Its
  `BUILD = .obj/$(ARCH)` is a cibuildmp-added line (the file is otherwise vendored from
  `vshymanskyy/wasm2mpy`) whose own comment already points at
  `examples/template/natmod/Makefile` for the reasoning — so it inherited the arch scoping and
  not the tag axis. Nothing but its `cibuildmp.toml` pinning a single tag (`mpy6.3-v1.29.0-*`)
  was keeping it from biting. **Measured against the unfixed file rather than argued**, since one
  build of one target only proves the path moved: `mpy6.3-v1.29.0-armv6m` then
  `mpy6.3-v1.25.0-armv6m`, one tree, no clean between, `--build` overriding that pin. Unfixed, the
  second target finished in **0.8s** and shipped a **4784-byte** `.mpy`; fixed, it takes **6.6s**
  and ships **4792 bytes**, with objects under `.obj/v1.25.0/armv6m/` beside `.obj/v1.29.0/armv6m/`.
  The eight-byte difference and the near-instant run are the same fact: unfixed, it relinked
  `v1.29.0`'s objects and called the result `v1.25.0`. **`verify_output()` passed on the wrong
  artifact** — the arch header is correct, only the `py/` it was compiled against is not — which is
  exactly the "silently mislabelled `.mpy`" half of this record's fix 3, here demonstrated rather
  than inferred from the `LinkError` half. Three arches back to back in one tree (`armv6m`,
  `armv7m`, `x64`: 4761/4117/5349 bytes) confirm the arch scoping still holds beside it.
- **`examples/natmod` needs nothing — it already solves this structurally.** It builds upstream's
  own `examples/natmod/*` through the `{micropython}` placeholder ([0072]), where the Makefiles are
  upstream's and set no `BUILD` at all; its `pre-build-command = "rm -rf *.mpy build build-*"` runs
  before *every* build, so no artifact from a previous tag, arch or arch-flags variant survives to
  be compared against. That config's own comment already reasons through the arch and arch-flags
  axes; the tag axis needs no separate answer because deleting everything covers all three.
- **`examples/template/usermod` and `examples/usercmodule` are immune by construction.** A usermod
  build's objects land inside the pinned MicroPython checkout
  (`<cache>/micropython/<tag>/ports/<port>/build…`), which is per-tag already — the contamination
  fix 3 describes needs one build tree shared across tags, and usermod never has one.

## Left open, deliberately: the old `.mpy` embeds its own build path

Noticed while checking whether fix 3 changed anything it should not: `mpy6-v1.19.1-armv7emsp`'s
artifact grew from 201 to 209 bytes, exactly the 8 characters `v1.19.1/` adds to `$(BUILD)`. The
reason is upstream's, not this project's — on ABI 5/6 the `.mpy` carries the *source path* it was
merged from as a string (`.obj/v1.19.1/armv7emsp/o/template.native.mpy`, visible in `strings`),
where `v1.29.0`'s carries the basename `template.mpy`. So on those nine tags the published artifact
leaks the build directory layout and is not byte-reproducible across build paths.

It already did before this record — the old string was `.obj/armv7emsp/o/template.native.mpy` — so
nothing regressed, and the module works either way. Not fixed here because the fix belongs in how
the intermediate is named, not in the scoping this record needed, and because no consumer of these
nine tags exists yet to care. Recorded so that a later "why does this `.mpy` have a path in it"
does not get re-derived from scratch.

## What this does not claim

Only `natmod` is verified for these tags, which is all that is reachable. The same `mpy-cross` path assumption also lives in
`usermod/build_common.py`'s own `container_mpy_cross()` (`mpy-cross/build-<slug>/mpy-cross`), and it
is **not** fixed here: on a pre-`v1.20.0` tag that build would drop the binary at the unscoped
`mpy-cross/mpy-cross`, defeating the per-image slug isolation the function exists for, so the
fallback would be wrong rather than merely absent. It is unreachable today — the only `usermod`
ports with rows in that tag range are `esp8266`, `cc3200`, `renesas-ra` and `nrf`, none of which has
a build driver ([0053]) — and whichever record gives one of them a driver has to solve it properly
rather than inherit `find_mpy_cross()`'s two-candidate answer.

[0010]: 0010-pinned-data-in-resources.md
[0013]: 0013-micropython-list-dedup-by-abi.md
[0045]: 0045-only-is-a-filter-not-a-forced-identifier.md
[0049]: 0049-no-matrix-generation-archs-vocabulary.md
[0053]: 0053-usermod-ports-without-a-build-driver.md
[0082]: 0082-natmod-old-tags-fail-mpy-cross-under-gcc-15.md
[0072]: 0072-natmod-micropython-placeholder-and-upstream-natmod-ci.md
[0084]: 0084-per-identifier-toolchain-tarballs-and-the-end-of-shared-images.md
[0091]: 0091-tag-cflags-into-every-ports-mpy-cross.md

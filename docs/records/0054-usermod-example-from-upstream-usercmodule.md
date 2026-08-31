# 0054 — an `examples/` usermod fixture built on upstream's own `examples/usercmodule`

- Status: Implemented — all six ports green via [0069]'s own widening, both open
  questions below answered; see this record's own closing addendum
- Related: [0016], [0021], [0023], [0033], [0046], [0053], [0069], [0071]

## Why a second usermod example at all

`examples/template` already carries a usermod side, and it is a good one: one module,
one shared `src/template_core.c`, a frozen `manifest.py`, driven across every port
cibuildmp claims by `build-examples.yml`. What it is not is *upstream's*. Every fact it
proves is a fact about a module cibuildmp wrote for itself, in the layout cibuildmp
documents, exercising the subset of `USER_C_MODULES` cibuildmp already knew it needed.

Upstream ships the canonical fixture for exactly this contract, and it is richer than
`template/` in three specific ways that are not stylistic. Read from a real checkout
(`micropython@e0e9fbb17`), `examples/usercmodule/` is:

```
examples/usercmodule/
  micropython.cmake            ← includes all three, the CMake-port entry point
  cexample/                    examplemodule.c  micropython.mk  micropython.cmake
  cppexample/                  example.cpp  examplemodule.c  examplemodule.h
                               micropython.mk  micropython.cmake
  subpackage/                  modexamplepackage.c  qstrdefsexamplepackage.h
                               micropython.mk  micropython.cmake  README.md
```

- **`cppexample` is C++, and mixed with C.** Its `micropython.mk` puts `example.cpp`
  in `SRC_USERMOD_CXX`, adds `CXXFLAGS_USERMOD += -std=c++11`, and — the part that
  matters most — `LDFLAGS_USERMOD += -lstdc++`. `template/` compiles no C++ anywhere,
  so nothing in this project has ever established that a C++ user module links on the
  ports cibuildmp drives.
- **`subpackage` carries its own `qstrdefsexamplepackage.h`** and builds a dotted
  package rather than a flat module. `template/` has no separate qstrdefs header at
  all.
- **Every directory ships both entry points**, `micropython.mk` *and*
  `micropython.cmake`. That is [0016]'s own decision — directory on Make ports, a
  `.cmake` entry point on CMake ports — with upstream's own reference implementation of
  both halves for one tree. Today [0016] is validated against a module this project
  wrote to satisfy it, which is close to validating it against itself.

## What this would actually test that nothing currently does

1. **That `-lstdc++` is satisfiable on each port image.** This is the single biggest
   unknown and it is not uniform. The `unix` targets run in manylinux/musllinux images
   where a C++ toolchain is present as a matter of course. `windows` builds through
   mingw, `webassembly` through `emsdk`, and `qemu` through `arm-none-eabi-` — the last
   of which is a bare-metal toolchain where a plain `-lstdc++` is not the same
   proposition it is on a hosted target. This record deliberately does not guess which
   of the three work; finding out *is* the work.
2. **That `SRC_USERMOD_CXX` is honoured by every port cibuildmp drives**, not just the
   Make ports upstream's own CI exercises. It is a `py/mkrules.mk` variable, so the
   CMake ports reach it by a different path entirely.
3. **That a `.cmake` entry point resolves for a tree that is not laid out the way
   `template/` is.** `usermod/portinfo.py` picks the entry point per port; upstream's
   `examples/usercmodule/micropython.cmake` is a real second implementation of the
   shape it expects.

## What is in the way

- **~~`user-c-modules` points at one thing~~ — answered by [0057]:** name the parent, and
  it stays one path. The plurality lives in the consumer's layout, not in the config.
  What that record found while deciding it is the thing this fixture has to handle:
  **the two build systems disagree about which modules the same directory contains.**
  `py/py.mk` globs `*/micropython.mk`, so a Make port picks up all three subdirectories
  with no file listing them. `examples/usercmodule/micropython.cmake` is an explicit
  two-line list of `cexample` and `cppexample` — `subpackage` is **not** in it, so a
  CMake port builds two. Building the same three everywhere means adding one
  `include()` line to the vendored aggregator, which is a further argument for
  vendoring below.
- **Vendoring policy — reconsidered, flipped.** Original call: vendor, the way
  `examples/wasm2mpy` vendors from `vshymanskyy/wasm2mpy` with its own `NOTICE` file,
  because reaching into the MicroPython checkout cibuildmp already resolves per tag
  would make the fixture's content "float" with whatever tag is under test, confusing
  upstream drift with a real cibuildmp regression.

  That reasoning doesn't hold: the tag is not floating, it's pinned — the same
  `micropython = "v1.28.0"` shape `examples/template`'s own `cibuildmp.toml` already
  uses, bumped only in a real, reviewed PR, the exact "a pin moves in a reviewed PR,
  because the diff is the review" cadence [0033]/[0046] already established for every
  other pin in this project. Reaching straight into `sources.fetch_micropython()`'s
  own resolved checkout for `examples/usercmodule/` means the fixture's content is
  exactly as pinned as anything else here — it changes only when a maintainer
  deliberately bumps the tag, and CI running against that bump's own new
  `usercmodule/` content *is* the review, not a source of confusion.

  Vendoring is the worse choice on the project's own terms: a hand-copied tree is a
  **second, independent pin** with its own bump schedule nothing watches — precisely
  the un-noticed-staleness shape [0046] exists to name. No vendoring, no `NOTICE`
  file, no separate bump step: read `examples/usercmodule/` straight out of the
  checkout `fetch_micropython()` already resolves for whatever tag is under test.
- **`build-examples.yml` runs `examples/template` on every leg.** A second usermod
  fixture is a second matrix's worth of CI minutes if it is added the same way. It is
  cheaper and more honest to run this one on a narrow port set at first — one Make port
  and one CMake port is enough to answer the three questions above — and widen only if
  it finds something.

## Not decided here

- Whether this replaces `template/`'s usermod side eventually or sits beside it
  permanently. They test different things (`template/` proves the shared-core layout
  this project documents to consumers; this proves upstream's own contract), so beside
  is the current assumption.
- Whether `cppexample` should be skipped on ports where `-lstdc++` turns out not to be
  available, or whether that unavailability is itself a finding worth recording per
  port in `resources/build-platforms.toml`.

## Addendum, 2026-08-30 — a narrow real slice landed ([0069]), and one factual correction

[0069] built the mechanism this record scoped but did not build: `unix` (Make) and `rp2`
(CMake) now actually build upstream's `examples/usercmodule/` in CI, resolved straight
from `sources.fetch_micropython()`'s own checkout per this record's own "no vendoring"
call above — see that record for the mechanism, the two live CI failures hit landing it,
and what is still left for `esp32`/`windows`/`webassembly`/`qemu`.

Also worth recording precisely because it was checked directly against a real checkout
rather than trusted from memory (this file's own opening section names exactly that
discipline): "Why a second usermod example at all" above, in its `cppexample` bullet,
reads `LDFLAGS_USERMOD += -lstdc++`. A real `v1.29.0` checkout's own
`cppexample/micropython.mk` says `LIBS_USERMOD += -lstdc++`, not `LDFLAGS_USERMOD`. Left
as the original, unedited text above per this project's own append-only convention for
records — this addendum is the correction, not a silent fix — but anyone citing that line
for the Makefile variable name itself should use `LIBS_USERMOD`.

## Addendum, 2026-08-31 — both "Not decided here" questions answered, all six ports green

[0069]'s own widening (`esp32`/`windows`/`webassembly`/`qemu` joined `unix`/`rp2`) answers
this record's own remaining open questions:

- **`cppexample`/`-lstdc++` question, and the skip-vs-record call** — every one of the six
  toolchain families links C++ once its own real bug is fixed (windows' image, webassembly's
  Makefile — see [0069]'s own addendum for both). `cppexample` is not skipped anywhere;
  nothing here ever needed skipping, only fixing.
- **Whether this replaces `template/`'s usermod side** — still not decided, and still not
  forced: nothing about widening to six ports argued either way, and both fixtures keep
  proving different things (`template/` the shared-core layout cibuildmp documents to
  consumers, this one upstream's own contract).

The two mechanisms this record's own text still describes as current —
"`user-c-modules`/`build =`" left unset here "on purpose" because "both are set per-invocation
by [the workflow]", and the CMake side's `-DCIBMP_UPSTREAM_USERCMODULE_DIR=…` injection named
in [0069]'s own original text — are both gone. [0071]'s own `{micropython}` placeholder and
the CMake side's own `MICROPY_DIR` read replace them; `examples/usercmodule/cibuildmp.toml`
itself now carries `user-c-modules` (as overrides, per port family) directly. See [0069]'s
own closing addendum for the full mechanism and [0071] for the placeholder itself.

[0016]: 0016-usermod-user-c-modules-dir-vs-cmake.md
[0021]: 0021-usermod-execution-central-value.md
[0023]: 0023-usermod-identifier-scheme-config-output.md
[0033]: 0033-cibuildmp-never-builds-docker-image-itself.md
[0046]: 0046-pin-staleness-checker.md
[0053]: 0053-usermod-ports-without-a-build-driver.md
[0057]: 0057-multiple-modules-per-build.md
[0069]: 0069-upstream-usercmodule-narrow-ci-slice.md
[0071]: 0071-micropython-placeholder-in-user-c-modules.md

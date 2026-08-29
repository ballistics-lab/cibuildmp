# 0054 — an `examples/` usermod fixture built on upstream's own `examples/usercmodule`

- Status: Proposed (nothing built; this record scopes the work and names what is
  already known to be in the way)
- Related: [0016], [0021], [0023], [0053]

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
- **Vendoring policy.** This is MicroPython's own code, MIT-licensed, and the project
  already has a precedent for carrying third-party source into `examples/`:
  `examples/wasm2mpy` vendors from `vshymanskyy/wasm2mpy` with a `NOTICE` file next to
  it. The alternative — reaching into the MicroPython checkout cibuildmp already
  resolves per tag — is tempting and is worse: it would make the fixture's own content
  change with the tag under test, so a failure could be upstream drift or a cibuildmp
  regression with nothing to tell them apart. Vendor, with a `NOTICE`, and bump by
  hand.
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

[0016]: 0016-usermod-user-c-modules-dir-vs-cmake.md
[0021]: 0021-usermod-execution-central-value.md
[0023]: 0023-usermod-identifier-scheme-config-output.md
[0053]: 0053-usermod-ports-without-a-build-driver.md
[0057]: 0057-multiple-modules-per-build.md

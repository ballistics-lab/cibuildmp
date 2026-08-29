# 0066. `extra-cmake-args` — the cmake-side `extra-make-args`

- Status: Implemented
- Related: [0038]

## What was missing

`extra-make-args` already lets a config append raw tokens onto a make
invocation's own command line, uniformly across all six `build_<port>()`
drivers. It works because none of the four Make-only ports (`unix`,
`windows`, `webassembly`, `qemu`) hand `extra-make-args`' own values back
into a *second*, internal `make` invocation — whatever a caller names there
just becomes another command-line variable assignment for that one `make`
process.

`rp2` and `esp32` are different: both are CMake-driven ports whose own
top-level `make` target wraps a `cmake`/`idf.py` invocation, and both
Makefiles build up their own cmake argument variable with a plain `+=`:

```make
# ports/rp2/Makefile
CMAKE_ARGS += -DMICROPY_BOARD=$(BOARD) ...

# ports/esp32/Makefile
IDFPY_FLAGS += -D MICROPY_BOARD=$(BOARD) ... $(CMAKE_ARGS)
```

Surfaced migrating `micropython-wasm3` to the unified CLI ([0038], M5): its
`rp2` usermod build needs `-DMICROPY_C_HEAP_SIZE=131072` (the port defaults
the C heap to 0; the module allocates through `calloc()` and faults without
one), and there was no way to hand a cmake-only flag through `extra-make-args`
that would actually reach `cmake` rather than being swallowed or, worse,
silently replacing what the Makefile itself needs to set.

## Why `extra-make-args` itself can't just carry it

Tried first, live, twice — not assumed:

```
make CMAKE_ARGS=-Dfoo=1        ...
make CMAKE_ARGS+=-Dfoo=1       ...
```

Both **replace** the makefile's own `-DMICROPY_BOARD=`/`-DUSER_C_MODULES=`
entirely rather than adding to them, whatever operator the command line
itself uses. GNU Make's own precedence order is command-line assignment >
makefile assignment > environment — a command-line-origin variable always
wins over whatever operator the makefile later applies to it, `+=` included.

An **environment** variable of the same name sits one precedence tier below
a makefile's own assignment, so the makefile's own `+=` treats it as the
*starting* value and appends its required flags on top of it — confirmed the
same way: `CMAKE_ARGS=-Dfoo=1 make ...` keeps every flag the makefile itself
still adds.

## What shipped

`build_common.cmake_extra_args_env(extra_cmake_args, *, var)` turns a
config's `extra-cmake-args` into the one `dockerrun.run()` `env={...}`
entry that actually reaches the build this way: `var="CMAKE_ARGS"` for
`rp2`, `var="IDFPY_FLAGS"` for `esp32` (ESP-IDF's own name for the same
idea). `{}` (no entry at all) when nothing is configured, not an explicit
empty value — an absent key keeps a call site free of a no-op entry when
nobody set anything.

`extra_cmake_args` is threaded through `Esp32BuildOptions`/`Rp2BuildOptions`
and `orchestrate.py` alongside `extra_make_args`, resolved through the same
generic/`[override]` cascade `extra-make-args` already uses
(`usermod/options.py`'s `USERMOD_PORT_BASE`, mirrored in `natmod/options.py`'s
own `_USERMOD_OVERRIDE_OPTION_KEYS_MIRROR` drift guard — natmod must never
import usermod, so this constant is hand-maintained and tested to stay in
sync). The four Make-only ports never read it — meaningless to them, same
as `extra-make-args` is meaningless to a port that never reads whatever
variable name a caller passes it.

## `micropython-wasm3` itself ends up not needing this after all

`usermod/micropython.cmake` can set `MICROPY_C_HEAP_SIZE` itself instead:
`py/usermod.cmake` `include()`s a user module's own `micropython.cmake` in
the *same* CMake scope as the port's own `CMakeLists.txt` (not a nested
scope), so a later `set(MICROPY_C_HEAP_SIZE 131072)` inside the module's own
`micropython.cmake` still reaches the linker-flag line the port reads it
from — verified live against a standalone `CMakeLists.txt` reproduction
matching `ports/rp2/CMakeLists.txt`'s own before-default/include/after-read
ordering. A caller's own external `-D` still wins when given, since it is
supplied before the module's own file runs.

That does not make the feature itself unneeded: `esp32` has no such
self-contained escape hatch for a future consumer that needs one, and the
asymmetric make/cmake support this record closes was never a deliberate
design choice to begin with — just an unfilled gap in `extra-make-args`'
own reach.

[0038]: 0038-m5-adopt-in-three-repos.md

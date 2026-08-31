# 0071. `{micropython}` — a placeholder in `user-c-modules` for a path inside the pinned checkout

- Status: Implemented
- Related: [0051], [0066], [0067], [0069]

## What was missing

`user-c-modules` names a module directory relative to `package_dir`
(`orchestrate.py`'s own `module_root = (package_dir / build_options.user_c_modules)
.resolve()`) — fine for the overwhelming majority of real consumers, whose module
lives inside their own project. [0069]'s own upstream-`examples/usercmodule` fixture
needed something different: a path *inside the pinned MicroPython checkout itself*
(`<checkout>/examples/usercmodule`), which does not exist anywhere until
`sources.fetch_micropython()` has actually run — and that call happens *inside*
`cibuildmp`, after config has already loaded.

[0069] named this gap explicitly and did not close it: "There is no `{micropython}`-style
template in `user-c-modules` today, and this record does not add one — seeing the
fixture build once with the existing option surface first … settles whether that
surface is even the right thing to extend before extending it." Its own workaround was
a pre-fetch step in the calling workflow (`sources.fetch_micropython()` called directly,
in a plain Python step, before `cibuildmp` itself ran), threading the resolved path in by
hand through `CIBMP_USER_C_MODULES`.

## What shipped

`_port_build_options()` (`orchestrate.py`) substitutes the literal text `{micropython}`
with `mpy_dir.as_posix()` before resolving `user_c_modules` against `package_dir`:

```python
user_c_modules = build_options.user_c_modules.replace(
    "{micropython}", mpy_dir.as_posix()
)
module_root = (package_dir / user_c_modules).resolve()
```

`mpy_dir` is already a real, fetched directory by the time `build_one()` calls this —
every caller (the CLI, the test suite, this fixture's own workflow) already has it in
hand before a single target builds, the same value `build_<port>()` itself uses for
`mpy_dir` mounts. The substitution runs once, in the one function every port's
`*BuildOptions` construction goes through, well before `usermod_mounts()` ever turns
the resolved value into a Docker bind mount — Make and CMake ports alike see an already-
real path, never the literal placeholder text.

A config (or a `CIBMP_USER_C_MODULES` env override) can now write
`user-c-modules = "{micropython}/examples/usercmodule"` and get the pinned checkout's
own path, with no pre-fetch step of its own required — [0069]'s own addendum switches
the four Make-port jobs in `test-upstream-usermodule.yml` to exactly this, dropping
their pre-fetch steps entirely.

## Why CMake ports never needed this

`rp2`/`esp32` reach the same checkout a different way: `examples/usercmodule/
micropython.cmake` reads `MICROPY_DIR` directly, a CMake variable every CMake port
already sets (`get_filename_component(MICROPY_DIR "../.." ABSOLUTE)` in
`ports/rp2/CMakeLists.txt`, an equivalent guard in `ports/esp32/main/CMakeLists.txt`)
before it ever `include()`s a user module. `{micropython}` and `MICROPY_DIR` solve the
identical problem from opposite sides of the same boundary: one is cibuildmp's own
Python substituting a real path before a build ever starts, the other is the build
system itself exposing a variable it already had. Neither needed inventing for the
other's sake.

## Scope: `user-c-modules` only, not `extra-make-args`/`extra-cmake-args`

Not extended to the other two keys `extra-make-args`/`extra-cmake-args` already cover —
no real caller has needed `{micropython}` inside either yet, and inventing the
substitution there ahead of a real need would repeat exactly the mistake this project's
own `CLAUDE.md` warns against (building something that resembles a real requirement
before one exists). If a real config ever needs `{micropython}` inside an
`extra-*-args` value, the same one-line `.replace()` extends cleanly — nothing about
this implementation is CLI-shaped or Make/CMake-specific.

## Live-verified

`test-upstream-usermodule.yml`'s four Make-port jobs (`unix`/`windows`/`webassembly`/
`qemu`) all build green using `{micropython}/examples/usercmodule` as their
`user-c-modules`, resolved with no pre-fetch step of their own — see [0069]'s own
addendum for the full six-port picture. 423 unit tests pass, including a new one
(`test_build_one_substitutes_micropython_placeholder_in_user_c_modules`) covering the
substitution directly.

[0051]: 0051-usermod-identifiers-have-no-version-axis.md
[0066]: 0066-extra-cmake-args.md
[0067]: 0067-user-c-modules-flat-shape-autodetect.md
[0069]: 0069-upstream-usercmodule-narrow-ci-slice.md

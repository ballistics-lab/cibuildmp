# 0067. `resolve_user_c_modules()` auto-detects the flat make-module shape

- Status: Implemented
- Related: [0016], [0038], [0056], [0057]

## The bug, live-caught

Migrating `micropython-wasm3` to the unified CLI ([0038], M5): every
make-port usermod build (`unix` x64/x86/aarch64/armhf, all three `windows`
arches, `webassembly`) reported success and produced a working port binary
with **zero user modules actually linked in** — no error, no warning,
anywhere in the build log. Only the *test* step surfaced it, and only
because it happened to import the module through a `try: from _wasm3 import
version, ... except ImportError: pass` fallback (the natmod/usermod
dual-mode wrapper `src/wasm3.py` uses) that silently swallowed the missing
module as an ordinary `ImportError`. Without that particular fallback shape,
the failure would have been even harder to notice — a green build, silently
missing the one thing the build exists to add.

## Why: two build systems, two different contracts, both undocumented outside code

`user-c-modules` was `"usermod"` — `micropython-wasm3`'s own
`usermod/micropython.mk`/`micropython.cmake` sit directly inside `usermod/`,
one level under the project root. `resolve_user_c_modules()`
([0016]) already knows the two build systems want different shapes:

- **cmake** (`rp2`/`esp32`): the value is used as-is, `/micropython.cmake`
  appended. `"usermod"` → `usermod/micropython.cmake`. Correct.
- **make** (`unix`/`windows`/`webassembly`/`qemu`): `py/py.mk` globs
  `<USER_C_MODULES>/*/micropython.mk` — the value must be the module's own
  **parent** directory, one level *above* where its `micropython.mk`
  actually sits, so several unrelated modules can each live in their own
  subdirectory of one shared `USER_C_MODULES=`. `"usermod"` needed to be
  `"."` instead. `py/py.mk`'s own `ifneq ($(USER_C_MODULES),)` guard only
  checks the string is non-empty, not that anything actually matched the
  glob — a glob matching nothing degrades to a legitimate-looking "no user
  modules" build with no error at all, the same "empty is a clean no-op
  everywhere" upstream behaviour [0056] already documented, reached here by
  accident rather than by [0056]'s own deliberate config surface.

**Both existing configs in the wild already worked, for two different, both
previously-implicit reasons — neither documented anywhere a new consumer
would find it:**

- **`a7p`** (`user-c-modules = "usermod"`, unchanged) works because its own
  physical layout is *nested*: `usermod/a7p/micropython.mk` (the actual
  module, one level deeper than `micropython-wasm3`'s), plus a separate
  `usermod/micropython.cmake` aggregator at the `usermod/` level itself.
  The make glob `usermod/*/micropython.mk` finds `usermod/a7p/
  micropython.mk` correctly; the cmake append finds `usermod/
  micropython.cmake` correctly. Confirmed not a deliberate multi-module
  design either — a coincidence of how that repo's own module happens to be
  organised, not a rule anyone wrote down.
- **`examples/template`** (`user-c-modules` unset, defaulting to `"."`)
  works because it structures around the asymmetry the *other* way:
  `usermod/micropython.mk` one level under `usermod/` (found by the make
  glob from `.`), `micropython.cmake` one level **up**, at the project root
  itself (found by the cmake append from `.`) — its own comment even names
  the reason (`src/` is a sibling of `usermod/`, so `USER_C_MODULES` has to
  reach one level above `usermod/` to see it at all), but says nothing
  about the make/cmake split this shape happens to also satisfy.
  `test-all-platforms.yml`/`test-platforms.yml` both build every real
  `rp2`/`esp32` identifier against this exact config on every push
  (`--build` override, not the file's own narrower default) and never
  surfaced this bug — not because the scenario is safe, but because this
  one project's own layout was already correct for it, by whoever wrote it
  already knowing the asymmetry existed.

`micropython-wasm3`'s own flat `usermod/micropython.mk` — no nesting, no
project-root-level `.cmake` — is a third, real shape: the one a new
single-module project reaches for first, and the one neither existing
config actually exercises.

## The fix

`resolve_user_c_modules()` now checks, for make ports only, whether
`module_dir` itself already contains a `micropython.mk`. If it does, it
resolves to `module_dir`'s own **parent** instead of `module_dir` itself —
the glob then finds it one level down, at
`<parent>/<module_dir's own name>/micropython.mk`, exactly matching the
multi-module shape (`a7p`'s own nested `usermod/a7p/`) that already worked.
That existing shape is unaffected by construction: a `module_dir` with no
`micropython.mk` directly inside it (`a7p`'s own `usermod/`,
`examples/template`'s own `.`) has nothing to detect and falls through to
the prior, unchanged return value. The cmake branch is untouched and
independent — a `module_dir` can legitimately hold both a `micropython.mk`
and a `micropython.cmake` side by side, which is exactly
`micropython-wasm3`'s own case now that both ports resolve correctly from
one `user-c-modules = "usermod"`.

3 new tests cover the flat shape resolving to its parent, the existing
multi-module shape staying unchanged, and the cmake branch's own
independence from the make-side check. Confirmed live against both real
repos' own directories (not just the test fixtures) before pushing the fix:
`resolve_user_c_modules("unix", ".../micropython-wasm3/usermod")` now
returns the project root; the identical call against `a7p`'s own
`.../usermod` is unchanged.

[0016]: 0016-usermod-user-c-modules-dir-vs-cmake.md
[0038]: 0038-m5-adopt-in-three-repos.md
[0056]: 0056-usermod-with-no-user-c-module.md
[0057]: 0057-multiple-modules-per-build.md

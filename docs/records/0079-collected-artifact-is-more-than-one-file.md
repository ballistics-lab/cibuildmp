# 0079 — a collected artifact is not always one file, and only the port knows

- Status: Implemented
- Related: [0069], [0070], [0054]

## What was wrong

`orchestrate.build_one()` collects a build by copying exactly one thing: the
`Path` that port's own `build_<port>()` returned. Record [0070] found the first
case where that was not the whole artifact — `unix`'s `repair_unix_binary()`
vendors `libffi.so.<N>` into a `lib/` beside the binary and sets
`--set-rpath '$ORIGIN/lib'`, so the collected copy failed with *"error while
loading shared libraries: libffi.so.6"* — and fixed it the narrow way: copy any
`lib/` sitting next to `produced`, for every port.

That fix was both too narrow and too broad, and both halves were caught on real
artifacts on 2026-08-31, not by reading the source.

**Too narrow — `webassembly`.** The driver returns `micropython.mjs`. Upstream's
own `ports/webassembly/README.md` says the port produces `micropython.mjs` *and*
`micropython.wasm`, and nothing passes emscripten `-sSINGLE_FILE`, so the `.mjs`
carries only the literal string `micropython.wasm`, resolved against whatever
directory it is loaded from. A real local build collected 217,344 of the 680,703
bytes it produced, and running the collected copy aborted:

```
failed to asynchronously prepare wasm: Error: ENOENT:
no such file or directory, open '.../mpyhouse/v1.28.0-wasm32/micropython.wasm'
```

**Too narrow — `esp32`.** The driver returns `micropython.bin`, the application
image. `ports/esp32/README.md`: the build "will produce a combined `firmware.bin`
image", combined meaning bootloader + partition table + `micropython.bin`. Only
the first was ever collected — 1,715,952 bytes of a pair whose other half is
1,777,392.

**Too broad — `qemu`.** That port's build directory has a `lib/` too, and it is
`libm/`'s own object files. A real collected
`mpyhouse/v1.28.0-qemu-MPS2_AN385/lib/` held 54 `.o`/`.P` intermediates, 240K of
build scratch, uploaded to a release by a consumer that correctly ships the whole
identifier directory.

## Why it survived a full green CI

This is the part worth keeping. Every one of these builds was green, in this
repository and in all three consuming repositories, continuously. Nothing was
broken about the *build*; what was broken was the *artifact*, and the entire
test suite — unit tests, `build-examples.yml`, `test-all-platforms.yml` — either
asserts on a build's exit code or `ls`es its output. [0069]'s own
`examples/usercmodule/smoke_test.py` is the only thing anywhere that executes a
collected artifact, and `test-upstream-usermodule.yml` ran it for `unix` alone.

Its own comment gave the reason: *"none of their outputs (a .exe, a .wasm, a
qemu ELF) runs directly on this runner the way unix's manylinux binary does"*.
For `.wasm` that is false — `node` is preinstalled on `ubuntu-latest`, every
consuming repo already runs its own wasm tests through it, and the unmodified
`smoke_test.py` passes under the wasm build (verified locally before this record
was written). The one port whose artifact was most broken was excluded from the
one check that would have caught it, on a premise that was never true.

The three consuming repos never hit the `webassembly`/`esp32` half at all, and
that is itself informative: `micropython-wasm3` and `micropython-bclibc` upload
both files explicitly from the port's own build directory — the pattern the
legacy composite-action layer established, where `build_dir` is a documented
*output* "so the caller can find `micropython.bin`/`firmware.bin` without
recomputing it" (`docs/ACTIONS.md`). Only `a7p` follows the collected
`mpyhouse/<identifier>/` contract, so only `a7p` shipped the broken artifact —
55,234 bytes for a wasm build whose two-file sibling in another repo is 281,694.
Following the documented contract was the losing move, which is the strongest
argument that the contract, not the consumer, was wrong.

## The fix

- Each port declares its own companions: `unix_companions()`,
  `webassembly_companions()`, `esp32_companions()`. `windows` (one `.exe`),
  `rp2` (one `.uf2`) and `qemu` (one `.elf`) declare none and are absent from
  the table, which is what stops the `lib/` over-copy.
- `orchestrate._COMPANION_FN` maps port to that function, next to `_BUILD_FN`
  and in the same shape. `build_one()`'s hardcoded `lib/` block is gone.
- Companions keep their own filenames rather than going through `_dest_name()`:
  `$ORIGIN/lib` and the `.mjs`'s own `micropython.wasm` are both references by
  exact name from inside the primary. Only the primary is safely renameable.
- `test-upstream-usermodule.yml`'s `build-webassembly` job gained a smoke step
  running the unmodified `smoke_test.py` under `node`, from `mpyhouse/` —
  and the stale "nothing here runs on this runner" comment is corrected rather
  than left to justify the gap a second time.
- Three regression tests in `tests/test_usermod_orchestrate.py`, alongside
  [0070]'s own two: the `.wasm` lands beside the `.mjs` under its own name, the
  esp32 `firmware.bin` lands beside `micropython.bin`, and a `qemu` build with a
  `lib/` in its build directory collects no `lib/` at all.

## Not done here

- **`windows` and `qemu` still have no smoke test.** Both are genuinely harder
  than `webassembly` was (wine; `qemu-system-arm`), and neither has a known
  missing-companion bug. The point of this record is that "the runner cannot run
  it" must be *checked* before it is used as a reason, not that every port must
  have one today.
- **`esp32`'s companion is covered by a unit test, not a real build.** The
  `firmware.bin`/`micropython.bin` pair is read off upstream's own README and off
  a real local build directory's listing; no full ESP-IDF build was run through
  the changed collection step before this record was written.
- **The consuming repos are not migrated.** `micropython-wasm3` and
  `micropython-bclibc` can now move their `webassembly`/`esp32` uploads onto
  `mpyhouse/<identifier>/` and pick up [0070]'s `lib/` repair for their `unix`
  rows at the same time, but nothing here changes them, and their current form
  is correct as it stands.

[0054]: 0054-usermod-example-from-upstream-usercmodule.md
[0069]: 0069-upstream-usercmodule-narrow-ci-slice.md
[0070]: 0070-unix-collected-binary-missing-repaired-lib-sidecar.md

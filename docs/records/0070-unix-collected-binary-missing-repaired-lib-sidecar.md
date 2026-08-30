# 0070 — the collected `unix` binary shipped without its own repaired `lib/` sidecar

- Status: Implemented (fixed and tested; not yet independently re-verified against a
  real container build — see "Not yet done" below)
- Related: [0069]

## What broke, and how it surfaced

[0069]'s own `examples/usercmodule/smoke_test.py` is the first thing anywhere in this
project to actually *execute* a `unix` usermod build's collected output, rather than
`ls`ing it (`build-examples.yml`'s own `build-usermod` job has never done more than
list `mpyhouse/`). The very first real run failed, with the actual build itself green:

```
examples/usercmodule/mpyhouse/v1.29.0-manylinux_2_28_x86_64/micropython-v1.29.0-manylinux_2_28_x86_64:
error while loading shared libraries: libffi.so.6: cannot open shared object file
```

`build_unix.py`'s own `repair_unix_binary()` is this project's `auditwheel repair`,
by its own docstring: for a target whose floor lacks `libffi` as a baseline shared
object (the dynamically-linked glibc cells), it vendors `libffi.so.<N>` into a `lib/`
directory beside the freshly-built binary and points the binary at it with
`patchelf --set-rpath '$ORIGIN/lib'`. `$ORIGIN` means "whatever directory the running
executable actually lives in" — not the directory it happened to be built in.

`orchestrate.py`'s `build_one()` — the one collection step shared by every usermod
port — copied only the binary itself into `<package_dir>/<output_dir>/<identifier>/`:

```python
shutil.copy(produced, dest)
```

The binary ran fine from inside `mpy_dir/ports/unix/build-<identifier>/`, because its
`lib/` sibling was still sitting right there. The moment it was actually run from
where cibuildmp says its output lives — the collected `mpyhouse/` copy, the thing a
real consumer would actually receive — the sidecar was missing and the dynamic loader
failed outright. This defeats the entire point of `repair_unix_binary()`: a repaired
binary that cannot be moved without its lib is not repaired.

## Why this went unnoticed until now

Every unix cell in `build-examples.yml`'s own matrix (`v1.29.0-manylinux_2_28_x86_64`
included) has been green for a long time — "green" meaning the build succeeded and
`ls -laR mpyhouse` printed a file. Nothing in this project's own CI, nor (as far as
this record can establish) in any real consumer's own workflow, has ever run the
collected artifact from its collected location. `repair_unix_binary()` was verified
against the binary immediately after building it, in its own build directory — never
against the thing that actually gets shipped.

## The fix

`build_one()` now copies `produced.parent / "lib"` to `dest.parent / "lib"` (via
`shutil.copytree(..., dirs_exist_ok=True)`) whenever it exists, right after copying
the binary itself. A no-op for every target and every other port that never creates
this directory — only `repair_unix_binary()` ever does. `tests/
test_usermod_orchestrate.py` gained two regression tests: one simulating a real
`repair_unix_binary()` run (a `lib/libffi.so.6` sitting beside the fake ELF) and
asserting it lands beside the collected copy too, one asserting the common
no-sidecar case stays a plain no-op.

## Not yet done

- **Not re-verified against a real container build.** The fix is covered by a unit
  test that simulates `repair_unix_binary()`'s own output (`dockerrun.subprocess.run`
  is stubbed in that test suite, the same way every other `test_usermod_orchestrate.py`
  case already stubs it — a real `ldd`/`patchelf` invocation never runs there). The
  next `test-upstream-usermodule.yml` run against this fix is the first real,
  end-to-end confirmation; if the smoke test is still red after this lands, the
  sidecar-copy fix itself is the next thing to re-examine, not assumed correct from
  the unit test alone.
- **Whether any other port's own build driver has an equivalent uncollected sidecar**
  was not audited here — `repair_unix_binary()` is the only place in `usermod/
  build_<port>.py` that creates a `lib/`-beside-the-binary shape today (grep-checked),
  so this fix's scope matches the one real instance, not a general "collect everything"
  rewrite.

[0069]: 0069-upstream-usercmodule-narrow-ci-slice.md

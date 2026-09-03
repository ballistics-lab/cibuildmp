# 0092 — two "should this live in `build-platforms.toml` instead" questions, answered differently

Status: Implemented. `usermod.toml` merged into `build-platforms.toml` the same session this
record was written, once it turned out to be as easy as the "not attempted here" section below
predicted; `tag_cflags.toml` stays closed as its own, separate file, unchanged.
Related: [0010], [0052], [0084], [0091]

Both raised directly while landing [0091]: once `TAG_CFLAGS` moved out of a Python dict into
`resources/tag_cflags.toml`, the obvious next question is whether it belongs in the *existing*
tag-keyed table (`build-platforms.toml`'s own `[tags]`) rather than a file of its own — and,
separately, whether `resources/usermod.toml`'s own small per-port table should fold into
`build-platforms.toml`'s `[usermod.<port>]` sections the same way. They look like the same
question. They are not, and the difference is worth writing down rather than re-deriving next
time either comes up.

## `tag_cflags.toml` into `[tags]`: no, and this is closed

Checked directly, not assumed: `bin/refresh_natmod_archs.py` and `bin/refresh_usermod_boards.py`
both emit `[tags]` from scratch on every run —

```python
entry = {"sha": sha}
if date is not None:
    entry["date"] = date
tags[tag_name] = entry
```

— with no `carry_forward()` call for it, unlike the row-level facts those same scripts *do*
protect (`carry_forward(rows, (...), args.merge_from)`, a separate call, a few lines below). A
`cflags` key hand-added to a `[tags]` row today would survive exactly until someone re-runs either
script against a new tag, at which point the whole `[tags]` block is replaced and the field is
gone — silently, since neither script errors on dropping a key it never knew to look for. Landing
`cflags` there without first teaching *both* scripts to carry it forward would be choosing a home
that looks more consolidated and is actually less safe than the file it already lives in.
`resources/tag_cflags.toml` is untouched by any `bin/` script, which is not an accident of naming
but the actual property that makes it safe today. [0091] already made this call while landing;
recorded here as its own citable answer, not left buried in that record's own implementation
notes.

**If the two-table duplication (both `[tags]` and `tag_cflags.toml` keyed by the same tag
strings) is ever worth closing**, the fix is to extend `carry_forward()` (or a sibling helper) to
protect a hand-merged `[tags]` field the way row-level ones already are, in both scripts at once
since both emit the same shared block. Not attempted here — no reason has come up to want it
enough to justify touching two regeneration scripts for a cosmetic consolidation.

## `usermod.toml` into `[usermod.<port>]`: a real simplification, not attempted here

Different shape entirely. `resources/usermod.toml` is not tag-keyed and is not machine-regenerated
by anything — its own header says it was "verified live against a real v1.28.0 checkout", by
hand, once, and `bin/refresh_usermod_boards.py`/`refresh_natmod_archs.py` never mention it. Its
only consumer is `usermod/portinfo.py`'s own `_PORTS = usermod_data()["port"]`, one dict lookup,
nothing else in the tree reads it. So the `carry_forward()` risk above simply does not apply —
there is no regeneration to silently drop anything.

What it holds — `build-system` (`"make"`/`"cmake"`) and `default-manifest` — is a fact about the
**port itself** (which build system its own `Makefile`/`CMakeLists.txt` uses, upstream's own
choice, never varying by tag or board), not about any `(tag, board)` row. `build-platforms.toml`
already has exactly this shape of fact living at a table's own top level rather than repeated
per-row: `[usermod.rp2]`'s `image = "arm_embedded"` and `post_checkout = "make -C mpy-cross && ..."`
sit beside `identifiers = [...]`, once per port, not once per row — the same place
`build-system`/`default-manifest` would sit if they moved. Nothing about TOML requires every
`[usermod.<port>]` table to carry the same keys, so the nine ports `usermod.toml` deliberately
excludes (`stm32`, `samd`, `nrf`, ... — "verified rows here but no build pipeline yet", [0053])
would simply not carry `build-system`/`default-manifest` yet, exactly mirroring today's absence
from `usermod.toml` rather than forcing a value into sections with no driver to consume it. That
is a real merge, not a workaround: one file fewer, one loader function fewer
(`resources.usermod_data()`), and every fact about a given port answerable by reading its one
table instead of two.

**Done after all, same session, once asked directly.** The paragraph above sized this as real but
unforced work; it turned out smaller in practice than the size estimate implied, because the
blast radius really was just the one consumer:

- `build-system`/`default-manifest` added to each of the six `[usermod.<port>]` tables' own top
  level (`unix`, `windows`, `webassembly`, `qemu`, `esp32`, `rp2`) in `build-platforms.toml`,
  right beside `identifier_format`/`artifacts_dir_name` — not per-row, matching `image`/
  `post_checkout`'s own existing placement exactly.
- `usermod/portinfo.py`'s `_PORTS` now reads `build_platforms_data()["usermod"]`, filtered to the
  tables that actually carry `"build-system"` — presence of the key is the signal, not a second
  allowlist, so the nine driver-less ports ([0053]) simply don't have it, the same absence
  `usermod.toml` already expressed by omitting their sections entirely.
- `resources.usermod_data()` deleted along with `resources/usermod.toml` itself; every source
  comment that named the file by path (`resources.py`, `portinfo.py`'s own docstrings,
  `manifests.py`, `build_windows.py`'s `[llvm-mingw]` history) reworded to not cite a path that no
  longer exists — `tests/test_docs.py`'s own `test_source_paths_exist` checks every repo-looking
  path named in `src/**/*.py` dynamically, so this was not optional cleanup.
- Verified live, not just by the test suite: `cibuildmp examples/template --dry-run
  --print-build-identifiers` still resolves every identifier, and a real `v1.20.0-rp2-PICO` build
  (`build_system("rp2")` → `"cmake"` → `resolve_user_c_modules()`'s own cmake branch) still
  produces a genuine `firmware-v1.20.0-rp2-PICO.uf2`.

591 tests, ruff, pyright, `bin/refresh_docs.py --check` and pre-commit all clean afterward.

## What this record is not

Not a reopening of [0091]'s own `tag_cflags.toml` placement — that half is closed, with the reason
spelled out so it does not get re-litigated from a surface-level "but isn't `[tags]` already right
there" reading the next time someone notices `resources/tag_cflags.toml` is the only tag-keyed
table left outside `build-platforms.toml`.

## Also verified while this question was being asked: `examples/usercmodule` against [0091]'s fix

Requested directly: run [0084]/[0085]'s harder fixture (`examples/usercmodule` — upstream's own
`cexample`/`cppexample`/`subpackage`, C++ included, not `examples/template`'s trivial C) through
the ports [0091] touched, looking for a bug the simpler fixture would not surface.

- **`rp2`, `v1.22.2-rp2-RPI_PICO`** (pre-`v1.26.0`): `mpy-cross` built clean — the fix holds. The
  actual failure was unrelated to any of this: `CMake Error ... Cannot find source file
  .../examples/usercmodule/subpackage/examplemodule.c`. Not a regression — `examples/usercmodule`
  is deliberately pinned to `CIBMP_UPSTREAM_TAG: v1.29.0` in
  `.github/workflows/test-upstream-usermodule.yml` and was never verified against `v1.22.2`'s own
  older `subpackage` layout; picking that tag for this fixture was outside its own documented
  scope, the same reason `examples/template`'s own header keeps a single pinned tag rather than a
  range.
- **`esp32`, `v1.29.0-esp32-ESP32_GENERIC`**: `mpy-cross` built clean again. The failure here was
  this sandbox's own proxy: ESP-IDF's tool installer hit `SSL: CERTIFICATE_VERIFY_FAILED:
  self-signed certificate in certificate chain` fetching a GitHub release asset — the `docker-local`
  skill's own documented class of problem (a runtime `RUN`-equivalent HTTPS fetch inside a
  container whose trust store does not carry this session's proxy CA), not something a real CI
  runner or a real machine would hit.
- **Real CI, already green**: `test-upstream-usermodule.yml` run `33699011204`, triggered
  automatically by this branch's own `ce95254` (the [0091] fix itself) via its `on: push` trigger
  — the full six-leg fixture (`rp2`/`esp32`/`manylinux_2_28_x86_64`/`win_amd64`/`wasm32`/`qemu`,
  all at `v1.29.0`) passed clean with the fix in place, confirming no regression on the one tag
  this fixture actually covers.

No new bug attributable to [0091] found. Both local failures are explained by something other
than the code this record's own family touches, and both are named here so neither gets
mistaken for one on a future re-read.

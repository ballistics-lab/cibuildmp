# 0092 — two "should this live in `build-platforms.toml` instead" questions, answered differently

Status: Proposed — one half (`usermod.toml`) is a real, unstarted simplification; the other
(`tag_cflags.toml`) is closed, not open.
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

**Not done in this record.** Small blast radius (one consumer, `portinfo.py`), but real work
(moving two keys into ~2200 lines of existing rows' own top-level sections, updating that one
consumer, and updating whatever doc/test currently names `resources/usermod.toml` directly —
`tests/test_docs.py`'s own path-existence check among them) with no forcing function behind it:
nothing is broken today by the two files staying separate, unlike `tag_cflags.toml`'s own
motivating problem (`natmod` needing a fact `usermod/build_common.py` owned). Worth doing the day
someone is already touching `usermod.toml` for an unrelated reason, not worth a dedicated session
on its own.

## What this record is not

Not a decision to leave `usermod.toml` alone forever — it names the merge as real and welcome,
just unscheduled. Not a reopening of [0091]'s own `tag_cflags.toml` placement — that half is
closed, with the reason spelled out so it does not get re-litigated from a surface-level "but
isn't `[tags]` already right there" reading the next time someone notices the two tables.

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

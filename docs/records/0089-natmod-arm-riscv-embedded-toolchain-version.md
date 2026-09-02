# 0089 — `natmod`'s own `arm_embedded`/`riscv_embedded` rows get `toolchain_version` too

Status: Proposed — blocked on [0086]/[0087]; not implemented.
Related: [0082], [0084], [0085], [0086], [0087]

## Why this is not covered by [0087] already

[0085]'s own table and [0087]'s scope both name the seven `usermod` ports that share
`arm_embedded` (six ordinary ones plus `mimxrt` in [0088]). `natmod` shares the same two images
for its own arm/riscv cross arches, through a different build driver, and [0085]'s own text names
this directly rather than leaving it to be inferred: *"[0085]'s own `toolchain_version` model is
the real fix, and it should cover `natmod`'s rows too when it lands, not just the seven `usermod`
ports its own table names."*

## What [0084] already did here, and what it explicitly did not

[0084] taught `bin/refresh_toolchain_pins.py` about `natmod.arm_embedded`/`natmod.riscv_embedded`
scopes this session (`real_rows()`/`image_for()` seeded from `natmod`'s own `arch -> image` map),
which moved `--check`'s count from 71 to **92**: 18 new `natmod.arm_embedded` rows (every
pre-`v1.26.0` tag) and 3 new `natmod.riscv_embedded` rows (`v1.24.0`-`v1.25.0`). That is
visibility only — `natmod`'s own `gcc` column already recorded the right split
(`14.2.1-1.1`/`15.2.1-1.1`) but nothing compared it to what the images actually ship, and nothing
in `src/cibuildmp` reads that column for `natmod` any more than it did for `unix` before
`4e222ab`.

## What this record is

Wire `natmod`'s own build driver for its arm/riscv cross arches to [0086]'s generic fetch
mechanism, the same way [0087] wires the six shared `usermod` ports — using `natmod`'s existing,
already-correct `gcc` column values as the source of the per-row `toolchain_version` fact (a
rename/re-read, not a re-derivation: the values are already right, only unread). This closes the
21 `natmod.*` violations [0084] surfaced, on the same two images [0087] thins out, without a
second mechanism.

## Ordering

Depends on [0086] (the generic fetch) and benefits from [0087] landing first (proves the
mechanism once, on `usermod`, before a second, differently-shaped build driver adopts it) — but
does not depend on [0087]'s own code, only on [0086]'s.

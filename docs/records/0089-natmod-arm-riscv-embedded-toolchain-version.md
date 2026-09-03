# 0089 — `natmod`'s own `arm_embedded`/`riscv_embedded` rows get `toolchain_version` too

Status: Implemented. See its own addendum below for what landed, one real correction
(`natmod`'s own `gcc` value for `rv32imc`/`rv64imc` was itself wrong, found while wiring this
record rather than assumed correct), and real verified builds.
Related: [0082], [0084], [0085], [0086], [0087], [0091]

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

## What this does not fix, and why it looks like it should

`natmod`'s arm/riscv cross arches build `mpy-cross` the same way every `arm_embedded`-family
`usermod` port does: with `container_mpy_cross()`, against the image's own *native* compiler, not
the row's cross toolchain this record wires up. That native compiler is `arm_embedded`/
`riscv_embedded`'s `ubuntu:26.04` `build-essential` gcc — the exact one [0084] measured as
15.2.0, and [0082] ties to nine failing pre-`v1.26.0` tags, on the same diagnostic already
confirmed for `natmod_host`'s own `x64`/`x86`. So this record's own per-row `toolchain_version`
does nothing about `natmod`'s pre-`v1.26.0` tags failing `mpy-cross` on this image family — that
is [0091], not this record, and this record should not be read as closing [0082] for `natmod`'s
arm/riscv rows just because it closes the checker's `image`/pin visibility for them.

## Ordering

Depends on [0086] (the generic fetch) and benefits from [0087] landing first (proves the
mechanism once, on `usermod`, before a second, differently-shaped build driver adopts it) — but
does not depend on [0087]'s own code, only on [0086]'s. Independent of [0091], which fixes a
different failure on the same rows.

## Addendum: what landed, one correction to "already-correct", and real builds

`natmod/build.py`'s `run_make()` now calls `targets.natmod_toolchain(tag, arch)` — a
`(tag, arch) -> (cross, version) | None` lookup, `None` meaning this arch needs no fetch at all
(native `x86`/`x64` on `natmod_host`; `xtensawin`/`xtensa`, whose images still bake a single
toolchain, see [0086]'s own addendum for the live verification behind that "no" for `xtensawin`
specifically). When it is not `None`, `run_make()` wraps its own `make` command in one `bash -c`
script exactly the way [0087] wires `build_rp2()` — fetch, then (for `riscv_embedded` only)
`toolchain_fetch.rename_prefix_script()`, then `export PATH=`, then the real command — and mounts
the fetched cache directory alongside its existing `mpy_dir`/`package_dir` mounts. `run_make()`/
`build_target()` both gained a `toolchain_root: Path | None = None` parameter purely so a test can
redirect the fetch away from the real, shared `sources.cache_root()` — no real caller passes
anything but `None` today.

**This record's own "using `natmod`'s existing, already-correct `gcc` column values... a
rename/re-read, not a re-derivation" was wrong for `rv32imc`/`rv64imc`.** Building
`resources/pinned_toolchains.toml` ([0086]'s own addendum) meant verifying every value against its
real publisher rather than trusting `build-platforms.toml`'s own column, and that caught a real
mismatch: those rows recorded `gcc = "14.3.0-1.1"`, a tag `riscv-none-elf-gcc-xpack` has never
published (its own release-suffix scheme is bare `-1`/`-2`, not `arm-none-eabi`'s `-1.1`). Fixed
directly in `build-platforms.toml` (13 rows, `"14.3.0-1.1"` → the real `"14.3.0-1"`) rather than
carried into the pin table as a value nothing would ever successfully fetch.

**Verified for real** — no Docker daemon needed, the same reasoning [0087]'s own addendum gives:
built `examples/natmod/features0` for both `ARCH=armv7emsp` (the real `arm-none-eabi-gcc`
`15.2.1-1.1` tarball, fetched live) and `ARCH=rv32imc` (the real `riscv-none-elf-gcc` `14.3.0-1`
tarball, fetched live, `rename_prefix_script()`'s own symlinks confirmed present and pointing at
the real binaries before the build ran) against `v1.29.0` — both produced a real `.mpy`
(`arch: EM_ARM`/`arch: EM_RISCV`, real `LINK`/`GEN` output), not a smoke test against a stub
toolchain.

**What this still does not fix, unchanged from this record's own text above:** `mpy-cross` on
these two images' own native compiler for pre-`v1.26.0` tags is [0091]'s own territory, not
touched here. And `bin/refresh_toolchain_pins.py`'s own `--check` is now checking nothing for
either image (see [0087]'s own addendum) — [0090], not fixed by this record either.

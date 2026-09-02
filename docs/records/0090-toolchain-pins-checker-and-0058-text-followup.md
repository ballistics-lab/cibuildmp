# 0090 — the checker stops reading a Dockerfile `ARG`, and [0058]'s own text gets its correction

Status: Proposed — blocked on [0087]; not implemented.
Related: [0058], [0077], [0085], [0087]

## Three things [0085] named and none of the implementation records above cover

**1. `bin/refresh_toolchain_pins.py` reads the version straight out of the Dockerfile.**
`DOCKERFILE_PIN` maps `arm_embedded`/`riscv_embedded` to their Dockerfile paths, and
`current_dockerfile_pin()` regexes `DOCKERFILE_VERSION_RE` (`xpack-\S+?-gcc-xpack/releases/
download/v([\d.]+)`) against the file text to learn the currently-baked version. [0087] deletes
the `ARG TOOLCHAIN_URL=` line that regex matches, so this function has nothing left to read once
[0087] lands. It needs to resolve the per-row `toolchain_version` field directly instead — the
same fact every other per-row check in this script already reads, not a new kind of lookup.

**2. The board-scoped floor problem, named directly in [0085] as a reason a naive fix would be
worse than the bug it catches.** `stm32`'s own `>= 14.3` floor (`$(error ... upgrade to GCC
14.3+ ...)` for Cortex-M55) fires only under `MCU_SERIES=n6`, and there is no N6 board among
`stm32`'s 1016 rows today. `refresh_toolchain_pins.py` resolves per `(tag, scope)`, not per board,
so once a `toolchain_version` old enough to violate that floor is chosen (which [0087] does, for
the pre-`v1.26.0` tags), `--check` would start reporting a floor violation that is not real for
any board that actually exists — and a permanently red `--check` is worse than the bug it exists
to catch. This record scopes teaching the checker to express "this floor applies to
`MCU_SERIES=n6` only" rather than to every row in the scope.

**3. [0058]'s own headline stops being true for this image group, and CLAUDE.md's own standing
rule says that gets fixed in the same session as the record that causes it, not left for a later
reader to trip over.** "Image groups are toolchains, not ports" is [0058]'s own title; under
[0087] the `arm_embedded`/`riscv_embedded` group stops encoding a single toolchain version at
all — the version is now a row fact, the same as `esp32`'s `idf_version`. [0085] already flagged
this as "a revision to state in [0058]'s own text, not a silent drift." This record is that
revision, plus regenerating `docs/reference/vendored-images.md`'s own mapping table
(`bin/refresh_docs.py`, [0077]'s machinery — a test already fails on staleness here) and grepping
`README.md`/`docs/reference/design.md` for any prose still describing `arm_embedded` as a single
baked-toolchain image, per CLAUDE.md's own repeated instruction on narrative docs surviving the
record that obsoletes them.

## Why this is one record and not three

All three are checker-and-docs follow-up to the same landing ([0087]), touch none of the same
files [0086]-[0089] touch, and none is large enough alone to be worth separately motivating —
unlike [0088]/[0089], which are each a real, independently verifiable code change to a build
path. Splitting further here would be the record-per-line-item CLAUDE.md's own tracker convention
already warns against ("a row that needs a sentence to explain itself is a record whose title
needs fixing").

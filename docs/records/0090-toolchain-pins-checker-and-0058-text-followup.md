# 0090 — the checker stops reading a Dockerfile `ARG`, and [0058]'s own text gets its correction

Status: Implemented in part — items 1 and 3 landed 2026-09-04 (this record's own addendum). Item
2 (the board-scoped floor) stays deliberately unimplemented: confirmed live, this session, that
it does not fire a false positive today (no `MCU_SERIES=n6` board exists in `stm32`'s own rows,
and every value [0087] actually chose already sits above the `14.3` floor regardless), so
building a feature this project has no real row to test it against is exactly the "leave it
theoretical rather than relying on it" [0085] itself already argued for. Revisit if an n6 board
is ever added.
Related: [0058], [0077], [0085], [0087], [0088], [0096]

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

## Addendum, 2026-09-04 — items 1 and 3, landed alongside [0096]

Picked back up while landing [0096] (merging `arm_embedded`/`riscv_embedded` into
`embedded_base`), which made item 1's own gap worse in a way this record had not anticipated:
[0087] had already made `current_dockerfile_pin()` read nothing at all (the regex it needs was
already gone), so `--check` was not just stale, it was silently a no-op — `exit 0`, "ok",
regardless of what `build-platforms.toml` actually held. Confirmed live before touching
anything: a deliberately broken `mimxrt` `v1.20.0` row (`gcc = "13.3.1-1.1"`, [0088]'s own first
wrong answer) passed `--check` clean.

**Item 1.** `bin/refresh_toolchain_pins.py`'s `DOCKERFILE_PIN`/`DOCKERFILE_VERSION_RE` are gone.
`current_row_pin()` reads `build-platforms.toml`'s own committed `gcc` field for the exact
`(scope, tag)` being checked instead — real per-row validation, not a stale shared-pin
comparison. Re-verified against the same deliberately-broken row: `--check` now exits 1 and
names it (`v1.20.0 usermod.mimxrt: pinned 13.3.1 >= ceiling 13`), then clean again once
restored. This surfaced a second bug [0096] itself would have shipped otherwise: natmod's own
`arm_embedded`/`riscv_embedded` families both resolve to the merged `embedded_base` image now,
so grouping this checker's own natmod rows by *image* (as item 1's own original text assumed)
would have silently conflated two different `gcc` facts into one scope. Fixed the same way
[0096] fixed the identical class of bug in `natmod/targets.py`'s own `natmod_toolchain()`: a
direct `arch -> toolchain family` table (`NATMOD_ARCH_FAMILY`), not the image name.

**Item 3.** [0096]'s own commits already regenerated `docs/reference/vendored-images.md`'s
mapping table and corrected `README.md`/`docs/reference/design.md`'s prose (group counts, the
`arm_embedded`/`riscv_embedded` names, [0077]'s own generator). What [0096] had not yet done —
because it is [0058]'s own text, not [0096]'s — is [0058] acknowledging its own headline no
longer holding for this group; added as [0058]'s own dated correction, in the same session as
this addendum, per CLAUDE.md's own standing rule.

**Item 2 stays open** — see this record's own Status line above.

# 0091 — `TAG_CFLAGS` reaches every port's `mpy-cross`, not just `unix`'s

Status: Implemented. **Local live verification found one real bug in the initial landing**,
fixed in the same pass — see its own addendum below.
Related: [0010], [0082], [0084], [0085], [0087], [0089], [0092]

## Why this is not covered by [0087]/[0089]

`arm_embedded`/`riscv_embedded` are both `FROM ubuntu:26.04`. [0084] measured, live, that this
exact base's `apt build-essential` resolves to **gcc 15.2.0-16ubuntu1** — the same compiler
already confirmed to break `natmod_host`'s `x64`/`x86` and `windows`'s own
`container_mpy_cross()` on [0082]'s nine pre-`v1.26.0` tags
(`-Werror=unterminated-string-literal`). `container_mpy_cross()` (`build_common.py`) always
builds `mpy-cross` with whatever `gcc` the *image's own native* `PATH` resolves to — never the
row's cross toolchain — for every port sharing that image, `natmod`'s own arm/riscv cross arches
and all seven `arm_embedded`-family `usermod` ports (`rp2`, `stm32`, `samd`, `nrf`, `cc3200`,
`renesas-ra`, `mimxrt`) alike. So moving the *cross* xpack version into a row fact ([0087],
[0089]) does nothing for this: `mpy-cross` fails before the cross compiler is ever invoked, the
same way [0084] found it fails before `ports/unix`'s own `make` runs.

[0082] already named this precisely as unverified rather than assumed-fine: confirmed against
`natmod_host`/`windows`, explicitly **"not independently checked against `unix`/`webassembly`/
`esp32`/`rp2`"** — and `rp2` sits on `arm_embedded` today. This is therefore not a risk this
project's own upcoming changes introduce; it is a live, unverified suspicion about the *current*
tree, independent of [0086]-[0090] landing or not.

## What already exists to build on

[0084] landed this for `unix` alone (commit `0f3038c`): `build_common.TAG_CFLAGS`, keyed by tag,
reaches both `container_mpy_cross()` and the port's own make invocation. `unix_extra_cflags()`
gained an optional `tag` parameter for this. The mechanism is generic already — what is missing
is every *caller* outside `build_unix.py` passing its own row's tag through to
`container_mpy_cross()`.

## Verified live, 2026-09-02/03 — the thing [0082] left unchecked

Dispatched `test-platforms.yml` directly (run `33697330722`, branch `claude/what-next-mu1m60`,
`package-dir: examples/template`) against `natmod`'s own `armv7emsp` (`arm_embedded`) and
`rv32imc`/`rv64imc` (`riscv_embedded`) identifiers. **One mechanism worth recording before the
result**: a `--build` glob like `mpy*-v*-armv7emsp` does not select every matching tag —
`selector_names_a_tag()` (`natmod/targets.py`) sees no literal `v\d+\.\d+` shape in it, so
`narrow_to_newest_tag()` keeps only the newest tag *per `(abi, arch, arch_flags)` group*, and the
dispatch actually built one representative tag from each of the five ABIs (`5`, `6`, `6.1`,
`6.2`, `6.3`) rather than all nineteen tags. **An explicit multi-tag list is not the fix, and is
not just a glob quirk to route around**: `[natmod]`'s own `artifacts_dir_name =
"{name}-{ver}-mpy{abi}-{arch}..."` keys the output path on `abi`, not `tag`, so two different
tags sharing one ABI in the same invocation would write into the same output directory —
building several tags per ABI at once is a real collision, not merely something the selector
happens to collapse. A genuine full-history sweep needs one invocation per tag (as
`test-upstream-natmod.yml`'s own per-tag jobs already do), not a single wider `--build`.

**Result, exactly matching the hypothesis:**

| identifier | tag family | outcome |
| --- | --- | --- |
| `mpy5-v1.18-armv7emsp` | ABI 5 (pre-`v1.26.0`) | **failed** — `mpy-cross` exit 2 |
| `mpy6-v1.19.1-armv7emsp` | ABI 6 (pre-`v1.26.0`) | **failed** — `mpy-cross` exit 2 |
| `mpy6.1-v1.21.0-armv7emsp` | ABI 6.1 (pre-`v1.26.0`) | **failed** — `mpy-cross` exit 2 |
| `mpy6.2-v1.22.2-armv7emsp` | ABI 6.2 (pre-`v1.26.0`) | **failed** — `mpy-cross` exit 2 |
| `mpy6.3-v1.29.0-armv7emsp` | ABI 6.3 (post-`v1.26.0`) | built clean, 0.7s |
| `mpy6.3-v1.29.0-rv32imc` | ABI 6.3 (post-`v1.26.0`) | built clean, 21.9s |
| `mpy6.3-v1.29.0-rv64imc` | ABI 6.3 (post-`v1.26.0`) | built clean, 0.6s |

The failing build's own compiler output is the exact diagnostic [0082]/[0084]/[0085] already
named for `natmod_host`/`windows`, now confirmed live on `arm_embedded`'s own native compiler
too (`mpy6.2-v1.22.2-armv7emsp`'s log, representative of all four failures):

```
../py/emitinlinethumb.c:383:24: error: initializer-string for array of 'unsigned char' truncates
  NUL terminator but destination lacks 'nonstring' attribute (3 chars into 2 available)
  [-Werror=unterminated-string-initialization]
cc1: all warnings being treated as errors
make: *** [../py/mkrules.mk:90: build/py/emitinlinethumb.o] Error 1
```

So this is not a theoretical risk `arm_embedded`/`riscv_embedded` might share — every
pre-`v1.26.0` ABI tested failed `mpy-cross` on this image family today, live, independent of
[0086]-[0090] landing or not. [0082]'s own "not independently checked against ... `rp2`" gap is
closed: it reaches `rp2` (and every other `arm_embedded`-family port) exactly as predicted.

## What this record scopes, and what landed

1. ~~Verify live, first~~ **Done above.**
2. ~~Thread `tag` through every non-`unix` caller of `container_mpy_cross()`~~ **Done.**
   `Esp32BuildOptions`/`Rp2BuildOptions`/`WebassemblyBuildOptions`/`WindowsBuildOptions` all gained
   a `tag: str = ""` field (mirroring `UnixBuildOptions.tag`), populated from `target.tag` in
   `orchestrate.py`'s `_port_build_options()`; each port's own `*_make_command()` now passes
   `CFLAGS_EXTRA=` from `build_common.tag_cflags(opts.tag)` **and** each `container_mpy_cross()`
   call passes the same as `extra_cflags=` — both, not just `mpy-cross`, because every one of
   these ports recompiles `py/` into the firmware/module itself (unlike `natmod`'s own per-target
   build, which never does — see below). `natmod`'s own `build_mpy_cross(mpy_dir, arch, tag="")`
   gained the same parameter and passes `CFLAGS_EXTRA=` into its one `make` invocation only,
   called with `tag=tag` from `natmod/__init__.py`'s own per-ABI-group loop — no change to
   `make_command()` (the module's own per-target build), since `dynruntime.mk` never recompiles
   `py/`, only the module's own sources against an already-built `mpy-cross`.

   **One correction made in passing, found reading `dockerrun.py` before writing any of this**:
   [0084]'s own root-then-drop-to-uid/`HOME`-relocation machinery does not apply anywhere here —
   `dockerrun.run()` already passes `--user {uid}:{gid}` unconditionally on every invocation, so
   there is no root step to drop from in the first place. That machinery was specific to
   [0084]'s own decision to `apt-get install` at every `unix` invocation against a bare
   `ubuntu:26.04`; nothing here does that.

   **A second, adjacent fix, not scope creep**: `build_windows()`'s own docstring claimed
   "mpy-cross is not built here... `sources.build_mpy_cross()` already builds a native one" —
   directly contradicted by the `container_mpy_cross()` call four lines below it (stale since
   [0044] moved `windows` onto that path). Corrected in the same edit, since leaving a
   docstring wrong right next to the code it was inaccurate about is exactly what CLAUDE.md's own
   top rule warns against noticing and not fixing.
3. ~~Leave the underlying `TAG_CFLAGS` table itself as `unix`'s own entries only~~ **Superseded,
   not just left alone.** No new diagnostic was found (`arm_embedded` hits the identical
   `-Werror=unterminated-string-initialization`), so the *entries* are unchanged — but the table
   itself moved out of `usermod/build_common.py` entirely, for two reasons landing together:
   - **The one-way dependency.** `natmod`'s own `build_mpy_cross()` needs `tag_cflags()` too, and
     `natmod` never imports `usermod`. `sources.py` — the module both families already import
     `fetch_micropython()`/`read_mpy_abi()` from — is the shared home now;
     `usermod/build_common.py` re-exports `TAG_CFLAGS`/`tag_cflags` unchanged so no existing
     caller's import line needed to move.
   - **[0010], raised directly during this work**: once a tag-keyed fact is confirmed (this
     record's own live verification) to mean "in any port", it stops being resolver logic
     specific to one platform and becomes exactly the "goes stale on someone else's schedule"
     data [0010] already has a rule for. `TAG_CFLAGS` is now `resources/tag_cflags.toml`
     (`resources.tag_cflags_data()`), the same escape from a Python dict literal
     `pinned_docker_images()`'s own docstring already documents for that table's history under
     [0043]. **Deliberately not folded into `build-platforms.toml`'s own `[tags]` table**, even
     though that table is the obvious-looking home (already tag-keyed, already shared across
     every section): `bin/refresh_natmod_archs.py`/`bin/refresh_usermod_boards.py` both
     regenerate `[tags]` from scratch on every run (`entry = {"sha": sha, "date": ...}`, no
     `carry_forward()` call for it, unlike the row-level facts those same scripts do protect) —
     adding `cflags` there without teaching both scripts to preserve it would make the next
     tag-refresh silently drop every entry. A real follow-up if the duplication (two tag-keyed
     tables in two files) is worth closing later; not bundled into this record.

## Ordering relative to the other `arm_embedded` records

Independent of [0086]'s fetch mechanism and orthogonal to whether [0087]/[0089] have landed —
this fixes the *native* compiler's use in `mpy-cross`, they fix the *cross* compiler's pin. Doing
this first would make more of [0087]/[0089]'s own boundary-sample verification meaningful (a
`mpy-cross` failure caused by this gets misread as a cross-toolchain problem otherwise); doing it
after is also fine functionally, just noisier to debug in the meantime.

## Addendum, 2026-09-03 — a real bug the CI verification did not reach, found by building locally

CI (the `Verified live` section above) exercised `natmod`'s own arm/riscv arches; it never built a
`usermod` port through the actual fix, and the docker-local skill made a real local Docker daemon
available in this session, so every touched path got built for real rather than trusted from the
mocked test suite alone.

**`natmod`, `mpy6.2-v1.22.2-armv7emsp`** (the exact identifier CI showed failing before this
record's fix): `mpy-cross` now links clean, module builds, `.mpy` produced. **`usermod`,
`v1.20.0-rp2-PICO`** (the one tag with *two* stacked `TAG_CFLAGS` entries at once): a real,
complete `firmware-v1.20.0-rp2-PICO.uf2` (632832 bytes) — `rp2`'s own `CFLAGS_EXTRA` threading
into `rp2_make_command()`, not just `container_mpy_cross()`, confirmed working end to end, pico-sdk/
tinyusb/mbedtls included. **`natmod`, `riscv_embedded`**: `mpy6.3-v1.25.0-rv32imc` built clean
(`mpy6.3-v1.24.0-rv32imc` hit an unrelated, real upstream fact instead — `dynruntime.mk` itself
does not support the `rv32imc` natmod arch until `v1.25.0`, confirmed by that row's own missing
`cross` field in `build-platforms.toml` for `v1.24.0`/`v1.24.1` — nothing to do with this record).

**`windows`, `v1.20.0-win_arm64`: real failure, not a false alarm.**

```
error: unknown warning option '-Werror=dangling-pointer' [-Werror,-Wunknown-warning-option]
```

`win_arm64`'s own cross compiler is Clang (`llvm-mingw`), the one project-owned image mixing
compiler families: `win32`/`win_amd64` cross-compile with real, apt-installed GCC, `win_arm64`
with Clang, in the same `docker/windows.Dockerfile`. `tag_cflags()`'s own
`-Wno-error=dangling-pointer` (`v1.20.0`) is a GCC-only diagnostic name — Clang's response to a
name it does not recognize is a hard `error: unknown warning option`, not a no-op, exactly the
failure class `probe_supported_cflags()`'s own docstring already documents for `unix`'s pypa gcc
ladder. Every other port this record touches shares one compiler family per image (`arm_embedded`/
`riscv_embedded`/`natmod_host`/`esp_idf_base`: real GCC throughout; `webassembly`'s own `emcc` —
also Clang-based — was checked live too and accepts both flags fine, so this is not "every Clang
fails," specifically llvm-mingw's own bundled version does not know this GCC-specific name)
— `windows` alone needed the fix.

**Fixed the same way `unix` already solves it**: `windows_make_command()` gained a
`windows_raw_cflags()` helper (the unprobed candidate list: `settings.extra_cflags` + `tag_cflags()`)
and an `extra_cflags` override parameter, mirroring `unix_make_command()`'s own shape exactly.
`build_windows()` now probes that candidate list against the real cross compiler
(`probe_supported_cflags(..., compiler=f"{cross_compile}gcc")`) before it ever reaches the make
command line — `container_mpy_cross()`'s own `extra_cflags=` stays unprobed, since mpy-cross always
builds with the image's *native* compiler (real GCC here, matching every other port's unprobed
native build). Re-verified after the fix: `v1.20.0-win_arm64` was not re-run to completion locally
(the probe alone was enough to confirm the flag list it produces no longer contains
`-Wno-error=dangling-pointer`, and `test_usermod_build_windows.py`'s own updated tests cover the
probing call shape) — a live full build is exactly what [0091]'s own CI coverage should widen to
next, since neither this record's CI run nor `test-upstream-usermodule.yml` builds `win_arm64`
today.

**What this changes about trusting the rest of this record's own "no probing needed" claims,
stated plainly rather than left implicit**: every other claim above was verified by a real build
succeeding, not by reasoning about compiler families in the abstract — `webassembly`'s own Clang
fork was checked live specifically because `windows` had just falsified the assumption once. Two
project-owned images were not exercised at all in this pass: `esp32` (ESP-IDF's own crosstool-NG
GCC, blocked locally by this sandbox's own proxy CA on the tool downloader, unrelated to this
record — see [0092]'s own addendum) and `mimxrt`'s own separate concern ([0088], unrelated to this
fix). Both are real GCC toolchains by the same reasoning that already held for `arm_embedded`/
`riscv_embedded`, but "by the same reasoning" is exactly the kind of claim this addendum exists to
warn against trusting without a live build behind it.

**`unix`, `v1.22.2-manylinux_2_28_x86_64`, `examples/usercmodule` (C++ included) — the case
`rp2`/`esp32`'s own sandbox-blocked runs couldn't reach.** Requested directly once `windows`'
Clang failure raised the question of whether a real C++ compile on an old tag could surface
something `examples/template`'s trivial C never would. `unix` has no build-time network
dependency of its own (no `picotool`/ESP-IDF fetch), so this ran clean where `rp2`/`esp32` hit
this sandbox's own proxy limits. All three of upstream's own modules confirmed compiled and
linked, not just present in the log: `Including User C Module from .../cexample`,
`.../cppexample`, `.../subpackage`, `CC .../cexample/examplemodule.c`,
`CXX .../cppexample/example.cpp` (real C++, not just a `.c` file with a `.cpp`-looking name), `CC
.../subpackage/modexamplepackage.c` — followed by a clean `LINK`, a real
`micropython-v1.22.2-manylinux_2_28_x86_64` binary, 672376 bytes. `unix` already had
`probe_supported_cflags()` before this record (record 0084) precisely because pypa's own images
span a real gcc version ladder, so this was the one port already defended against exactly the
class of failure `windows` turned out to have; this run confirms that defense still holds with
[0091]'s own tag threading in place, C++ included, not just that it holds in the abstract.

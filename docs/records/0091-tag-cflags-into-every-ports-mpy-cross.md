# 0091 — `TAG_CFLAGS` reaches every port's `mpy-cross`, not just `unix`'s

Status: Proposed — scoped, not implemented outside `unix`.
Related: [0082], [0084], [0085], [0087], [0089]

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

## What this record scopes

1. **Verify live, first** — the thing [0082] left unchecked — whether `rp2`'s (or any
   `arm_embedded`-family port's) `mpy-cross` build actually fails on a pre-`v1.26.0` tag today,
   before assuming the fix is needed everywhere the theory predicts it.
2. **Thread `tag` through every non-`unix` caller of `container_mpy_cross()`** — `natmod`'s own
   build drivers and every `usermod` port's `build_<port>.py` — the same way `build_unix.py`
   already does, so `TAG_CFLAGS` reaches `mpy-cross` regardless of which image or port is
   building it.
3. **Leave the underlying `TAG_CFLAGS` table itself as `unix`'s own `v1.20.0` entry only**, unless
   step 1's verification finds a *different* diagnostic on a different port — [0082]'s own
   nine-tag boundary was measured against `unix`/`natmod_host`/`windows` specifically
   (`-Werror=unterminated-string-literal`), and a new port hitting it is expected to be the same
   diagnostic, not assumed to be.

## Ordering relative to the other `arm_embedded` records

Independent of [0086]'s fetch mechanism and orthogonal to whether [0087]/[0089] have landed —
this fixes the *native* compiler's use in `mpy-cross`, they fix the *cross* compiler's pin. Doing
this first would make more of [0087]/[0089]'s own boundary-sample verification meaningful (a
`mpy-cross` failure caused by this gets misread as a cross-toolchain problem otherwise); doing it
after is also fine functionally, just noisier to debug in the meantime.

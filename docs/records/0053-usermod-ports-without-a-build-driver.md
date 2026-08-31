# 0053. usermod ports with verified facts but no build driver

- Status: Not scheduled
- Related: [0052], [0022]

## What this is

`resources/build-platforms.toml` has independently-verified `(tag, arch/board)`
rows, walked by `bin/refresh_usermod_boards.py` against real MicroPython
checkouts, for fifteen usermod ports. `platforms/usermod/targets.py`'s own
`KNOWN_PORTS` only wires five of them (`unix`, `windows`, `qemu`, `webassembly`,
`esp32`) — the five with a real `build_<port>()` driver in
`platforms/usermod/build.py`. The other ten have verified identifiers a config
can already *name* (they exist as facts) but nothing to actually build them:

`rp2`, `mimxrt`, `samd`, `stm32`, `psoc-edge`, `alif`, `esp8266`, `cc3200`,
`renesas-ra`, `nrf`.

Surfaced while closing [0052]'s own Track C, Phase C2 (usermod's real-row
target model) — see that record's closing addendum for the live-caught
context. Flagged directly by the user as the genuinely larger remaining
piece of work, distinct from any config-surface question:

> Набагато важливішим і складнішим буде дописати решту білд пайплайні для
> всього списку фактів

`rp2` is a partial exception: it already has its own tracker row under
[0022] (the zephyr epic), which separately notes "`rp2`'s own build driver
not started." Not duplicated here — [0022] stays the record of record for
`rp2` specifically; this one covers the other nine, plus notes the overlap
so a future session doesn't schedule the same work twice under two numbers.

## Why this is bigger than it looks

Each of the ten is a genuinely separate build pipeline, not a config
addition over the existing five-port `_BUILD_FN` table: a real toolchain
(host-provisioned or a new Docker image), a real `USER_C_MODULES`/manifest
convention for that port, and a real verified build command — the same
amount of work `unix`/`windows`/`webassembly`/`qemu`/`esp32` each already
took, per port. Record 0052's own Track B research (before Track B itself
was reverted, see that record's later addenda) found eleven of MicroPython's
ports could plausibly share one image and toolchain investment
(`qemu` partially, `mimxrt`, `samd`, `stm32`, `psoc-edge`, `cc3200`,
`renesas-ra`, `nrf`) — a real head start if this is picked up, not a reason
to treat it as small.

## Not decided here

Which port(s) go first, what a shared-image grouping should look like in
practice, and whether any of the ten need their own record before code
starts (the existing five each got one, per port, when they landed) are all
open. This record exists to give the tracker item its own number and a
place to grow, not to answer those questions.

[0022]: 0022-zephyr-third-selector-axis.md
[0052]: 0052-config-is-a-tree-not-a-selector-matrix.md

## Correction, 2026-08-31 — `rp2` is not one of these ports

This record lists `rp2` among the ports with verified rows and no driver, and
its own §27 defers to [0022] for it. Both are out of date: [0060] shipped
`build_rp2()`, and `usermod/targets.py`'s `KNOWN_PORTS` has held six entries
including `rp2` since. The real list here is **nine** ports, not ten:
`mimxrt`, `samd`, `stm32`, `psoc-edge`, `alif`, `esp8266`, `cc3200`,
`renesas-ra`, `nrf`.

The tracker's own conventions call this exact claim out as a repeat offender,
and [0022]'s status line was corrected while this record's was not.

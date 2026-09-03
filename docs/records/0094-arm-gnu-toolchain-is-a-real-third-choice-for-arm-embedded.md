# 0094 — Arm's own GNU toolchain registry is the third choice [0085] said did not exist

Status: Proposed — verified this session against real downloads and real builds; no Dockerfile
or config changed. Corrects [0085]'s own claim rather than replacing its decision.
Related: [0058], [0084], [0085], [0086], [0087], [0088], [0090]

## What [0085] claimed, and what it actually checked

[0085]'s own text: *"the real release list, which goes `13.3.1-1.1`, `14.2.1-1.1`,
`15.2.1-1.1`. So `14.2.1` violates the newer floor and `15.2.1` violates the older ceiling;
**there is no third choice**."* That statement is true of xpack's own ladder — the only
publisher checked. Arm publishes its own GNU toolchain independently of xpack, at
`gitlab.arm.com/tooling/gnu-toolchains-for-arm` (the successor to the now-frozen
`developer.arm.com` downloads page — its `15.3.rel1` tarball already 404s there while the
gitlab registry serves it fine, confirmed live this session). Its branch listing
(`releases/11.2-2022.02` through `releases/15.3.rel1`) is finer-grained than xpack's own:
`12.2`, `12.3`, `13.2`, `13.3`, `14.2`, `14.3`, `15.2`, `15.3` — a `14.3` rung xpack's own
ladder skips entirely (xpack goes straight `14.2.1` → `15.2.1`).

## Verified, not assumed

- Downloaded `x86_64-arm-none-eabi` tarballs for `12.3.rel1` through `15.3.rel1` from
  `gitlab.arm.com/api/v4/projects/tooling%2Fgnu-toolchains-for-arm/packages/generic/`
  `gnu-toolchain/<version>/arm-gnu-toolchain-<version>-x86_64-arm-none-eabi.tar.xz` — no auth
  needed — and checked sha256 against Arm's own `.sha256asc` sidecar at the same path.
  `14.2.rel1` (`62a63b98…8823`) and `15.3.rel1` (`563bebb2…b5fa`) both match Arm's published
  value exactly.
- Built [docker/arm_embedded.Dockerfile](../../docker/arm_embedded.Dockerfile) **unmodified** —
  only `--build-arg TOOLCHAIN_URL=…tar.xz --build-arg TOOLCHAIN_SHA256=…` pointed at Arm's
  registry instead of xpack's GitHub releases. `.tar.xz` + `--strip-components=1` extracts the
  same way `.tar.gz` does; `xz-utils` is already in the file's own apt layer. Three images built
  this way: Arm `14.2.rel1`, `14.3.rel1`, `15.3.rel1`.
- `arm-none-eabi-gcc -print-multi-lib` diffed **byte-for-byte identical** between the published
  `arm_embedded` image (xpack `15.2.1`) and the locally-built Arm `14.2.rel1` image — 39
  multilibs, same set. Every tool `usermod`/`natmod` invoke (`gcc`, `g++`, `ld`, `as`, `ar`,
  `objcopy`, `objdump`, `size`, `nm`, `readelf`, `strip`, `ranlib`) present in Arm's tarball;
  `libstdc++.a`, newlib's `libc.a`, and `include/c++/<ver>/` all present, the same set
  `arm_embedded.Dockerfile`'s own comment already checks xpack for.
- Real builds, not smoke tests:
  - natmod, all four `arm_embedded`-scoped arches (`armv6m`/`armv7m`/`armv7emsp`/`armv7emdp`)
    across five tags (`v1.18`–`v1.29.0`) on Arm `14.2.rel1` and `14.3.rel1`: **19/20 pass**. The
    one failure (`v1.18`+`armv6m`) is `py/dynruntime.mk:96: architecture 'armv6m' not supported`
    — upstream's own file, at that tag, unrelated to the toolchain (reproduced identically
    against the *published* xpack image, same failure).
  - `examples/template` on `usermod.rp2`, `BOARD=RPI_PICO`: `v1.29.0` produces a real
    `firmware.uf2` on `14.2.rel1` (684544 B), `14.3.rel1` (684544 B), `15.3.rel1` (680960 B). A
    raw `make` (no cibuildmp, no user modules) at `v1.24.1` — the oldest tag under [0085]'s own
    `>=15.1` ceiling window — succeeds identically on the published xpack `15.2.1` image and on
    Arm `14.2.rel1`/`14.3.rel1`, producing a `.uf2` every time.

## What this corrects in the checker's own numbers

Simulated against `bin/refresh_toolchain_pins.py`'s own `resolve_row()`/`real_rows()` — the
checker's own comparator, not a re-derivation — across every `arm_embedded`-scoped row:

| shared pin | violations remaining |
| --- | --- |
| xpack `15.2.1` (today's Dockerfile pin) | 89 |
| xpack/Arm `14.2.1` | 7 |
| xpack `13.3.1` | 7 |
| Arm `12.3.1` (`12.3.rel1`) | 6 |
| **Arm `14.3.1` (`14.3.rel1`)** | **1** |

**`14.2.1` does not close all 89 — it leaves seven.** One is `usermod.mimxrt`'s `v1.20.0`
ceiling ([0088]'s own row, `<13`, which no pin above `13` can ever satisfy). The other six are
`usermod.stm32` floor violations (`v1.26.0` through `v1.30.0-preview`), each needing `>=14.3` for
the Cortex-M55/N6 guard `tools/ci.sh`'s own `ci_stm32_setup` already pins toward — `14.2.1` sits
one rung below that floor. Only the finer-grained Arm ladder's `14.3.1` clears both windows at
once: inside `stm32`'s `>=14.3` floor, still under every pre-`v1.26.0` tag's `<15.1` ceiling —
leaving `mimxrt` as the sole remaining violation, exactly the one [0088] already scopes a
disjoint per-row fix for.

## What this does not change

- **No Dockerfile edit landed.** This is evidence for [0087]/[0088]'s own eventual per-row
  `toolchain_version`, and a candidate *shared*-pin bump (`14.3.rel1`) worth weighing against
  [0086]'s per-row mechanism on its own merits — not a decision made here between them.
- **`riscv_embedded` is untouched and unverified against Arm's own registry.**
  `gitlab.arm.com`'s package registry has no `riscv-none-elf` product under this project's own
  name pattern (`404`, checked live); [docker/riscv_embedded.Dockerfile](../../docker/riscv_embedded.Dockerfile)
  stays on xpack regardless of what this record finds for `arm_embedded`. RISC-V's own
  equivalent check is deferred, not answered here.
- **The `stm32` floor is still board-scoped, not row-scoped** — [0090]'s own open item
  (`MCU_SERIES=n6`, no such board exists among today's 1016 `stm32` rows) is unaffected by which
  toolchain answers it.

# 0088 — `mimxrt`'s own `>= 13` ceiling gets its own `toolchain_version` row, once [0087] exists

Status: Implemented — landed 2026-09-04, once [0087] existed. `mimxrt`'s eleven `v1.20.0` rows
carry `gcc = "12.3.1-1.2"` (the addendum's own corrected value, not this record's first, wrong
one), pinned for real in `pinned_toolchains.toml`, and `bin/refresh_toolchain_pins.py --check`
now validates it directly ([0090]'s own item 1).
Related: [0084], [0085], [0087], [0090]

## The one violation the other six ports' fix does not reach

[0085] counted 71 real `(tag, port)` ceiling violations under the current shared `arm_embedded`
pin. Seventy are one fact — the shared xpack `15.2.1-1.1` pin exceeds every pre-`v1.26.0` tag's
`>= 15.1` ceiling — and [0087] answers all seventy by letting each row name its own
`toolchain_version` instead of inheriting the image's pin. The 71st is `mimxrt`'s own extra
combination: a floor of `>= 13` that the same `14.2.1`/`15.2.1` choices both exceed, and that no
single shared pin — old or new — could ever satisfy alongside the other six ports' own ceilings.
[0085] named this explicitly as **not solved** by its own main decision.

## What this record is

Small and mechanical, once [0087]'s per-row mechanism exists: `mimxrt`'s own affected rows name
`toolchain_version = "13.3.1-1.1"` (xpack's own real published release nearest that floor,
confirmed against the release list [0085] already checked) instead of whatever [0087] resolves
for the other six ports. No new mechanism, no Dockerfile change beyond what [0087] already makes
— this is a config-row change plus whatever `bin/refresh_toolchain_pins.py` follow-up ([0090])
is needed so the checker accepts a genuinely different per-row value in the same image group
without flagging it as a new kind of violation.

## Why this is its own record rather than a line inside [0087]

[0087] closes 70 of 71 violations with one mechanism and one value per non-`mimxrt` row;
`mimxrt` needs a *different* value, is the one case [0085] itself calls out as "the first case
where the per-row selector earns itself rather than duplicating a group name" — worth landing as
its own commit, separately verified, rather than bundled into [0087]'s larger cutover.

## Addendum, 2026-09-03 — `13.3.1-1.1` is on the wrong side of the constraint

Found while answering a question about which `gcc-arm-none-eabi` versions this project actually
needs, by resolving it from the checker's own data rather than from this record's summary of it.

**The constraint is a ceiling, and it is exclusive.** `toolchains.toml`'s row is
`{ scope = "usermod.mimxrt", tool = "gcc", kind = "breaks-with", value = ">=13", detail = "This
updates the declaration of 'sdcard_cmd_set_bus_width()' ...", source = "0f0dcec98 ... first in
v1.21.0" }`. `bin/refresh_toolchain_pins.py` snaps a value inside `[floor, ceiling)` — its own
module docstring — and reports the violation as `pinned {v} >= ceiling {c}`. So the requirement is
**strictly below 13**, not "as close to 13 as possible".

**`13.3.1-1.1` does not meet it**, checked with the script's own comparator rather than by reading
the string:

```
parse_ver("13.3.1-1.1") -> (13, 3, 1)      < 13 ?  False
parse_ver("12.3.1-1.2") -> (12, 3, 1)      < 13 ?  True
```

Landing this record as written would leave its own violation exactly where it is, while looking
like it had been fixed — the worst shape for a one-row change nobody re-checks afterwards.

**Where the mistake came from, since it was not carelessness about the number.** [0085] records
the xpack release list as *"the real release list, which goes `13.3.1-1.1`, `14.2.1-1.1`,
`15.2.1-1.1`"*. That is a truthful *tail* — those are the three most recent — but it reads as the
whole list, and this record then picked "the nearest" from it. The real ladder
(`xpack-dev-tools/arm-none-eabi-gcc-xpack`, 25 published releases) has four below 13:
`12.2.1-1.1`, `12.2.1-1.2`, `12.3.1-1.1`, `12.3.1-1.2`, plus `13.2.1-1.1` between that group and
`13.3.1-1.1`.

**The value to land is `12.3.1-1.2`** — the newest xpack release below the ceiling. Its assets
exist in the shape `arm_embedded.Dockerfile`/[0086] need, verified rather than assumed:

| asset | |
| --- | --- |
| `xpack-arm-none-eabi-gcc-12.3.1-1.2-linux-x64.tar.gz` | 200 |
| `xpack-arm-none-eabi-gcc-12.3.1-1.2-linux-arm64.tar.gz` | 200 |
| `…-linux-x64.tar.gz.sha` | 200, `771dfb9d10e7339ac40f3a32be9cd287405c537ca0bf16e1dbf6fa6f1fc1dd2a` |

**Two wording fixes to make in the same commit as the eventual change**, because they are what
made the wrong value look right: this record's body calls the constraint a *floor* three times
while its own title correctly calls it a ceiling, and "xpack's own real published release nearest
that floor" is precisely the reasoning that selects a version *above* an exclusive ceiling. [0085]
inherits the same slip ("`mimxrt`'s own disjoint floor").

**One number aged, and it is not an error.** This record counts 71 violations, which was right
when it was written; [0084] later taught `refresh_toolchain_pins.py` about the
`natmod.arm_embedded`/`natmod.riscv_embedded` scopes, and `--check` now reports **92** (18
`natmod.arm_embedded`, 12 `nrf`, 12 `cc3200`, 11 `renesas-ra`, 9 each for `stm32`/`samd`/`rp2`, 8
`mimxrt` on the ordinary `15.1` ceiling, 3 `natmod.riscv_embedded`, and 1 `mimxrt` on the `13`
one). **`mimxrt`'s own share of the disjoint case is still exactly one row** — `v1.20.0`, the
first tag with `mimxrt` boards and the last before upstream's own fix — so nothing about this
record's scope changes, only the total it is one of.

Still `Proposed`, still blocked on [0087]. Nothing implemented here; this addendum only replaces
the value the implementation should use.

## Addendum, 2026-09-04 — landed, using this addendum's own corrected value

[0087] had long since landed by the time this record was picked back up. All eleven `mimxrt`
`v1.20.0` rows in `build-platforms.toml` now carry `gcc = "12.3.1-1.2"` (replacing
`14.2.1-1.1`, the ordinary shared value every other pre-`v1.26.0` row on this image got from
[0087]'s own general mechanism, which never special-cased `mimxrt`). `resources/
pinned_toolchains.toml` gets the real `["arm-none-eabi-"]."12.3.1-1.2"` entry, sha256 verified
live against the publisher's own `.sha` sidecar a second time (matches this addendum's own
table above, and the tarball itself, byte for byte). The orphaned `"13.3.1-1.1"` entry this
record's own first, wrong answer left behind -- never referenced by any real row -- is removed
rather than kept alongside the correct one.

Verified by the mechanism this record depends on existing: [0090]'s own item 1 landed in the
same session, so `bin/refresh_toolchain_pins.py --check` now reads `mimxrt`'s real, committed
`gcc` field directly and confirms `12.3.1-1.2` sits inside `[floor, ceiling) = (-, 13)` for
`v1.20.0` -- deliberately re-broken to `13.3.1-1.1` and re-checked first, to confirm the checker
actually catches the violation this record exists to prevent, not just that it runs clean
against an already-correct file.

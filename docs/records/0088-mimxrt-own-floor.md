# 0088 — `mimxrt`'s own `>= 13` ceiling gets its own `toolchain_version` row, once [0087] exists

Status: Proposed — blocked on [0087]; not implemented.
Related: [0085], [0087]

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

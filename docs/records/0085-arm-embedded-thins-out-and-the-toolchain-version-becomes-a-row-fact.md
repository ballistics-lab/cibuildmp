# 0085 — `arm_embedded` thins out: the toolchain version stops being the image's name and becomes a row fact

Status: Proposed — the constraint arithmetic and the sizes below are measured; nothing is
implemented.
Related: [0025], [0031], [0046], [0058], [0068], [0082], [0084]

## The problem, counted rather than described

`bin/refresh_toolchain_pins.py --check` exits 1 today with **71 real `(tag, port)` violations**, and
they are not seventy-one problems:

| port | combinations | ceiling |
| --- | --- | --- |
| `nrf`, `cc3200` | 12 each | `>= 15.1` |
| `renesas-ra` | 11 | `>= 15.1` |
| `stm32`, `samd`, `rp2` | 9 each | `>= 15.1` |
| `mimxrt` | 8 + **1** | `>= 15.1` and **`>= 13`** |

Seventy of them are one fact: `docker/arm_embedded.Dockerfile` pins xpack `15.2.1-1.1`, and every
tag before `v1.26.0` has a `>= 15.1` ceiling. Seven ports share that image ([0058]), so one pin
produces seventy rows of the same complaint.

**The ceiling has two distinct causes, and only one of them is a diagnostic.**
`toolchains.toml` records both: `Wunterminated-string-literal` under gcc 15.1 (scope `any` and
`mpy-cross`), and `rp2`'s own workaround for [pico-sdk#2448](https://github.com/raspberrypi/pico-sdk/issues/2448).
The first would yield to a `-Wno-error=` flag the way [0084]'s `v1.20.0` case did; the second is a
real build failure in a vendored SDK and would not. So the relaxation axis cannot substitute for a
correct toolchain here.

## Why "just repin it to 14.2.1" is the wrong shape, twice over

**First, because of what the name would then be lying about.** [0031] settled this for `unix`
already: when `mipsel`'s glibc moved, the tag was *renamed* `manylinux_2_39_mipsel` ->
`manylinux_2_41_mipsel` rather than repointed, on the principle that "a real PEP 600 tag must not
keep claiming a floor its image no longer has". `arm_embedded` names no version at all, so
repinning it silently changes what every consumer of that name gets. Following the principle
gives `arm_embedded_xpack_14` and `arm_embedded_xpack_15` — which is honest, and which
immediately needs a per-row selector to choose between them.

**Second, because a single pin cannot satisfy the constraints anyway.** They fall on disjoint tag
ranges, which is easy to miss:

- tags before `v1.26.0`: ceiling `< 15.1`, no floor
- `v1.26.0` onward: floor **`14.3`** (`stm32`'s `$(error ... upgrade to GCC 14.3+ ...)` for
  Cortex-M55), no ceiling

And xpack publishes **nothing in `[14.3, 15.1)`** — checked against the real release list, which
goes `13.3.1-1.1`, `14.2.1-1.1`, `15.2.1-1.1`. So `14.2.1` violates the newer floor and `15.2.1`
violates the older ceiling; there is no third choice.

**The floor is theoretical for this matrix, and that is worth knowing rather than relying on.**
The guard fires only under `MCU_SERIES=n6`, and there is no N6 board among `stm32`'s 1016 rows
(its MCUs are f0/f4/f7/g0/g4/h5/h7/l0/l1/l4/u5/wb). So `14.2.1` is safe *in practice* — but
`refresh_toolchain_pins.py` resolves per `(tag, scope)`, not per board, so it would start
reporting floor violations that are not real, and a permanently red `--check` is worse than the
bug it catches.

## The decision: the image carries no toolchain, and the row names the version

The same shape this project already uses twice, rather than a new one:

- **`esp32`** carries `idf_version` per row — eight distinct values — and
  `usermod/espidf.py` provisions that version at build time into a `cache_root()`-keyed cache
  ([0058] chose this precisely because baking eight images would be wrong seven times out of
  eight).
- **`alif`** already carries `toolchain_version = "13.3.Rel1"` per row. **Nothing reads it** —
  no module in `src/cibuildmp` references the field — so this record does not invent the name, it
  becomes its first consumer.

So `arm_embedded` becomes a thin base (upstream image plus the apt set every build needs) and the
xpack version moves into the row as `toolchain_version`, fetched into the mounted cache the way
[0084]'s own live proof did it: download, sha256-verify, extract, marker, `PATH`.

**Measured, so the trade is not guessed at:**

| | today | under this record |
| --- | --- | --- |
| image | `arm_embedded`, **501 MiB** compressed, 4 layers | upstream base + apt set |
| toolchain | baked, one version for every tag | cached tarball: **270 MiB** (14.2.1) or **292 MiB** (15.2.1) |
| two versions side by side | a second image and a new name | two cache entries |
| bumping a version | rebuild, publish, repin a digest | edit a row |

**What it costs, stated rather than discovered later:**

- **Ephemeral runners pay the fetch.** A GitHub runner starts cold, so without `actions/cache`
  every job downloads the tarball — but it also stops pulling a 501 MiB image, so on bytes this is
  a wash at worst and a win at best. Measure it before claiming either.
- **The container has to change user mid-run.** [0084]'s own addendum records both halves the hard
  way: a run-time install needs root, the build must not run as root (or it leaves root-owned
  directories in the mounted tree), and `HOME` has to move with the uid — otherwise `git`'s
  warnings end up inside `MICROPY_GIT_TAG` and the build dies on a *generated* header.
- **[0058]'s own headline stops being true for this group.** "Image groups are toolchains, not
  ports" is what that record is called; under this one the group stops encoding a toolchain
  version at all. That is a revision to state in [0058]'s own text, not a silent drift.

## What this does not solve

- **`mimxrt`'s `>= 13` ceiling** (the 71st violation) still needs an answer no shared pin can
  give: `14.2.1` and `15.2.1` both exceed it. With the version in the row it becomes expressible
  — that row simply names `13.3.1-1.1` — which is the first case where the per-row selector earns
  itself rather than duplicating a group name ([0084] removed exactly such a duplicate for `unix`).
- **Whether a downgrade breaks the newest tags.** Every incompatibility this project has measured
  ran one way, a newer compiler rejecting older code, but that is an empirical pattern and not a
  guarantee. So the verification order is the reverse of the intuitive one: build a **new** tag
  (`v1.29.0`/`v1.30.0-preview`) on the older toolchain first, because the old tags are the case
  this change is *for* and the new ones are the case it could break.
- **The checker's board-scoped floor.** Until `refresh_toolchain_pins.py` can express "this floor
  applies to `MCU_SERIES=n6` only", `--check` cannot be both correct and green after this change.

# 0076 — the `unix-mipsel` holdout is `micropython-bclibc` and `micropython-wasm3`, not `a7p`

- Status: Implemented
- Related: [0038], [0039], [0067], [0073]

## What was wrong

[0073] rewrote three places to say that the legacy `.github/actions/*` layer is
a permanent fallback rather than a usage path, and gave one concrete reason for
keeping it, in all three:

> It stays only because one real case still depends on it directly: `a7p`'s own
> `unix-mipsel` cross-compile has no native runner and deliberately stays on
> `build-usermod-unix` ([0067]).

Every clause of that except "one real case still depends on it" is wrong, and it
now sits in `README.md`, `docs/ACTIONS.md` and [0073]'s own text.

**The repo is wrong.** Checked directly against the three consuming repos'
workflows rather than recalled:

| Repo | Composite actions used today |
| --- | --- |
| `micropython-bclibc` | `fetch-micropython` ×3, **`build-usermod-unix` (`arch: mipsel`)** — `usermod.yml`'s own `build-test-unix-mipsel` job |
| `micropython-wasm3` | `fetch-micropython` ×5, **`build-usermod-unix` (`arch: mipsel`)** — its own equivalent job, which bclibc's comment already names |
| `a7p` | none |

`a7p`'s mipsel cell is `identifier: v1.29.0-manylinux_2_39_mipsel`, built through
the CLI action like every other cell it has. It has been that way since
`o-murphy/a7p#86` — **the same PR [0038]'s own tracker row cites as merged**, so
the claim was already false when it was written, not made false later. Its last
two `clone-micropython` references (in `mp-natmod.yml`, for `$MPY_DIR` only, not
for any build) went in the session that found this; `a7p` now touches no
composite action at all.

**The citation is wrong too.** [0067] is `resolve_user_c_modules()`'s flat
make-module autodetect, live-caught on `micropython-wasm3`. It does not contain
the string `mipsel`, and never did.

**Where it came from.** The tracker's own [0038] row: "`a7p`'s own `unix-mipsel`
cell stays on the old composite action deliberately ([0067])". [0073] read that
row, believed it, and propagated it into two user-facing documents — which is
precisely the drift [0073] was written to fix, reproduced inside the fix. A
tracker row is a status claim about someone else's repository; unlike a claim
about this repo's own source, nothing here can go stale-detect it.

## The fix

- `README.md`'s "Legacy composite actions" section and `docs/ACTIONS.md`'s intro
  now name the two repos that actually depend on this layer, and say what they
  depend on it for (`build-usermod-unix` for mipsel in both; `fetch-micropython`
  much more widely than the mipsel story alone suggested — eight call sites
  across the two, none of them about mipsel).
- The tracker's [0038] and [0073] rows corrected in place, since the tracker is
  the living status source.
- [0073] keeps its own text and gains a pointer to this record, per the
  append-only rule — its argument (the layer is permanent, not being absorbed)
  is unaffected; only the example attached to it was wrong.

## What this does not decide

Whether either repo's mipsel cell *should* move to `v1.29.0-manylinux_2_39_mipsel`
the way `a7p`'s already has. bclibc's own job comment gives a reason not to —
[0043] kept the vendored `MICROPY_STANDALONE=1`/`deplibs` static-libffi path for
exactly this cell, and its test step runs the binary under `qemu-user`, which
`a7p` handles with a host `qemu-user-static` install its own job documents at
length. That is a real question about two other repositories, and this record
does not answer it; it only stops this one describing their state incorrectly.

[0038]: 0038-m5-adopt-in-three-repos.md
[0039]: 0039-usermod-composite-actions-status.md
[0043]: 0043-unix-adopts-cibuildwheel-native-image-model.md
[0067]: 0067-user-c-modules-flat-shape-autodetect.md
[0073]: 0073-composite-actions-are-a-permanent-legacy-fallback.md

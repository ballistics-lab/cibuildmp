# 0073 — the legacy composite actions are a permanent fallback, not a usage path being absorbed

- Status: Implemented
- Related: [0038], [0039], [0067]

## What was wrong

`docs/reference/design.md`'s own "Positioning" section (a *living* reference, meant to
be kept current with what is true today) still said, verbatim:

> The actions stay as the low-level layer until `cibuildmp` covers their ground, then
> become thin wrappers over it (the same relationship `pypa/cibuildwheel@v3` has with
> `python -m cibuildwheel`).

That plan was floated as [0038]'s own open item ("reduce `build-natmod` to a wrapper
over `cibuildmp --build`") and explicitly **rejected** by the user on 2026-08-30 — the
tracker's own "Rejected" section says so in one line. Nobody went back and fixed the
sentence in `design.md` that this rejection made false. This is exactly the failure
mode `CLAUDE.md`/`CONTRIBUTING.md` already name for `README.md`: closing a record (or,
here, rejecting a proposed one) updates the tracker's own row and nothing else.

Downstream of that stale sentence, both `README.md`'s "Composite actions" section and
`docs/ACTIONS.md`'s own intro framed `.github/actions/{fetch-micropython,
clone-micropython,build-natmod,build-usermod-*}` as a second, still-current way to use
this project ("Still fully supported for CI" / "these actions absorb the CLI's work
once it's wired up") — read next to `action.yml`'s own Quick-start example, that reads
as two supported integration paths, not one primary path plus a historical layer. A
grep confirms none of `.github/actions/*` invokes the `cibuildmp` CLI at all — every one
is its own bare-host toolchain-install-then-`make`/`idf.py` implementation, predating
the CLI outright, not a thin shim over it.

## The fix

Rewrote all three places, verified against the actual rejection ([0038]) and the one
real, still-live dependency on this layer (`a7p`'s own `unix-mipsel` cross-compile,
[0067]) rather than the old "will eventually be absorbed" framing:

- `README.md`'s "Composite actions" section, renamed "Legacy composite actions (not a
  way to use `cibuildmp`)".
- `docs/ACTIONS.md`'s intro, opening with "This is not usage documentation for
  `cibuildmp`."
- `docs/reference/design.md`'s "Positioning" section, replacing the stale
  wrapper-someday sentence with what actually happened: the wrapper plan was proposed
  and rejected, so this layer is a **permanent** separate implementation, not a
  temporary one being absorbed.

All three now say the same three things: these actions don't call `cibuildmp` at all,
they are not a second supported integration path, and the one reason they still exist
is `a7p`'s own `unix-mipsel` holdout — read `docs/ACTIONS.md` only if maintaining or
migrating off something like that, not as a starting point for a new module.

## Addendum, 2026-08-31 -- the example was wrong, the argument stands

Every one of the three rewrites above justified keeping this layer with the same
concrete case: `a7p`'s own `unix-mipsel` cross-compile staying on
`build-usermod-unix` ([0067]). That case does not exist and never did -- wrong
repo, wrong record, and false already when this record was written. The real
holdouts are `micropython-bclibc` and `micropython-wasm3`. See [0076], which
corrects `README.md`, `docs/ACTIONS.md` and this tracker's own rows.

Worth noting where it came from, since this record is itself about drift: the
claim was read out of the tracker's own [0038] row and believed. A tracker row
asserting something about *another repository* is the one kind of status claim
nothing in this repo can check for itself -- unlike a claim about this project's
own source, which a grep settles. The argument this record actually makes (the
layer is permanent, not being absorbed) never depended on which repo the example
named, and is unaffected.

[0038]: 0038-m5-adopt-in-three-repos.md
[0039]: 0039-usermod-composite-actions-status.md
[0067]: 0067-user-c-modules-flat-shape-autodetect.md
[0076]: 0076-the-mipsel-holdout-is-bclibc-and-wasm3-not-a7p.md

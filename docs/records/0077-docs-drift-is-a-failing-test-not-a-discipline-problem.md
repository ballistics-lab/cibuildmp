# 0077 — docs drift is a failing test, not a discipline problem

- Status: Implemented
- Related: [0041], [0050], [0073], [0076]

## What was wrong

`CLAUDE.md` already carries a list of the living docs that have drifted from real
project state, with the incidents named. The list keeps growing, and the
countermeasure has always been the same one: a rule telling the next person to
check. In this session alone, four more:

- `README.md`'s `@vX.Y.Z` pins and per-port rows, stale across a release.
- `docs/reference/design.md` describing a natmod toolchain resolver [0050] had
  deleted, for weeks.
- [0073] writing `a7p`'s `unix-mipsel` into `README.md` and `docs/ACTIONS.md` as
  the reason the legacy action layer survives — false in every particular, and
  corrected only by [0076]. That one landed *inside a change whose entire
  purpose was fixing drift*.
- Nine record numbers in `README.md` with no link definition at all, rendering
  as literal `[0043]`.

The pattern is not carelessness. It is that these are facts living somewhere
else — in `resources/build-platforms.toml`, in the option schema, in another
repository's CI — restated by hand in prose that nothing re-derives. A rule
asking people to re-check by hand scales exactly as far as the last person's
attention, and the [0073] incident is the proof: the person writing it was
thinking about drift at that very moment and still shipped some.

## The fix

`tests/test_docs.py`, running in the existing `pytest` job — no new
infrastructure, no new workflow step. Seven checks over `README.md`,
`docs/ACTIONS.md` and `docs/reference/*.md`:

- **Identifiers** named in a code span must exist in `build-platforms.toml`, or
  — for a glob — match something that does. This is what catches a pinned-tag
  bump leaving one example behind.
- **README's option table** must equal `FAMILIES`' own `OPTION_KEYS` ([0075]),
  in both directions. A renamed key leaves a stale row; a *new* key never grows
  one, and that is the quieter failure, since nothing on the page looks wrong.
- **The table's `[override]` column** against the real `OVERRIDE_UNION_KEYS`.
- **`CIBMP_*` variables** must be read by something. Runtime-constructed names
  (`CIBMP_<KEY>`, `CIBMP_BUILD_<PORT>`, `CIBMP_<PORT>_<TARGET>_TIMEOUT`) are
  generated from the real port/target table rather than allowlisted by hand.
- **Repo paths** in code spans must exist — the exact shape `design.md` had
  after [0050].
- **`vendored-images.md`'s image groups** against `pinned_docker_images.toml`.
- **Record links** resolve, and every `[NNNN]` used is defined — over
  `CHANGELOG.md`, `CLAUDE.md` and the tracker too, since a broken link is broken
  whether or not the prose around it is history.

**`docs/records/` is deliberately not checked.** A record describing the state
at the time it was written is correct *as history* even when that state is long
gone; "fixing" one to satisfy a test would destroy the thing it exists to
preserve. The tracker is checked for link resolution only, for the same reason.

## What it found on the first run

Every failure was real; after tightening the extractors there were no false
positives left to suppress:

- `design.md` claimed a usermod identifier is `{tag}-{port}` or
  `{tag}-{port}-{axis}`, with `v1.29.0-unix-manylinux_2_28_x86_64` and
  `v1.29.0-webassembly` as examples. Neither exists. `unix`, `windows` and
  `webassembly` all use a bare `{tag}-{arch}` with **no port segment** —
  `v1.29.0-manylinux_2_28_x86_64`, `v1.29.0-wasm32` — and only board ports
  carry one. Rewritten against each port's own real `identifier_format`.
- Fifteen undefined record links across `docs/ACTIONS.md`,
  `docs/reference/design.md`, `CHANGELOG.md` and `CLAUDE.md`.

## What this does not do

It checks facts with a machine-readable counterpart. Prose making a *claim*
about behaviour — "the actions stay until the CLI covers their ground", [0073]'s
own stale sentence — still needs a person, and so does anything about another
repository's state, which is why [0076] proposes keeping such claims out of
living docs entirely rather than trying to test them. The four incidents this
suite was written after were all of the mechanical kind, which is the argument
for it, not a claim that it is sufficient.

## Addendum, same day -- the stronger half: generate what can be generated

The checks above catch a documented fact that *became* wrong. `bin/refresh_docs.py`
removes the chance to write one by hand at all, for the subset that is a pure
function of the resource tables. Two blocks so far, each between a
`<!-- generated: <name> -->` marker pair, with `tests/test_docs.py` failing the
build when either is out of date:

- **README's identifier-shape table.** Every example is now picked from a real
  row at that port's own newest stable tag, rather than composed from the format
  string -- a composed example can be well-formed and name nothing, which is the
  exact failure this record's own audit found in `design.md`.
- **`vendored-images.md`'s port/arch -> group mapping.** That section carried the
  sentence "current as of this file's own last edit", which is the promise that
  goes stale with nobody noticing; it is generated now, exhaustive over all
  fifteen usermod ports rather than the subset a person kept up, and a group no
  published image backs is marked inline instead of resolving to nothing at
  build time.

One more stale number found while wiring this up, and deliberately **not**
replaced with a fresh one: README claimed `test-all-platforms.yml` covers "83
real `esp32` identifiers and 74 real `rp2` ones". Those were a two-tag slice,
accurate when written; the real totals are now 442 and 374, off by five times,
because each new MicroPython tag adds a whole board set. The rows are the fact
and the matrix already says "every row" -- the count was never load-bearing, so
it is gone rather than pinned to today's value.

## Addendum, same day -- reading the reference docs claim by claim

The mechanical checks are a floor, not a ceiling. Reading
`docs/reference/*.md` against the source found six more, none of which any
test could have caught:

- **`design.md`'s Positioning section still carried the false `a7p`
  `unix-mipsel` claim.** [0076] corrected `README.md`, `docs/ACTIONS.md` and
  the tracker; this was the fourth copy and was missed, staying wrong a
  further day. It is the clearest possible case for [0076]'s own proposal
  that other-repo status claims do not belong in living docs: nothing here
  can check them, and they get copied.
- **Two contradictory precedence statements, in one file.** One paragraph
  said per-target options resolve `default → global → env → CLI`; sixty
  lines later the same file said `defaults → config → [override] → env →
  CLI`. Neither is right, and there is no single chain: invocation-wide
  options resolve `default → file → env → CLI`, per-target options resolve
  `default → file → matching [override] → env`, and only three options have
  a CLI flag at all. Verified by running each, not by reading.
- **`arch-flags` documented as a string** (`arch-flags = ""`). It is a list,
  and an axis rather than a flag: each entry becomes its own target, with the
  packed value in that target's identifier.
- **"three settable option keys" for usermod overrides.** Four:
  `extra-cmake-args` was missing.
- **The toolchain map was stale and structurally unfixable by hand.** It gave
  `x64`/`x86` no `CROSS` prefix, true up to v1.28.0 and false from v1.29.0.
  Since it is a per-tag fact, any single hand-written table is only true for
  the tag it was written against — so it is generated now, naming its tag.
- **`open-questions.md`'s first entry asked how MSYS2 and ESP-IDF fit the
  `host`/`download`/`docker` toolchain-strategy shape** — a shape [0050]
  deleted. Its second cites `usermod-dev.yml`, a workflow that no longer
  exists. Both rewritten rather than deleted, since the underlying questions
  (a non-Linux host reaching a daemon) are still real.

One source comment went the same way: `usermod/__init__.py` explained that
`--toolchain` "is natmod-specific and stays that way", outliving the flag
itself by two records.

## Addendum, same day -- `docs/ACTIONS.md`, and the fifth copy

`docs/ACTIONS.md`'s own input tables turned out to be **completely accurate**:
all nine actions documented, every real input covered, nothing fictional --
checked mechanically against each `.github/actions/*/action.yml`. Worth
recording, because the assumption going in was the opposite.

What was wrong was the version pin and one paragraph in `README.md`.

**The pin, again.** Four `@v0.4.1` pins across `README.md` and
`docs/ACTIONS.md` with `v0.4.2` released. `CLAUDE.md` already names this pin
as a repeat offender in its own right -- it sat on `@v0.3.0` for weeks after
`v0.4.0` shipped. Now guarded: `tests/test_docs.py` compares every
`ballistics-lab/cibuildmp...@vX.Y.Z` in a living doc against
`cibuildmp.__version__`, not against git tags, which a shallow CI checkout
does not have.

**The fifth copy.** A `README.md` paragraph claimed all three consuming repos
were "fully migrated off every" composite action and then, in its own
parenthesis, that two of them were not; named `a7p` as a `unix-mipsel`
holdout; paired it with `micropython-wasm3` when the real pair is
`micropython-bclibc` and `micropython-wasm3`; and carried the stale pin. It
closed by telling the reader not to trust it and to check the tracker
instead -- and was believed anyway, in four other files.

That paragraph is now deleted rather than corrected. Counting this one, the
same false claim had been copied to five places from a single tracker row.
The lesson is [0076]'s, sharpened: a status claim about another repository is
not merely hard to keep current, it is the one kind nothing in this repo can
check *at all*, so a living document should not make one. Point at the
tracker row and stop.

## Addendum, same day -- the one rule that stays a rule

The obvious next step was a test for the class that caused the most damage:
a living document asserting another repository's state. It was prototyped and
**deliberately not shipped**. The mechanical proxy -- a consuming repo's name
near a composite-action name -- fired four times on `docs/ACTIONS.md` and
three of the four were legitimate examples (`a7p passes path: mpy`, `a7p uses
make fetch-nanopb`). A guard with that false-positive rate needs an allowlist
of prose snippets, and an allowlist of prose snippets rots faster than the
prose does.

So this one is enforced by a written rule in `CONTRIBUTING.md` and by having
removed every instance, not by CI:

- `README.md`, `docs/ACTIONS.md` and `docs/reference/design.md` no longer say
  which consuming repo calls what. Each points at the tracker's [0038] row.
- That row now carries the status with a date and the method
  (checked against each repo's own default branch, 2026-08-31), including
  that both migrations exist on unmerged branches and have not run in their
  own CI.
- A second `README.md` paragraph -- the post-mortem of the deleted one -- went
  too. Explaining at length why a document used to be wrong is itself
  living-doc content that will go stale; it belongs in a record, which is
  where it now is.

Naming a consuming repo stays fine as an *example*. Asserting its current
state does not. The distinction is one a person can make and a regex cannot,
which is the honest reason this is not a test.

## Addendum, same day -- what a "finished" audit missed

Asked whether the audit was complete, the honest answer was no, and two more
turned up in the `README.md` sections the first pass had not reached --
"Conventions this repo assumes" and "Versioning", neither of which looks like
it carries version-dependent facts:

- **"`dynruntime.mk` defaults `BUILD ?= build` unscoped."** True to v1.28.0,
  false from v1.29.0, which made it `BUILD ?= build-$(ARCH)`. This one is not
  cosmetic: the whole paragraph exists to tell a consumer to scope `BUILD`
  themselves or watch a second `ARCH=` silently reuse the first one's objects,
  and on the current pin that collision cannot happen by default at all.
- **"`v0.4.0` is the current tag, and the one every example in this README
  targets."** Both halves false, two releases running. The pin guard added
  earlier that day did not catch it, because it only reads `@vX.Y.Z` in a
  `uses:` line and this was bare prose.

Neither is restated now -- the version lives in `CHANGELOG.md`, and the
`BUILD` advice names the tag it applies to. The general lesson is the one
this record keeps circling: a section with no version-shaped content in it
still carries version-dependent claims, so "which files did I audit" is a
weaker question than "which claims did I check". The mechanical guards cover
the claims that have a machine-readable counterpart; everything else is
found by reading, and is found in the places you did not expect to look.

## Addendum, same day -- the generator fought the editor, and lost

A generated block is a byte-for-byte comparison, and a markdown table
formatter -- an editor's format-on-save here, but prettier or anything else
would do the same -- pads cells to a common column width and widens the
`---` separator to match. That is a no-op to every renderer, and a byte
difference to `--check`. The two then undo each other on every save and every
run, and whichever went last decided whether CI passed.

Replicating the formatter's exact output was the wrong fix: it means matching
a tool this repo does not configure, own, or even know the identity of.

`_normalize()` compares what the block *asserts* instead -- cell content,
column count, row order -- and ignores padding inside rows, separator width
and trailing whitespace. `refresh_docs.py` also leaves a block alone when it
is equivalent modulo whitespace, so a plain run no longer churns a diff the
formatter will only re-apply.

Verified both directions, not just the happy one: a simulated format-on-save
over a generated block leaves `--check` clean and causes no rewrite, while
changing one real value in the same block still fails `--check` (exit 1) and
the test. A guard that stops flapping is only worth having if it still
catches the thing it exists for.

[0041]: 0041-docs-restructure.md
[0050]: 0050-natmod-is-docker-only.md
[0073]: 0073-composite-actions-are-a-permanent-legacy-fallback.md
[0075]: 0075-top-level-scalar-keys-are-validated.md
[0076]: 0076-the-mipsel-holdout-is-bclibc-and-wasm3-not-a7p.md

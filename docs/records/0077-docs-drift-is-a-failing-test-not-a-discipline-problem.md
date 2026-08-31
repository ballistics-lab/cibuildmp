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

[0041]: 0041-docs-restructure.md
[0050]: 0050-natmod-is-docker-only.md
[0073]: 0073-composite-actions-are-a-permanent-legacy-fallback.md
[0075]: 0075-top-level-scalar-keys-are-validated.md
[0076]: 0076-the-mipsel-holdout-is-bclibc-and-wasm3-not-a7p.md

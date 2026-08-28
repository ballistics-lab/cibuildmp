# 0041. Documentation restructure — numbered records

- Status: Accepted / implemented
- Conceived: 2026-08-25
- Related: supersedes the monolithic `docs/BACKLOG.md` (see 0000-TRACKER.md); scheme copied from `o-murphy/rp2040py`'s own record 0032

## Context

`docs/BACKLOG.md` had grown to 3666 lines: 33 "locked decisions" (`D1`-`D33`),
five build-phase write-ups (`M0`-`M5`), a long usermod status section, open
questions, and living design reference (positioning, identifier scheme,
config schema, toolchain map) — all in one file, appended to in place for
the life of the project. Some individual decisions (`D28`, the
container-per-port migration plan) had grown past 700 lines on their own,
with later corrections and addenda interleaved with the original text.
Finding "what does cibuildmp currently do for Windows usermod builds" meant
reading through `D18`, its addendum, its "final state", `D20`'s note about
it, and `D30`'s point 2 — none adjacent in the file, and no index pointing
between them. The file was no longer possible to maintain or navigate.

## Decision

Split into numbered, append-only records under `docs/records/`, indexed by
`docs/0000-TRACKER.md` — the same scheme `o-murphy/rp2040py` uses (see that
project's own `docs/records/0032-docs-restructure.md` for the original
design rationale, quoted here since this project adopts it directly rather
than reinventing it):

- **Number = a record**, assigned in order of appearance in the old file
  (which, since `cibuildmp.toml`'s own decisions were already labelled
  `D1`-`D33` in arrival order, meant keeping each decision's existing
  `D`-number as its record number — `D9` is record `0009`, `D25` is record
  `0025`, and so on. This is a deliberate deviation from rp2040py's own
  numbering, made because every decision in this file already
  cross-references others by `D`-number throughout the prose ("supersedes
  D9", "closing D28's own gap") — renumbering would have meant rewriting
  every one of those references or leaving them stale. Numbers `0034`-`0041`
  cover content that had no `D`/`M` label of its own: the five `M`-phase
  write-ups (`0034`-`0038`), the usermod status preamble (`0039`), the
  deferred-tests note (`0040`), and this record (`0041`).
- Each record carries a `Status` line and is migrated **verbatim** from the
  old file — exact line slices, quoted in an HTML comment naming the source
  range, no rewording. Where a decision's own follow-up text (an
  "addendum", a "final state") was physically separated in the old file by
  an unrelated decision inserted between them, the record reassembles them
  in one file (noted in that record's own migration comment) rather than
  preserving the physical, accidental split — the record is the append-only
  unit, not the byte range.
- **Living design reference** (positioning, identifier scheme, config
  schema, toolchain map, local-use table, non-goals) moved to
  `docs/reference/design.md`, unnumbered, since it describes *current
  state* rather than a decision with a lifecycle — matching rp2040py's own
  `reference/` convention for living how-to/checklist material. **Open
  questions** moved to `docs/reference/open-questions.md` for the same
  reason: an open question is not yet a decision, and the list itself keeps
  changing shape as items resolve.
- `docs/0000-TRACKER.md` is a projection of state — one row per idea
  (checkbox + link + short note), newest/most-active first within each
  section, mirroring rp2040py's own tracker format exactly.

## Consequences

- **Zero information loss was the hard requirement**, the same as
  rp2040py's own restructure: every decision, addendum, correction, and
  "rejected" note in the old `BACKLOG.md` is preserved verbatim in its
  record. Nothing was trimmed, summarized, or reworded during migration.
- `docs/BACKLOG.md` itself becomes a short pointer file (mirroring
  rp2040py's own post-restructure `docs/BACKLOG.md`), not deleted outright,
  so an existing bookmark or link into it still lands somewhere useful.
- Every `**D<N>**`/`**M<N>**` cross-reference already inside the migrated
  text still resolves the same way a reader expects — `D25` still means the
  Dockerfile-bugs decision, now at `docs/records/0025-...md` instead of a
  line range in a single file.
- `CLAUDE.md` gained a short section pointing at the tracker as the one
  maintained answer to "what's currently being worked on", the same role it
  plays in rp2040py — see that file's own "Where things stand" section.

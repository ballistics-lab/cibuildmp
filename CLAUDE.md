# Working on cibuildmp

## Where things stand

Engineering notes live as numbered, append-only records under [docs/records/](docs/records/),
indexed by [docs/0000-TRACKER.md](docs/0000-TRACKER.md) (the scheme itself is
[record 0041](docs/records/0041-docs-restructure.md), adapted from `o-murphy/rp2040py`'s
identical convention). Records `0001`-`0033` keep the decision's own original `D`-number
as its record number (`D9` is `0009`, `D25` is `0025`) so every in-text cross-reference
("supersedes D9", "closing D28's own gap") still resolves; `0034`-`0038` are the `M0`-`M5`
build-phase write-ups, `0039`/`0040` are context notes, `0041` is the restructure record
itself. Living design reference (positioning, identifier scheme, config schema, toolchain
map) lives separately in [docs/reference/design.md](docs/reference/design.md), and unresolved
questions in [docs/reference/open-questions.md](docs/reference/open-questions.md) — neither
is a decision history, so keep them current with *what is true today* rather than appending
to them.

**What is currently being worked on is not listed here — read the tracker.** Its
"In progress / Proposed" section is the only maintained answer: right now that's [0022]
(zephyr, plus the unstarted `rp2` usermod build driver), [0031] (the musllinux half of the
unix libc axis), [0038] (two open M5 cleanup items), and [0040] (the usermod test-runner
axis, not scheduled). "Implemented" below it is everything already landed. A summary
duplicated into this file would go stale within a session or two — don't add one here.

From there, drill down rather than infer:

- Each record's own header carries its `Status:` line. A record marked `Implemented` can
  still carry open items inside itself (checkboxes, "not started" notes, "still open"
  paragraphs) — the tracker's own row for it says so in its one-line note; read the record
  before treating a `[x]` as "nothing left."
- Supersession is recorded, not deleted: a record whose approach was later replaced (e.g.
  [0028]'s local-Docker-build mechanism, replaced by [0033]'s pull-only design) says so in
  its own text and stays as the historical account of how the design actually evolved. Trust
  the newest record on a topic, but read the older one for *why*, not just *what changed*.
- Adding a new decision or phase write-up: give it the next unused number after `0041`
  (do **not** try to match a `D`/`M` label — that scheme ended with the migration), migrate
  or write its content into `docs/records/NNNN-<slug>.md`, add a row to
  `docs/0000-TRACKER.md`'s "Ideas" section and to its "Record links" list.

[0022]: docs/records/0022-zephyr-third-selector-axis.md
[0028]: docs/records/0028-container-per-port-migration-plan.md
[0031]: docs/records/0031-unix-musllinux-libc-axis.md
[0033]: docs/records/0033-cibuildmp-never-builds-docker-image-itself.md
[0038]: docs/records/0038-m5-adopt-in-three-repos.md
[0040]: docs/records/0040-usermod-tests-deferred.md

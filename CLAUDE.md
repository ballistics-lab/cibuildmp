# Working on cibuildmp

## Check cibuildwheel first. Every time. By reading it, not recalling it.

**This is the first rule because ignoring it is what got this project stuck.**
cibuildmp is cibuildwheel for MicroPython. Before designing, renaming or
arguing about anything that has an upstream counterpart -- selectors,
identifiers, options and their precedence, `--platform`, `--only`, `--archs`,
container invocation, opt-in behaviour, config layout -- **install cibuildwheel
and read the relevant module**:

```bash
uv pip install --target /tmp/cbw --no-deps cibuildwheel
# then read /tmp/cbw/cibuildwheel/{selector,options,architecture,oci_container}.py
```

Paraphrasing it from memory has cost this project four separate times, and
every one was recorded only after the damage:

- **[0045]** -- `--only` carried an in-code comment claiming it matched
  upstream's semantics. It did not, and a test asserting the behaviour passed
  vacuously for months.
- **[0049]** -- `default_runner`, `--print-build-matrix` and a composite matrix
  action were invented for a concept upstream does not have at all. All
  deleted.
- **[0050]** -- a 302-line toolchain resolver, replaced by a `FROM` line and
  four symlinks.
- **[0051]** -- `--platform` sits one level above upstream's, which is the root
  cause of a "heterogeneous axis" problem that simply does not exist once it is
  at the right level.

The pattern is always the same: something is built that *resembles* upstream,
drifts, and then needs a record to explain why it is being removed. Reading
takes minutes; a wrong abstraction takes a session to unwind.

Where cibuildmp deliberately diverges, that divergence must be **argued in a
record**, not left implicit -- [0045] separates the reasoned differences
(`--platform` means the build mode; natmod's `--archs` has no `auto`) from the
accidental ones, and that separation is the useful part.

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
(zephyr, plus the unstarted `rp2` usermod build driver), [0028] (`esp32.Dockerfile` still
not started — no Docker path for that port at all), [0031] (the musllinux half of the unix
libc axis, now folded under [0043]), [0032] (`qemu` never wired to `ensure_image()`, despite [0030]'s Docker-only
mandate — `windows` was wired by [0042]), [0038] (two open M5 cleanup items), and [0040]
(the usermod
test-runner axis, not scheduled). "Implemented" below it is everything already landed —
including [0008], whose only unfinished aside (reserving the PyPI name) was never
committed follow-up work, just a "worth doing" note in the decision's own text. A summary
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

[0008]: docs/records/0008-tool-distribution-deferred.md
[0022]: docs/records/0022-zephyr-third-selector-axis.md
[0028]: docs/records/0028-container-per-port-migration-plan.md
[0030]: docs/records/0030-container-approach-natmod-and-docker-vs-qemu.md
[0031]: docs/records/0031-unix-musllinux-libc-axis.md
[0032]: docs/records/0032-unix-docker-default-and-webassembly-wiring.md
[0033]: docs/records/0033-cibuildmp-never-builds-docker-image-itself.md
[0038]: docs/records/0038-m5-adopt-in-three-repos.md
[0040]: docs/records/0040-usermod-tests-deferred.md
[0042]: docs/records/0042-windows-docker-wiring-and-resolver-removal.md
[0043]: docs/records/0043-unix-adopts-cibuildwheel-native-image-model.md
[0045]: docs/records/0045-only-is-a-filter-not-a-forced-identifier.md
[0049]: docs/records/0049-no-matrix-generation-archs-vocabulary.md
[0050]: docs/records/0050-natmod-is-docker-only.md
[0051]: docs/records/0051-usermod-identifiers-have-no-version-axis.md

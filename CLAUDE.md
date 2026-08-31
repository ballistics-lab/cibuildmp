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

**What is currently being worked on is not listed here — read the tracker, every time,
not this file's memory of it.** Its "In progress / Proposed" section is the only
maintained answer. This exact sentence went stale once already: an earlier version of
this file named [0028] ("`esp32.Dockerfile` still not started — no Docker path for that
port at all") and [0022] ("unstarted `rp2` usermod build driver") as open, weeks after
[0028] and [0060] had both actually closed — and an agent trusting that claim over the
tracker is what caused real, user-visible confusion in a consuming repo's own migration
work. A summary duplicated into this file would go stale within a session or two — don't
add one here, and don't trust one you find here either if it ever creeps back in;
`docs/0000-TRACKER.md`'s own "Implemented" vs "In progress / Proposed" split, not this
file's prose, is the only claim about current status worth acting on.

**The tracker is the only status source that self-corrects; narrative docs (`README.md`,
docstrings, this file) do not.** Closing a record updates the tracker's own row and the
record's own `Status:` line — nothing about that process touches `README.md`'s prose
automatically. A closed record can leave a README paragraph describing the state it just
superseded (e.g. [0028]/[0060] making an old "`esp32`/`rp2` not wired into `action.yml`
yet" sentence false the moment they landed) sitting there, unrevised, for however long
until someone reads it at face value and repeats the stale claim downstream. When closing
a record, grep `README.md` (and any other narrative doc) for text describing the
pre-record state and fix it in the same session — don't leave that for whoever reads that
paragraph next to discover the hard way.

**The specific floating files, so "any other narrative doc" isn't a search you have to
invent each time.** Every one of these has actually drifted from real project state at
least once, not hypothetically:

- **`README.md`** — natmod/usermod's container story (image names, "one Dockerfile"
  claims), per-port provisioning rows, migration/adoption status paragraphs, the
  `@vX.Y.Z` pin in every example. Stale three separate times on record: [0028]/[0060]'s
  esp32/rp2 claim named in this file's own earlier text (see above), a version pin stuck
  on `@v0.3.0` weeks after `v0.4.0` shipped plus a `windows` row still describing deleted
  bare-host `apt` provisioning (both fixed same session as [0068]'s own docs pass), and
  this file's own "one `docker/natmod.Dockerfile` image" claim surviving [0058]'s
  six-way toolchain-image split for two weeks after it landed.
- **`docs/reference/design.md`** — explicitly a *living* reference, which does not make
  it immune: its own "Toolchain map"/"Local use" sections kept describing natmod's
  host-side toolchain resolver as current for weeks after [0050] deleted it and made
  every build Docker-only.
- **`docs/reference/vendored-images.md`** — the image-group model itself (which
  arch/port/board resolves to which published image). Its mapping table is
  **generated** now (`bin/refresh_docs.py`, [0077]) and a test fails if it is stale,
  so a Dockerfile split/merge or a group rename can no longer invalidate it silently —
  the prose around it still can.
- **`docs/ACTIONS.md`** — the composite-action reference. It pins the composite
  sub-actions (`.../.github/actions/build-natmod@vX.Y.Z`), not `cibuildmp@vX.Y.Z`
  as this bullet used to say; both it and README drifted from the real published
  version at the same time, twice. Every such pin is checked against
  `CHANGELOG.md`'s newest released heading now ([0077]).
- **`CHANGELOG.md`** — append-only in principle, but a squash-merge has silently
  dropped an entire released-version section before, leaving a dangling link reference
  at the bottom with nothing in the body to anchor to.

**Two of those files are now partly machine-checked, and one is partly generated.**
`tests/test_docs.py` fails the build on a doc naming an identifier, option key,
`CIBMP_*` variable, repo path, image group, record link or action pin that does not
exist — over `README.md`, `CONTRIBUTING.md`, `docs/ACTIONS.md`, `docs/reference/*.md`,
and (for paths and removed names) source comments and the example configs too.
`bin/refresh_docs.py` generates the identifier-shape table, the image-group mapping
and the toolchain map; edit those by hand and a test says so. What none of it checks
is prose making a claim about *behaviour* — for that, [0078] is the procedure, and it
is the one that found the false claims a reader could not.

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
[0058]: docs/records/0058-image-groups-are-toolchains-not-ports.md
[0060]: docs/records/0060-rp2-build-driver.md
[0068]: docs/records/0068-docker-dependabot-grouping-and-mipsel-ubuntu-26-04.md
[0077]: docs/records/0077-docs-drift-is-a-failing-test-not-a-discipline-problem.md
[0078]: docs/records/0078-uncontexted-agent-audit-as-a-docs-test.md

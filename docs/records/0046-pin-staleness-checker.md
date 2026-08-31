# 0046 — nothing notices when a pin goes stale, except container images

Status: Implemented in part — container images ([0044]), the docker base-OS tag
([0068]), and the six toolchain-tarball pins plus a weekly schedule (this record's
own 2026-08-31 addendum). Still open: results go only to a job log, and whether
consumers' own `micropython` pins are in scope.

Lifted out of [reference/open-questions.md](../reference/open-questions.md),
where it had grown into a real work item sitting in a living document. It
belongs here because it is a decision to make and a thing to build, not a
question about what is true today.

## The claim

`cibuildmp`'s value is that it owns the environment ([0002]). Owning an
environment means pinning it, and this repo pins a lot: toolchain tarballs with
sha256s, container image digests, an apt package version, a MicroPython release
tag, an ESP-IDF git tag, an emsdk build hash. **Not one of those tells anyone
when it has fallen behind.** Dependabot watches the repo's own `uv` and Actions
dependencies — visible in Actions history as "Graph Update" runs — and has no
visibility into any of the above.

[0010] already said the general thing ("every value in there goes stale on an
upstream's schedule"). This record is about noticing *when*.

## What is actually pinned, and by what mechanism

The inventory matters more than the principle, because the mechanisms differ
enough that one generic checker cannot cover them:

| pin | where | shape | upstream |
| --- | --- | --- | --- |
| container images (18) | `resources/pinned_docker_images.toml` | `@sha256:` | GHCR |
| pypa base images | `resources/pinned_pypa_images.toml` | `@sha256:` + dated tag | quay.io |
| arm-none-eabi `15.2.1-1.1` | `resources/natmod.toml` | version + URL + sha256 | GitHub releases (xpack) |
| riscv-none-elf `15.2.0-1` | `resources/natmod.toml` | version + URL + sha256 | GitHub releases (xpack) |
| xtensa-esp `16.1.0_20260609` | `resources/natmod.toml` | version + URL + sha256 | GitHub releases (espressif) |
| xtensa-lx106 `standalone` | `resources/natmod.toml` | URL + sha256, **no version** | `micropython.org/resources/` |
| emsdk | `docker/webassembly.Dockerfile` | **build hash** + sha256 | `storage.googleapis.com` |
| llvm-mingw `20260616` | `docker/windows.Dockerfile` | version + URL + sha256 | GitHub releases |
| `libc6-dev-mipsel-cross=2.39-*` | `docker/manylinux_2_39_mipsel.Dockerfile` | **apt version constraint** | Ubuntu archive |
| MicroPython tag | each `examples/*/cibuildmp.toml` (`v1.28.0`), consumers' own configs | git tag → `sources.RELEASE_TARBALL` | GitHub releases |
| ESP-IDF tag | config, e.g. `v5.5.1` (`usermod/espidf.py`) | git tag | GitHub |
| apt package sets | `docker/*.Dockerfile` | unversioned names | distro archives |

Two of these are genuinely awkward, one only looked it, and naming all three is
most of the point of writing this down:

- **emsdk is pinned by build hash, and that turns out to be fine.** The URL
  carries `.../emscripten-releases-builds/linux/9d70dbe.../wasm-binaries.tar.xz`,
  which first looked like the hard case here — a hash cannot be compared against
  a version. It can, because emsdk publishes the mapping itself:
  `emscripten-core/emsdk`'s own `emscripten-releases-tags.json` has
  `aliases.latest` and a `releases` table, and checked live it reads
  `latest = "6.0.8"` with `releases["6.0.8"] =
  "9d70dbe8860ccdd3595f6e6065d94bfb543ae955"` — byte-for-byte the hash in our
  Dockerfile, so this pin is currently *current*. A checker is therefore one
  fetch and two lookups, and the same file also gives the human-readable version
  that `resources/usermod.toml`'s `[emsdk]` table records separately.
  This is the git-submodule shape Dependabot already understands — a pinned ref
  compared against what upstream now calls latest — and it is the easiest of the
  uncovered pins rather than the hardest.
- **xtensa-lx106 has no version at all.** Its URL is a stable
  `micropython.org/resources/xtensa-lx106-elf-standalone.tar.gz`; the only way
  to notice a change is that the sha256 stops matching, which is a *build*
  failure rather than a notification.
- **The mipsel apt pin is a claim about a name.** `manylinux_2_39_mipsel` says
  glibc 2.39, and `libc6-dev-mipsel-cross=2.39-*` is what makes that true
  ([0044]). Nothing notices when Ubuntu moves to 2.40 — the image build simply
  starts failing, or worse, keeps working against a version the tag no longer
  describes if the constraint is ever loosened.

## What already exists

[0044] built `bin/update_docker.py`, and it is the worked example of the shape
this record wants for everything else:

- resolve each pin against its own registry (`quay.io` tag API for the pypa
  bases, GHCR manifest digests for cibuildmp's own images);
- `--check` reports drift and exits non-zero, so it is usable as a scheduled
  job; without it, rewrite the value in place and leave the surrounding
  explanation byte-for-byte intact;
- **never** repoint a pin on its own. A pin moves in a reviewed PR ([0033]'s
  cadence), because the diff is the review.

It justified itself on first run: the pypa bases, transcribed from
cibuildwheel's own file, were already nine days stale
(`2026.08.15-1` → `2026.08.24-1`).

## What this decides

**One script per upstream shape, not one generic checker.** The table above has
six distinct resolution mechanisms; a single "check everything" entry point that
dispatches to per-source resolvers is the honest structure, and
`update_docker.py`'s quay/GHCR split is already that pattern in miniature. The
obvious next one is a `bin/update_toolchains.py` covering `resources/natmod.toml`
— four entries, three of which are GitHub releases and therefore one API call
each, plus a re-download to recompute the sha256.

**It reports; it does not decide.** A base image bump is not routine hygiene: for
`armv7l` the choice between `manylinux_2_31` and `_2_35` is a different libc
floor, and a MicroPython tag bump can change the `.mpy` ABI, which changes every
natmod identifier ([0013]). The checker's job is to make staleness *visible* on a
schedule, not to open a PR that silently changes what this project builds.

**Scheduled, not per-push.** Nothing here changes between commits; it changes
between weeks. A weekly workflow calling every checker with `--check` and
failing loudly is the right cadence, and it costs nothing on a normal push.

## Not decided here

- Whether the xtensa-lx106 case is worth automating at all, or is better served
  by a documented manual review cadence: it has no version and no upstream
  metadata to compare against, only a sha256 that changes when the file does.
  (emsdk was in this bullet until its own `emscripten-releases-tags.json` turned
  it into the straightforward case above.)
- Whether consumers' own `micropython` pins are in scope. `examples/*` are this
  repo's, but the tag is fundamentally a *consumer's* choice, and [0013] already
  allows a list of them. Checking our own examples is clearly in scope; telling
  other projects their tag is old is not obviously cibuildmp's job.
- Where the results go: a failing scheduled job, an issue, or a job summary
  ([0029] already has real `stepsummary.py` machinery to reuse).

---

## Addendum, 2026-08-30 — partially resolved by [0068], for one pin the table above misses

The table above inventories `resources/pinned_docker_images.toml`/`pinned_pypa_images.toml`
as "container images" and "pypa base images", but not the plain `FROM ubuntu:24.04`-style base
OS tag each `docker/*.Dockerfile` also carries independently of those two tables — a pin this
record's own inventory missed entirely.

[0068] found that gap the hard way (a real `ubuntu:24.04` → `26.04` bump breaking
`manylinux_2_39_mipsel`) and closed it for that one pin category, not by building a checker
script but by making Dependabot itself the notifier: `docker-images`' group now excludes
`ubuntu`, so a base-OS tag bump always lands as its own isolated PR — never silently bundled
with a routine pypa digest bump — and still requires the human review [0033]'s own cadence
already demands before any pin moves. That is exactly the "make staleness visible on a
schedule, report don't decide" shape this record asked for, just riding Dependabot's own
schedule instead of a new script.

Everything else this record names is still unbuilt: `bin/update_toolchains.py` for
`resources/natmod.toml`, an emsdk checker, a decision on xtensa-lx106, and `update_docker.py`'s
own `--check` still runs on no schedule at all ([0068] confirmed this directly: no `cron:`
anywhere relevant in `.github/workflows/*.yml`). *(All four of those are built as of the
next addendum below, 2026-08-31.)*

## Addendum, 2026-08-31 — the toolchain checker and the schedule, both built

Two of the three things this record asked for now exist, and the inventory table
above needs one correction before either makes sense.

**The table is wrong about where the toolchain pins live.** It says
`resources/natmod.toml`; they moved out of it, and today the four
`TOOLCHAIN_URL`/`TOOLCHAIN_SHA256` pairs are `ARG`s in
`docker/{arm_embedded,riscv_embedded,xtensa_esp,xtensa_lx106}.Dockerfile`, with
llvm-mingw and emsdk inline in `docker/{windows,webassembly}.Dockerfile`. That
is [0058]'s own still-open "`resources/pinned_toolchains.toml` not written" item
seen from the other side; noted here rather than silently, since anyone picking
this work up from the table alone would look in the wrong file.

**The emsdk bullet above is wrong about `resources/usermod.toml` too.** It says
that file's own `[emsdk]` table records the human-readable version separately;
[0042] had already deleted `[emsdk]` and `[llvm-mingw]` from it before this
record was written. What `usermod.toml` still carries is one table, `[port]`,
and `natmod.toml` two, `[arch]` and `[arch-flags.rv32imc]` -- all three live,
all three read (`usermod/portinfo.py`, `natmod/targets.py`). The emsdk version
is only in `emscripten-releases-tags.json` upstream, which is where
`bin/update_toolchains.py` reads it from.

**`bin/update_toolchains.py`** covers all six, in the three shapes this record
predicted: four GitHub releases (one API call each), emsdk via
`emscripten-releases-tags.json` (which is as easy as this record said), and
`xtensa-lx106`'s unversioned URL, reported *as* unversioned rather than
pretended into a version — with `--slow` to re-download and compare the served
sha256, since that is its only real signal.

It reports and never rewrites, which is a deliberate narrowing of
`update_docker.py`'s shape: moving one of these means re-downloading a tarball
to recompute a sha256, and this record already says a pin moves in a reviewed
PR. `--check` is accepted purely so the scheduled invocation reads the same as
`update_docker.py --check`.

It justified itself on the first run, the same way `update_docker.py` did:
**llvm-mingw pinned at `20260616`, upstream at `20260826`** — a bit over two
months behind, and nothing would have said so.

**`.github/workflows/pin-staleness.yml`** is the "scheduled, not per-push" half.
Weekly, Mondays 04:00 UTC, calling both checkers, running both even when the
first reports drift so one run names everything that is behind. Until it
existed, `update_docker.py --check` had been written for exactly this purpose
and had no caller at all.

Still unbuilt from this record: nothing writes results anywhere but the job log
([0029]'s `stepsummary.py` is still unreused here), and the "are consumers' own
`micropython` pins in scope" question stays open.

[0002]: 0002-delegate-compile-own-environment.md
[0010]: 0010-pinned-data-in-resources.md
[0013]: 0013-micropython-list-dedup-by-abi.md
[0029]: 0029-github-actions-job-summary.md
[0033]: 0033-cibuildmp-never-builds-docker-image-itself.md
[0044]: 0044-unix-native-images-landed.md
[0068]: 0068-docker-dependabot-grouping-and-mipsel-ubuntu-26-04.md

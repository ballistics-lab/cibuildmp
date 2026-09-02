# 0084 — unix's pypa image pin moves from the architecture to the row, and the end of shared/floating compilers

Status: Implemented — **the destination changed late on 2026-09-02, and the sections between
"The destination, revised" and the first Addendum are the account of how that answer was reached,
not a plan to execute.** The premise and the investigation stand; the *answer* they were pointing
at (Bootlin uniformly, a toolchain tarball per identifier) is superseded by a much smaller one:
keep pypa's own images, move the image pin from the architecture to the row. That smaller answer
has landed and is live-verified across the full tag history (native and emulated) — see this
record's own last two addenda for the complete landed scope and the bugs found verifying it.
**Two real items are spun off, not closed here**: carrying `TAG_CFLAGS` into every port's own
`mpy-cross` (today: `unix` only) and dropping the `gcc` column from the remaining nine
non-`unix` scopes — both scoped, well-understood follow-ups affecting ports this record never
touched, not gaps in `unix`'s own model. `arm_embedded` is [0085], already its own record.
Related: [0013], [0031], [0033], [0043], [0044], [0045], [0046], [0052], [0058], [0068], [0082], [0083], [0085], [0091]

## The premise, and why it replaced the original ask

The session started from a narrower question ("propose a `windows.Dockerfile` → fully prebuilt
mingw" and "propose an ESP-IDF/rp2-SDK vendoring alternative") and ended somewhere much larger,
through direct, repeated user pushback on every intermediate answer — recorded here in full
because the reasoning is what a future session needs, not just the destination.

**Stated directly by the user, and the premise this whole record is measured against:** MicroPython's
own maintainers never tracked forward compiler compatibility. Each tag's own upstream CI used
*whatever specific toolchain version existed on Launchpad/xpack/Bootlin at release time* — not a
range, not "anything recent enough." A cibuildmp toolchain choice that tries to be *universal*
across a tag range is therefore not a simplification that costs a little precision; it is
structurally guaranteed to eventually break, because there is no version of "recent enough" that
upstream ever actually promised, tested, or maintained.

## What was tried first, and why each attempt failed live

Recorded in full because each failure taught something the next attempt needed, and this is
exactly the class of churn CLAUDE.md's own convention asks be kept rather than silently
overwritten:

1. **A single shared, floor/ceiling-computed pin per image** (`docs/records/0082`'s own scope,
   extended here). Confirmed live: `docker/arm_embedded.Dockerfile`/`riscv_embedded.Dockerfile`
   are *already* broken this way — pinned at xpack `15.2.1`/`15.2.0`, both above the `<15.1`
   ceiling `resources/toolchains.toml` derives for every tag before `v1.26.0`, for all seven
   `usermod` ports sharing that image (71 real `(tag, port)` combinations, `bin/
   refresh_toolchain_pins.py --check` catches it, exit 1). A *window* computed across many tags
   is exactly the "universal" shape the premise above already rules out — it just has a wider
   blast radius than one shared unversioned pin.
2. **A resolved version string per row** (`gcc = "14.2.1-1.1"`, written into `build-platforms.toml`
   directly). Caught its own bug before landing: `parse_ver("15") == (15,)` sorts *below*
   `(15, 1)` in Python's own tuple comparison, so a naive apt-major-version pin ("15") silently
   compared as satisfying a `<15.1` ceiling it does not — contradicted by `[0082]`'s own live
   bisection of the exact tag (`v1.21.0`) this produced a wrong answer for. Fixed by comparing
   against the *real observed* Ubuntu package version (`15.2.0`), not the bare major.
3. **`apt-get install gcc-<N>` as "pin enough."** Live-tested building `ports/rp2`'s `PICO`
   board at `v1.20.0`: `gcc-14` on `ubuntu:26.04` resolved to **`14.3.0-14ubuntu1`** — a *later
   point release* than the `14.2.x` this session's earlier host tests had verified clean — and it
   broke on a **different, second, real incompatibility**: `-Werror=dangling-pointer=` in
   `py/stackctrl.c`, not yet in `toolchains.toml`'s own `COMPAT_FIXES`. `gcc-13` (resolved to
   `13.4.0-10ubuntu1`, also later than the `13.3.0` tested earlier) hit the identical error. This
   is not a one-off: it is the premise's own prediction landing a second time, one level deeper
   — Ubuntu's own point-release drift *inside one apt major version* is exactly as unreliable as
   Ubuntu's own base-image major-version drift ([0068]'s own `ubuntu:24.04`→`26.04` incident).
4. **A Launchpad-pinned exact `.deb`, matching upstream's own historical CI package exactly**
   (`toolchains.toml`'s own `apt-resolved` facts already carry the exact epoch+version, e.g.
   `v1.29.0`/`usermod.unix`/`gcc-x86-64-linux-gnu` → `4:13.2.0-7ubuntu1`). Correct in principle —
   this *is* what upstream's own CI verified, per tag, exactly — but raises a real, unresolved
   technical risk flagged and not yet tested: a `.deb` built for Ubuntu (glibc ~2.35+) may not
   even *execute* inside an AlmaLinux 8 (glibc 2.28) container, the same `GLIBC_x.xx not found`
   class of failure `container_mpy_cross()`'s own docstring already documents for a *different*
   host/container mismatch (record 0043's own native-image landing). Superseded by (5) before
   this was tested, because (5) removes the question entirely rather than answering it.
5. **Bootlin, uniformly, for every toolchain this project needs — natmod and usermod, native and
   cross, glibc and musl alike.** The destination. See below.

## The destination, revised: pypa stays, and the image pin moves from the architecture to the row

**Proposed by the user after a full day of live investigation into the alternative, and it is
smaller than everything below it.** The change is one key: `[usermod.unix].images` maps an
*architecture* to an image group today; it becomes a per-row field instead, resolved for the
`(tag, arch, libc)` triple the same way `gcc` and `idf_version` already are. Nothing else about
the mechanism moves -- pull-only, digest-pinned, `image_for()` resolving, all unchanged ([0033]).

**Why this is better than what the rest of this record argues for, on this project's own terms:**

- **It answers the premise directly.** Upstream pinned whatever toolchain existed at release time;
  pypa publishes a dated image per build, and those images stay pullable. Checked, not assumed:
  `manylinux_2_28_x86_64` has **573 dated tags still active, back to 2022-05-30**, and the
  compiler moves with the date -- `2022-05-30` carries `gcc-toolset-11`, `2023-02-09` carries
  `12`, `2025-03-09` onward carries `14`. Read out of each image's own config blob through the
  registry API, without pulling a layer.
- **[0082] does not need fixing here, it does not arise.** No `manylinux_2_28` image carries gcc 15
  at all; the ladder is 11, 12, 14. Three distinct values across four years, so a per-row pin has
  three values to choose from, not twenty.
- **The libc floor does not get worse -- the Bootlin plan made it worse.** `manylinux_2_28` means
  glibc 2.28; Bootlin's oldest `x86-64` toolchain is glibc **2.34**, so the plan below would have
  raised every `unix` consumer's floor while claiming to be more faithful.
- **The identifier keeps its floor, so this record's own argued identifier change is withdrawn.**
  The floor stays an independently published axis (pypa publishes several simultaneously), which
  is exactly the condition under which [0043]/[0045] said it earns its place in the identifier.
  `manylinux_2_28_x86_64` stays as it is.
- **Six problems found live today simply do not exist on this path**: no vendored libffi, so no
  autotools, so no `libtool`-pulls-in-`gcc-15`; no `out/lib64` mismatch; no `ffi_closure_alloc`
  collision; no sysroot `pkg-config` plumbing. All six are documented below, and all six are
  artefacts of leaving pypa, not of anything upstream does.
- **It shrinks what CI has to prove, which was the whole cost argument.** A tag that names exactly
  one image never has to be shown to work across a toolchain *range* -- the thing this session
  spent a day on and which failed at `v1.20.0`. Build count is unchanged (225 `unix` cells stay
  225); what disappears is the verification matrix and the maintenance of a toolchain story of
  our own.

**The one real gap, named here rather than discovered later: pypa's image history is not uniform.**
Also checked directly:

| image | oldest still-active dated tag |
| --- | --- |
| `manylinux_2_28_x86_64` | 2022-05-30 |
| `manylinux_2_28_s390x` | 2022-09-03 |
| `musllinux_1_2_x86_64` | 2023-07-29 |
| `manylinux_2_31_armv7l` | **2025-02-08** |
| `manylinux_2_39_riscv64` | **2025.07.20** |
| `musllinux_1_2_riscv64` | **2025.07.20** |

So "pin the image that was current when the tag shipped" is available for `x86_64`/`s390x` and
not for `armv7l`/`riscv64`, whose images only exist from 2025. Those cells take the oldest
available image, on the same reasoning this record already uses for Bootlin's own pre-2021.11 gap
-- every incompatibility found this session broke in one direction only, a newer compiler
rejecting older code. It is an argued fallback, not a verified one, and it should be written next
to the pin rather than left to be rediscovered.

**`mipsel` is the one cell this does not reach**, and that is already recorded: pypa publishes no
mipsel image, PEP 600 defines no `manylinux_*_mipsel` tag, and [0043] documents the exception.
It keeps its Bootlin tarball ([0068]), so what survives of the plan below is one cell of it rather
than all fifteen.

**Everything from here to the Addendum is superseded as a plan.** It is kept because it is the
account of how this answer was reached: the premise it starts from is what rules out a universal
pin, and the live failures it records are what make the case that leaving pypa costs more than
staying.

## Where this stands, 2026-09-02 — what landed, and what the next session starts from

Written as a handoff rather than as a decision: the sections below are the argument, this one is
the state. Everything named here is in git; nothing depends on a local cache, a pulled image or a
scratch directory.

**The `unix` baseline, measured before touching anything** (run 33640288717, `v1.29.0` across
every cell, bucketed): **14 cells built, 0 failed.** The fifteenth,
`musllinux_1_2_ppc64le`, never ran -- it sits in `test-all-platforms.yml`'s own default skip as
confirmed-live breakage, and [0044] records the cause precisely: `mpy-cross` builds fine inside
the image and then fails *when run* under QEMU user-mode to freeze `argparse.py`. A QEMU limit,
not a cibuildmp bug.

**Rechecked this session (run 33642497696) and still broken, with the cause narrowed.** The
failure is `Error relocating .../mpy-cross: unsupported relocation type`, which is **musl's own
dynamic loader**, raised when the freshly built `mpy-cross` is executed under `qemu-ppc64le` to
compile `argparse.py` -- 526s of emulation to get there. The narrowing matters: this is not "ppc64le
under QEMU does not work". `manylinux_2_28_ppc64le` is green on the same architecture under the
same emulation (1037s) in the same sweep. It is musl's loader and QEMU's ppc64le relocation
support specifically, which is why exactly one of the two ppc64le cells fails.

That also makes it the first thing this session ran through the new
`tolerate_failures=false` input: the same failure would have produced a green run before, and
produced a red one here.

**A prediction this session made and the run falsified.** `manylinux_2_31_armv7l` and
`manylinux_2_39_riscv64` resolve straight to pypa's images with no layer of this project's own,
and `manylinux_2_28_x86_64` was measured to ship no `libffi-devel` -- from which it seemed to
follow that those two cells could not be building. They build, in 55s and 961s. Unpacking the
image filesystem settles it: `manylinux_2_31_armv7l` carries libffi already. The five images this
project publishes exist for the **AlmaLinux 8** family alone, not for manylinux generally, and
step 5 below is scoped accordingly.

**The emulated cells, now measured rather than estimated** -- the first time each landed in a
single-cell bucket, which is what `bin/plan_test_matrix.py`'s own comment says had never happened:

| cell | seconds |
| --- | --- |
| `manylinux_2_28_ppc64le` | 1037 |
| `manylinux_2_39_riscv64` | 961 |
| `musllinux_1_2_riscv64` | 888 |
| `musllinux_1_2_s390x` | 872 |
| `manylinux_2_28_s390x` | 812 |
| every native or cross cell | 55-93 |

`_EMULATED_UNIX_WEIGHT = 1050` was seeded from isolated runs at 800-1200s and is confirmed by
these; the six emulated cells cost more than the other nine together, which is the concrete
version of this record's own CI-cost argument. `manylinux_2_41_mipsel` at 67s is the tell: it is
the one `unix` cell that cross-compiles rather than emulating.

**One trap worth not repeating:** `test-all-platforms.yml` reads
`${{ inputs.skip || '<defaults>' }}`, and an empty string is falsy in a GitHub expression -- so
passing `skip: ""` to disable skipping silently keeps the defaults. That is why the fifteenth cell
was absent, and it was visible only in the report, never in a job colour.

**A per-tag sweep was dispatched at the end of this session and its results are not in yet.**
Fifteen `test-platforms.yml` runs, one per MicroPython tag, each building that tag's own fifteen
`unix` cells: run ids **33642989476 through 33643188693** (plus 33642497696, a recheck of
`musllinux_1_2_ppc64le` alone). Each was dispatched with `keep_going=true`,
`tolerate_failures=false`, `step_summary=true` -- the sweep wants every cell's outcome, wants a
red job when one fails, and wants the summary rendered on the run page rather than only in an
artifact.

Collecting them needs no local state, which is the point:

```bash
gh run list --workflow=test-platforms.yml --limit 20 \
  --json databaseId,status,conclusion,createdAt
gh run download <id> -D reports/   # artifact is report-unix-<tag>
```

Each artifact is [0063]'s own report shape (`{"results": [{"identifier", "duration", "error"},
...]}`), and the `error` field is the authority -- a green job can still contain failed cells
under `--keep-going`.

**What the sweep is actually asking**, so its result is read rather than merely collected: whether
`TAG_CFLAGS` fixes `v1.20.0` on all fifteen cells (it was only ever proven on two x86_64 ones);
whether any tag other than `v1.20.0` needs a relaxation on a real per-cell image rather than on
the Bootlin toolchain this session tested them against; and whether
`musllinux_1_2_ppc64le` fails on every tag or only the two [0044] marks.

**Landed (all pushed, `575 passed`):**

- `[usermod.unix]`'s 225 rows lost the `gcc` column entirely — the image fixes the compiler, so a
  ceiling-derived pin had nothing left to decide (`4e222ab`).
- The one relaxation a MicroPython release needs lives in `build_common.TAG_CFLAGS`, keyed by tag
  (`41e7732`), and reaches `container_mpy_cross()` as well as the port's own make (`0f3038c`) --
  the CI failure that forced the second of those is recorded above.
- `resources/toolchains.toml` and `resources/bootlin.toml` left the wheel for
  `docs/reference/toolchain-facts/` (`cb9132e`): evidence, never loaded at runtime.
- `bin/fetch_bootlin_metadata.py` writes the Bootlin catalogue (419 releases, every arch this
  project could target, with url/sha256/size and the versions inside each).
- `bin/refresh_usermod_boards.py`/`refresh_natmod_archs.py` gained `carry_forward()`, so a
  regeneration can no longer silently drop a hand-merged per-row fact -- which it could, and
  nothing checked.
- `test-platforms.yml` gained `keep_going`/`tolerate_failures`/`step_summary` inputs
  (`c0079e3`), defaulting to how a *direct* dispatch should behave; `test-all-platforms.yml`
  opts into the tolerant behaviour explicitly.

**Not started, in the order that gets the most for the least:**

1. **`arm_embedded`** — [0085] has the whole argument and the measurements. 70 of 71 live ceiling
   violations, and the answer is not a repin.
2. **Carry `TAG_CFLAGS` into every port's `mpy-cross`.** It is wired through `unix` only today, so
   the other eight ports still meet the same diagnostic on the same shared `py/` sources -- and
   this is also how [0082]'s nine tags get answered for every port at once.
3. **Drop the `gcc` column from the remaining nine scopes.** It restates a tag fact about a
   thousand times; removing it from `unix` cost nothing.
4. ~~Teach the checker about `natmod`.~~ **Done this session** -- see below.
5. ~~Run-time `dnf install libffi-devel` for the five `manylinux_2_28_*` cells.~~ **Done this
   session, and smaller than planned: no run-time install needed at all** -- see the Addendum
   below.

**Two facts a fresh session should not have to rediscover:**

- A run-time install needs root and the build must not run as root, and **`HOME` has to move with
  the uid** -- otherwise `git`'s stderr lands inside `MICROPY_GIT_TAG` and the build dies on a
  generated header. Both halves cost an hour here.
- `--keep-going` plus `continue-on-error` means a green run can contain red cells. The per-bucket
  JSON report artifact is the authority, never the job colour.

**Item 4 done this session: the checker now knows about `natmod`.** `refresh_toolchain_pins.py`'s
`real_rows()` used to fold every `natmod` row -- x86/x64 host arches and the arm/riscv cross arches
alike -- into the `unix` scope, and `image_for()` had no case for a `natmod.*` scope at all, so
`image` resolved to `None` and `--check` silently skipped every one of them. `natmod`'s own
`arch -> image` map already says which of its rows build in `arm_embedded`/`riscv_embedded` (the
only two images `DOCKERFILE_PIN` knows how to check); `main()` now seeds those as
`natmod.arm_embedded`/`natmod.riscv_embedded` scopes even though `toolchains.toml` carries no fact
row for either name, and `real_rows()`/`image_for()` resolve them straight off that map instead of
through the unrelated `unix` scope. No new `toolchains.toml` rows were needed for this: the
`any`/`mpy-cross` thresholds `resolve_row()` already matches regardless of `scope` are exactly the
constraint `natmod`'s cross arches hit.

`--check` goes from 71 problems to **92**: 18 new `natmod.arm_embedded` rows (every pre-`v1.26.0`
tag) and 3 new `natmod.riscv_embedded` rows (`v1.24.0`-`v1.25.0`). `natmod`'s own `gcc` column
already recorded the correct `14.2.1-1.1`/`15.2.1-1.1` split -- nobody had touched it since it
predates this record -- but nothing had ever compared that claim to what `arm_embedded`/
`riscv_embedded` actually ship, so it was silently wrong on every one of those rows. Not fixed
here -- `natmod`'s `gcc` field is read by nothing in `src/cibuildmp` today, same as `unix`'s was
before `4e222ab` -- so this is visibility only. [0085]'s own `toolchain_version` model is the real
fix, and it should cover `natmod`'s rows too when it lands, not just the seven `usermod` ports its
own table names.

## The plan, revised — what actually gets done

Decided with the revised destination, and deliberately much smaller than the phased plan further
down.

**`mipsel` is untouched.** Not migrated, not re-pinned, not re-argued: it keeps
`docker/manylinux_2_41_mipsel.Dockerfile` and its Bootlin tarball exactly as [0068] left them.
Everything below concerns the other fourteen `unix` cells.

*Possibly, later*: whether Buildroot's own Docker images could stand in for that one hand-built
image. Not now, and two facts already gathered belong next to the idea so it is not re-researched
from scratch. Buildroot's own published image (`registry.gitlab.com/buildroot.org/buildroot/base`,
read from its `support/docker/Dockerfile`) is `debian:bookworm` plus `build-essential`, `g++` and,
on amd64, `g++-multilib` -- it exists to *compile* toolchains, which needs a host compiler, so it
is both large and carries exactly the stray native compiler this record spends a section warning
about. And the toolchain in `manylinux_2_41_mipsel` is already Buildroot's own output: a Bootlin
tarball is a Buildroot SDK. So the question is not "Buildroot or not" but whether an image
someone else assembles beats the four lines that assemble this one.

**No image of this project's own, for any of those fourteen.** They resolve to **pypa's own
published image**, digest-pinned per row, and whatever the build needs on top is installed at run
time -- the same call already argued in this record's own Addendum, now applied to pypa's images
rather than to a generic Ubuntu base. So `docker/manylinux_2_28_*.Dockerfile`,
`docker/musllinux_*.Dockerfile` and their `publish-docker-images.yml` cycle retire, and
`resources/pinned_docker_images.toml` loses its `unix` entries; `resources/pinned_pypa_images.toml`
stops being a mirror kept for reference and becomes the table builds actually resolve against.

**The run-time install has two forms, not one**, and that is a fact about the base images rather
than a complication we are adding: `manylinux` is AlmaLinux (`dnf install libffi-devel`, the exact
line `docker/manylinux_2_28_x86_64.Dockerfile` carries today as its only layer) and `musllinux` is
Alpine (`apk add`). Whichever it is, it stays internal to cibuildmp: cibuildwheel's own answer to
the same gap is `before-all`, a user-configured hook, and [0028]'s call that a build image is
infrastructure rather than a `cibuildmp.toml` knob is unchanged by any of this.

**Steps, in order:**

1. **Resolve the per-row image.** For each `(tag, arch, libc)`, the pypa dated tag whose compiler
   matches what upstream's own CI used at that tag, subject to `toolchains.toml`'s own ceilings.
   Three toolset values exist across the whole history (11, 12, 14), so this is a small table, not
   a per-row research project. `armv7l`/`riscv64` take the oldest available image with the
   fallback reasoning written next to the pin.

   **One measurement already narrows this to a single open question.** Every supported `unix` tag
   was built this session against gcc **14.3.0** (Bootlin's `2025.08-1`, before the destination
   changed) in a compiler-free container: `v1.21.0` through `v1.29.0` all built and linked; only
   **`v1.20.0` failed**, on `-Werror=dangling-pointer=` in `py/stackctrl.c`, during `mpy-cross`.
   So under a gcc-14 image exactly one tag needs an older one. Whether even that is true depends
   on a point release this record cannot read from a registry: `gcc-toolset-14` names a major, and
   this session's own earlier tests found `14.2.x` clean where `14.3.0` broke. Running
   `gcc --version` inside one current pypa image answers it, and it is the cheapest next step in
   this list.
   **The first cell is already resolved, by building it.** For `manylinux_2_28_x86_64` the answer
   is **two images, not fifteen**, and the boundary is one tag wide:

   | tag | image | evidence |
   | --- | --- | --- |
   | `v1.20.0` | a `gcc-toolset-12` image (`2024.06.09-3`) | fails the current image on `-Werror=dangling-pointer=` in `py/stackctrl.c` during `mpy-cross`; builds clean on 12.2.1, artifact needs only `GLIBC_2.25` |
   | `v1.21.0` … `v1.30.0-preview` | the current image | `v1.21.0`, `v1.29.0` and `v1.30.0-preview` built and linked live (floors `GLIBC_2.25`, `2.28`, `2.28`); `v1.22.0`-`v1.28.0` had already built under gcc **14.3.0**, newer than the image's own 14.2.1 |

   **All fifteen tags are accounted for, and exactly one needs the older image.** That is the
   whole of this cell's table.

   **Three failures on `v1.30.0-preview` along the way were the harness, not the tag**, and two of
   them are requirements the mechanism inherits rather than incidents:

   - A run-time `dnf install` needs root, but the build must not: leaving the container as root
     puts root-owned directories into the mounted tree, and the next `fetch_micropython()` fails
     with `Permission denied` somewhere else entirely. So the container starts as root, installs,
     then drops to the caller's uid -- and **`HOME` has to move with it**. Without that, `git`
     cannot read its config, writes warnings to stderr, and `makeversionhdr.py` folds them into
     `MICROPY_GIT_TAG`, so the build dies on `missing terminating " character` in a *generated*
     header, mentioning neither permissions nor `HOME`. `build_esp32.py` already sets `HOME`
     explicitly for the same reason ([0058]'s own `--user` consequence); this raises that from one
     port's workaround to a property of the shared mechanism.
   - A preview tag has no release tarball, so it arrives by clone with no submodules, and
     `unix` needs `lib/micropython-lib` to freeze its manifest (`Error: micropython-lib submodule
     is not initialized`). `[usermod.unix]`'s own `post_checkout` already says
     `make -C ports/unix submodules`; on the clone path it is not optional.

   **Corrected in passing, because this record earlier implied otherwise:** `gcc-toolset-14` ships
   **14.2.1**, and the `-Wdangling-pointer` failure reproduces on it. The earlier note that
   "14.2.x was clean" came from a different check and does not hold for `py/stackctrl.c` -- which
   is why `v1.20.0` needs the older image rather than the table being uniform.

   **Three facts about the image itself, read from inside it rather than assumed:** `gcc (GCC)
   14.2.1 20250110 (Red Hat 14.2.1-11)`; `ldd (GNU libc) 2.28`, so the floor the identifier claims
   is the floor the image has; and **`libffi-devel` is not installed** (`pkg-config` finds nothing
   without it), which is exactly why the layer this project publishes today exists and what step 3
   replaces.

   **Then the ladders were read for every other cell, and they made the table simpler still --
   by first making it impossible.** Read from the registry without pulling a layer:

   | cell | dated tags | ladder |
   | --- | --- | --- |
   | `x86_64`, `aarch64`, `ppc64le` | 563-573, from 2022-05-30 | `gcc-toolset-11` -> `12` -> `14` |
   | `s390x` | 531, from 2022-09-03 | same |
   | **`i686`** | **173, only from 2025-06-17** | **`14` only** |
   | `armv7l` | 242, from 2025-02-08 | (2025 onward) |
   | `riscv64` | 141, from 2025.07.20 | (2025 onward) |

   So `i686`, `armv7l` and `riscv64` have **no older image to pin at all** -- and `gcc-toolset-14`
   is exactly what `v1.20.0` fails on. "Take the oldest available" does not save those cells;
   there is no available image that works.

   **What saves them is cheaper than an image, and it was verified rather than assumed:**
   `CFLAGS_EXTRA=-Wno-error=dangling-pointer` builds `v1.20.0` on the *current* image, `mpy-cross`
   and the full port, artifact floor `GLIBC_2.25`. The same diagnostic fires identically on
   `musllinux` (Alpine 3.22.5, gcc **14.2.0**), so the boundary is a property of the compiler
   version, not of the distribution.

   **musl needs one more, and it is a weaker claim than the first**: `-Wno-error=cpp`, because
   `lib/berkeley-db-1.xx/PORT/include/db.h` -- a vendored third-party header, not MicroPython's own
   code -- raises `#warning usage of non-standard #include <sys/cdefs.h> is deprecated`. With both,
   `v1.20.0` builds on the current `musllinux_1_2_x86_64`. So the per-row fact is a short list of
   named relaxations, not a single flag, and the list is per (tag, libc) rather than per tag.

   **That collapses the design one step further than the pin did.** Every cell takes **one image,
   the current one**, for all fifteen tags; what varies per row is not a pinned date but a named
   relaxation for the one tag that needs it. Three things follow:

   - the `i686`/`armv7l`/`riscv64` gap closes by disappearing, rather than by an argued fallback;
   - nothing depends on pypa keeping four-year-old dated tags pullable -- `i686` already proves
     they do not always exist, so a design resting on them was resting on an accident;
   - it is closer to upstream's own position than pinning would be: MicroPython later fixed
     `py/stackctrl.c` itself, so this does not work around a compiler defect, it declines to hold
     a 2023 tag to a diagnostic that did not exist when it shipped.

   **The digest pin stays, and this is the correction to the paragraph above.** "Every cell takes
   the current image" is about *which* image a row names, not about whether the row names one:
   without a per-row digest, the compiler moves under rows that were already verified, which is
   precisely what this record's own premise forbids. So each row pins a digest even while every
   row today pins the *same* digest -- the relaxation removes the need for an *older* image in the
   cells that have none, it does not remove the pin.

   **And the floor is verified on the artifact, never trusted from the image name.** Measured this
   session: `v1.20.0` produces a binary needing `GLIBC_2.25`, `v1.29.0` one needing `GLIBC_2.28`.
   The requirement rises with the code and the toolchain while the image name stays
   `manylinux_2_28` -- so a future image whose headers push a build past 2.28 would leave the
   identifier claiming a floor the artifact no longer meets, silently. `verify_unix_floor()`
   ([0044]) already reads the real binary's own `GLIBC_x.y` requirement; under this design it stops
   being a safety net and becomes the gate.

   **A pinned older image stays available as the fallback** for any future tag where a relaxation
   is not enough, in the four cells that have the history for it.

2. **Move the key -- and what actually landed is narrower than this step first said.** The
   per-row `image` field was written (225 rows, digest-pinned) and then **removed before
   committing**: with every cell resolving to the same image, it duplicated `arch` in every row
   for no information, and the one tag that needs different treatment turned out to need a *flag*
   rather than a different image -- which is just as well, since `i686`/`armv7l`/`riscv64` have no
   older image published to fall back to. `[usermod.unix].images.<arch>` therefore stays as it is.

   **What landed instead** (commit `4e222ab`): the `gcc` column is gone from all 225 `unix` rows,
   because the image fixes the compiler and a ceiling-derived pin has nothing left to decide; and
   the 15 rows of `v1.20.0` carry `cflags_extra = "-Wno-error=dangling-pointer"`. That is a
   **fourth axis** for `build_unix.py`'s own flag composition, and the reason it has to be a row
   fact: the three tables already there key on platform tag, architecture and libc, while a
   MicroPython *release* is none of those -- it needs the flag in every cell at once.
   `unix_extra_cflags()` gained an optional `tag` and appends the row's flags after the other
   three; a caller with no tag in hand still resolves the first three.

   **One earlier claim in this record is wrong and is corrected here:** `-Wno-error=cpp` was
   presented as a musl finding of this session. It is not new -- `build_unix.py`'s own
   `_MUSL_CFLAGS` has carried it column-wide for some time, with a comment naming the same
   `berkeley-db` -> `sys/cdefs.h` cause. The hand-run build needed it only because it bypassed
   cibuildmp entirely. The row therefore carries the dangling-pointer flag alone, on both libc
   columns.

   `bin/refresh_usermod_boards.py`'s own `carry_forward()` protects the new per-row fact from
   being dropped by a regeneration, and `tests/test_platform_row_facts.py`'s inventory lock caught
   the migration exactly as intended -- it failed on the `gcc`/`cflags_extra` swap and on nothing
   else, which is how it was verified that nothing outside the table read `gcc` for `unix`.
3. **Install at run time** what the retired layer used to bake in, per base-image family.
4. **Verify a boundary sample, not the matrix** -- one tag per distinct toolset value, both libc
   families, plus one `armv7l`/`riscv64` cell to exercise the oldest-available fallback.
5. **Retire the fourteen Dockerfiles and their pins** only once that is green, as a separate
   commit from the cutover, so a revert is one config change.

## The destination: one toolchain vendor, self-contained tarballs, no shared/floating compiler anywhere

**Bootlin's own toolchains carry their own complete sysroot** (glibc or musl, matched, baked in)
— the same `relocate-sdk.sh`-and-`sha256`-pinned pattern this project already trusts for
`manylinux_2_41_mipsel`/`ppc64le_linux` ([0068]'s own fix for exactly this class of problem).
Two things verified live this session that make this the answer rather than another guess:

- **Coverage is real and complete for every arch this project needs**, checked directly against
  `toolchains.bootlin.com`'s own download index, not assumed:

  | arch | glibc | musl | earliest release |
  | --- | --- | --- | --- |
  | `x86-64` | yes | yes | 2021.11 |
  | `aarch64` | yes | yes | 2018.02 |
  | `x86-i686` | yes | yes | 2018.02 |
  | `powerpc64le-power8` | yes | yes | 2018.02 |
  | `s390x-z13` | yes | musl only from 2024.05 | 2021.05 (glibc) |

  One real gap: `x86-64` has no release before **2021.11**, so natmod's own oldest tags
  (`v1.12`-`v1.19`, 2019-2022) have no exact historical match. Not a blocker — every
  incompatibility found this session broke in one direction only (a *newer* compiler rejecting
  *older* code, never the reverse), so the oldest available release (`2021.11-5`) is a safe,
  argued fallback for anything older than it, not a guess.

- **A Bootlin `--musl--` toolchain, run from a plain glibc (Ubuntu) host, produces a genuine musl
  binary — verified live, not assumed.** Built a trivial program with `x86-64--musl--stable-
  2025.08-1`'s own `x86_64-buildroot-linux-musl-gcc` on this session's own Ubuntu sandbox:

  ```
  test-musl: ELF 64-bit ... interpreter /lib/ld-musl-x86_64.so.1
  NEEDED: libc.so
  ```

  — and it correctly *refuses* to execute on that same glibc host (`required file not found`,
  since `/lib/ld-musl-x86_64.so.1` does not exist there) — proof the binary is genuinely
  musl-linked, not glibc with a coincidentally-similar name. **The output's libc floor comes
  entirely from the toolchain's own sysroot, never from the host OS.** This is the finding that
  collapses the whole image fleet: nothing about `unix`'s glibc/musl split requires two different
  *host* environments any more.

## What this does to the Docker image fleet

**pypa/manylinux is dropped entirely for `unix`.** Its only remaining job today — supplying a
compiler with a known, versioned glibc/musl floor — Bootlin now does directly, per identifier,
with the same tarball discipline every other cross target in `docker/` already uses. The base
image `unix` builds inside stops needing to *be* AlmaLinux 8/Alpine at all; it only needs to be
able to *run* Bootlin's own host tool binaries and provide `make`/`python3`/`git`/`cmake`/
`pyelftools`.

**The fleet collapses from 17 `docker/*.Dockerfile` files to two of this project's own** —
and the third entry below is deliberately not one of them:

- **No generic base *image* at all, decided directly in conversation** — the official
  `ubuntu:26.04` tag, unmodified, pulled straight from Docker Hub. No `docker/*.Dockerfile` of
  this project's own, no `publish-docker-images.yml` entry, no digest for anyone to repin. This
  is [0033]'s own "cibuildmp never builds a Docker image itself" carried to its end — not merely
  "we do not build it", but "there is no intermediate artifact to publish", which is only
  available *because* no toolchain is baked in any more. It serves natmod (every arch), every
  `usermod` port on `arm_embedded`/`riscv_embedded` today, and all of `unix` (5 arches ×
  glibc/musl). Two different things are provisioned into it, and they are **not** the same
  mechanism — see the addendum below, which is where the whole of this bullet was decided:
  the **toolchain** arrives as a Bootlin tarball fetched into a host-mounted cache, per
  identifier, once per version; the **small auxiliary set** (`curl`, `ca-certificates`,
  `xz-utils`/`bzip2`, `make`, `python3`, `python3-pyelftools`, `git`, and `cmake` where the port
  needs it — no compiler of any kind) is a plain `apt-get install` on **every** invocation,
  accepted for now and revisited if it proves too slow in practice.
- **`esp_idf_base`** — unchanged. ESP-IDF's own toolchain is a whole versioned tool set
  (compiler + `esptool` + ROM ELFs + components, resolved together by IDF's own `idf_tools.py`),
  not a single compiler a tarball pin can stand in for. Explicitly out of scope for this record,
  same conclusion the deleted first draft of this record reached before being told to redo the
  whole premise.
- **`webassembly`** — unchanged. emsdk is its own pinned, self-contained tarball already; nothing
  here changes it.

**Both toolchain layers a build actually needs get the same treatment, and this session found
the distinction the hard way:** `mpy-cross` is always a *native* (host-architecture) build, even
inside an image whose whole purpose is cross-compiling a *different* target — confirmed live
when fetching `arm_embedded`'s xpack `arm-none-eabi-gcc` alone left `mpy-cross` still failing,
because that step never touches the cross compiler at all; it needs the image's own native `gcc`.
**So every row needs two independent toolchain facts where a cross target is involved** — a
native pin (for `mpy-cross`) and a cross pin (for the actual firmware) — not one.

## What this does to the identifier

**Nothing new — this confirms `[0043]`/`[0045]`'s own already-argued position, it does not
change it.** An identifier names a compatibility class ("what this build is compatible with"),
never how it was built — the same reasoning that already keeps host architecture and toolchain
choice out of every identifier this project has. The per-row toolchain fact (`gcc = "..."`, a
tarball URL+sha256) lives *beside* the identifier in the same row, the same way `idf_version`/
`pre_checkout` already do for `esp32` — it was never a candidate for the identifier string itself.

**One real, argued change: the glibc/musl floor number drops out of `usermod.unix`'s own
identifier**, decided directly in conversation, not assumed. Written against the real strings in
`build-platforms.toml` rather than approximated, because the first draft of this paragraph
spelled them a third way that exists nowhere:

| | today | under this record |
| --- | --- | --- |
| `arch` | `manylinux_2_28_x86_64` | `manylinux-x86_64` |
| | `musllinux_1_2_x86_64` | `musllinux-x86_64` |
| `identifier` (`{tag}-{arch}`) | `v1.20.0-manylinux_2_28_x86_64` | `v1.20.0-manylinux-x86_64` |

**The hyphen is upstream's own spelling, not a departure from it**, which is why it was chosen
over `manylinux_x86_64`: cibuildwheel names this exact (family, architecture) pair
`manylinux-x86_64-image` in its own options, a fact `dockerrun.py`'s own comment already cites.
It costs two things, both named here rather than discovered later. `split_tag()` finds the
architecture by the suffix `f"_{arch}"`, which `manylinux-x86_64` no longer ends with, so that
rule has to change with this. And the string stops being PEP 600-shaped -- `build_unix.py`'s own
comment observes that `manylinux_2_28_x86_64` is a real platform tag -- which it can afford to
be, since once the floor is gone it is no longer making a PEP 600 claim at all. The floor axis was only *independently selectable* because pypa
publishes several floors simultaneously for any given release, unrelated to which floor a
toolchain choice implies — cibuildwheel's own real manylinux model, [0043]'s own stated
inspiration. **Bootlin does not have that shape**: one release date bundles one specific glibc
version inseparably with one specific compiler build, so once pypa is gone, floor stops being an
independent user choice and becomes a fact *derived from* `(tag, arch)`, exactly like
`idf_version` already is for `esp32`. A derived fact that cannot be picked independently no longer
earns a place in the selector-facing identifier — it moves to provenance instead, next to the
toolchain version. `verify_unix_floor()` ([0044]) is unaffected: it still checks the real
binary's own `GLIBC_x.y` requirement, just against the value provenance names rather than the
value the identifier does.

**This is a real, argued divergence from upstream cibuildwheel's own manylinux tagging
convention**, and CLAUDE.md's own standing rule requires it be argued here rather than left
implicit: cibuildwheel keeps the floor in the tag because *pypa's own publishing model* makes it
a genuine, independently-chosen axis for a wheel consumer. cibuildmp's, under this record, is not
independently chosen at all once pypa is gone — carrying a number that looks like a choice but
isn't one is worse than not carrying it, the same reasoning [0045] already used to keep host
architecture out of every identifier.

## Provenance: what the artifact itself will say, and what it does not today

**Checked directly, not assumed: neither natmod nor usermod records toolchain provenance in the
output today.** natmod's `package.json` (D14) writes exactly `{urls, version}` — no toolchain
field exists, though the file already carries one non-schema provenance field by [0052]'s own
precedent (the real tag used, when it differs from the ABI-only identifier), so adding another is
not a new kind of change, only a new field. **usermod has no sidecar file at all** —
`orchestrate.py`'s own docstring is explicit that D14's mip-manifest model does not apply to a
firmware build, and nothing has stood in for it since. This record does not build that file; it
only names that a new usermod sidecar (holding, at minimum, the toolchain reference and the
derived floor for `unix`) is required for this record's own provenance goal to be real rather
than aspirational, and flags it as an open item below.

## What this does to CI cost — the argument for doing this at all, beyond correctness

**Old tags are historical and cannot change.** MicroPython will never release a new `v1.20.0`.
Once a tag's own toolchain fact is verified and committed, in this model *nothing shared can ever
invalidate it again* — there is no floating base-image tag, no apt-archive drift, no xpack
"latest" pin moving underneath it, because nothing about its build depends on anything that isn't
itself pinned by the same commit. This is the structural fix to the exact failure class [0068]
documents twice (`ubuntu:24.04`→`26.04` silently breaking `natmod_host`/`ppc64le_linux`) and
[0082] found a third time (`arm_embedded`/`riscv_embedded`'s own xpack pin, silently too new for
71 real combinations) — not a policy asking someone to be more careful next time, a mechanism
that removes the shared thing that kept breaking.

**Consequence for `test-all-platforms.yml`'s own full sweep** (already "too slow to gate every
PR", [0068]'s own third addendum): under this model, re-verifying an already-landed row buys
nothing, because nothing can have changed under it. The sweep's real job narrows to exactly two
cases — a newly added tag/row (verify once, at addition, the same discipline `refresh_natmod_archs.py`/
`refresh_usermod_boards.py` already require for a new tag's own facts), and a change to the fetch
*mechanism* itself (`dockerrun`, the build driver, the generic base image) which needs a
representative sample, not the full matrix. This is a real, load-bearing argument for the whole
redesign, not a side benefit — flagged here so a future session sizing the migration weighs it
correctly.

## Phased implementation plan

**One port migrates at a time; nothing else moves until that port is proven end-to-end and its
old path is still available to fall back to.** The failure mode this order exists to avoid is the
one CLAUDE.md's own top rule already warns about generally: a wrong abstraction discovered after
touching every port at once costs a session to unwind, where discovering it after touching one
port costs an edit. **`unix` goes first**, by direct user choice — it is the port this session's
own live verification already covers most completely (Bootlin's glibc/musl coverage checked
across all 5 arches, the cross-libc-from-a-glibc-host proof already done), and it is the one
whose current pypa-based mechanism this record argues should disappear entirely rather than
merely gain a sibling, so proving it first retires a whole subsystem rather than adding one.

**Phase 0 — the base image and the two provisioning steps, proven on nothing yet.** Every step
here reflects the addendum's own decisions, not the shape this plan was first written in.
1. **No `docker/*.Dockerfile` is written.** The base is the official `ubuntu:26.04`, unmodified
   and unpublished. What has to be decided instead is where its *reference* lives so the rest of
   the code can resolve it the way `dockerrun.image_for()` resolves every other one today — and
   whether that reference stays digest-pinned in `resources/pinned_docker_images.toml` (pinning
   and publishing are separate; keeping the pin costs nothing this decision removes, and
   [0068] is twice the record of what a floating base tag does).
2. **Auxiliary packages: a plain `apt-get install` inside the container, every invocation** —
   option (b), decided. `curl`, `ca-certificates`, `xz-utils`/`bzip2`, `make`, `python3`,
   `python3-pyelftools`, `git`, plus `cmake` only where the port needs it (`rp2`, per
   `arm_embedded.Dockerfile`'s own "cmake is here because rp2 needs it" precedent — do not carry
   it in for `unix` alone), plus the four `deplibs` needs (next item): `pkg-config`, `autoconf`,
   `automake`, `libtool`, `libltdl-dev`. **No compiler.** Measure what this actually costs per
   invocation while proving step 4, since that number is the only thing that would send this back
   to option (a) (a published image), and nothing else about the design changes if it does.

   `libltdl-dev` is not guessable and is here because D25 paid for it live:
   `deplibs`' own `autogen.sh` fails with `possibly undefined macro:
   LT_SYS_SYMBOL_USCORE` without it, and `autoconf`/`automake`/`libtool` between them ship no
   `ltdl.m4` at all (`build_unix.py`'s own module docstring).
3. **`unix` moves to `MICROPY_STANDALONE=1` on every arch, and `-static` does not come with
   it.** A Bootlin SDK carries a matched libc sysroot and nothing else — no libffi — while
   `ports/unix/Makefile` needs one either from `pkg-config` (the system) or from its own vendored
   `lib/libffi` under `MICROPY_STANDALONE=1`. Taking it from apt would link a libffi built
   against the *host's* glibc into the artifact, which is precisely the claim this record rests
   on ("the output's libc floor comes entirely from the toolchain's own sysroot, never from the
   host OS") quietly ceasing to be true. So the standalone path becomes the default for every
   cell, not the exception it is today.

   **This is a wider default, not new machinery.** `standalone` is already a per-arch flag in
   `build_unix.py`'s own `UNIX_ARCH_SETTINGS`; `mipsel` sets it today for the same reason
   generalised here — its own comment, "existed because no cross-usable libffi was available" —
   and `run_unix_deplibs()` has been exercised live end to end, with a real custom C module.

   **`LDFLAGS_EXTRA=-static` is a separate flag and stays behind.** The `mipsel` row happens to
   set both, which makes them look like one decision; they are not. A statically-linked libffi is
   a consequence of the toolchain having no system one. A fully static binary is a change to what
   cibuildmp ships, and [0031] already notes that even a "static" binary reaches `dlopen`. Nothing
   here argues for it, so nothing here should quietly deliver it.

   **Two things this drags along.** The cost is per *build*, not per toolchain: `deplibs` writes
   into `$(BUILD)/lib/libffi`, so libffi is rebuilt for every (tag, arch, libc) cell — measure it
   in step 4 alongside the apt number. And `[usermod.unix]`'s own `pre_checkout` in
   `build-platforms.toml` currently documents the opposite path (`apt install build-essential git
   python3 pkg-config libffi-dev`) and has to be rewritten with this, documentation though it is
   ([0052]).

   **The optimisation this leaves on the table, named so it is not rediscovered as a problem:**
   building libffi once *into the cached SDK's own sysroot* would return every arch to its normal
   `pkg-config` path and charge the build once per toolchain rather than once per cell. It is not
   chosen here because it makes the cache hold a *modified* SDK (the cache key then has to say
   so) and because sysroot-aware `pkg-config` (`PKG_CONFIG_SYSROOT_DIR`/`PKG_CONFIG_LIBDIR`) is
   exactly the plumbing that silently resolves to the host's `/usr` instead — the failure this
   whole item exists to prevent. It is a cache-population change, not a design change, so it stays
   available once there is a measured reason to want it.
4. **The toolchain fetch, and it runs inside the container, not on the host.** Download,
   sha256-verify, extract, `relocate-sdk.sh`, marked done by a `.installed`-style file, all
   *into a host directory `dockerrun.run()` mounts at its own identical path* — the shape
   `build_esp32.py`'s own `_esp32_container_script()` already has, for the reason [0058] gives
   ("the cache must be populated from inside the container, not on the host"). One mechanism,
   two toolchain kinds it can fetch (native, cross): `unix` only ever needs the native one, but
   it must not assume that, since the `arm_embedded` family needs both in a later phase, and
   since `container_mpy_cross()` needs the *native* one on `PATH` before it can build `mpy-cross`
   at all now that the base ships no compiler.
5. Prove it on one cell by hand, live, the way every claim in this record's own investigation was
   proven: fetch `x86-64--glibc--stable-2025.08-1` inside a bare `ubuntu:26.04`, build a real
   `ports/unix` (not just `mpy-cross`) for a *current* tag (`v1.29.0`) end to end, `examples/
   usercmodule`'s own C module included so `deplibs`/libffi linkage is exercised too, not just a
   trivial build.

**Phase 1 — determine every `unix` identifier's own toolchain fact, for real, not sampled.**
1. Extend `bin/refresh_toolchains.py`'s own `--resolve-apt` coverage (or a new, narrower script —
   decide by writing it, not in advance) to answer, per `(tag, arch, libc)`, which Bootlin release
   date is the right one: newest release whose own bundled compiler doesn't reintroduce a known
   incompatibility for that tag (`toolchains.toml`'s own `breaks-with` facts, extended with the
   `-Wdangling-pointer` finding this session made and has not yet written back into that table —
   a real, tracked gap, not forgotten).
2. For the pre-2021.11 `x86-64` tags and pre-2024.05 `s390x` musl tags (this record's own named
   gap), pin the oldest available Bootlin release explicitly, with the "newer breaks older, never
   the reverse" reasoning written next to the pin, not left to be rediscovered.
3. Write every resolved fact into `build-platforms.toml`'s own `[usermod.unix]` rows — this is
   the point where the identifier's own floor-number drop (already decided above) actually lands
   in a file, alongside the toolchain reference.
4. Live-verify a real sample spanning every discovered incompatibility boundary this session
   found (at minimum: one tag below the `15.1` ceiling, one at/after `v1.26.0`, and the
   `v1.20.0`-shaped `-Wdangling-pointer` case if it reaches `unix` at all — confirm live rather
   than assume it does or doesn't) — not the full 15-cell-per-arch matrix, a boundary sample,
   per this record's own CI-cost argument.
5. **For every tool the MicroPython build can see, not only the compiler, decide whether its
   version matters** — the checklist the addendum's own risk tiering argues for, rather than
   assuming the auxiliary set is safe because it has never visibly broken. `python3` (it runs
   upstream's own `makeqstrdefs.py`/`mpy-tool.py`/`makeversionhdr.py`, which change per tag) and
   `cmake` (`rp2` only; policy changes, against a `pico-sdk` version the tag itself pins) are the
   two priority candidates. If either turns out to matter per tag, it becomes a per-row fact
   beside the toolchain reference, the same shape everything else in this record already takes.

**Phase 2 — cut `unix` over, keep pypa reachable until it's proven safe to remove.**
1. `dockerrun.image_for()`/`build_unix.py` resolve `unix` to the bare `ubuntu:26.04` reference
   plus the apt step and the in-container toolchain fetch; every other port's own resolution is
   untouched. This is also where `image_for()` first has to answer a reference that this project
   does not publish, which is new — every entry it resolves today is one of this repo's own
   images.
2. `resources/pinned_pypa_images.toml` stays in the repo, unused by `unix`, until this phase is
   confirmed stable in real CI — deleting it is a separate, later commit, not bundled with the
   cutover, so a revert is one config change rather than a file resurrection.
3. `docs/reference/vendored-images.md`'s own generated table ([0077]'s machinery), every test
   fixture naming a `manylinux_2_28_*`/`musllinux_1_2_*` identifier, and `README.md`'s own
   `unix` section all need updating in the same session this lands — CLAUDE.md's own standing
   instruction about narrative docs surviving the record that obsoletes them applies exactly
   here.
4. Only once `unix` is green in real CI, on the new mechanism, for a real span of releases: retire
   `docker/manylinux_2_28_*.Dockerfile`/`pypa-tracker.Dockerfile`/`pinned_pypa_images.toml` for
   real, and update the tracker row for this record from "unix migrated" to closed-for-unix,
   open-for-everything-else.

**Phase 3+ — every other port, one at a time, same shape, order not fixed here.** Natmod's own
`x64`/`x86` (closes [0082] for real, not just documents it) and the `arm_embedded`/
`riscv_embedded`-sharing seven `usermod` ports (closes the live bug this record's own
investigation found in both Dockerfiles) are the next two candidates by evidence already in hand,
but which goes second is not decided here — pick it when `unix`'s own phase 2 is actually done,
informed by whatever phase 0-2 turned out to cost in practice rather than estimated now.

## Not decided here

- **The exact fetch mechanism.** *Where* it runs is decided (inside the container, into a
  host-mounted cache — see the addendum); what it looks like is not designed or implemented.
  Needs: one generic native+cross tarball fetcher (unlike ESP-IDF's own bespoke installer, this
  is the *same* mechanism — download, sha256-verify, extract, `relocate-sdk.sh`, mark, cache by
  version — for every port), and a decision about which module owns the host half of it (the
  `mkdir` and the `mounts=` entry, `build_esp32.py`'s own shape) versus the script half.
- **The `x86-64` pre-2021.11 fallback and the `s390x` musl pre-2024.05 fallback** — argued safe
  above (newer-breaks-older, never the reverse), not independently verified live the way every
  other claim in this record was.
- **Two things left over from deciding there is no image of this project's own.** First, where
  the `ubuntu:26.04` reference lives for `dockerrun.image_for()` to resolve, and whether it stays
  digest-pinned in `resources/pinned_docker_images.toml` — pinning and publishing are separate,
  and [0068] is twice the record of a floating base tag moving underneath this project. Second,
  what a per-invocation `apt-get install` actually costs in real CI, which is the one measurement
  that would send the auxiliary set back to option (a), a published image. Neither blocks Phase
  0; both should come out of it with a number or an answer rather than an assumption.
- **The usermod provenance sidecar's own exact shape** — named as required above, not designed.
- **Migration order and blast radius** — seventeen Dockerfiles, `resources/pinned_docker_images.toml`,
  `resources/pinned_pypa_images.toml` (removed entirely once `unix` no longer uses pypa),
  `dockerrun.image_for()`'s own resolution logic, every doc naming a current image group
  (`docs/reference/vendored-images.md`'s own generated table, [0077]/[0078]'s docs-drift
  machinery), and every test fixture referencing a `manylinux_2_28_*`/`musllinux_1_2_*`
  identifier. **Superseded in part by the phased plan above, which was written after this
  paragraph and decides what it left open**: `unix` goes first, not the `rp2` reference port this
  sentence originally named, and nothing existing is touched until Phase 2. What still stands
  here is the inventory — the list of everything a full migration eventually has to reach.
- **[0083]'s own windows-fully-prebuilt-mingw proposal** — not superseded, but now a special case
  of this record's own broader shape (llvm-mingw is itself exactly the kind of self-contained,
  per-arch tarball this record generalizes to everywhere) rather than a separate one-off decision.

## Addendum — no image of this project's own, and the two provisioning mechanisms that are not one mechanism

**Recorded after the fact, and this is why it is worth the words.** Everything below was decided
in conversation in the same session as the body above, and was lost before it reached a file: the
session's own transcript was deleted, and its last edit to this record (the fleet bullet, since
restored above) was never committed. It is reconstructed from the user's own screenshots of that
exchange plus the mechanism already in the tree. One pass of "it is decided, it will get written
down" has already failed here once; that is the argument for recording even the parts that feel
obvious.

**The question, asked directly:** must cibuildmp publish a Docker image of its own for this at
all, or can it run the official `ubuntu` image and install what it needs — `python3`, `curl`, the
rest — at run time rather than vendoring them into an image?

**The answer, and why it follows rather than being a new preference:** it is [0033]'s own rule
("cibuildmp never builds a Docker image itself; it only resolves a reference and pulls it") taken
to its end. Once no toolchain is baked into an image — exactly what the body argues for, every
compiler a per-identifier Bootlin tarball — the base holds nothing cibuildmp itself must produce,
and so **stops needing to be published at all**, not merely stops being built locally. A whole
level of [0046]'s own problem then disappears rather than being watched more carefully: no
Dockerfile of this project's own for it, no `publish-docker-images.yml` cycle, no digest-repin
PR, so there is no pin here that can go stale unnoticed because there is no pin.

**What the base then needs:** `curl`, `ca-certificates`, `xz-utils`/`bzip2` (Bootlin ships both),
`make`, `python3`, `python3-pyelftools`, `git`, and `cmake` only where a port needs it (`rp2`).
**No compiler of any kind.** That is the load-bearing half: the compiler was the single source of
every instability this project has chased — [0068]'s `ubuntu:24.04`->`26.04` breaking
`natmod_host`'s multilib pairing and `ppc64le_linux`'s long-double link, [0082]'s nine tags
failing `mpy-cross` under gcc 15, and this session's own `gcc-14`/`gcc-13` point-release drift.

### The correction that mattered most: the mounted cache is the toolchain's, and only the toolchain's

Stated first as though one mechanism covered both halves, and corrected in the same exchange
after re-reading `usermod/espidf.py`. Written out because the wrong version of it is an easy
mistake to make twice, and because the body's own fleet bullet made it once already (citing
`fetch_esp_idf()`, the `git clone` — i.e. *source* — for a pattern that is about binaries).

**Nothing is passed from host into container as a ready-made binary. The direction is the
opposite one:**

1. `dockerrun.run()` mounts an **empty (or already-populated-by-an-earlier-run) host directory**
   into the container at a specific path (`tools_dir = cache_root()/esp-idf/<version>/tools/...`).
2. Inside the container, the shell script itself does the `curl`/install **into that mounted
   path**.
3. Because it is a bind mount and not a container layer, what was downloaded **stays on the
   host's disk** after the container exits.
4. The next run sees the marker file (`.installed`) in that same mounted directory and **skips
   the download**.

So it is **caching of the toolchain itself**, nothing to do with apt packages, and not
"projecting host binaries into a container" — which also means it keeps [0058]'s own rule intact
("the cache must be populated from inside the container, not on the host"), the rule that exists
because a binary resolved against the host's glibc is exactly the `GLIBC_x.y not found` failure
`build_common.container_mpy_cross()`'s own docstring documents hitting for real.

**`python3`/`make`/`curl`/`git` are a separate question, and that mechanism does not answer it.**
apt writes into `/var/lib/dpkg` and system paths, not into one clean directory the way a tarball
does, so the same mount trick does not cache it. Two options, and they were named as such:

- **(a)** bake them into a **published image** of this project's own — one build-time `apt
  install`, fast, but an artifact to maintain and publish again.
- **(b)** `apt install` **on every invocation** in a bare `ubuntu:26.04` — nothing published, at
  the cost of network and time per invocation.

**Decided: (b), to start with** ("можемо для початку спробувати b"). The trade is practical, not
architectural — both work and both are consistent with [0033]; (a) is faster and one more thing
to maintain, (b) is less to maintain and slightly slower per invocation. If (b) proves too slow
in real CI, (a) is the fallback, and moving between them changes no design decision in this
record.

### Not every auxiliary tool carries the same risk, and two of them are not obviously safe

Raised in the same exchange, and it is the part most likely to be assumed away by a future
session: the tools above were sorted by whether the tool touches MicroPython's own build logic or
is purely cibuildmp's own mechanics.

- **Real risk, the same category as gcc — it touches the MicroPython build directly.**
  `python3` runs upstream's *own* scripts (`makeqstrdefs.py`, `mpy-tool.py`,
  `makeversionhdr.py`, qstr generation). Those scripts change with the tag: an old one may rely
  on old Python syntax or behaviour, a newer one may require a newer Python. Structurally this is
  the same risk class as the compiler — it simply has not been tested live yet. `cmake` (`rp2`
  only) is the second: cmake releases carry real policy behaviour changes, and `pico-sdk`, whose
  version is pinned to the tag through MicroPython's own submodule, may demand a minimum cmake
  version that does not match what the current Ubuntu ships.
- **Low but not zero.** `make`, `git` — stable for years, but that is an assumption, not a
  verified fact, and it should be written down as an assumption.
- **Practically zero — purely cibuildmp's own mechanics, never MicroPython's build logic.**
  `curl`, `ca-certificates`, `xz-utils`/`bzip2` only download and unpack tarballs;
  `python3-pyelftools` is cibuildmp's own dependency, not an upstream requirement (the same fact
  [0012] already recorded for `pyelftools`/`ar`).

**Stated honestly rather than folded into the recommendation: there is no evidence that
`python3`/`cmake` drift has ever actually broken a tag here** — unlike gcc, which has three
confirmed live incidents. It is an open question, not a verified fact, which is exactly why it
belongs in Phase 1 as a checklist item (added there) rather than being silently treated as safe.

### Weighed and rejected: vendor our own image, but bake every Bootlin release into it

Raised directly after the decision above ("maybe vendor our own after all, but bake *all* the
versions in at once — a `bootlin-musllinux.Dockerfile`?"), and answered by measuring rather than
estimating, since the whole question is a size question. Measured live, 2026-09-02, against
`toolchains.bootlin.com` itself:

- **One toolchain is 450 MiB on disk.** `x86-64--glibc--stable-2025.08-1` is 89 MiB compressed and
  **450 MiB extracted** — downloaded and unpacked, not inferred (ratio 5.06x).
- **There are seven stable releases per (arch, libc)**, not one or two: `2021.11-5`, `2022.08-1`,
  `2023.08-1`, `2023.11-1`, `2024.02-1`, `2024.05-1`, `2025.08-1`. The older four are `.tar.bz2`
  and are *larger* compressed than the newer `.tar.xz` ones (133-155 MiB against 82-88), so they
  do not extract any smaller.
- **For `x86-64` alone, glibc + musl, all seven releases each: 1 690 MiB compressed** (893 glibc,
  797 musl), roughly **6.3 GB extracted**.

What that makes each proposed shape:

| shape | contents | size |
| --- | --- | --- |
| one image per libc, all arches, all releases (the proposal as put) | 5 arches x 7 releases | **~16 GB** |
| one image per (arch, libc), i.e. today's fifteen cells | 7 releases each | ~3.2 GB each, **~47 GB** published |
| for comparison: the largest image this project has today | `riscv_embedded` | 2.06 GB |
| for comparison: the monolithic `natmod.Dockerfile` [0058] split up *because of its size* | | 4.09 GB |

So the cheapest baked variant is four times the thing [0058] already judged too big and broke
apart.

**Size is not even the decisive argument.** Baking reintroduces exactly the artifact the decision
above removes: adding a tag, or correcting one row's release, becomes a rebuild and a repin of a
multi-gigabyte image instead of a one-line config change, and [0046]'s own "nothing notices when
a pin goes stale" comes back with it. Every job also pulls the whole image to use one 450 MiB
toolchain out of it, where the mounted cache costs 89 MiB on a cold runner and nothing on a warm
one.

**And it is premature in a way the numbers alone do not show.** `unix` has 225 identifiers across
15 tags, and *which* Bootlin releases they actually need is what Phase 1 exists to determine.
An image baked before that answer exists is wrong the moment the answer arrives.

**The obvious middle ground fails for a reason already recorded:** baking exactly the one release
each identifier needs means one image per identifier — 70+ of them for `unix` alone, the same
fleet explosion [0058] rejected in a different form.

**The one real advantage of baking** — no download on a cold runner — is available without any of
this, by caching `cache_root()` with `actions/cache` on top of the mounted-cache model. That is
worth doing on its own merits, and it needs no image at all.

### Phase 0 step 5, run for real: what the live proof actually produced

Run 2026-09-02 on a real Docker host, exactly as the step above specifies -- a bare `ubuntu:26.04`,
the auxiliary set by `apt` at invocation time, `x86-64--glibc--stable-2025.08-1` fetched from
inside the container into a host-mounted cache, `ports/unix` at `v1.29.0` built with upstream's
own `examples/usercmodule` (so `cexample`, `cppexample` and `subpackage`, i.e. C++ included).

**It works, and the numbers Phase 0 asked for:**

| step | cost |
| --- | --- |
| `apt`, build-only set (no compiler) | **23 s** |
| `apt`, plus the autotools `deplibs` needs | 41-46 s |
| toolchain fetch + `relocate-sdk.sh` | 38 s cold, 0 s warm (marker) |
| `mpy-cross`, built by the Bootlin compiler | 4 s |
| `deplibs` (standalone libffi) | **9 s** |

The 9 s is the number that retires one of this record's own arguments: "the cost is per build, not
per toolchain" is true and nearly free. What actually recommends building libffi into the cached
SDK is therefore *not* time -- it is keeping autotools, and the compiler they drag in, out of the
build container (below).

**What the artifact proves.** `ELF 64-bit LSB pie executable, x86-64`; the smoke test runs, with
all three modules importing. `libffi` is absent from `NEEDED`, so the standalone static link
worked. The decisive check is not the floor number but the `.comment` section: it reads
`GCC: (Buildroot ...)`, so the Bootlin toolchain produced this binary and the apt `gcc 15.2.0`
sitting in the same image did not. Highest glibc symbol required: `GLIBC_2.38` -- below the
sysroot's own 2.41 and well below the host's 2.43.

**Two findings the run made that no amount of reading would have.**

1. **"No compiler of any kind" and "standalone libffi in the build container" are mutually
   exclusive under apt.** `libtool` hard-depends on `gcc | <c-compiler>`, so asking for the
   autotools `deplibs` needs installs `gcc-15` (`4:15.2.0-5ubuntu1`) -- precisely the version
   [0082] names as breaking nine tags. The build image cannot be compiler-free while it also
   builds libffi from source. **This is what turns "build libffi into the cached sysroot" from an
   optimisation into the resolution**: put autotools in the *provisioning* invocation, which runs
   once per toolchain, and the build invocation keeps the 23-second compiler-free set.
2. **`ports/unix`'s standalone path silently assumes a Debian/Ubuntu compiler.** Upstream hardcodes
   `$(BUILD)/lib/libffi/out/lib/libffi.a`, but libtool installs by the compiler's own
   `-print-multi-os-directory`: Ubuntu's multiarch-patched gcc answers `../lib`, a stock Buildroot
   toolchain answers `../lib64`, so the link fails with `cannot find .../out/lib/libffi.a`. It is
   arch-dependent -- 64-bit stock toolchains hit it, 32-bit ones do not, which is exactly why
   `mipsel` has used this path for a year without meeting it. One symlink in `run_unix_deplibs()`
   settles it ([0050]'s own "a FROM line and four symlinks" shape); building libffi into the
   sysroot avoids the question entirely, since `pkg-config` then reports whatever path is real.

**Why `mipsel` never had the compiler problem either, and why `unix` will.**
`manylinux_2_41_mipsel` installs `build-essential`, `libtool` and `libltdl-dev` *explicitly* and
is fine, because a stray host gcc emits x86-64 objects that cannot link into a MIPS32 ELF -- the
architecture mismatch is a hard, self-enforcing barrier. `unix`'s native cells have no such
barrier: the apt compiler's output links perfectly and the artifact silently acquires the host's
glibc. This is the same asymmetry [0068] and [0082] have now landed on three times -- what broke
under `ubuntu:24.04`->`26.04` was `natmod_host`, the *native* group, while every cross image
crossed that bump untouched.

### The resolution, run for real: libffi into the sysroot, and two package sets

The two findings above (a compiler-free base and a standalone libffi being mutually exclusive
under apt; the `out/lib64` mismatch) both dissolve if libffi is provisioned into the cached SDK's
own sysroot instead of being rebuilt inside every build. Tested rather than assumed, same day,
same host:

- **A provisioning invocation** -- autotools allowed, because it runs once per toolchain, not once
  per build -- builds `lib/libffi` with the Bootlin compiler at
  `--prefix=<sdk>/x86_64-buildroot-linux-gnu/sysroot/usr`. **8 s** (plus 41 s of apt, also once).
- **A build invocation** with the small set plus `pkg-config` and **no compiler at all**:
  `command -v gcc` is empty, confirmed in the run. `PKG_CONFIG_LIBDIR` points at the sysroot, and
  `pkg-config --cflags --libs libffi` answers with sysroot paths, not the host's `/usr`.
- **`ports/unix` goes back to its own normal branch**: no `MICROPY_STANDALONE`, no `deplibs`, no
  symlink. **8 s.** The binary's `.comment` reads `GCC: (Buildroot 2021.11-...) 14.3.0`, its
  highest required symbol is `GLIBC_2.38`, and the smoke test passes with all three of upstream's
  modules, C++ included.

**So the standalone decision recorded above is superseded before it landed anywhere.** Keep
`UNIX_ARCH_SETTINGS`'s `standalone` flag for `mipsel`, which needs it for its own reasons; `unix`
does not adopt it. What replaces it is the provisioning step, and with it the auxiliary package
list splits in two: **provisioning** (`autoconf`, `automake`, `libtool`, `libltdl-dev`,
`pkg-config`, once per toolchain) and **build** (`ca-certificates`, `curl`, `xz-utils`/`bzip2`,
`make`, `python3`, `python3-pyelftools`, `git`, `pkg-config` -- 25 s, and no compiler).

**`lib` vs `lib64` also stops being a question on this path**, for a reason worth writing down
rather than rediscovering: Buildroot's own sysroot already ships `usr/lib64 -> lib`, so the `.pc`
file's `-L.../usr/lib/../lib64` resolves to the real directory whichever spelling libtool picks.

**One thing a compiler-free base costs, named because its error message does not explain itself:**
the image has no binutils either, so `strip` and `size` must come from the SDK
(`CROSS_COMPILE`-prefixed) for `mpy-cross` as well as for the port. Without that the build stops
at `make: strip: No such file or directory`, which reads like a missing package rather than the
design working as intended.

### The compiler constraint is a fact about the MicroPython tag, not about the port

Proposed by the user as a hypothesis worth testing -- if the gcc a tag needs is the same in every
port, a pile of separate problems collapses into one. Tested against the real table rather than
argued, and it holds:

- **18 of 24 tags: every port agrees**, on gcc major 14. Nine scopes carry a `gcc` row fact
  (`natmod` plus eight `usermod` ports), and for every tag up to `v1.25.0` all nine say the same
  thing.
- **The six newest tags "disagree" only inside `natmod`**, and per *architecture* rather than per
  port: its ARM arches pin xpack `arm-none-eabi` 15.2.1 while its RISC-V arches pin xpack
  `riscv-none-elf` 14.3.0. Every one of the eight `usermod` scopes says 15 for those tags,
  unanimously. So the split is a difference of *vendor product*, not of constraint.
- **The boundary is exactly where a tag fact already says it is.** `toolchains.toml` carries
  `scope = "any"`, `breaks-with >= 15.1`, whose own detail names
  `-Wunterminated-string-literal` and the commit that fixed it "first in v1.26.0". `any` is
  already the tag axis; the per-port columns restate it.

**What follows, and it changes the model rather than the plan:**

- **The `gcc` column in nine scopes restates one tag fact about a thousand times.** It is derived,
  not observed -- which is why removing it from `usermod.unix` cost nothing (`4e222ab`), and why
  the same is true of the rest.
- **The 71 ceiling violations are one statement, not seven ports' worth**: the shared
  `arm_embedded` image is pinned above the tag ceiling. One repin answers 70 of them; the
  remaining one is `mimxrt`'s own `>= 13`, which no single shared pin can satisfy alongside the
  others and which is therefore the one genuine per-row case in that family.
- **`natmod` falls under the same check with no new machinery** -- and it needs to, because today
  it is not checked at all. `toolchains.toml` has no `natmod*` scope (its scopes are `any`,
  `mpy-cross`, `unix` and `usermod.*`), and `bin/refresh_toolchain_pins.py` iterates the scopes it
  finds in the facts, so `real_rows()`'s own `scope.startswith("natmod")` branch never runs on a
  default invocation. Its rows say 14.2.1 for old tags while `arm_embedded` ships 15.2.1, and
  nothing compares the two.

**The one distinction to keep**: same *constraint* is not same *version*. What a port may use is a
tag fact; what it actually installs is whatever its toolchain vendor publishes near that ceiling,
and those numbering schemes have nothing to do with each other.

### Verified in CI: `v1.20.0` was broken on the published images, and the row flag fixes it

Not a precaution. Two dispatches of `test-platforms.yml` against `v1.20.0-*linux*x86_64`:

- **run 33636118022 -- both cells red.** `py/stackctrl.c`'s `-Werror=dangling-pointer=`, inside
  `ghcr.io/ballistics-lab/manylinux_2_28_x86_64@sha256:1ad90a7...` and
  `quay.io/pypa/musllinux_1_2_x86_64@sha256:8900a53...`. Our own published manylinux image already
  carries `gcc-toolset-14`, so this tag has not been buildable on it.
- **run 33636602839 -- both green**, after the fix.

**What the first run caught that local work had not:** the failure is in `mpy-cross`, not in
`ports/unix`. `mpy-cross` compiles `py/` too, so the diagnostic stops that build before the port's
own make ever runs, while the row's `cflags_extra` was reaching only the port
(`container_mpy_cross()` now takes the same tuple, `0f3038c`). That is also why the relaxation
axis reaches [0082]'s nine tags for *every* port at once: they fail in the shared `mpy-cross`
build, not in a port.

### Weighed and rejected: `zig cc` instead of a per-identifier toolchain

Proposed as a way to replace the whole `unix` toolchain story with one 47 MiB self-contained
tarball, with the glibc floor as an explicit target parameter (`-target x86_64-linux-gnu.2.28`)
rather than a fact derived from a release date. It is a serious proposal and it was tested, not
argued away -- the "upstream never builds with clang" objection is simply false, as
`toolchains.toml`'s own rows show: `ci_unix_clang_setup` gives 22 `ci-apt` clang facts for
`usermod.unix`, with one ceiling (`clang >= 19`, `py/nlrx86`, fixed in v1.29.0).

**What it delivered.** A real `aarch64` binary, cross-built from an x86-64 host with no compiler
installed at all, whose highest required symbol is exactly the `GLIBC_2.28` that was asked for.
On the axis this record had to concede -- the floor becoming derived rather than chosen -- zig
genuinely wins.

**What it cost, measured over 4 tags x 4 targets x 2 user modules (32 real builds): 5 passed.**
Every passing cell was the native `x86_64`; every cross target failed. Six distinct
incompatibilities, each found by running it:

1. `zig cc -E` with more than one input file loses clang's own resource directory (`stddef.h`,
   `stdint.h` not found). MicroPython preprocesses every source in one invocation to extract
   qstrs, so this is hit on every build. Needs `-isystem <zig>/lib/include`.
2. zig's linker rejects `-Map`/`--cref`, which `mpy-cross/Makefile` and `ports/unix/Makefile` add
   unconditionally via `LDFLAGS_ARCH`.
3. `zig cc -E` rejects the *versioned* triple outright (`version '.2.28' ... is invalid`) -- the
   one feature zig is wanted for is rejected by the one step every build runs.
4. `-print-multi-os-directory` is `unsupported option`; libffi's own `configure.ac`/`libtool.m4`
   asks for it, so `MICROPY_STANDALONE` cannot configure.
5. `zig cc -E` does not select the C++ driver for a `.cpp` input, where `gcc -E` does (both run
   side by side to confirm). Since qstr extraction preprocesses C++ user-module sources through
   `$(CPP)` = `$(CC) -E`, any C++ user module fails.
6. `CROSS_COMPILE_HOST = --host=$(patsubst %-,%,$(CROSS_COMPILE))` -- passing `CC=` directly
   leaves it empty, so libffi's configure runs in native mode and dies on "cannot run C compiled
   programs".

**A `<triple>-gcc` wrapper script fixes 3, 4 and 6** -- and that is the argument against it, not
for it. The fix is to reconstruct a gcc-shaped driver around zig, which is what a Bootlin tarball
already is. 5 is not fixed by it. And zig covers no bare-metal target, so it cannot be the
uniform answer this record is about; it would be a second toolchain mechanism living beside the
first, for one port.

**For comparison, the Bootlin path needed exactly one workaround** (the `out/lib64` symlink above)
and produced a binary that passes the smoke test. That is the whole of the decision.

### What this changes in the phased plan above

- **Phase 0 step 1 is no longer "write the real `docker/<generic-base>.Dockerfile`."** Under this
  decision there is no Dockerfile of this project's own to write; the base is an upstream
  `ubuntu:26.04` reference plus a run-time provisioning step.
- **Phase 0 step 2 cannot be wired where that step puts it.** It says "wired into whichever of
  `build_common.py`/`orchestrate.py`" — host-side — while [0058] and `container_mpy_cross()`'s
  own docstring both document why a *binary* toolchain fetched on the host and used inside a
  container is the failure this project has already hit. The fetch runs **inside** the container,
  writing into the host-mounted cache, the way `_esp32_container_script()` already does.
- **One consequence the conversation did not reach, and it decides whether a compiler-free base
  works in practice.** `container_mpy_cross()` builds `mpy-cross` with the *image's own* native
  compiler. With no compiler in the base, the native Bootlin toolchain must already be on `PATH`
  from the same mounted cache before that call — which is this record's own "two independent
  toolchain facts per row" landing in code rather than in a table. Keep an apt `build-essential`
  for convenience instead and [0082] is reintroduced on day one, for every tag it names.

## Addendum, 2026-09-02 — item 5 landed, and turned out smaller than planned

**"Run-time `dnf install libffi-devel` for the five `manylinux_2_28_*` cells"** (the "Not started"
list above) shipped, but not as written: it needs no run-time install at all, on any cell.

Two things converged to make the layer itself pointless, not just movable. First, `unix` moved to
`MICROPY_STANDALONE=1` on every arch this session (record 0043's own `libffi-dev` reliance
reversed) — `ports/unix/Makefile`'s own `ifeq ($(MICROPY_PY_FFI),1) ifeq ($(MICROPY_STANDALONE),1)`
branch is the only one a cibuildmp build ever reaches now, and that branch builds `lib/libffi`
from source; it never calls `pkg-config --cflags/libs libffi`. `libffi-devel` — the one thing
`docker/manylinux_2_28_*.Dockerfile` ever added, and the whole reason those five images were
published — stops being read by anything. Live-verified against a bare `quay.io/pypa/
manylinux_2_28_x86_64` (`rpm -q libffi-devel`: not installed; `pkg-config --exists libffi`: fails,
as expected): a real `ports/unix` build, `deplibs` and the main link both, still succeeds end to
end and produces a running binary.

Second, `MICROPY_STANDALONE=1` everywhere surfaced two more real bugs, both fixed, both live-
verified against the actual published image rather than assumed:

- **`lib/libffi/configure.ac`'s own `toolexeclibdir`** (`${libdir}/$(gcc -print-multi-os-directory)`)
  installs `libffi.a` to `out/lib64/` on a RHEL-family host (`gcc -print-multi-os-directory` prints
  `../lib64` there, confirmed live) while `ports/unix/Makefile`'s own `LIBFFI_LDFLAGS`
  unconditionally expects `out/lib/libffi.a`. `musllinux_1_2_x86_64` prints `../lib`, which
  normalizes back to `lib` and needs nothing. `deplibs` has no hook to pass `--libdir=` through to
  libffi's own `configure` (hardcoded in the port's own Makefile), so `run_unix_deplibs()` now runs
  the `make ... deplibs` step through `sh -c` with a symlink fixup appended.
- **`LDFLAGS_EXTRA=-static`, bundled with `MICROPY_STANDALONE=1` into one `STATIC_LINK_OPTS` pair
  applied to every arch earlier this session, is not one decision and this record already said
  so** ("`LDFLAGS_EXTRA=-static` is a separate flag and stays behind", Phase 0 step 3, above) —
  reversed back apart. A `manylinux_2_28` image is a live, native glibc userland; PEP 600's own
  portability guarantee is *ordinary dynamic linking* against its symbol versions, the same
  mechanism every real manylinux wheel already uses, and reaching for `-static` on top of that
  bought nothing but a linker error (`cannot find -lm/-lpthread/-ldl/-lc`) on every
  `manylinux_2_28_*` cell — none of the five images ship `glibc-static`, confirmed live — for a
  guarantee record 0031 already documents as leaky on glibc regardless (`dlopen`/NSS still reach
  the *linking host's* glibc at runtime, static binary or not — the exact warning a real build
  prints for `modsocket.c`/`modffi.c`). `-static` stays on `musllinux` (no such leak — musl's own
  static story is genuinely complete, which is why Alpine/musl static binaries are a well-
  established pattern) and on `mipsel` (a Bootlin cross sysroot with no dynamic floor to link
  against in the first place, unrelated to which tag is being built).

**What actually landed** (all three commits live-verified against the real
`ghcr.io/ballistics-lab/manylinux_2_28_x86_64` and, for the last one, the bare
`quay.io/pypa/manylinux_2_28_x86_64` underneath it, not merely unit-tested):

- `sources.fetch_micropython()`'s clone path takes a `ports: list[str]` argument now, running each
  named port's own `make submodules` instead of a cibuildmp-maintained `RP2_SUBMODULES`/
  `UNIX_SUBMODULES` path list — the same "don't duplicate what the port's own Makefile already
  knows" argument this record already makes about toolchain versions, applied one layer over.
  `esp32` stays excluded (its own `submodules` target shells out to `idf.py`, needs the ESP-IDF
  environment, and declares no `GIT_SUBMODULES` of its own against `lib/` in the first place).
  natmod's own `micropython_submodules` config knob is untouched — user-supplied arbitrary paths
  for a module natmod itself does not own, with no port Makefile to delegate to.
- `run_unix_deplibs()` runs through `sh -c` with the `out/lib64` symlink fixup appended.
- `UNIX_ARCH_SETTINGS` drops the combined `STATIC_LINK_OPTS`; `unix_make_command()`'s own
  `_use_static()` decides per build (`musllinux_*` or `UnixArchSettings.force_static`, `mipsel`
  alone) rather than per arch alone.
- **All fourteen non-`mipsel` `unix` cells now resolve straight to `pinned_pypa_images.toml`'s own
  digest**, joining the nine that already did (`resources/pinned_docker_images.toml`'s own header
  comment, `bin/update_docker.py`'s `_pypa_mirror()` — already general enough that the five joining
  needed no code change, only data). `docker/manylinux_2_28_{x86_64,aarch64,ppc64le,s390x,
  i686}.Dockerfile` and their five `publish-docker-images.yml` matrix rows are deleted, not kept
  idle. `mipsel` is now the *only* `unix` cell — and the only image in the whole matrix outside the
  six toolchain groups/`windows`/`webassembly`/`esp_idf_base` — with a `ghcr.io/ballistics-lab/...`
  layer of its own.

**One more thing this incidentally proved**, worth stating since Phase 0-2 of the plan above still
assumes it needs proving: **item 5's own "run-time install" framing was the wrong shape for this
specific gap**, not wrong in general. The broader Bootlin-tarball-per-identifier destination this
record argues against, and the "pypa stays, install what's missing at run time" destination it
argues for instead, both still stand for whatever gap turns out to be real on a future tag. This
one just was not real to begin with, once `MICROPY_STANDALONE=1` closed it from a different
direction.

## Addendum, 2026-09-02 (second) — the full branch state against `main`, not just today's slice

This branch carries 43 commits over `main` by now, spanning several sessions and this record's
own multiple direction changes (Bootlin-uniformly, abandoned; pypa-stays-row-pin, landed). A
session picking this up cold should not have to `git log` its way through all of them to know
what is actually different. This section is that description, current as of this addendum —
re-derive it from `git diff main...HEAD --stat` rather than trusting it verbatim once more commits
land, the same caution CLAUDE.md's own top rule asks for everywhere else.

**The `unix` compiler/toolchain model, end to end:**
- `[usermod.unix]`'s `build-platforms.toml` rows lost the `gcc` column — the image fixes the
  compiler now, so a ceiling-derived pin had nothing left to decide.
- Per-tag gcc relaxations (`TAG_CFLAGS`, [0082]) reach both the port's own build and
  `container_mpy_cross()` — a diagnostic that stops one stops the other first.
- Per-architecture relaxations (`_ARCH_CFLAGS`): `aarch64` (`-Wno-error=array-bounds`), `s390x` and
  `riscv64` (`-Wno-error=clobbered`, this addendum's own item 4 below).
- Every `-Wno-error=<diagnostic>` candidate is **live-probed** against the actual compiler that
  will use it (`build_common.probe_supported_cflags()`) before being trusted — replacing every
  earlier version of this idea that predicted a gcc version instead of asking it, including this
  addendum's own item 2 below, found the same way.

**The Docker image fleet:** the five `docker/manylinux_2_28_*.Dockerfile` images and their
`ghcr.io/ballistics-lab/...` publishes are deleted. Every `unix` cell but `mipsel` (no pypa image
to begin with) resolves straight to `quay.io/pypa/<target>` — no cibuildmp layer at all, since
`libffi-devel` (the one thing those five images ever added) stopped being read once
`MICROPY_STANDALONE=1` went universal.

**`libffi`/`deplibs` robustness**, the actual subject of this addendum's own "five bugs" list
below: `MICROPY_STANDALONE=1` (vendor and build `lib/libffi` from source) applies to every `unix`
arch now, not just `mipsel`; the RHEL `../lib64` symlink fixup generalizes to *any*
`gcc -print-multi-os-directory` answer, queried live rather than predicted; `riscv64` gets
`MICROPY_PY_FFI=0` on the tags whose vendored `libffi` genuinely cannot build there; the clone-path
`make submodules` step actually fetches `lib/libffi` now (it silently didn't, for a tag with no
release tarball).

**CI infrastructure:** `bin/plan_test_matrix.py` buckets by image (not `(image, tag)`) to cut
redundant Docker pulls, and partitions the six real-QEMU-execution `unix` cells into their own
`emulated` bucket set, priced at their own measured weight rather than the shared default.
`test-platforms.yml` gained `keep_going`/`tolerate_failures`/`step_summary` inputs. `unix`'s main
build and `deplibs` step build with `-j<host cores>` now, matching `mpy-cross`'s own build (both
ran fully single-threaded before).

**Toolchain evidence tooling**, mostly unrelated to `unix` specifically: `resources/toolchains.toml`
and `resources/bootlin.toml` left the installed wheel for `docs/reference/toolchain-facts/` — real
data now, evidence rather than something loaded at runtime. `bin/fetch_bootlin_metadata.py` writes
the Bootlin release catalogue; `bin/refresh_toolchain_pins.py` checks a row's own claimed compiler
ceiling against it (and now knows about `natmod`'s own two cross scopes, not just `unix`'s);
`bin/refresh_usermod_boards.py`/`refresh_natmod_archs.py` gained `carry_forward()` so a
regeneration cannot silently drop a hand-merged per-row fact.

**New records this branch adds:** [0082] (`natmod` old tags fail `mpy-cross` under gcc 15), [0083]
(`windows` fully prebuilt MinGW toolchain), this one, and [0085] (`arm_embedded` thins out — not
started, see below).

**Verification status, as of this addendum:** native fully green (11 latest-patch tags × every
native `unix` cell, [33679538003]/[33681567696]). Emulated, all six cells now fully green across
every one of the 11 tags: `ppc64le` (unaffected by anything above), `s390x` (fix 4), `riscv64`
(fixes 1/3/4/5 together — the `../lib64/lp64d` fix's own scoped re-confirmation across all seven
affected identifiers, [33692643570], is the run that closed this out). `musllinux_1_2_ppc64le` (a
real QEMU relocation gap, [0044],
unrelated to anything on this branch) stays descoped.

**What is genuinely not done, unchanged by any of the above:** the two items this record's own
Status line now names as spun off (`TAG_CFLAGS` into every port's own `mpy-cross` rather than
`unix`'s alone, dropping the `gcc` column from the remaining nine scopes), plus `arm_embedded`
under its own record, [0085]. Nothing in this branch's 43 commits touches any of the three.

## Addendum, 2026-09-02 (third) — verifying item 5 live, on the full tag history, found five unrelated real bugs

The previous addendum closed item 5 (pypa stays, `MICROPY_STANDALONE=1` universal) on the
strength of the manylinux vendoring change alone. Actually running the resulting matrix — every
`unix` platform tag × the 11 latest-patch MicroPython releases, native and emulated, dispatched
separately (`plan_test_matrix.py`'s own `emulated` bucket partition, [12fe0fd]) — surfaced five
real, independent bugs the manylinux-only verification never exercised. None of them are on this
record's own "Not started" list (items 1-3 below, unchanged); all five are fixed, and every one
was live-verified against the real image before being called done, the same discipline this
record's own earlier addenda already used:

1. **The clone-path `make submodules` step never fetched `lib/libffi`.** `ports/unix/Makefile`'s
   own `GIT_SUBMODULES += lib/libffi` sits behind `ifeq ($(MICROPY_STANDALONE),1)`, and
   `sources._clone()` ran `make -C ports/<port> submodules` with no `MICROPY_STANDALONE=1` —
   silently computing a different, incomplete submodule list than the real build (which always
   sets it now) needs. Only reachable on a tag with no release tarball (`v1.30.0-preview` in this
   sweep); every tag with one vendors every submodule via the tarball itself, which is why nine
   sessions of manylinux-only testing never hit it. `sources.py`.
2. **`probe_supported_cflags()`'s own gcc probe (this record's item 5 machinery) checked the wrong
   compiler for `mipsel`.** It always probed an image's bare `gcc`, correct for every native pypa
   image but wrong for `mipsel`'s Bootlin cross-toolchain: the real build compiler is
   `mipsel-linux-gnu-gcc` (gcc 14.3.0), a different, older binary than whatever bare `gcc` resolves
   to inside the same image. The probe's own false-positive verdict let a gcc-15-only flag back
   into `CFLAGS_EXTRA`, and the real cross-compiler rejected it — disproving this project's own
   prior assumption that every Bootlin/xpack toolchain here was already gcc >=15. Now probes the
   actual compiler each build step uses. `build_common.py`.
3. **`riscv64` fails `deplibs` outright on every tag through `v1.23.0`.** `lib/libffi`'s own
   submodule pin, on those tags, points to `https://github.com/atgreen/libffi`, a fork whose
   `configure.host` has no `riscv*` case at all — `v1.24.0` moves the pin to the canonical
   `libffi/libffi` (`v3.4.6`), which does. Filed upstream; nothing to backport onto a tag that has
   already shipped. `MICROPY_PY_FFI=0` for exactly this (tag, `riscv64`) combination.
   `build_unix.py`'s own `_riscv64_ffi_unported()`.
4. **`s390x`/`riscv64` fail a real `-Werror=clobbered` diagnostic in `ports/unix/main.c`, on
   multiple tags, on both architectures.** [0044] found a narrower instance of this (`mpy-cross`'s
   own `main.c`, `s390x`, `v1.28.0` only) and descoped it by identifier; this sweep found it broad
   enough to suppress at the architecture level instead (`_ARCH_CFLAGS`), the same escalation
   `aarch64`'s own `-Wno-error=array-bounds` entry already went through — see [0044]'s own
   2026-09-02 addendum.
5. **`riscv64`'s `deplibs` symlink fixup (the RHEL `../lib64` one, this record's earlier addendum)
   only checked one hardcoded path.** `riscv64`'s own image answers `../lib64/lp64d` from
   `gcc -print-multi-os-directory` — its own ABI-variant subdirectory, one level deeper than the
   RHEL case the fixup was first written against. The fixup now runs
   `$(CC) -print-multi-os-directory` live, with the same compiler `deplibs` itself just used,
   instead of a value predicted in advance.

**Current sweep status.** Native: fully green (11 tags × 9 native cells, [33679538003]/[33681567696]).
Emulated: `ppc64le` fully green; `s390x` fully green after fix 4; `riscv64` green after fixes 1/3/4/5,
final scoped re-confirmation of the fix-5 tags in progress as this addendum is written — check
`test-all-platforms.yml`'s own latest scheduled/dispatched run before trusting that last clause
without re-verifying, the same caution this file's own top rule asks for everywhere else.
`musllinux_1_2_ppc64le` (QEMU relocation gap, [0044], unrelated to anything above) is still
descoped.

**Not evidence that items 1-3 below are any closer to done.** Every fix above was found *while
verifying* item 5, not while working any of the three "Not started" items — they remain exactly
as open as before this addendum.

[12fe0fd]: https://github.com/ballistics-lab/cibuildmp/commit/12fe0fd
[33679538003]: https://github.com/ballistics-lab/cibuildmp/actions/runs/33679538003
[33681567696]: https://github.com/ballistics-lab/cibuildmp/actions/runs/33681567696
[33692643570]: https://github.com/ballistics-lab/cibuildmp/actions/runs/33692643570

[0013]: 0013-micropython-list-dedup-by-abi.md
[0031]: 0031-unix-musllinux-libc-axis.md
[0033]: 0033-cibuildmp-never-builds-docker-image-itself.md
[0043]: 0043-unix-adopts-cibuildwheel-native-image-model.md
[0044]: 0044-unix-native-images-landed.md
[0045]: 0045-only-is-a-filter-not-a-forced-identifier.md
[0046]: 0046-pin-staleness-checker.md
[0052]: 0052-config-is-a-tree-not-a-selector-matrix.md
[0058]: 0058-image-groups-are-toolchains-not-ports.md
[0068]: 0068-docker-dependabot-grouping-and-mipsel-ubuntu-26-04.md
[0082]: 0082-natmod-old-tags-fail-mpy-cross-under-gcc-15.md
[0083]: 0083-windows-fully-prebuilt-mingw-toolchain.md

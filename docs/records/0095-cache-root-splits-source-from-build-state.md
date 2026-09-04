# 0095 — `cache_root()` is not one cache: fetched source persists, build state dies with the container

Status: In progress — **the plan below is superseded by addendum 2 (2026-09-04); read that
first, then addendum 4 (the runner allows it) and addendum 5 (what is actually in the code).**
One of six ports is migrated; the transitional dual path addendum 5 describes has to be deleted
when the last one is. Only item 5 (reports out of `cache_root()`) is settled and landed. Items 1-3 landed as
described and work, but answer the wrong question — they place a build tree on the host, which the
tool has no reason to own; addendum 2 replaces them with a `:ro` bind plus an overlayfs upper
inside the container, measured working. Item 4's instinct was right and its mechanism wrong. Item
6 was scoped out here and matters more than this record's own text says (addendum 1).
Related: [0009], [0012], [0019], [0033], [0043], [0044], [0058], [0063], [0069], [0084]

## The problem

The motivating question was whether `CIBMP_CACHE_PATH` (`sources.cache_root()`) can be handed to
an `actions/cache`-style step so a later CI run skips re-fetching MicroPython/ESP-IDF. It cannot,
today, because `cache_root()` is not one kind of thing — it already mixes fetched source with
compiled build state, and this project has a live, in-repo proof of what that mixing costs even
*within a single job*, before any cross-run persistence is involved at all.

`orchestrate.py:327-345` (`build_one()`) documents it directly: `build_dir`
(`mpy_dir/ports/<port>/build-<identifier>/`) is never cleaned between separate `cibuildmp`
invocations by anything but an explicit `shutil.rmtree()` this function runs first. A leftover
`build-unix-x64/` from an earlier run, built against a different (or no) `USER_C_MODULES`, carried
a stale `genhdr/qstrdefs.generated.h` missing the new run's QSTRs — `'MP_QSTR_mymod' undeclared`.
That `rmtree` only defends this one path, only host-side, only for the duration of one `run()`
call. It says nothing about the mpy-cross build state living in the same tree, which has no
cleanup at all — `container_mpy_cross()` (`build_common.py:340-341`) and
`sources.build_mpy_cross()` (`sources.py:323-341`) both cache their binary purely by
`binary.exists()`, with no key on the toolchain image, the identifier, or anything else that could
have changed since it was written. Handing `cache_root()` to a persistent CI cache as-is would
turn "reused within one run" into "reused forever, until someone notices the build is wrong" —
exactly the kind of accidental abstraction CLAUDE.md's own opening section warns costs a session to
unwind once it needs a record to undo.

## Three kinds of data live under `cache_root()`, undifferentiated

**A. Input — fetched once, host-visible, safe to persist across CI runs:**

- `micropython/<tag>/` (`sources.py:115-116`, `fetch_micropython()`)
- `esp-idf/<version>/idf/` (`espidf.py:67-132`, `fetch_esp_idf()`)
- (not under `cache_root()`, but the same class: cibuildmp's own installed `elftools`/`ar`,
  mounted for natmod — `natmod/build.py`'s `_deps_mount()`, [0012])

Plain git clones/tarballs. No ABI, no compiler, deterministic per key — this is the half worth
persisting.

**B. Output — host-owned, written directly by cibuildmp's own Python after a container exits, a
container never writes to it:**

- `options.package_dir / options.output_dir` (`mpyhouse`) — `orchestrate.py:356-380`
- `CIBMP_REPORT_PATH`, defaulting today to `cache_root() / "reports"` (`report.py:115-119`) —
  wrongly rooted; see item 5 below.

**C. Intermediate — must exist only inside the container's own ephemeral filesystem (or, where a
run genuinely needs to reuse it across identifiers, a host scratch path outside `cache_root()`),
never on a path that could be part of a persisted cache:**

- `mpy_dir/ports/<port>/build-<identifier>/` (`orchestrate.py:107-112`) — today `rmtree`'d
  host-side before each build (`orchestrate.py:343-345`), the exact mechanism the qstrdefs bug
  above already broke once
- `mpy_dir/mpy-cross/build-<slug>/` — `container_mpy_cross()`'s own build dir
  (`build_common.py:340-341`), reused across every identifier sharing a `slug` **by design**
  within one run, keyed on nothing but "does the file exist"
- `mpy_dir/mpy-cross/build/` — `sources.build_mpy_cross()`'s host-side build for the one
  remaining `_HOST_MPY_CROSS_PORTS` member, `qemu` (`sources.py:323-341`,
  `orchestrate.py:275-302`) — not container output at all, a real host-compiled binary, needing a
  different fix (item 3)

All three of C sit physically inside `mpy_dir` — the same directory A is fetched into, and the one
that would be handed to a persistent cache. That nesting is the entire mechanism by which compiled
state leaks into what should be pure fetched source.

## The plan

1. **`_resolved_build_dir()`** (`orchestrate.py:107-112`) stops nesting under `mpy_dir`. Each
   build gets a path that exists only inside the container's own filesystem — not bind-mounted at
   all — unless the produced artifact still needs to be read back from it (item 4).
2. **`container_mpy_cross()`'s `build_dir`** (`build_common.py:340`) moves the same way. Its
   existing within-run reuse across identifiers sharing a `slug` is a deliberate optimization, not
   a bug, and can survive by putting that path in a host scratch directory that is explicitly
   *outside* `cache_root()` (e.g. `runner.temp`) — reused for the life of one `cibuildmp`
   invocation, never a candidate for anything a CI cache step saves.
3. **`sources.build_mpy_cross()`** (the `qemu` host build) gets the same scratch-directory
   treatment as (2). It never runs inside a container, so redirecting `BUILD=` into one does not
   apply here — the fix is purely "not under `cache_root()`."
4. **`dockerrun.run()`'s `mounts`** (`dockerrun.py:582, 695-696`) stops being a flat, uniformly-`rw`
   `list[Path]`. `mpy_dir`, `esp-idf/<version>/idf`, and `package_dir` (`usermod_mounts()`,
   `build_common.py:87-90`; natmod's own `[mpy_dir, package_dir.resolve()]`) all become `:ro` —
   nothing about the user's own project needs write access either. The one thing every build still
   needs is a way to hand its produced artifact back to the host. Today the host reads `produced`
   directly out of the (currently writable) `build_dir` inside `mpy_dir` once the container exits.
   Once that tree is `:ro`, either the container's own command copies the produced file into a
   small, dedicated `:rw` staging mount before exiting, or the host runs `docker cp` before the
   `--rm` container is removed. **Left open deliberately** — this needs a live run to pick between,
   the same way [0085] left its own open items rather than guessing.
5. **`report_dir()`** (`report.py:115-119`) stops defaulting under `cache_root()` at all. Its
   default moves under the same root `output_dir` already resolves against
   (`options.package_dir / options.output_dir`, `orchestrate.py:356-366`) — reports join category
   B's own single, already-host-owned location instead of sitting in a second root that happens to
   be the same tree as category A. This needs `write_report()`'s two call sites
   (`natmod/__init__.py:269`, `usermod/orchestrate.py:543`) to start passing
   `options.package_dir`/`options.output_dir` through — `write_report()` today takes only
   `entries`/`total_duration` and knows nothing about either.
6. Once (1)-(5) land, a CI workflow step that saves/restores `CIBMP_CACHE_PATH` scopes its own
   `path:` to the category-A subtrees only (`micropython/*/`, `esp-idf/*/idf`) as a second,
   independent line of defense — not because (1)-(5) leave anything behind, but so a future change
   that puts something new under `mpy_dir` without reading this record does not silently start
   riding along in a persisted cache just because nobody remembered to ask.

## What this does not solve

- **`fetch_micropython()`'s own cache key is `tag` alone** (`micropython_dir()`,
  `sources.py:115-116`) — `ports=`/`submodules=` never participate in it. A checkout persisted
  across CI runs and then reused for the same tag with a *different* `ports=` set than whatever
  fetched it first silently serves an incomplete tree. Real today, independent of this record, not
  fixed here.
- **Whether `qemu`'s host-built mpy-cross is safe to execute against whatever image `qemu`'s own
  container build might one day use.** `orchestrate.py:294-298`'s own comment already flags this
  as unresolved ("whether this is exactly the mismatch `container_mpy_cross()` exists to prevent...
  is not established here"). This record only keeps that binary out of a persisted CI cache; it
  does not decide whether `qemu` needs its own `container_mpy_cross()`-equivalent.
- **Actually wiring an `actions/cache` step into any workflow.** This record only makes
  `cache_root()` safe to hand to one; it does not add the step, and does not repeat
  `action.yml:100-114`'s own apt-archives cache-key story (a different, already-documented
  fragility, not one this record touches).
- **natmod's own `build/<arch>*/` scratch space** (`natmod/__init__.py:119-128`) looks like the
  same shape but is not: it lives under the *user's own `package_dir`*, never under `cache_root()`,
  and is already handled by a pre-loop `rmtree` per `module_root`. Out of scope here.

## Addendum, 2026-09-04 — items 1, 2, 3 and 5 landed; a live run found three more sources of category C

Implemented as scoped: `_resolved_build_dir()` (1), `container_mpy_cross()`'s build directory
(2), `sources.build_mpy_cross()`'s host build (3) and `report_dir()` (5). Item 4 stays open --
this record left it open on purpose pending a live run, and the run below did not need it decided,
because the mechanism chosen for (1)-(3) keeps the produced artifact host-readable without any
`:ro`/`docker cp` question arising. Item 6 was already out of scope here and still is.

### The mechanism

`sources.scratch_root()` -- a fresh `tempfile.mkdtemp()` per invocation, removed at exit,
overridable with `CIBMP_SCRATCH_PATH` (which also disables the cleanup, since the path is then the
caller's; that is how a failed build's tree is kept for inspection, and `runner.temp` is the
natural CI value). `usermod_mounts()` adds it for **every** port, unconditionally.

Two details that are not obvious from the plan above and were decided by how Docker actually
behaves, not by preference:

- **The mount is `scratch_root()` itself, never the individual `build-<identifier>/`.** `docker
  run -v` creates a missing bind source **root-owned**, and `build_one()` deletes and recreates
  that directory before every build -- so mounting it directly would hand the `--user` container a
  path it cannot write to. `scratch_root()` always exists (the function creates it eagerly, for
  this reason) and is never removed mid-run.
- **`sources.build_mpy_cross()`'s pre-build cache check now looks only in the scratch
  directory**, not at `find_mpy_cross(mpy_dir)`'s in-tree layouts. Those in-tree paths are where
  `natmod`'s own container-built binary lives, so the old check could hand this function's one
  caller (`usermod`'s `qemu`, host-built by definition) a binary compiled under a different libc.
  Latent, never observed; now structurally impossible.

### Live-verified, not reviewed

Real builds from `examples/template`, real Docker, on this machine:

- `v1.29.0-manylinux_2_28_x86_64` -- **built in 156.6s**, 738024 bytes. Every object and the link
  step ran against `/tmp/cibuildmp-build-<rand>/ports/unix/build-v1.29.0-manylinux_2_28_x86_64/`,
  i.e. `make BUILD=` pointed **outside the checkout** works, which was the one mechanical
  assumption items 1-3 rest on. The collected binary runs and imports the module
  (`micropython-... -c "import template"` -> `template`), so `repair_unix_binary()`'s `lib/`
  sidecar still lands on the host through the new mount.
- `mpy6.3-v1.29.0-x64` (natmod) -- built in 100.3s, 237 bytes.
- Both reports landed in `examples/template/mpyhouse/reports/`, not under `cache_root()`.
- The scratch directory was gone after the process exited (`ls -d /tmp/cibuildmp-build-*` -> none).

### What the run found that this record's category C had missed

Counting files under `cache_root()/micropython/v1.29.0/` newer than that checkout's own
`.cibuildmp-complete` stamp separates what these two runs wrote from what earlier ones left. Three
of the four remaining writers are **not** in this record's own list above, and two of them cannot
be moved by the mechanism this record proposes:

| what | where | movable? |
| --- | --- | --- |
| `natmod`'s container-built `mpy-cross` | `mpy_dir/mpy-cross/build/` | **No.** `py/dynruntime.mk` hardcodes `MPY_CROSS = $(MPY_DIR)/mpy-cross/...` with no override -- `natmod/build.py`'s own `build_mpy_cross()` says so, and record [0093] establishes the path is a fact about the tag |
| `rp2`/`esp32` CMake build trees | `mpy_dir/ports/<port>/build-<BOARD>/` | **No**, not without reopening a settled decision: `rp2_make_command()` deliberately passes no `BUILD=` because a mismatched one breaks the port's own internal mpy-cross sub-build. 2186 files measured under `ports/rp2` from an earlier run |
| libffi's autotools output | `mpy_dir/lib/libffi/` (`configure`, `Makefile.in`, `aclocal.m4`, `ltmain.sh`, …) | **No.** `ports/unix/Makefile`'s own `deplibs` target runs libffi's `autogen.sh`/`configure` *in the source tree*; only the `out/` prefix follows `BUILD=`. **29 files, created by the verification run above**, timestamped inside its own window |
| the combined frozen manifest | `mpy_dir/ports/<port>/cibuildmp-manifest-<identifier>.py` | Yes, but it is generated config rather than build state -- 1 file, not addressed here |

**This changes item 6 from a belt-and-braces measure into the actual mechanism.** This record's own
wording -- *"not because (1)-(5) leave anything behind"* -- is now known to be false: they do, and
three of the four writers have no lever to stop them. A cache step that saves `CIBMP_CACHE_PATH`
must therefore *exclude*, not merely *scope*:

```yaml
path: |
  ${{ env.CIBMP_CACHE_PATH }}/micropython
  ${{ env.CIBMP_CACHE_PATH }}/esp-idf
  !${{ env.CIBMP_CACHE_PATH }}/micropython/*/mpy-cross/build*
  !${{ env.CIBMP_CACHE_PATH }}/micropython/*/ports/*/build*
  !${{ env.CIBMP_CACHE_PATH }}/micropython/*/lib/libffi
```

Still not wired into any workflow -- this record scoped that out and the addendum does not change
it -- but the exclusion list is no longer something the person wiring it can derive from the plan
above, which is why it is written down here.

### Docs corrected in the same session

`README.md`'s report paragraph (`~/.cache/cibuildmp/reports/`), its "Disk, and clearing it"
section (which claimed `--clean-cache` takes the reports with it -- it no longer can), its
`CIBMP_CACHE_PATH` row (which said mpy-cross builds are cached there), and `--clean-cache`'s own
`--help` text (same claim). `CIBMP_SCRATCH_PATH` added to the environment-variable table. This is
CLAUDE.md's own rule about narrative docs not self-correcting, applied at the time rather than
left for a reader to find.

## Addendum 2, 2026-09-04 — the plan above is the wrong shape; an overlay makes the whole question go away

The addendum above moved compiled state to a host scratch directory and redirected `BUILD=` into
it. That works, and it is live-verified, but it answers the wrong question. It accepts as given
that cibuildmp must own, place and clean a build tree on the host. It does not have to. **Nothing
outside the container needs a build file at all** — the tool's job is fetching and caching
tarballs and dispatching containers, and a build directory on the host is not part of that job.

Two constraints have to hold at once, and this record kept treating them as one:

- **No duplication.** The checkout is 1.7 GB extracted, 1.6 GB of it `lib/` (the release tarball
  vendors every port's submodules). Copying it into each container — cibuildwheel's own
  `copy_into()` tar-pipe, `oci_container.py:442` — is fine for a Python project of a few MB and
  wrong here. Extracting the 154 MB tarball inside the container instead takes **17.5 s**
  (measured, real image, `tar -xJf` from a `:ro`-mounted tarball) — cheap enough to consider, but
  it still writes 1.6 GB per container for data the host already has.
- **Nothing compiled on the host.** Which a plain `:ro` bind cannot give, because four things
  write into the checkout and none can be redirected (see the previous addendum's own table).

### The shape that satisfies both: `:ro` bind + overlayfs upper inside the container

`lowerdir` is the read-only bind of the existing host checkout — shared by every container, copied
never. `upperdir`/`workdir` live inside the container. Every write the build makes — `BUILD=`
trees, libffi's `autogen.sh` output, `mpy-cross/build/`, rp2's CMake directory — lands in the
upper layer and dies with the container.

**Measured, this session, not reasoned:**

| test | result |
| --- | --- |
| `make -C mpy-cross` (no `BUILD=`), checkout `:ro`, no overlay | fails: `OSError: [Errno 30] Read-only file system: 'build/genhdr/mpversion.h'`, `py/mkrules.mk:236` |
| same, **through the overlay**, cold build on a clean `v1.24.1` | **BUILD OK**, 4.7 s, binary at `/mp/mpy-cross/build/mpy-cross` (407760 B) |
| host checkout afterwards | **unchanged** — no `build/` directory created |
| overlay upper after that build | 19 MB — only what changed |

The privilege needed is **less than `--privileged`**: `--cap-add SYS_ADMIN --security-opt
apparmor=unconfined --security-opt seccomp=unconfined` is sufficient (verified; full
`--privileged` also works, and is not required). Without them the mount fails as `cannot mount
overlay read-only` — and it fails that way **even when `lowerdir` is itself inside the container**,
so the blocker is the `mount(2)` call being denied, not anything about the `:ro` bind. `upperdir`
cannot sit on the container's own overlayfs root; an anonymous volume (`-v /ovl`, disk-backed,
removed with `--rm`) or a tmpfs works.

### What this does to what already landed

- **`sources.scratch_root()` and the `BUILD=` redirect become unnecessary**, not wrong. They are
  the only thing that makes a `:ro` bind survivable *without* an overlay, so they stay useful as
  the fallback path for any environment where the overlay mount is unavailable — which is exactly
  the question the open items below have to answer before either is removed.
- **`report_dir()`'s move out of `cache_root()` (item 5) stands unconditionally.** A report is
  host-written output and has nothing to do with which side of the container a build tree lives
  on.
- **Items 1-4 of the original plan are superseded by this addendum.** Item 4 in particular
  (`mpy_dir` becomes `:ro`, plus a `docker cp`/staging-mount decision for getting the artifact
  back) is the right instinct with the wrong mechanism: `:ro` is achievable, but only with the
  overlay above, and the artifact still has to come out — and it cannot come out of a
  `docker run --rm` one-shot, which is why cibuildwheel keeps a **long-lived container**
  (`docker create` → many `exec` → `copy_out()` via `docker cp` → `rm -f`,
  `oci_container.py:320-360,478`) rather than a container per command the way `dockerrun.run()`
  does today. That refactor is the real work this record now implies.

### Open, and honestly not answered here

- **Does the overlay mount work on a GitHub Actions runner?** Verified only on this workstation.
  The runner's own Docker daemon is reachable from a plain step (`0028` established that), but
  nothing here checked whether `--cap-add SYS_ADMIN` plus relaxed apparmor/seccomp is permitted
  there. If it is not, the previous addendum's scratch directory is the fallback, and both paths
  have to coexist.
- **Docker Desktop / rootless / Podman.** Unchecked.
- **A full port build through the overlay.** Only `mpy-cross` was built this way. `unix` (with
  libffi's in-tree `autogen.sh`, the case that motivated all of this) and `rp2`'s CMake tree are
  the two that matter and neither has been run yet.
- **Whether `mpy_dir` stops being a host path in cibuildmp's own API.** Every build driver takes
  it as one today and embeds it in `make` command lines; under the overlay the container-side path
  (`/mp`) is what those commands need, and the host path is only what gets bind-mounted.

## Addendum 3, 2026-09-04 — every port that could not redirect `BUILD=` builds through the overlay

Addendum 2 left "a full port build through the overlay" open, naming `unix` and `rp2` as the two
that mattered. Both were run, on a clean `v1.24.1` checkout mounted `:ro`, upper on an anonymous
volume:

| build | result | host checkout afterwards |
| --- | --- | --- |
| `mpy-cross`, no `BUILD=` | 4.7 s, 407760 B | unchanged |
| `unix` `MICROPY_STANDALONE=1` (libffi from source) | **24 s**, 709416 B, binary runs — `MicroPython v1.24.1` | unchanged |
| `rp2` `BOARD=RPI_PICO` (CMake, no `BUILD=`) | **44.6 s**, `firmware.uf2` 667648 B | unchanged |

`unix` is the decisive one. `ports/unix/Makefile:299` ran libffi's `autogen.sh` and wrote
`configure` into the source tree — verified by printing `/mp/lib/libffi/configure` from inside the
container — and the host's own `lib/libffi/configure` still did not exist afterwards. The write
that made a plain `:ro` bind impossible now happens, in the right place, and evaporates with the
container. Overlay upper: 72 MB for `unix`, 101 MB for `rp2`.

Two things this did **not** settle:

- **`esp32`.** Untested; it needs the ESP-IDF image and its own toolchain provisioning, and
  nothing about its shape suggests a different answer, but that is an expectation, not a result.
- **The GitHub Actions runner.** Still the one blocking unknown, and now the *only* one:
  everything else in addendum 2's open list is answered. If `--cap-add SYS_ADMIN` with relaxed
  apparmor/seccomp is refused there, addendum 1's scratch directory is the fallback and both paths
  have to coexist — which is why that code stays rather than being reverted now.

**A cleanup mistake worth recording, since the next person will reach for the same command.**
Clearing build state from a cached checkout with a name pattern (`find -type d -name "build" -o
-name "build-*"`) destroys upstream *source*: the release tarball vendors submodules that ship
directories called exactly that — `lib/protobuf-c/build-cmake`,
`lib/alif-security-toolkit/toolkit/build`, `lib/CMSIS_5/CMSIS/DSP/SDFTools/examples/build`,
`lib/tinyusb/.claude/skills/build-doc`. Six cached tags were damaged this way this session, and
`.cibuildmp-complete` went on marking them valid, so `sources.py:152` would have kept serving
them. The recovery is to delete the stamp, not to repair the tree. Delete only the paths cibuildmp
itself creates, named explicitly, and never below `lib/`.

## Addendum 4, 2026-09-04 — the runner allows it, on both architectures; the last open item is closed

`.github/workflows/probe-overlay.yml`, run 33866525827. Five privilege levels, bottom up, each
running a real `make -C mpy-cross` with **no** `BUILD=` override against a real `v1.24.1` tarball
mounted `:ro` — the exact command that fails under a plain `:ro` bind:

| level | `ubuntu-latest` | `ubuntu-24.04-arm` |
| --- | --- | --- |
| bare `docker run` | `mount: /mp: permission denied` | same |
| `--cap-add SYS_ADMIN` | `mount: /mp: cannot mount overlay read-only` | same |
| **`+ --security-opt apparmor=unconfined`** | **mount ok, build ok (347072 B), upper 16 MB** | **mount ok, build ok (527296 B), upper 16 MB** |
| `+ --security-opt seccomp=unconfined` | pass | pass |
| `--privileged` | pass | pass |

`host-clean: PASS` on both — the `:ro` checkout carried no `build*` anywhere after all five levels.

**The minimum is `--cap-add SYS_ADMIN --security-opt apparmor=unconfined`.** Neither
`seccomp=unconfined` nor `--privileged` is needed — the workstation verification in addendum 2 had
tested the two upper rungs together and could not tell which was load-bearing.

**So there is no fallback to maintain.** Addendum 3 kept `sources.scratch_root()` alive
specifically against the possibility that a runner would refuse this; it does not, on either
architecture, so the two-mechanism outcome that made that hedge necessary is off the table and
the scratch path can be removed with the rest of the implementation.

### Two false conclusions this probe produced before it produced a true one

Both worth writing down, because in each case the *summary* was green-or-red in a way the run had
not earned, and only the elapsed time gave it away:

1. **Run 33866098636** — the arm job reported five `FAIL` in two seconds, which is not enough for
   five `docker run`s that each pull an image. Cause: `no matching manifest for linux/arm64/v8`.
   **`ghcr.io/ballistics-lab/embedded_base` is published amd64-only** — a fact worth knowing well
   outside this probe, for a project whose own CI uses arm runners. The arm half had mounted
   nothing; its `FAIL`s said nothing about overlays. Fixed by making the image a matrix field
   (the pypa manylinux images are per-architecture repositories this project already pins) and by
   pulling once, up front and unsuppressed.
2. **Run 33866281084** — then *both* runners reported five `FAIL`. The mount was not the reason:
   levels 3, 4 and 5 each printed `mount: ok` and the *build* after them failed.
   `-Wunterminated-string-initialization` is a **gcc 15** option ([0082]), `manylinux_2_28` ships
   gcc 14.2.1, and gcc does not quietly ignore `-Wno-error=` for a warning it has never heard of —
   it errors with `no option '-Wunterminated-string-initialization'`. Fixed by asking the compiler
   whether it takes the flag, which is exactly what `build_common.probe_supported_cflags()` already
   does and what this file should have done from the start.

The probe now prints `mount:` / `cflags:` / `build:` as separate lines and dumps the build tail on
failure, so a future failure names its stage instead of collapsing into one bit. **It stays in the
repo rather than being deleted as a one-off**: the whole build model now rests on a runner-image
property that nothing else in this project would notice changing.

## Addendum 5, 2026-09-04 — what has actually landed, and what the half-migrated state costs

Addenda 2-4 argued and measured the design. This one records the code, so the next reader is not
left inferring it from four commits.

### Landed

- **`dockerrun.Container`** (`a5bb9e7`) — `docker create` → `exec`* → `rm --force`, upstream's own
  shape. `OVERLAY_CREATE_ARGS` is the measured privilege pair and nothing more. The container is
  created as root because the overlay mount needs `CAP_SYS_ADMIN`; **every other command runs under
  `docker exec --user <uid>:<gid>`**, which is what keeps anything written to a read-write mount
  owned by the invoking user. Verified: mount as root, `make` as the host user into the same
  overlay, artifact out owned by `murphy`, mode 755, no `chown` anywhere.
- **The overlay mounts at the checkout's own host path** (`7827335`), not a tidy `/mp`. The
  read-only bind goes to `/cibuildmp-lower-N` instead. This was the difference between a mechanical
  port migration and one where every driver rewrites `mpy_dir`, `BUILD=`, `USER_C_MODULES`,
  `FROZEN_MANIFEST` and `MICROPY_MPYCROSS` — and where one missed path builds successfully against
  the wrong tree.
- **`unix` migrated** (`5059016`). One container for the whole build where there were six
  `docker run --rm`, all of the same image (`ensure_image()` resolves it once and every step took
  that same value — the six containers were never doing anything the one cannot). The gain is not
  the five saved containers: the steps now share a filesystem, which is the only reason the build
  tree ever had to be on a host mount at all. `deplibs` leaves `libffi.a` where the port's `make`
  finds it, `mpy-cross` leaves a binary `MICROPY_MPYCROSS=` names, `repair` reaches the binary the
  build left — none of which survived a `--rm` between steps.

### The shape the artifact takes now

`orchestrate.build_one()` creates `<output_dir>/.build-<identifier>/`, passes it to the driver as
`staging`, and removes it once the artifact is collected. The container writes the finished binary
there with an ordinary `cp` — it is the one read-write mount — and `repair_unix_binary()` then runs
against *that* copy, so `ldd` resolves against the container's own libraries while the `lib/` it
vendors lands beside the artifact where `unix_companions()` looks for it.

`build_unix()` therefore returns a path in `staging`, not a path into a build tree. That is a
contract change, and the tests now assert it.

**`Container.copy_out()` has no production caller.** It exists, is tested, and carries the
`docker cp` finding, but the `cp`-into-a-read-write-mount route turned out simpler for every case
so far. If the remaining five ports do not need it either, it should go rather than sit as
machinery nothing uses — the same judgement [0049] and [0050] applied.

### What the half-migrated state costs, and when it has to end

`probe_supported_cflags()`, `container_mpy_cross()`, `run_unix_deplibs()` and
`repair_unix_binary()` all take an optional `container=` and keep their pre-[0095] `dockerrun.run()`
path for the five ports still on it (`windows`, `webassembly`, `qemu`, `rp2`, `esp32`). That is a
deliberate transition, not a design: **two ways to run a build command is exactly the kind of
duplication that ossifies if it outlives the migration**, and the honest cost of not doing all six
ports at once is that only `unix` is verified end to end.

`sources.scratch_root()` is likewise still real, for those five. `_resolved_build_dir()` returns
the same string for every port; for `unix` that path is now only ever created *inside* the
container, so nothing lands on the host at it.

**When the last port migrates, all of it goes**: the `container=` parameters, `dockerrun.run()`
itself, `scratch_root()`, and `_resolved_build_dir()`'s scratch prefix.

### Live-caught, not reviewed

The first real end-to-end run failed at `docker create`:

    invalid mount path: 'mpyhouse/.build-v1.29.0-manylinux_2_28_x86_64' mount path must be absolute

`output_dir` defaults to a relative `"mpyhouse"` and `package_dir` to `"."`; Docker rejects a
relative bind source outright. `staging` is `.resolve()`d now. Nothing in the unit tests could have
caught this — they never reach a real `docker create`.

After the fix: `examples/template`, `v1.29.0-manylinux_2_28_x86_64`, **24.5 s, 738024 bytes**, the
collected binary runs and imports the module. The cached checkout afterwards holds no
`ports/unix/build*`, no `lib/libffi/configure` and no `mpy-cross/build`; the staging directory is
gone; `mpyhouse/` holds the artifact, `reports/` and `.gitignore`.

### Next, in order

1. `rp2` — already run through an overlay by hand (44.6 s, `firmware.uf2` 667648 B), so the
   unknowns are cibuildmp's own plumbing rather than the model.
2. `windows`, `webassembly`, `qemu`.
3. `esp32` — the only port never run through an overlay at all.
4. Delete the transition: `container=`, `run()`, `scratch_root()`.

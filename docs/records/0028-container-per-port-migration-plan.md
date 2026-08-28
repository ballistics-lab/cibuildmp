# 0028. Full migration plan: container-per-port for usermod

- Status: Implemented. **Closed 2026-08-28** (second addendum, below): `esp32` was the last
  bare-host port, now migrated to `esp_idf_base` ([0058]). Superseded in part by [0033]
- Related: [0019], [0025], [0026], [0029], [0030], [0031], [0032], [0033], [0053], [0058]

<!-- migrated verbatim from docs/BACKLOG.md lines 1943-2654 -->

**Superseded by D33, below: `ensure_image()`'s own "build cibuildmp's
packaged Dockerfile locally when nothing is registered" fallback,
described throughout this entry (and D26/D30/D31/D32), no longer
exists. cibuildmp never builds a Docker image itself any more -- see
D33 for the current design (checked against cibuildwheel's real source
before deciding, not assumed) and `usermod/dockerrun.py`'s own module
docstring for the code as it stands today. The rest of D28 stays as the
real record of how the container-per-port migration actually happened
-- the isolation argument, the per-arch image split, the buildx/type=gha
caching mechanics later removed by D33 are all still true engineering
history, just not the current build-vs-pull design.**

**D28 — full migration plan: container-per-port for usermod (D26),
written as a standalone handoff for a fresh session to execute.
Isolation between ports is the primary driver, not a side benefit** --
the user's own framing, directly: real builds should not be able to
break each other across ports the way **D25**'s six bugs all did within
`unix` alone, and CI's own cache story needs a documented, deliberate
answer before the migration starts, not discovered mid-flight the way
**D25**'s bugs were. Originally written as a plan, not a status report
-- since substantially updated in place, this same session, as steps 1
through most of 3 actually landed. The **"Handoff: exact state as of
this session's end"** block immediately below is the one to read first
if picking this up fresh; everything after "Why isolation is the real
driver" is the original plan text, kept (and updated in place) as the
detailed record of *why* each piece looks the way it does, not
re-derived from scratch.

---

**Handoff: exact state as of this session's end, for whoever (or
whatever session) picks this up next.**

**Done and verified on real CI:**
- Migration step 1 -- `action.yml` is a composite action, not a
  Docker action. Live-verified: natmod + all 5 `unix` usermod arches
  build correctly through it.
- Migration step 2 -- `usermod/dockerrun.py`'s resolver is real:
  `image_for(port, arch, libc=None)`, `PORT_IMAGES: dict[str, str]`
  keyed `"{port}-{arch}"` / `"{port}-{arch}-{libc}"`, env var override
  `CIBMP_<PORT>_<ARCH>[_<LIBC>]_DOCKER_IMAGE`. Covered by
  `tests/test_usermod_dockerrun.py` (6 cases). **`PORT_IMAGES` is still
  empty** -- nothing is registered as any caller's default yet, on
  purpose (see "the one real gap" below).
- Migration step 3, six of seven Dockerfiles written and building green
  in CI (`build-examples.yml`'s `verify-docker-images` matrix job,
  build-only + push on `push:` events):
  `unix-manylinux-{x64,x86,aarch64,armhf,mipsel}`, `windows` (x64+x86
  only, arm64 stays bare-host), `qemu`, `webassembly` (emsdk baked in,
  ~1.5GB image, **now wired to `ensure_image()` -- see D32's own
  "webassembly landed next" note below**). **Not started: `esp32`** --
  the one remaining port. Bake-vs-mount is decided (bake ESP-IDF in,
  same as `webassembly`'s emsdk, per **D19**); the Dockerfile itself
  just hasn't been written.
- Every Dockerfile that builds green also gets pushed to
  `ghcr.io/ballistics-lab/cibuildmp-<dockerfile>:sha-<gitsha>` on every
  real push (not gated behind a release tag -- the user's own explicit
  call: without a real pullable image, `PORT_IMAGES` could never be
  exercised end to end on a dev branch at all).
- `resources/docker/*.Dockerfile` all live as real package resources
  (`pyproject.toml`'s own `package-data`), not a top-level `docker/`
  directory -- verified live by building a real wheel and confirming
  every file lands inside it.
- Two real CI bugs found and fixed this session, both root-caused from
  actual job logs, neither guessed: (1) the `CIBMP_*`/`ACTION_*` env
  var collision (the composite action's own plumbing vars silently
  overrode `cibuildmp.toml` config -- see the ninth-bug writeup under
  migration step 1's own detail below); (2) the apt-archives GHA cache
  never actually saved even once (`Failed to save: Unable to reserve
  cache with key ..., another job may be creating this cache`, on
  every run checked) -- root cause: rapid-fire pushes left the cache
  key genuinely stuck (not just racing -- confirmed by a later run's
  own *restore*, uncontested by any save-timing collision, never once
  hitting either). Fixed by adding real `concurrency:` blocks to
  `build-examples.yml`/`usermod-dev.yml` (matching `publish.yml`'s own
  existing pattern, confirmed live to actually cancel superseded runs)
  plus minting a fresh `v2-`-prefixed cache key once the old one proved
  unrecoverable. **Confirmed fixed with real log evidence**: the first
  run on the new key logged `Cache saved with key:
  v2-apt-archives-Linux-<hash>` cleanly.

**The one real gap left before this stops being "images exist" and
starts being "the feature works": nobody has ever run a real usermod
build *through* `dockerrun.run()` against one of these pushed images.**
Every image proven so far only proves `docker build` (and `docker
push`) succeeded -- not that `cibuildmp` can actually use one to
produce a real binary. **Closed by D32, below**, in a slightly different
shape than the paragraph originally proposed here: rather than a
one-off manual env-var pointed at `unix`/`x64` alone, `unix` now
defaults to Docker for every one of its five arches via
`ensure_image()`, and `build-examples.yml`'s own CI proves the real
`ghcr.io/...:sha-<gitsha>` pull-and-run path on every push. Only after
that succeeds does registering anything in `PORT_IMAGES` as a real
pinned-release default become a reasonable next move.

**Explicitly not started at all:** `esp32.Dockerfile` (bake-vs-mount is
decided, see **D19** -- bake ESP-IDF in, same as `webassembly`'s emsdk;
just not written yet); `natmod`'s
own single combined Dockerfile (**D30**'s own point 2 -- a genuinely
separate track from this port-per-image work, confirmed out of scope
for the manylinux/musllinux split specifically: a `.mpy` loads into an
already-running target interpreter, no build-host libc linkage
involved at all); the musllinux identifier axis and any real musl
toolchain (**D31** -- large, multi-session, not attempted); registering
anything real in `PORT_IMAGES`; wiring `--platform usermod` or any CLI
flag to actually select a Docker-backed build by default (today it's
still opt-in only, via the env var, and not reachable from the CLI or
`action.yml` at all).

---

**Why isolation is the real driver, restated plainly.** Today, one
combined image (`action.Dockerfile`, and the standalone `Dockerfile`)
bakes every port's toolchain into one filesystem: `unix`'s five
cross-compilers, `windows`'s mingw pair, `esp32`'s ESP-IDF-adjacent
`libusb-1.0-0`. **D25**'s own six bugs were all *internal* to `unix`
(its own five architectures colliding), so per-port splitting alone
would not have caught any of them -- but it does bound the blast
radius going forward: an ESP-IDF version bump breaking `esp32`'s image
cannot silently break a `unix`-only build's image the way one shared
`apt-get install` line can today, and a caller building only `unix`
never pays for `windows`/`esp32`/`webassembly` toolchain weight at all
(today's single image pays that cost for every caller, every port,
unconditionally).

**Current state, precisely.**

- `resources/docker/unix-manylinux-<arch>.Dockerfile` exists for all
  five arches (`x64`/`x86`/`aarch64`/`armhf`/`mipsel`) -- one image per
  arch, not one combined `unix.Dockerfile` any more (this decision's
  own amendment above, **D31**): each holds only that arch's own
  packages (the exact per-arch set **D20/D24/D25** verified live,
  cross-checked directly against a real `v1.28.0` `ports/unix/Makefile`
  for which arches even need `pkg-config`/`libffi-dev` at all --
  `MICROPY_STANDALONE=1` arches, armhf/mipsel, build libffi from the
  vendored submodule instead and need neither). No `cibuildmp`
  installed inside any of them -- deliberately, since the whole point
  of the split is that `cibuildmp` stays on the bare host and only ever
  `docker run`s a port's own build command as a sibling container
  (never Docker-in-Docker; **D26**'s own reasoning for why: today's
  `action.yml` already runs *inside* one container, so nesting a second
  `docker run` from in there would need the host's Docker socket passed
  through -- fragile, avoidable by flipping which side runs bare).
- `usermod/dockerrun.py` exists: a sibling-container runner with a real
  resolver, migration step 2 (below), now implemented -- and corrected
  twice mid-session, on review. `image_for(port, arch, libc=None)`
  checks `CIBMP_<PORT>_<ARCH>[_<LIBC>]_DOCKER_IMAGE` first (an override
  for local testing/forks), then falls back to `PORT_IMAGES`, a plain
  `dict[str, str]` **in this file's own source** that a maintainer edits
  to register a port's canonical image -- not a `cibuildmp.toml` key.
  Keyed by `(port, arch)`, with an optional trailing `libc` segment only
  for ports that actually have one (`unix`, passing `"manylinux"`
  explicitly from `build_unix()`) -- `windows`/`qemu`/`webassembly`/
  `esp32` call it with no `libc` at all rather than defaulting to a
  "manylinux" label that means nothing for them. `PORT_IMAGES` is still
  empty today: the five `unix-manylinux-*` images above all exist and
  build correctly (inferred, not yet docker-built) but aren't published
  to GHCR yet (step 5), and registering any of them before a real
  pullable image exists would make every unopted-in `unix` usermod
  build for that arch start trying, and failing, to pull it -- so
  `image_for()` still returns `None` for every real caller today,
  unchanged. `build_unix()` in `usermod/build.py` checks this and, when
  it returns an image, routes both `run_unix_deplibs()` and the main
  `make` invocation through `dockerrun.run()` instead of a bare
  `subprocess.run()`. `dockerrun.run()` itself passes `docker run
  --pull missing` explicitly -- Docker's own default, confirmed live
  via `docker run --help`, pinned rather than relied on -- which is the
  entire answer to "how does cibuildmp decide build-vs-cache": it never
  decides anything, Docker does, and that only stays correct because
  every image this project resolves to is `:sha-<gitsha>`-tagged
  (immutable by construction) rather than `:latest` -- a cached local
  copy and a still-correct one are the same fact for a sha tag, which
  is not true for a mutable one.
- **`action.yml` is now a composite action -- migration step 1, done
  and live-verified on real CI, not just implemented.** `runs: using:
  "docker"` → `"composite"`, `entrypoint.sh` deleted (dead code,
  nothing references it any more), the apt-prerequisite list kept
  byte-for-byte identical to `action.Dockerfile`'s own (deliberately
  -- see migration step 1's own note on why slimming it now would have
  broken every existing usermod build), env vars renamed to clean,
  explicit names (`ACTION_PACKAGE_DIR`, not `INPUT_PACKAGE-DIR`) per
  the cibuildwheel-confirmed win noted above. `publish.yml`'s own
  `publish-docker` job and `action.Dockerfile` itself both still
  exist, now explicitly standalone (no longer feeding `action.yml`'s
  own `runs.image`, since there is no longer one). README updated to
  match.
  - **A ninth real bug, caught on the very first real CI run of this
    conversion:** the plumbing env vars were first named `CIBMP_*`
    (`CIBMP_PACKAGE_DIR`, `CIBMP_OUTPUT_DIR`, ...) -- and collided
    outright with `cibuildmp`'s own real, pre-existing, documented
    `CIBMP_<KEY>` config-override convention (`options.py`'s own
    `opt()`, the same mechanism `CIBMP_VERSION`/`CIBMP_CACHE_PATH` already
    use, checked *before* the config file and before any default).
    GitHub Actions always sets a step's own `env:` vars, even for an
    empty-string input, so every push silently exported
    `CIBMP_OUTPUT_DIR=""` -- and `opt()`'s own `environ.get(...) is
    not None` check has no way to tell "empty" from "unset", so it
    read that as an explicit override, replacing `DEFAULT_OUTPUT_DIR`
    ("mpyhouse") with nothing. Every natmod example built
    successfully (`cibuildmp: 10 target(s) built`,
    `cibuildmp: 7 target(s) built`) but collected its own output one
    directory too high (`examples/template/mpy6.3-natmod-x64/...`
    instead of `examples/template/mpyhouse/mpy6.3-natmod-x64/...`) --
    the mismatch only surfaced on the unrelated "List built artifacts"
    step, `ls: cannot access 'examples/template/mpyhouse': No such
    file or directory`. Confirmed live, both the reproduction and the
    fix: `CIBMP_OUTPUT_DIR=""` in the environment resolves
    `Options.load()`'s own `output_dir` to `Path('.')`; unset, or
    renamed to `ACTION_OUTPUT_DIR`, it correctly resolves to
    `Path('mpyhouse')`. Fixed by renaming every one of this step's own
    plumbing vars to an `ACTION_*` prefix, which cannot collide with
    any real `cibuildmp.toml` key, present or future.
  - **Still not yet done:** `--platform usermod` still always builds
    on the bare host inside this new composite action too -- there is
    no flag or config key yet that makes a caller's own build actually
    go through one of the `unix-manylinux-*` images as a sibling
    container (migration step 2's own resolver exists now, but nothing
    calls it with an image registered -- `PORT_IMAGES` is still empty).
    This remains the single largest gap before the `unix` slice is a
    real, usable feature rather than a proof-of-concept -- step 1 only
    removed the *structural* blocker (Docker-in-Docker), it did not yet
    wire the mechanism through.
- `resources/docker/windows.Dockerfile` also now exists (migration step
  3's first item -- one combined x64+x86 image, the two apt-installed
  mingw-w64 GCC packages `build_windows()` already proves work for this
  port; `arm64` stays bare-host-only until step 4 gives `dockerrun.py`
  real mount coverage for `sources.cache_root()`, where `llvm-mingw`
  downloads). Not split per arch the way `unix` is -- this port has no
  manylinux/musllinux-shaped axis, so the isolation argument for
  splitting `unix` doesn't carry over. Same open verification gap as
  every `unix-manylinux-*` image: not yet built for real via `docker
  build` (no reachable Docker daemon in the sandbox this was written
  in) -- correctness inferred from matching `action.Dockerfile`'s own
  already-proven package list for this exact port/arch pair, not yet
  confirmed independently. `build-examples.yml` now has a
  `verify-docker-images` job (matrix over all six Dockerfiles) that
  build-only `docker build`s each of them on every push -- no publish,
  no GHCR credentials, independent of `publish.yml`'s own `v*`-tag-gated
  `publish-docker` job -- closing this specific gap for real the moment
  it runs, not just documenting it as open.
- All six Dockerfiles live under `src/cibuildmp/resources/docker/`, not
  a top-level `docker/` directory -- moved there mid-session, on the
  user's own correction, once it was pointed out that a top-level
  `docker/` never shipped in the installed package at all
  (`pyproject.toml`'s own `package-data` only listed
  `resources/*.toml`). Real package resources now, the same as
  `natmod.toml`/`usermod.toml` already are -- `package-data` extended
  to `resources/docker/*` to match, verified live by building a real
  wheel and confirming all six files land inside it.
- `qemu`/`webassembly`/`esp32` still have no Dockerfile of their own at
  all yet.
- `action.yml`'s own apt-prerequisites step also now caches
  `/var/cache/apt/archives` via `actions/cache@v4.3.0` (pinned by
  commit SHA, verified live against a real `git ls-remote --tags` on
  `actions/cache` before pinning, not guessed), keyed on this file's
  own hash so a future package-list change busts the cache
  automatically. Orthogonal to the Docker migration above and not
  waiting on it -- the user's own observation, directly: this step is
  the slow part of every run today, independent of *which* toolchains
  it installs.
  - **A real bug, caught live by directly asking "did this actually
    help" rather than assuming it did -- the cache never saved even
    once.** `build`'s own duration got slightly *worse* after this
    landed (~355-365s before, ~410-415s after, both measured directly
    from real job timestamps), not better. Root-caused from real job
    logs, not guessed: every save attempt, on every run checked, failed
    with `Failed to save: Unable to reserve cache with key
    apt-archives-Linux-<hash>, another job may be creating this cache`
    -- and there is never a single "cache restored"/"cache hit" line
    for that key anywhere, on any of the (several, individually
    checked) runs this session pushed. The cause: seven commits landed
    in about 15 minutes, most sharing an unchanged `action.yml` (hence
    an identical hash-derived cache key), so multiple
    `build-examples.yml` runs raced each other to reserve+save it.
    **Not just simple two-run overlap, checked and ruled out as the
    whole story**: one run (`3f66aa6`) still failed all three of its
    own save attempts even though its own save-phase timestamps don't
    clearly overlap any single other run's own save phase -- consistent
    with GitHub's own cache API leaving a *stuck* reservation (a
    `reserve` that never reaches a completed `commit`, from an earlier
    run in the same pileup) rather than every failure being a clean
    two-way race at that exact instant. (Also confirmed separately:
    `action.yml`'s own composite action runs 3 times *within* one
    `build` job -- template/wasm2mpy/usermod-unix -- each with its own
    identical-keyed "Cache apt archives" step; harmless on its own,
    since only the first of the three needs to actually win the save
    and the other two would see the key already exists and skip
    cleanly -- but every one of the three failed here too, on every run
    checked, which is itself part of what points at a stuck reservation
    rather than a plain race.) **Fix attempted**: `build-examples.yml`
    and `usermod-dev.yml` both now have a real `concurrency:` block
    (`group: <workflow>-${{ github.workflow }}-${{ github.ref }}`,
    `cancel-in-progress: true`), the same pattern `publish.yml` already
    used -- a superseded run on the same branch gets cancelled outright
    instead of racing the newer one, live-confirmed to actually cancel
    a run (`3c1b389`'s own run was cancelled the moment `160a361` was
    pushed, and again when `160a361` itself was cancelled by `cf40ca5`
    moments later). **Confirmed the concurrency fix alone was not
    enough**: `cf40ca5` -- a completely clean run, nothing else active,
    nothing racing it -- still failed all three save attempts,
    identically. Conclusive, not just suspected: a later run's own
    *restore* (early in the job, before any same-job-save timing
    collision can even happen) never once found anything for this key
    either, across every run checked including `cf40ca5` -- if any save
    had genuinely completed at any point this session, some later run
    sharing that key would have hit it on restore. GitHub's own cache
    API documents no way to clear a stuck reservation directly, so the
    real fix was simpler: mint a fresh key. `action.yml`'s own cache
    key now has a `v2-` prefix (bump to `v3-`, etc. if this one also
    ends up stuck). **Confirmed fixed, real log evidence**: the very
    next run (`4837c58`) logged `Cache saved with key:
    v2-apt-archives-Linux-<hash>` on its own first of three save
    attempts -- the other two got the same "another job may be creating
    this cache" message, but this time it's the genuinely benign case
    (already saved earlier in the same job, moments prior), not a stuck
    reservation. This closes the apt-cache saga for real: the mechanism
    itself was always sound, the specific key it landed on this session
    just got stuck by a self-inflicted pileup of rapid pushes. The next
    real push after this one is the first that can show an actual
    restore/hit, still worth a glance but no longer in doubt.

**The full migration plan, in dependency order -- reordered from the
first pass above, per the user's own explicit follow-up.** The
original order built all five Dockerfiles before touching `action.yml`
at all; now that the Docker-daemon-reachability question is answered
(confirmed live, see the former "open question" below, now resolved)
and Docker is a required dependency rather than an optional path
(point 2 above), there is no more reason to keep writing Dockerfiles
nobody can reach yet -- wiring the mechanism through first, proven on
the one port (`unix`) that already has a real image, unblocks every
port after it and gives each new port a working end-to-end path the
moment its own Dockerfile lands, rather than five unreachable images
followed by one big wiring pass at the end.

1. **`action.yml` stops being a Docker action, becomes a composite
   action.** Moved first: this is the actual blocking gap ("not yet
   wired into the CLI or `action.yml` at all," the largest one flagged
   in this plan's own "current state" above), and nothing about it was
   waiting on more Dockerfiles existing -- `unix`'s own image already
   proves the mechanism. `runs: using: "docker"` → `runs: using:
   "composite"`, steps: ensure `cibuildmp` is installed on the runner
   (`uv tool install` from a pinned ref or, once GHCR-published images
   exist, possibly nothing at all if a future release ships a
   self-contained binary -- not decided, flag it as an open question
   rather than assuming), then invoke it directly. `entrypoint.sh`'s
   own input-parsing logic (the `INPUT_PACKAGE-DIR` etc. env-var
   reading, including the documented bash-not-dash requirement) moves
   into a composite action's own `run:` step -- and this is not just a
   move, it genuinely simplifies, confirmed against `pypa/cibuildwheel`'s
   own real `action.yml` (the user supplied its actual source directly,
   not a description of it): a composite action's own step-level
   `env:` block maps `${{ inputs.package-dir }}` to *any* env var name
   the step chooses, e.g. `INPUT_PACKAGE_DIR` with an underscore --
   cibuildwheel's own action does exactly this. That sidesteps
   `entrypoint.sh`'s whole `printenv 'INPUT_PACKAGE-DIR'` workaround
   entirely, not just moves it: the hyphen problem only exists because
   a *Docker* action's auto-generated `INPUT_<NAME>` env vars keep the
   input's own hyphens verbatim (undocumented by GitHub, found the hard
   way, `entrypoint.sh`'s own header comment has the full story) --
   nothing forces a composite action's own `env:` block to reuse that
   same broken naming, so the new composite `action.yml` should define
   clean, underscored env var names explicitly from the start rather
   than reproducing the workaround.
   - Two more real patterns worth deliberately deciding on, not just
     copying, from that same cibuildwheel `action.yml`: it builds an
     **isolated venv** per run (`venv.EnvBuilder`, installed into
     `$RUNNER_TEMP`) and exposes only the `cibuildwheel` binary (plus
     `uv` if requested via `extras`) on `PATH`, rather than a plain
     `pip install`/`uv tool install` into whatever Python the runner
     already has -- avoids polluting a job's own Python environment
     with `cibuildmp`'s own dependencies, relevant since composite
     actions run directly on the bare runner (unlike today's Docker
     action, where the whole container is disposable and pollution
     never mattered). Decide deliberately whether `cibuildmp` needs
     the same isolation or whether `uv tool install`'s own existing
     isolation (already a separate venv under `~/.local/share/uv/tools`,
     not the runner's system Python) already covers it -- plausibly
     yes, worth confirming rather than assuming either way.
   - It also branches explicitly on `runner.os == 'Windows'` (`pwsh`
     vs `bash`, quoting rules genuinely differ) -- irrelevant to
     `cibuildmp` today (Linux-runner-only, per the open questions
     below), but exactly the shape this migration would need to
     extend into if the Windows/macOS open question ever resolves
     towards "yes."
2. **The Docker-image resolver becomes real -- done, refined twice.**
   `usermod/dockerrun.py` now has `PORT_IMAGES: dict[str, str]`, a
   maintainer-owned mapping in the module's own source, plus
   `image_for(port, arch, libc=None)` checking
   `CIBMP_<PORT>_<ARCH>[_<LIBC>]_DOCKER_IMAGE` first (override) and
   falling back to `PORT_IMAGES` (the registered default). This is the
   literal shape of the user's own framing: adding a new port's support
   becomes "write one Dockerfile, then declare it in the resolver" -- a
   one-line addition to `PORT_IMAGES`, a maintainer editing source, not
   an end user's `cibuildmp.toml`.
   - **A real misunderstanding, caught and corrected before any wrong
     code shipped.** The first pass at this step started down a
     config-file path instead -- threading a `docker-image` key through
     `[usermod.<port>]` in `cibuildmp.toml`, `UsermodOptions.load()`, and
     a new field on `UnixBuildOptions`, on the theory that "declare it in
     the resolver" meant an end user's own config declaring which image
     to use. The user stopped this immediately: *"Стоп при чому тут
     конфіг???????"* / *"Я думав ми постачатимемо Dockerfile's для
     портів а не юзер через конфіг додаватиме"* (I thought **we** would
     ship the Dockerfiles for the ports, not that the user adds them via
     config) -- "the resolver" is `dockerrun.py`'s own Python source;
     "declare" means a maintainer registers a port's image there when
     its Dockerfile lands, the same way `UNIX_ARCH_SETTINGS` in
     `usermod/build.py` is itself a maintainer-owned dict, not a config
     surface. No `Edit`/`Write` had happened yet under the wrong
     reading -- caught at the investigation stage, corrected.
   - **Refined again, same session: keyed by `(port, arch)`, not `port`
     alone.** First implemented as `image_for_port(port)`/
     `PORT_IMAGES.get(port)`; the user then pointed out `unix.Dockerfile`
     itself was the wrong shape ("це херня, я думав ми наріжемо
     manylinux-x64 muslinux-aarch64 тощо") -- cibuildwheel's own
     per-(arch, libc) image shape, not one combined `unix` image (this
     decision's own amendment above, **D31**). Re-implemented as
     `image_for(port, arch, libc=None)`, `PORT_IMAGES` keyed
     `"{port}-{arch}"` or `"{port}-{arch}-{libc}"` -- `libc` stays
     optional (not defaulted to `"manylinux"`) so `windows`/`qemu`/
     `webassembly`/`esp32`, none of which have any libc axis at all,
     never carry a meaningless label; only `build_unix()` passes
     `"manylinux"` explicitly, `unix`'s own only real value today.
     `tests/test_usermod_dockerrun.py` covers six cases (no override +
     no registration → host build; registered default used; env
     override wins; an unregistered arch stays a host build even when a
     sibling arch is registered; an unregistered port stays a host
     build; `libc` omitted uses a two-part key/env name, not a
     `"manylinux"` stand-in). `PORT_IMAGES` stays empty until step 5
     actually publishes a pullable image for at least one `(port, arch)`
     pair -- registering one before that would break every unopted-in
     build for that exact pair the moment this step lands, not just
     when the port's own Dockerfile does.
3. **The remaining three per-port Dockerfiles, one at a time, each
   immediately usable the moment it lands** (step 1 and 2 already
   wired the mechanism, so this stops being "write five images, then
   wire them all at the end"). Any `resources/docker/unix-manylinux-*.Dockerfile`
   is the template to copy for a port with no libc axis (just drop the
   trailing `-<arch>` split unless the port genuinely needs it the way
   `unix` does): only that port's own toolchain, no `cibuildmp` baked
   in. `windows` was next -- apt-only toolchain, no large download like
   `esp32`'s ESP-IDF or `webassembly`'s emsdk, closest in shape to
   `unix` (**D26**'s own "first slice" precedent: one port, proven
   live, before the next).
   - **`resources/docker/windows.Dockerfile` -- written.**
     `gcc-mingw-w64-x86-64`/`gcc-mingw-w64-i686` only; `arm64` downloads
     `llvm-mingw` at build time regardless (`usermod/llvmmingw.py`),
     same as today. Not registered in `PORT_IMAGES` -- same as `unix`,
     not yet published (step 5), and not yet confirmed via a real
     `docker build` (see "current state" above).
   - **`resources/docker/qemu.Dockerfile` -- written, one combined
     image (no `unix`-style per-arch/libc split -- `qemu` only ever
     targets one board, `MPS2_AN385`, and a bare-metal ELF has no
     libc/musl axis at all).** Package list confirmed against two real
     sources, not memory (this bullet's own original instruction): (1)
     `o-murphy/a7p`'s own real `mp-usermod.yml`, whose
     `usermod-qemu-armv7m` job installs the toolchain via
     `cibuildmp/.github/actions/build-usermod-armv7m` --
     `gcc-arm-none-eabi libnewlib-arm-none-eabi`, `qemu-system-arm`
     installed separately, in the *caller's* own job, explicitly not a
     build dependency ("QEMU itself is deliberately NOT installed here:
     it is a runtime emulator... not a build dependency"); (2) this
     project's own `resources/natmod.toml`'s `arm-none-eabi` toolchain
     entry, whose `apt-packages` field is the identical string --
     `build_qemu()` already resolves this exact toolchain via
     `toolchains.resolve("armv7m")`, whose own "auto" strategy checks
     PATH before ever downloading the pinned xpack tarball, so
     apt-installing it here needs no code change to `build_qemu()` at
     all for this image to be usable. `qemu-system-arm` (the
     *execution* axis, **D21**) deliberately stays out of this image,
     matching `a7p`'s own split exactly -- registered in
     `verify-docker-images`'s own matrix, so it now builds (and
     publishes, on a real push) for real like every other Dockerfile
     here, not left open as a documented gap.
   - **`resources/docker/webassembly.Dockerfile` -- written, emsdk
     baked in.** A first pass here mounted emsdk from the host's own
     `sources.cache_root()` instead, on reasoning that does not
     actually hold: a Dockerfile `RUN` step's own output is a real
     image layer, reused unchanged by every later `docker run --rm`
     (only the ephemeral *container* is discarded per run, never the
     *image* a `RUN` step wrote into) -- there was never a
     "redownloads every run" problem baking in would have caused,
     unlike unix's own apt packages this reasoning was supposed to
     mirror. Asked the user directly once the real tradeoff (image
     size, not correctness) was clear: the extracted emsdk here is
     ~1.5GB, measured live via a real download + `tar tJf`, not
     guessed -- baking it in duplicates that download against
     `resolve_emsdk()`'s own bare-host cache rather than sharing one
     copy the way a mount would, but needs no `dockerrun.py`
     mount/PATH-injection support at all (a plain `ENV PATH` in the
     Dockerfile is enough) and ships a genuinely self-contained image
     the moment `docker build` finishes, consistent with every other
     image here. Baking in won. The pinned URL/sha256 (transcribed from
     `resources/usermod.toml`'s own `[emsdk]` table, `version =
     "6.0.8"`) was verified live before pinning -- downloaded for real,
     `sha256sum -c`'d, and its own internal `tar tJf` layout confirmed
     (a top-level `install/` containing `install/emscripten/` and
     `install/bin/`, exactly what `ResolvedEmsdk.env()` already
     expects) rather than assumed from the tarball's name. Real,
     live-checked finding while writing this: `ports/webassembly/Makefile`
     also declares `TERSER`/`NODE` (`npx terser`, for `.min.mjs`) --
     but only the `min`/`repl`/`test` targets touch them, never the
     default `all` target `webassembly_make_command()` always builds,
     so Node.js/npm are deliberately not installed here at all, not an
     oversight.
   - `resources/docker/esp32.Dockerfile` -- the heaviest one: ESP-IDF itself is
     a multi-gigabyte checkout with its own Python env bootstrap
     (`usermod/espidf.py`). Worth deciding explicitly whether ESP-IDF
     bakes into the image (large image, fast job) or stays a
     download-at-build-time step (small image, slow first job, cache
     shared across jobs via the cache strategy below) -- a real
     tradeoff, not an oversight, and should get its own one-paragraph
     decision when this Dockerfile is written, not silently default
     one way.
4. **`usermod/dockerrun.py` grows real mount coverage -- probably only
   for `esp32`, revised from the original three-port scope below once
   its own reasoning turned out flawed.** Originally written as: every
   port whose toolchain is a downloaded tarball rather than an apt
   package (`windows/arm64`'s `llvm-mingw`, `webassembly`'s `emsdk`,
   `esp32`'s `esp-idf`) would need `sources.cache_root()` bind-mounted
   into its container at *run* time, "or the image rebuilds/redownloads
   every single run." **That premise is wrong** -- caught while
   actually writing `webassembly.Dockerfile`: a Dockerfile `RUN` step's
   own output is a real image layer, reused unchanged by every later
   `docker run --rm` (only the ephemeral *container* is discarded per
   run, never the *image* a `RUN` step wrote into), so there was never
   a correctness reason to avoid baking a downloaded toolchain straight
   into the image the way `unix`'s own apt packages already are.
   `webassembly.Dockerfile` now bakes `emsdk` in directly (see "current
   state" above) -- no mount, no `dockerrun.py` changes needed at all
   for that port. The only real reason left to ever prefer mounting
   over baking is image size / avoiding a duplicate download between
   the host's own cache and the image layer (`emsdk`'s own ~1.5GB,
   measured live, was judged worth baking in anyway, on the user's own
   call) -- `windows/arm64`'s `llvm-mingw` is almost certainly small
   enough that the same call goes the same way when that arch's own
   Dockerfile coverage is written (not attempted yet -- `windows.Dockerfile`
   still explicitly excludes `arm64`). `esp32`'s `esp-idf` is the one
   case genuinely large enough (multi-gigabyte) that this decision
   still needs making deliberately rather than assumed either way --
   see its own bullet in step 3. If `esp32` does end up mounted rather
   than baked, this step is exactly that: `dockerrun.py` grows real
   mount coverage for `sources.cache_root()`, and `build_esp32()` needs
   its own docker-image-selection branch added alongside
   `build_unix()`'s existing one (`build_windows()`/`build_webassembly()`
   need no such branch for this reason any more -- both bake their own
   toolchain, `webassembly` already does, `windows/arm64` almost
   certainly will too). If `esp32` also ends up baked, this step may
   turn out to have nothing left to do at all -- genuinely open until
   that Dockerfile is written and its own tradeoff decided.
5. **`publish.yml`'s existing `publish-docker` job extends from one
   image to six** -- the job already exists (`docker/build-push-action`
   with `cache-from/cache-to: type=gha`, pushing
   `ghcr.io/ballistics-lab/cibuildmp:<tag>`/`:latest`); it needs a
   matrix over the six Dockerfiles (`unix-manylinux-x64`/`x86`/
   `aarch64`/`armhf`/`mipsel`, `windows`), pushing
   `ghcr.io/ballistics-lab/cibuildmp-<port>[-<arch>][-<libc>]:<tag>`/`:latest`
   each. Note the existing job's own comment: `action.yml` does not
   even consume this published image today -- it rebuilds
   `action.Dockerfile` from source on every single consuming job,
   across every repo, forever. That gap should very likely close in the
   same pass as this migration (composite `action.yml` pulls the
   pinned per-port image by default), not stay open a second time.
   - **Real correctness gap in this trigger, caught by the user's own
     question -- resolved, but not the way this bullet first
     described.** Copying `publish-docker`'s own trigger as-is (`if:
     github.event_name == 'push'`, and `publish.yml`'s only `push:`
     trigger is `tags: v*`) would mean per-port images publish *only*
     on a real release tag. But `cibuildmp` itself installs from
     `$GITHUB_ACTION_PATH` fresh on every ref (`uv tool install`
     already gives this reproducibility for the Python side) -- once
     `PORT_IMAGES` actually references a GHCR tag, a consumer on
     `@main` or any commit SHA that isn't an exact release tag would
     hit a real code/image mismatch: `dockerrun.py`'s own registered
     tag either doesn't exist yet, or points at a stale image built
     from an older Dockerfile. First asked directly and answered "leave
     this as a TODO, don't wire real pushes yet" -- then revised in the
     same session once the actual cost of that became concrete: without
     a real, currently-pullable image, `PORT_IMAGES` can never be
     exercised end to end on a dev branch at all, and waiting for a
     real release just to prove the mechanism this decision exists to
     build isn't reasonable ("щоб не чекати по пів року").
     **Implemented, in `build-examples.yml`'s own `verify-docker-images`
     job, not `publish.yml`** -- every `push:` event (never
     `pull_request`, so a fork's own PR never needs registry
     credentials) now also pushes each Dockerfile that builds green to
     `ghcr.io/ballistics-lab/cibuildmp-<dockerfile>:sha-<gitsha>`,
     `docker/build-push-action` with `cache-from/cache-to:
     type=gha,scope=<dockerfile>` (per-leg cache scope, so one image's
     rebuild can't invalidate another's). Deliberately `:sha-<gitsha>`
     only, no `:latest` -- a shared mutable tag across arbitrary
     branches would let one branch's push silently clobber what another
     branch, or a real release, expects `:latest` to mean; a real
     stable `:vX.Y.Z`/`:latest` alias still belongs to `publish.yml`'s
     own release-tag-gated job specifically, not here -- so this step's
     own "extends from one image to six" work above is still real,
     separate work, not superseded by this. `PORT_IMAGES` itself is
     still empty -- this only makes a real image reachable by an exact
     sha tag; registering one as every unopted-in caller's default is a
     separate, deliberate step once a specific `(port, arch[, libc])`
     combination has actually been proven end to end through
     `dockerrun.run()`, not just built.

**Cache strategy -- the direct answer to "we need a `CIBW_CACHE_PATH`
equivalent," in two genuinely separate parts.** cibuildwheel's own
`CIBW_CACHE_PATH` covers two different things at once (downloaded
build dependencies, and pulled container images); cibuildmp already
has a real answer for the first and needs a deliberate one for the
second -- conflating them would be a mistake.

1. **Toolchain/source cache -- already exists, `CIBMP_CACHE_PATH`.**
   `sources.cache_root()` (`src/cibuildmp/sources.py`) already reads
   `CIBMP_CACHE_PATH`, falling back to `$XDG_CACHE_HOME/cibuildmp` or
   `~/.cache/cibuildmp` -- this *is* the direct analogue of
   `CIBW_CACHE_PATH` for MicroPython checkouts, `mpy-cross`, and every
   downloaded toolchain (`toolchains.py`, `llvmmingw.py`, `emsdk.py`,
   `espidf.py` all resolve under it). Nothing new needs inventing
   here. What genuinely is new, for the migration:
   - Every sibling container needs the *right* subset of
     `cache_root()` bind-mounted in (see migration step 2 above) --
     today only `unix` is exempt from needing this at all.
   - `mpy-cross` itself should keep building on the bare host, not
     inside any per-port container -- it is architecture-independent
     shared infrastructure (`sources.build_mpy_cross()`, called once
     per `orchestrate.build()` invocation, before the per-target loop
     starts), not a port-specific toolchain artifact. Do not move it
     into a container "for consistency" -- there is no real reason to,
     and it would need its own image otherwise.
   - In CI, once `action.yml` is a composite action (migration step
     3), a caller gets to add a completely ordinary `actions/cache`
     step over `~/.cache/cibuildmp` (or wherever `CIBMP_CACHE_PATH` points)
     around the `cibuildmp` invocation -- something a Docker action
     structurally cannot offer at all today (GitHub's Docker-action
     mechanism has no way for a caller to mount a volume into the
     container it creates; the composite-action conversion is what
     actually unlocks this, not a new cache mechanism of its own).
     Document this prominently in README once it's real: it is the
     single biggest CI speed win this whole migration produces,
     independent of the isolation motivation.
2. **Docker image cache -- new, needs a real design, currently only
   half-built.** Two related but distinct things:
   - *Building* a per-port image already has a real cache
     (`publish.yml`'s own `cache-from/cache-to: type=gha`, GitHub's
     own Actions cache backend, persists across workflow runs in this
     repo) -- extending this to five images (migration step 5) is
     mechanical, the pattern is already proven.
   - *Consuming* a per-port image (any caller's own `uses:
     ballistics-lab/cibuildmp@vX` build) should default to `docker
     pull`ing the pinned GHCR tag, which benefits from the registry's
     own layer cache automatically -- no extra configuration needed,
     the same way any other published Docker image works. This is
     where `CIBMP_<PORT>_DOCKER_IMAGE` becomes a real, documented
     *override* (build your own local image, or pin an older
     release's image) rather than the only way in.
   - **Genuinely open, not yet decided:** should there be a
     `CIBMP_DOCKER_CACHE`-style env var at all, analogous to
     `CIBW_CACHE_PATH`'s own directory, for a self-hosted runner or a
     laptop that wants pulled images to live somewhere specific (not
     Docker's own default storage driver location)? `docker`'s own
     `--data-root` / `daemon.json` already covers this at the daemon
     level, arguably making a cibuildmp-specific env var redundant --
     lean towards *not* inventing one unless a concrete need surfaces,
     but flag it explicitly here rather than silently deciding either
     way.

**Risks and open questions to resolve before or during implementation,
not after:**

- ~~Can a GitHub-hosted runner's own Docker daemon actually be reached
  from a composite action's plain shell step~~ -- **resolved, confirmed
  live on real CI, not just reasoned about:** a throwaway diagnostic
  job (`composite-action-docker-reach-check`, `usermod-dev.yml`, no
  `uses: docker` anywhere) ran a plain `docker info` and `docker run
  --rm hello-world` directly in an ordinary `run:` step on
  `ubuntu-latest`. Both worked immediately, no setup step of any kind:
  `docker info` reported a real, already-running daemon (Docker Engine
  28.0.4, `overlay2`, `runc`), and `docker run --rm hello-world`
  genuinely pulled the image from Docker Hub and printed its own real
  "Hello from Docker!" banner. Confirms the entire premise this
  migration's composite-action step depends on: GitHub-hosted runners
  really do ship a live, reachable Docker daemon with zero container
  boundary in the way, for any plain step, not just inside a Docker
  action's own container. The diagnostic job has been removed
  (`usermod-dev.yml`) now that its answer is folded in here.
- Self-hosted runners without Docker at all (mentioned nowhere in this
  session, but a real category of `cibuildmp` user going forward) lose
  the per-port image path entirely under this design. **Decided, below
  under this same decision's usermod bullet: fail loudly, no bare-host
  fallback** -- Docker is a hard requirement for usermod, not an
  optional one with a silent fallback.
- Windows/macOS runners: **D2/M2**'s own "why not docker for x86"
  reasoning, and the open question already in this document's own
  "Windows/macOS hosts" entry, both predate this plan -- a per-port
  *Linux* container obviously cannot run on a bare Windows/macOS
  runner at all, so this migration is implicitly Linux-runner-only
  unless and until that open question resolves separately.
- This is genuinely large, multi-session work -- five Dockerfiles, a
  real `action.yml` rewrite affecting three consuming repos'
  workflows, `publish.yml` extended, `dockerrun.py` mount coverage for
  four more ports, `docker`-strategy branches in four more
  `build_<port>()` functions, README's own Docker section rewritten.
  Do not attempt it in one sitting; **D26**'s own "first slice"
  precedent (one port, proven live, before committing to the rest) is
  the right shape to keep following -- `windows` is the natural next
  slice (apt-only toolchain, no large download like `esp32`'s
  ESP-IDF or `webassembly`'s emsdk, closest in shape to `unix`).

## Addendum, 2026-08-28 — closed: `esp32` was the last bare-host port

`unix` ([0043]/[0044]), `windows` ([0042]), `webassembly` and `qemu` ([0032]/[0058]) all
migrated to per-port containers in the sessions after this plan was written. `esp32` stayed
bare-host the whole time -- [0050] even took it out of the default port set specifically
because it was the one remaining bare-host build path -- until now: `build_esp32()`
(`usermod/build.py`) runs entirely inside `esp_idf_base` ([0058], the image this plan's own
D19 already flagged Docker for and then dropped after live-testing found the bare-host path
"just worked"). Only `espidf.fetch_esp_idf()`'s `git clone` stays host-side, on the same
"source, not a binary" reasoning `mpy_dir` itself is mounted straight into every image with
no rebuild -- see `usermod/espidf.py`'s own module docstring for the full account of why the
bare-host path finally broke (ESP-IDF's own `install-python-env` refusing to run from inside
cibuildmp's own `uv tool install` venv, once `esp32` was exercised broadly rather than by
hand) and what changed.

Two more real bugs this session's own live run found, neither visible from review:

- **`examples/template` had no `micropython.cmake` at all.** Every other usermod port here is
  a Make port, whose `USER_C_MODULES=` value (a directory, D16) happens to also cover this
  project's own `manifest = "usermod/manifest.py"` as a mount side effect. `esp32` is a CMake
  port -- `USER_C_MODULES=` there is a single `.cmake` *file* -- so mounting just that file
  left the sibling `usermod/manifest.py` unreachable inside the container the first time
  `esp32` ever really built through it (`CMake Error ... [Errno 2] No such file or
  directory`), and once that was fixed, a second error showed `examples/template` had simply
  never had a `micropython.cmake` to find in the first place -- `esp32` (and `rp2` and every
  other CMake port [0053] still has no driver for) had never been exercised against this
  project's own fixture at all before this session. Fixed by mounting
  `Path(opts.user_c_modules).parent` instead of the bare file (bringing esp32 up to the same
  directory-level mount coverage every Make port already had) and by writing a real
  `examples/template/micropython.cmake`, mirrored from upstream's own
  `examples/usercmodule/usercmodule.cmake`.
- **`fetch_esp_idf()`'s plain `--recursive` clone was needlessly slow.** MicroPython's own
  `ports/esp32/README.md` says so directly: "You don't need a full recursive clone; see the
  `ci_esp32_setup` function in `tools/ci.sh`." That function clones `--depth 1` with no
  `--recursive` at all, then `git submodule update --init --recursive --filter=tree:0` as a
  separate step -- a treeless partial clone, its own comment explaining the choice over the
  more obvious `--shallow-submodules`: "works when the submodule commit isn't a head."
  `fetch_esp_idf()` now does the same two-step clone.

Live-verified, not just implemented: a real `examples/template --build v1.29.0-esp32-*`
invocation produced a genuine `micropython.bin` with the project's own C module
(`template_usermod.c`/`template_core.c`) linked into it, through the full container path --
install, `mpy-cross` (moved out of `orchestrate.py`'s own `_HOST_MPY_CROSS_PORTS`, matching
`unix`/`windows`/`webassembly`), and `make` itself, none of it touching the bare host.

## Addendum, 2026-08-28 (second) — `idf_version`/`idf_target` threaded from the real row

Found the same day, once `test-platforms.yml` (no longer skipping `esp32`) was actually run:
every board resolved `Esp32BuildOptions`' own dataclass defaults (`v5.5.1`/`esp32`)
regardless of what its real `build-platforms.toml` row said, because `UsermodTarget` itself
only ever carried `port`/`arch`/`tag` -- `idf_version`/`mcu` were dropped the moment
`all_usermod_targets()` built one from a row. A RISC-V board (`esp32c2`/`c3`/`c6`) would have
installed the Xtensa toolchain and failed.

Closed by a lookup, not by widening `UsermodTarget`: `targets.py`'s new
`esp32_idf_info(tag, board)` resolves `(idf_version, mcu)` from the same rows
`_IDENTIFIER_BY_PORT_TAG_AXIS` already indexes, keyed the same way. `_port_build_options()`
(`orchestrate.py`) calls it when `target.tag` is set, falling back to the dataclass defaults
only for a hand-built target with none (most of this project's own tests) -- the same
allowance `UsermodTarget.identifier`'s own docstring already makes for that case.

Live-verified for both instruction-set families, not inferred from the lookup being correct
on paper: `v1.29.0-esp32-ESP32_GENERIC` (Xtensa, `esp32`/`v5.5.1`) and
`v1.29.0-esp32-ESP32_GENERIC_C3` (RISC-V, `esp32c3`/`v5.5.2`) each produced a real
`micropython.bin`, the second confirmed via its own build log ("Creating esp32c3 image...",
not `esp32`) that the resolved `idf_target` actually reached `idf_tools.py install
--targets=`, not just the identifier string.

[0032]: 0032-unix-docker-default-and-webassembly-wiring.md
[0042]: 0042-windows-docker-wiring-and-resolver-removal.md
[0043]: 0043-unix-adopts-cibuildwheel-native-image-model.md
[0044]: 0044-unix-native-images-landed.md
[0050]: 0050-natmod-is-docker-only.md
[0053]: 0053-usermod-ports-without-a-build-driver.md
[0058]: 0058-image-groups-are-toolchains-not-ports.md

# 0030. Extending the container approach to natmod too, and "Docker or QEMU" answered directly

- Status: Accepted
- Related: [0002], [0021], [0025], [0026], [0028]

<!-- migrated verbatim from docs/BACKLOG.md lines 3005-3160 -->

**D30 — extending the container approach to natmod too, and a direct
answer to "Docker or QEMU" (they are not competing choices).** The
user's own follow-up to **D28**, six concrete points, addressed here
individually so a fresh session has the reasoning, not just the
conclusion.

1. **Confirmed, already the design**: `cibuildmp` stops running inside
   a container and starts launching container builds itself (**D26**'s
   own "sibling containers, not Docker-in-Docker" reasoning). No change
   from **D28**.
2. **natmod already builds cleanly through one combined Dockerfile
   today -- genuinely proven, not aspirational.** Every one of
   **D25**'s six real bugs happened inside `unix`'s own five
   architectures colliding; natmod's own arches, sharing that exact
   same combined image the whole time, never broke once across this
   entire session's CI chain. **Revised, more decisive than the first
   pass above -- the user's own direct correction:** **D3**'s own
   "works on a bare laptop, no Docker, mutates nothing" promise is
   itself now superseded, not a constraint this plan needs to route
   around. Docker becomes a **required dependency for real builds**
   going forward, not an escape hatch. The two ports genuinely differ
   though, and the plan should say so plainly rather than treat them
   identically:
   - **natmod**: `toolchains.py`'s existing host/download resolution
     stays, purely because it already works and costs nothing further
     to leave in place -- not preserved as a load-bearing design
     promise any more, just not worth deleting. Docker is the
     preferred, default path once available; the old path answers
     "Docker isn't installed" without anyone having to build or
     maintain anything new for it.
   - **usermod**: no non-Docker path is worth pursuing for any port at
     all, including `unix`. **Superseding this decision's own first
     pass** (which called `unix`'s existing host-based cross-compile
     path -- **D20/D24/D25**, real, proven, already shipping --
     "grandfathered," kept purely because ripping out working code
     costs something for no benefit): the user's own direct, later
     call is Docker-only, full stop, no exception for `unix` either.
     **The reason inverts D3's own original framing, above, not just
     overrides it:** D3 called bare-host the non-mutating option and
     Docker the heavier one. For usermod that framing is backwards --
     a bare-host build means `apt-get install`ing arch-specific
     cross-toolchains onto whatever's running the build, a real,
     persistent mutation of that host. A container is the actually
     non-mutating, deterministic, isolated option: it is built once
     from a pinned Dockerfile and discarded per run, touching nothing
     outside itself. Docker-only is the isolation-preserving choice,
     not a tradeoff against it. The real toolchain diversity across
     ports (ESP-IDF, emsdk,
     llvm-mingw, five different `unix` cross-compilers) makes a
     parallel, dual-maintained non-Docker path prohibitively expensive
     for every port, `unix` included, not just the ones added from
     here on. Every port's Docker path is mandatory, not a preferred
     default with a bare-host escape hatch. `llvmmingw.py`/`emsdk.py`/
     `espidf.py` (already written, from earlier in this session) stay
     as `docker/<port>.Dockerfile`'s own *build-time* provisioning
     mechanism -- called once when the image is built, not something a
     caller's own bare-host run falls back to. **Done (D33's own
     session): `usermod/dockerrun.py`'s `ensure_image()` no longer has
     a local-build fallback at all (build vs. pull, a separate change),
     and `build_unix()`'s own bare-host branch (the `toolchains.resolve
     ("x86")` / `shutil.which()`-plus-apt-package probe, and
     `UnixArchSettings.apt_package`, which nothing else read once that
     branch was gone) is deleted outright, not merely deprioritized.**
     `docker_image is None` is now the immediate, clearly-worded error
     this bullet called for ("no Docker image registered ... usermod
     builds are Docker-only"), matching `build_webassembly()`'s own
     shape exactly. Also closes **D32**'s own "self-hosted runners
     without Docker" question the way this bullet already predicted:
     fail loudly, never fall back. **Scoped to an actual build only, not the CLI as a whole:**
     the error belongs at the point a usermod port is actually about
     to be built (inside `build_<port>()`, once it needs a real image),
     not as a blanket check `cli.py`/`usermod/cli.py` run up front.
     natmod never touches this path at all (**D30**'s own natmod
     bullet, above -- Docker is preferred there, not required), and a
     usermod invocation that does not build anything --
     `--dry-run`, `--print-build-identifiers`, `--print-build-matrix`
     -- must keep working with no Docker installed at all, the same as
     today.
   - **A genuine, concrete payoff of this, the user's own observation:**
     adding a new port's own support becomes strictly simpler than it
     is today -- write one Dockerfile, then declare it in the resolver
     (`usermod/dockerrun.py`'s own `image_for_port()`, or whatever
     config-driven mapping replaces the current env-var-only lookup).
     No new Python resolution module to write and test (the shape
     `llvmmingw.py`/`emsdk.py`/`espidf.py` each are today), no new
     `download`/`host` probing logic, no new apt-package-list
     duplicated between a Dockerfile and a bare-host README section.
     One artifact per port, not two.
3. **Confirmed, already the design**: `usermod` gets one Dockerfile
   *per port*, not per architecture/board -- **D28**'s own "one port,
   one toolchain" framing, unchanged.
4. **A concrete, actionable addition, not yet done:** check `mpbuild`'s
   own and `cibuildwheel`'s own real Dockerfiles before writing any of
   **D28**'s five per-port images from scratch, particularly
   `esp32`/`webassembly` where the real apt/toolchain list is heavy
   and plausibly already solved correctly somewhere public. Not
   independently verified in this session at all (same "cited by the
   user, not yet checked against source" caveat **D26** already
   carries for `mpbuild`'s own container-per-port precedent) -- a
   concrete first step for whoever picks up **D28**'s implementation,
   not a claim about what those Dockerfiles actually contain.
5. **Direct consequence of point 2, same caveat:** yes, on the
   Docker-active branch, "resolve toolchain" becomes "which Dockerfile"
   for natmod exactly the way it already does for usermod's own ports
   -- conditional on Docker being the selected path, not a blanket
   replacement of `toolchains.py`.
6. **"Docker over QEMU or QEMU over Docker" -- neither; they solve
   different problems, not a build-time either/or.** **D2/M2** already
   decided, with reasoning, not to emulate for cross-compilation at
   all: real cross-compiling beats QEMU user-mode emulation for
   something as light as MicroPython's own build (the same reasoning
   **D25**'s own cibuildwheel comparison restates -- manylinux uses one
   container *per architecture* plus `qemu-user`, specifically because
   Python wheels are far more expensive to build than MicroPython is).
   Wrapping toolchains in Docker containers does not change that
   calculus at all -- the containers exist for **dependency isolation
   between ports** (**D28**'s own "why isolation is the real driver"),
   not to enable emulation as an alternative to cross-compiling. QEMU
   stays exactly where **D21** already puts it: a separate *execution*
   axis (`qemu-system`, running/testing an already-built binary under
   an emulated target), never a *build-time* one. Three orthogonal
   concerns, not a competing pair: **Docker for isolation,
   cross-compilation for building, QEMU only for execution/testing.**

- **D28's own open Docker-daemon-reachability question is now
  resolved, confirmed live, not just reasoned about** -- see **D28**'s
  own "risks and open questions" section for the real result (a
  genuine `docker info`/`docker run --rm hello-world` from a plain,
  non-Docker-action `run:` step on `ubuntu-latest`, both worked
  immediately). The diagnostic job has been removed from
  `usermod-dev.yml`.
- **`build-examples.yml` should test every available port, the same
  discipline `examples/usermod-unix` already holds `unix` to, not just
  the one port that happens to be furthest along.** The user's own
  explicit ask. Today only `unix` has an integration example at all
  (`examples/usermod-unix`) -- once **D28**'s remaining Dockerfiles
  land (migration step 3: `windows`, `qemu`, `webassembly`, `esp32`),
  each needs its own real example wired into `build-examples.yml`'s
  own `uses: ./` steps the same way, not left as a claim nobody's CI
  run actually proves. This is the same "no target claimed without a
  real CI proof" rule that caught all six of **D25**'s own bugs in the
  first place -- skipping it for the later ports would reopen exactly
  the risk this whole session's own discipline was built to close.
- **A real side benefit, the user's own observation: this also makes
  local use on Windows genuinely simpler, via Docker Desktop's own
  WSL2 backend.** The root `Dockerfile`'s own comment already
  documents running it through WSL2 (`README.md`'s "Running via
  Docker" section) -- once usermod's own port builds go through Docker
  as the required path (**D30**'s own point 2), that same WSL2 path
  covers usermod too, not just the natmod-only bare CLI it covers
  today. Does not change the "Windows/macOS *runners*" open question
  below at all (a per-port *Linux* container still cannot run on a
  bare Windows/macOS CI runner) -- this is specifically about a
  Windows *developer's own machine* running Docker locally, a genuinely
  different case from CI.

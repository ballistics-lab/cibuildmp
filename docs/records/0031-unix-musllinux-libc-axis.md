# 0031. unix usermod builds are glibc-only; there is no musllinux-equivalent, and identifiers carry no libc axis

- Status: Accepted; manylinux half done, musllinux half not started
- Related: [0020], [0023], [0026], [0028]

<!-- migrated verbatim from docs/BACKLOG.md lines 3161-3317 -->

**D31 — `unix` usermod builds are glibc-only today; there is no
musllinux-equivalent, and build identifiers carry no libc axis to name
one even once it exists.** The user's own framing, directly: cibuildwheel
distinguishes `manylinux`/`musllinux` in its own wheel tags because a
compiled extension's libc linkage determines which host it actually runs
on; `cibuildmp`'s own usermod identifiers (`targets.py`'s own
`identifier` property, `{ABI}-{platform}_{arch}` shaped after
cibuildwheel's `cp311-manylinux_x86_64`) have no equivalent axis at all
-- `mpy6.3-usermod-unix-x64` says nothing about which libc the binary
inside was linked against, because today there is only ever one answer.

Verified live in this session, not assumed:

- `x64`/`x86`/`aarch64` (`usermod/build.py`'s own `UNIX_ARCH_SETTINGS`)
  build with a plain dynamic link. A real `v1.28.0` `ports/unix` build
  confirmed via `ldd`: `libc.so.6`, `libffi.so.8`, and the dynamic
  `ld-linux-x86-64.so.2` interpreter are all real runtime dependencies --
  this binary will not run at all on a musl-only host (Alpine and
  similar) with no glibc compatibility layer installed.
- `armhf`/`mipsel` already build with `MICROPY_STANDALONE=1
  LDFLAGS_EXTRA=-static` (**D20**'s own deplibs story) -- the natural
  guess is that this already makes them musl-portable, since a fully
  static ELF has no dynamic libc dependency at all. **That guess was
  checked live and is wrong for this codebase.** Rebuilding `x64` with
  the exact same static recipe still links and runs on the host
  (confirmed: `file` reports "statically linked", the binary executes),
  but the linker itself warns, for real, on this exact source:
  `modffi.c`'s `ffimod_make_new` (the `ffi` module's own `dlopen()`,
  a real, exercised usermod feature) and `modsocket.c`'s
  `mod_socket_getaddrinfo` (`getaddrinfo()`) both print "requires at
  runtime the shared libraries from the glibc version used for linking"
  -- glibc's own NSS design loads its network/name-resolution backends
  via `dlopen()` at runtime even from a "static" binary, so a fully
  static glibc build is *not* actually libc-implementation-portable the
  moment code reaches either function. `armhf`/`mipsel`'s own existing
  "static" builds inherit this same latent gap and have never been
  verified against a real musl host either -- this was not previously
  known or documented anywhere in this codebase.
- Not verified live: actually running a build under a real musl host
  (Alpine). This sandbox's `docker` CLI has no reachable daemon
  (`failed to connect to the docker API at unix:///var/run/docker.sock`)
  -- the same gap **D28**'s own "Docker-daemon-reachability" question
  hit earlier, resolved there only because a real GitHub Actions runner
  was reachable to test against. Whoever picks this up should confirm
  the `ldd`/linker-warning findings above against a real Alpine
  container before trusting them as the final word.

**The real fix is a musl toolchain, not a linker flag** -- `-static`
alone was the tempting, cheap-looking answer and it does not work, per
the live finding above. **The manylinux half of this is now done, the
musllinux half is not, and both halves live in the same mechanism.**
Following directly from this decision's own finding, the earlier
`resources/docker/unix.Dockerfile` (one image, all five arches) was
replaced with five per-arch `unix-manylinux-<arch>.Dockerfile` images
(**D26**'s own amendment above) -- the same correction the user pushed
for directly ("це херня, я думав ми наріжемо manylinux-x64
muslinux-aarch64 тощо"), and `usermod/dockerrun.py`'s own resolver now
takes an explicit `libc` parameter for exactly this reason
(`image_for(port, arch, libc=None)`, **D28** step 2). What's still
genuinely missing is only the musl side: an Alpine-based
`unix-musllinux-<arch>.Dockerfile` per arch (musl's own `gcc`, not
Ubuntu's), registered in `PORT_IMAGES` the same one-line way
(`"unix-x64-musllinux"`), no resolver changes needed at that point --
the mechanism already accepts this shape today, it just has nothing to
register yet. `targets.py`'s own `identifier` property still needs a
matching new axis alongside `arch` (`mpy6.3-usermod-unix-x64-manylinux`
/ `-x64-musllinux`, cibuildwheel-shaped, defaulting to `manylinux` so
every existing identifier stays valid unless a caller opts into
`musllinux` explicitly) -- threading this through
`UsermodOptions`/`orchestrate.py`'s own axis-override machinery
(**D20**) the same way `arch`/`board` already work is real, multi-file
work, not a one-line addition, and is explicitly **not attempted in
this session**: it needs a real musl cross-toolchain resolved per arch,
real Dockerfiles, and real verification against an actual musl host,
none of which fit alongside the resolver/image work above. Flagged
here, precisely, so a future session designs the axis once rather than
bolting it on ad hoc the way **D25**'s six bugs show what "discovered
mid-flight" costs.

- **"manylinux" here is a label, not a version pin -- a sharper version
  of a gap this decision already flagged loosely, made concrete by the
  user's own real example.** Real manylinux wheel tags carry a specific
  minimum glibc version as part of the tag itself --
  `rp2040py-0.3.1-cp314-cp314t-manylinux2014_armv7l.manylinux_2_17_armv7l.manylinux_2_31_armv7l.whl`
  names `manylinux2014`/`manylinux_2_17`/`manylinux_2_31` as three
  *specific*, independently-checkable glibc-version floors a wheel with
  that tag is guaranteed compatible with -- that guarantee is the whole
  point of the tag, not incidental to it. `cibuildmp`'s own
  `unix-manylinux-<arch>` images carry no such pin at all: "manylinux"
  today just means "whatever glibc `ubuntu:24.04` happens to ship,"
  which changes underneath every image silently whenever the base image
  itself gets rebuilt or Ubuntu patches it, with nothing recorded
  anywhere about what floor a binary built there actually needs. Not
  designed or fixed here -- raised mid-incident, correctly deferred
  alongside the QEMU/native-image question above rather than expanding
  scope further while chasing a live CI failure -- but a real, separate
  gap from the manylinux/musllinux axis itself: even a `unix` build that
  never touches musl at all still makes no claim about which glibc
  versions it actually runs on. The user's own explicit follow-up,
  directly: this isn't just "add a version number somewhere" -- it's
  "follow the actual convention" rather than reinvent a worse one.
  Real manylinux tags follow **PEP 600**, which stacks *multiple*
  compatibility floors on one artifact (`manylinux_2_17_armv7l` *and*
  `manylinux_2_31_armv7l` together in the one filename above, not a
  single flag) precisely so a checker can verify the binary's actual
  symbol versions against each floor independently, and a consumer
  picks whichever floor its own host clears; **musllinux is the same
  shape under a separate spec, PEP 656**, versioned against musl
  releases instead of glibc ones. **Decided, not just raised: a future
  session adopts this for real** -- the user's own explicit call, not
  merely "worth considering." Whoever picks this up should read both
  PEPs directly before designing anything (not re-derive the shape from
  this summary alone), and start from how `cibuildwheel` itself
  actually resolves them, checked live against a real `v4.2.0`
  checkout, not assumed: it does **not** compute a floor at all --
  `resources/defaults.toml` is a static, maintainer-curated table
  (`manylinux-x86_64-image = "manylinux_2_28"`,
  `manylinux-armv7l-image = "manylinux_2_31"`, one pinned image per
  arch from the separate `pypa/manylinux` project, trusted rather than
  verified at build time) that only decides *which base image* to
  build inside; the real, computed answer -- what glibc/musl floor a
  *just-built* binary's own symbols actually require -- comes from
  shelling out to **`auditwheel repair`** (manylinux) /
  `auditwheel repair --ldpaths` (musllinux) as the default
  `repair-wheel-command`, an external CLI cibuildwheel merely invokes
  as a subprocess inside the container, not a library it imports
  (`packaging` *is* a real cibuildwheel dependency, but only for
  `Version`/`SpecifierSet` version-range parsing -- unrelated to tag
  resolution at all). `cibuildmp`'s own equivalent, if it follows this
  precedent rather than reinventing it, is therefore two separate
  pieces, not one: (1) a maintainer-curated `PORT_IMAGES`-shaped table
  naming which base image backs each floor -- already exactly
  `dockerrun.py`'s own shape, extended with a floor segment -- and (2)
  a real post-build checker in that same spirit as `auditwheel` (built
  on `pyelftools`-style ELF symbol-version inspection, since `unix`
  produces a bare executable, not a wheel `auditwheel` itself knows how
  to repair) that verifies a `micropython` binary's own actual glibc
  symbol versions against the floor its image claims, rather than
  trusting the claim silently the way today's plain "manylinux" label
  does. **This needs zero new dependencies, checked directly against
  `pyproject.toml`**: `pyelftools`/`ar` are already real, existing
  `cibuildmp` dependencies -- today only because `tools/mpy_ld.py`
  (MicroPython's own native-`.mpy` linker, D2) is itself a Python
  script that imports them, and `make_command()`'s own
  `PYTHON=<sys.executable>` (`build.py`, D12's own mechanism) is what
  makes cibuildmp's own environment satisfy that need rather than
  requiring a separate `pip install` at build time -- not because
  `cibuildmp`'s own code does any ELF inspection of its own yet. A real
  glibc-floor checker for `unix` is therefore new *code* using an
  already-present dependency, not a new dependency to add.
  `auditwheel`'s own `elfutils.py` module (`elf_read_dt_needed`,
  `elf_find_versioned_symbols`) is worth reading directly before
  writing that code from scratch, confirmed live against a real
  `pypa/auditwheel` checkout to operate on a bare ELF `Path`, fully
  decoupled from the wheel-archive-specific code (`wheel_abi.py`,
  `repair.py`) that can't be reused as-is (`auditwheel`'s own CLI is
  hard-wired to a `.whl` file argument, not a bare executable).

- **M10** — runner/matrix integration, fan-out-by-default for usermod
  identifiers (**D20**).
- **M11** — execution axis: qemu-system, rp2040py, node, native — four of
  seven already proven working, just not owned by `cibuildmp` yet
  (**D21**).
- **M12** — adopt in the three consuming repos, mirroring **M5**.

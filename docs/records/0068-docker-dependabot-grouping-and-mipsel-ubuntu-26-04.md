# 0068 — docker Dependabot grouping, and what the first grouped bump exposed

Status: Accepted (incident record — a mechanism fixed, a gap it exposed, not a new design)
Related: [0046], [0059]

## What was wrong

`.github/dependabot.yml`'s `github-actions` entry has always grouped every update into one PR
(`groups: github-actions: patterns: ["*"]`, added specifically so `directories:`'s own
per-directory fan-out didn't reopen the one-PR-per-dependency problem the old five-entry file
had). The `docker` entry never got the same treatment — no `groups:` block at all. Six of the
Dockerfiles under `docker/` pin a real digest under a differently-named `quay.io/pypa/...`
image (five `manylinux_2_28_*` arches plus `pypa-tracker.Dockerfile`), so to Dependabot each is
a distinct dependency: a single upstream pypa republish opened up to six separate PRs instead
of one. Fixed by adding the same catch-all `groups: docker-images: patterns: ["*"]` the
`github-actions` entry already had.

## What the first grouped bump did instead

The fix worked exactly as intended — PR #16 ("bump the docker-images group in /docker with 15
updates") landed nine routine `quay.io/pypa/...@sha256:...` digest bumps and `ubuntu:24.04` →
`ubuntu:26.04` in one PR, across ten `docker/*.Dockerfile` files. That grouping is also what
made the PR dangerous to merge blindly: the ten `ubuntu:26.04` files and the nine pypa digest
bumps carry completely different risk profiles, and a single PR gives no way to accept one
without the other through Dependabot's own UI (one branch, one commit).

`docker/manylinux_2_39_mipsel.Dockerfile`'s own `verify-docker-images` CI leg caught the real
break: `ubuntu:26.04`'s apt archive has no `gcc-mipsel-linux-gnu`/`libc6-dev-mipsel-cross`
package at all —

```
E: Package 'gcc-mipsel-linux-gnu' has no installation candidate
E: Unable to locate package libc6-dev-mipsel-cross
```

— not a version mismatch (the Dockerfile already pins `libc6-dev-mipsel-cross=2.39-*`
deliberately, exactly so an Ubuntu bump that moves the glibc-cross line fails loudly rather
than silently drifting past what the `manylinux_2_39_mipsel` tag claims), but the package
itself gone from the archive. Root cause, confirmed against Debian's own bug tracker: Debian 13
"Trixie" (released August 2025) is the first release with no `mipsel` port at all —
[Debian bug #1043114](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=1043114) cites the
32-bit 2GB user-space limit, the unresolved Y2038 problem (which needs a near-total
architecture rebootstrap), and insufficient porter manpower. Ubuntu's own
`gcc-*-cross-mipsen` packages are built from that same Debian source, so once Ubuntu's archive
moved past Trixie's cutover, the cross-toolchain packages had nothing upstream to build from.
`mips64el` followed the same path out of Debian unstable/experimental in November 2025.

The other nine `ubuntu:26.04` bumps in the PR built cleanly through `verify-docker-images`
(`esp_idf_base`, `webassembly`, `windows` confirmed green; the rest still running when this was
written) — this is not a blanket "ubuntu:26.04 is broken" finding, only a `mipsel`-specific one.

## What this decides

**The docker Dependabot group stays one group** (matching `github-actions`'s own shape) for
routine same-name digest bumps — that half of the fix is right and stays. **A major-version
bump of a floating tag (`ubuntu:24.04` → `26.04`) needs a human decision before merge, every
time**, the same way [0033] already requires a reviewed PR before a pypa base repoints rather
than trusting Dependabot's own judgment. Two ways to get there, not chosen yet (see below):
Dependabot's own `ignore` directive on `ubuntu`'s major version, or a second `docker` entry
scoped to `docker/manylinux_2_39_mipsel.Dockerfile` alone so it never shares a PR — and,
independently of Dependabot's own config, splitting `.github/dependabot.yml`'s single
`docker-images` group into a `pypa-digests` group (safe to merge routinely) and a
`base-os-major-bumps` group (always reviewed) would keep the one-PR benefit for the routine
half without re-bundling it with the risky half.

**`manylinux_2_39_mipsel`'s apt-based cross-toolchain is now a standing liability, not a
one-time incident.** It is the one `unix` image that never adopted the pinned-tarball model
[0025]'s own embedded Dockerfiles (`arm_embedded`, `riscv_embedded`, `xtensa_esp`,
`xtensa_lx106`) already use — every one of those pins a toolchain by version + URL + sha256,
independent of whatever the base OS's package archive currently carries. `mipsel`'s reliance on
`apt install gcc-mipsel-linux-gnu` ties its buildability to an upstream (Debian/Ubuntu) that
has explicitly abandoned the architecture; the same failure would resurface on the next Ubuntu
LTS bump regardless of Dependabot, and eventually on a security-only apt mirror pruning old
packages even without a base bump at all. A pinned-tarball cross-toolchain (e.g. one of
Bootlin's `mips32el--glibc--stable-*` releases, the shape a sibling project's own
`Dockerfile.bin` already uses for the same architecture) would decouple this image from
Ubuntu's archive the same way the embedded images already are — at the cost of picking a
specific Bootlin release and re-deriving what glibc floor it actually provides, since
`manylinux_2_39_mipsel`'s own `2_39` is a claim about the *current* apt package's version, not
something a different toolchain vendor is guaranteed to match.

## Not decided here

- Whether to actually move `manylinux_2_39_mipsel` onto a pinned tarball toolchain, and if so
  which release and what floor it claims. A real design decision (new toolchain, likely a new
  or renamed identifier), not a docs fix.
- ~~PR #16 itself — still open as of this record, not merged, not closed.~~ Resolved by the
  group-split addendum below: Dependabot auto-closed #16 once the group definition changed and
  recreated it as #18 (14 updates, `ubuntu` no longer among them), which merged. `ubuntu` itself
  was never re-proposed on its own in this pass -- `main` still carries `ubuntu:24.04` until
  Dependabot next opens a standalone `ubuntu` PR under the new split.

**Addendum, 2026-08-30.** The group split is implemented: `docker-images`' own `patterns: ["*"]`
gained `exclude-patterns: ["ubuntu"]`, so `ubuntu` gets its own PR (still one, since every
Dockerfile referencing it collapses onto that one dependency name already) and never shares a
PR with a pypa digest bump again. Chosen over a second `dependabot.yml` entry or an `ignore`
directive: `exclude-patterns` keeps the fix inside the one group block that already explains
itself, and — unlike `ignore` — still lets Dependabot open the (now-isolated) `ubuntu` PR for a
human to look at, rather than silently never proposing the bump at all.

Two more things this incident's own CI runs surfaced, fixed alongside since they're the same
"a Dependabot PR pays for CI it gets nothing from" shape: `publish.yml`'s `deploy` job ran its
own `checkout` on every `pull_request` even though every real step behind it was already gated
to `push`/`workflow_dispatch` — confirmed live doing nothing useful and once flaking red on this
repo's own PR #17 for exactly that reason; now `if: github.event_name != 'pull_request'`, so it
doesn't run there at all. `test-all-platforms.yml`'s `paths-ignore` excludes `**.md`/`docs/**`/
`LICENSE` but not `docker/**` or `.github/dependabot.yml`, so any Dependabot docker PR (or a
docs PR that happens to also touch `dependabot.yml`, as this record's own PR did) fired the full
200+-identifier matrix for a change `verify-docker-images.yml` already covers; `plan` and
`aggregate-results` both gained `if: github.actor != 'dependabot[bot]'` (the latter alongside its
existing `always()`, so a skipped `plan` doesn't leave it aggregating zero buckets).

## Why this belongs next to [0046]

[0046] ("nothing notices when a pin goes stale, except container images") already named
Dependabot as the mechanism that watches `docker/`'s own `FROM` lines, with `bin/update_docker.py`
covering the two pypa/GHCR pin tables it does *not* reach. This incident is a live demonstration
of exactly the gap [0046] describes as still open — a pin (here, the base OS tag, not one of
the two tables [0046] inventories) went stale in a way nothing caught until a scheduled
Dependabot bump forced the question, and the checker workflow's own `--check` mode still runs
on no schedule at all (confirmed this session: `grep -rn "cron:" .github/workflows/*.yml` finds
exactly one cron in the whole repo, unrelated to any of this). [0046]'s own tracker row is
updated to point here as the concrete proof this is not hypothetical.

**Addendum, 2026-08-30 (second) — the `manylinux_2_39_mipsel` toolchain decision, recorded here rather than as a new record.**

Decided, **not yet executed in code**: `manylinux_2_39_mipsel`'s toolchain moves off `apt install
gcc-mipsel-linux-gnu`/`libc6-dev-mipsel-cross` (unavailable since Debian 13 "Trixie", per this
record's own root-cause section above) onto a pinned Bootlin tarball — the same version + URL +
sha256 pattern `arm_embedded`/`riscv_embedded`/`xtensa_esp`/`xtensa_lx106` already use, independent
of whatever the base OS's own apt archive currently carries.

Bootlin's own releases are versioned by build date (`stable-YYYY.MM-N`), not by glibc version —
`manylinux_2_39` was never a Bootlin release name, it is cibuildmp's own PEP 600-style floor claim
(checked, in this record's own root-cause section, against the *apt* package specifically —
`2.39-0ubuntu8cross2` — which a different toolchain vendor was never guaranteed to match, exactly
the caveat this record raised and left open). Checked live against `toolchains.bootlin.com`'s own
`mips32el` release list: `mips32el--glibc--stable-2024.05-1` bundles glibc `2.39-74` (matches
today's floor exactly); the newest release, `mips32el--glibc--stable-2025.08-1`, bundles glibc
`2.41-70`.

**Chosen: the newest release (`2025.08-1`, glibc 2.41), not the floor-matching one.** Taking the
newest maintained Bootlin release over freezing at the old floor means the identifier itself has
to be renamed once this lands — `manylinux_2_39_mipsel` → `manylinux_2_41_mipsel` — a real PEP 600
tag must not keep claiming a floor the image no longer has, the same principle [0031] already
established for this exact cell.

**Also decided: this image comes out of `pinned_docker_images.toml`'s `image_group` table
entirely, not just repointed at a new pin.** mipsel is EOL upstream (this record's own root-cause
section), and nothing here proposes to keep publishing and maintaining a GHCR image for an
architecture Debian/Ubuntu no longer support at the OS level. A user who still needs it builds
`docker/manylinux_2_41_mipsel.Dockerfile` themselves with a plain `docker build` and points
cibuildmp at the result via the **already-existing** `CIBMP_UNIX_MANYLINUX_2_41_MIPSEL_DOCKER_IMAGE`
override — `dockerrun.image_for()` already checks an env override before ever consulting the
pinned table, and a group absent from that table already resolves to a clean `UsermodBuildError`
("no image registered...") rather than any fallback build. No new cibuildmp code needed for this,
and cibuildmp still never builds a Docker image itself ([0033]) — the user's own `docker build` is
the only build that happens. This is a stronger version of [0044]'s own "descoped from CI, kept in
the matrix" treatment for `ppc64le`/`s390x`/`riscv64`: those three still get a real,
`bin/update_docker.py`-maintained digest with no CI leg; mipsel gets no digest published at all.

**Not yet done** (code-level, tracked as this row's own follow-through, not a new record): the
Dockerfile edit itself, the `pinned_docker_images.toml` row removal, the identifier rename across
`build-platforms.toml`/README/tests, `verify-docker-images`/`test-all-platforms.yml` dropping their
mipsel leg, and a README ⚠️ note explaining "build it yourself, nothing published" the way the
three descoped cells above already carry one.

**Addendum, 2026-08-31.** `test-all-platforms.yml` dropped its `pull_request` trigger
entirely (schedule + `workflow_dispatch` only now — the full sweep is too slow to gate every
PR's own turnaround time for how rarely its answer changes), which makes this record's own
`if: github.actor != 'dependabot[bot]'` guard on `plan`/`aggregate-results` moot rather than
just redundant: neither `schedule` nor a human's own `workflow_dispatch` ever runs as that
actor. Removed from both jobs rather than left as harmless dead weight — the guard's own
comment referenced a `pull_request`-triggered Dependabot PR that can no longer trigger this
file at all.

**Addendum, 2026-09-01 — the toolchain and the rename both landed, and one thing decided
above was reversed.**

Executed, and verified on real artifacts rather than inferred at every step:

* **`docker/manylinux_2_41_mipsel.Dockerfile` pins `mips32el--glibc--stable-2025.08-1`**
  (URL + sha256 `1085fe6b…`, `relocate-sdk.sh` after extraction), exactly the release this
  record's own addendum chose. Read out of the tarball's own `README.txt` rather than
  assumed from the release name: gcc 14.3.0, binutils 2.43.1, glibc `2.41-70`.
  `gcc-mipsel-linux-gnu`/`libc6-dev-mipsel-cross` are gone from the file entirely; the base
  stays `ubuntu:24.04`, and is now incidental to the toolchain rather than the source of it.
* **The `mipsel-linux-gnu-*` frontends are generated `exec` scripts, not symlinks, and that
  is a live-caught correction rather than a preference.** Bootlin ships the `mipsel-linux-`
  prefix; `UNIX_ARCH_SETTINGS["mipsel"].cross_compile` is apt's `mipsel-linux-gnu-`. Symlinks
  were the obvious bridge and they fail: every Bootlin frontend is Buildroot's
  `toolchain-wrapper`, which finds the real binary as *its own directory* (from
  `/proc/self/exe`, so it follows a symlink) plus *`argv[0]`'s basename* (so it does not)
  plus `.br_real` — a `mipsel-linux-gnu-gcc` symlink therefore looks for
  `/opt/.../bin/mipsel-linux-gnu-gcc.br_real`, which does not exist. The image build failed
  on its own `--version` check, which is why that check is in the same `RUN`. Wrapping keeps
  `argv[0]` resolvable and keeps this a Dockerfile-only change, with no source constant,
  fixture or test moving for it.
* **Verified:** a full `examples/usercmodule` build (`deplibs` static-libffi step included,
  since this is still the one `MICROPY_STANDALONE` cell) links, and the artifact runs under
  `qemu-mipsel` with all three upstream modules importing — `ELF 32-bit LSB executable, MIPS,
  statically linked`. `verify-docker-images`' own mipsel leg is green on the real runner too.
  One genuine difference from the apt toolchain, worth recording because it is a property of
  the shipped binary and not of the build: the ELF is now `o32, mips32` (r1) where apt's gcc
  emitted `mips32r2`. That widens the hardware it runs on rather than narrowing it.
* **The rename landed:** `manylinux_2_39_mipsel` -> `manylinux_2_41_mipsel` across
  `build-platforms.toml` (sixteen identifier rows plus the `images.` key),
  `pinned_docker_images.toml`, `dockerrun.py`, `build_unix.py`, three workflows, four test
  modules and the living docs. Breaking, with no alias: an old identifier now gets
  `matches no known identifier`.

**Reversed from this record's own second addendum: the image keeps its
`pinned_docker_images.toml` row and stays published.** That addendum argued mipsel should
come out of the pin table entirely — EOL upstream, so stop publishing for it — with users
building the Dockerfile themselves through the existing env override. The argument does not
survive the fix it was attached to. Its own premise was that this image is a standing
liability *because* it depends on an archive Debian has abandoned; pinning the toolchain by
URL + sha256 is precisely what removes that dependency, so the reason to stop publishing
went away in the same change that was supposed to justify it. What remains is only the cost:
`micropython-bclibc` runs a real mipsel leg in CI, and "build a Dockerfile out of another
repository, then set an env override" is a worse story than a pulled image for no benefit it
receives.

**The row is empty rather than repointed, and that is not an unfinished edit.** A GHCR digest
is per package *name*: the last publish went out under `manylinux_2_39_mipsel` (its digest is
still pullable, and the old pinned one is still tagged `pre-aec4468c39bd` — [0059]'s own
preserve step working as designed), and nothing has been published under the new name yet.
`dockerrun.image_for()` already defines an empty group as "this target exists, nothing
published for it yet" and raises a clean "no image registered", which beats a
plausible-looking reference to a digest that does not exist under that name. Filling it is a
`publish-docker-images.yml` dispatch with `only=manylinux_2_41_mipsel` plus the usual repin
PR.

**`publish-docker-images.yml` no longer runs on push.** It carried `push: branches: [main],
paths: docker/**`, marked `# temporary` from the day it was written. The `only` filter lives
on the steps, and a `push` event leaves `github.event.inputs.only` empty — so every such push
republished all **fifteen** images (three of them emulated) for a one-Dockerfile change, and
moved fifteen `:latest` tags, opening [0059]'s untagged-cleanup window fifteen times to
publish fourteen images nobody had touched. It also made a merge publish a Dockerfile the
moment it landed, before anyone decided the image was ready to go out under that name — and
this record is the concrete example: merging the toolchain change with that trigger in place
would have published glibc 2.41 under a tag claiming 2.39, automatically. Dispatch-only now;
`verify-docker-images.yml` still build-checks every Dockerfile on every push and PR, which is
the part that catches breakage.

**Two smaller things this pass surfaced, both by a test rather than by reading.**
`bin/publish_images.py` filtered its publish list with "does not start with `ghcr.io/`" to
mean "upstream's own image, nothing to build" — which swallowed the *empty* case too, so the
one image with nothing published was the one the script would not publish;
`test_publish_script_and_workflow_publish_the_same_images` caught it the moment the row was
emptied. And `publish-docker-images.yml`'s own `only` input documented values that could not
work: its example named `natmod` and `qemu`, neither a matrix entry since [0058] split them
into the six toolchain-group images, so both matched nothing silently — and it said "all ten"
for a fifteen-entry matrix.

**Update, same day.** The publish and the repin both landed:
`ghcr.io/ballistics-lab/manylinux_2_41_mipsel@sha256:eee14e84bb5ce27c1e65c467f664a7f13443664766c530d07b161011318e7226`,
a `linux/amd64` OCI index (checked against the registry directly, anonymously, not taken from
the job summary alone), now `pinned_docker_images.toml`'s own row. Verified the way this record
verifies everything else — a real `examples/usercmodule` build with **no**
`CIBMP_UNIX_MANYLINUX_2_41_MIPSEL_DOCKER_IMAGE` override and the locally built image deleted
first, so the pin is what was exercised. Byte-identical artifact to the locally built one
(1850396 bytes).

**Correction, written the same day this record was closed.** Two paragraphs above said
`micropython-bclibc` **and** `micropython-wasm3` both run a mipsel leg, on [0076]'s
authority. Half wrong, and wrong in [0076]'s own way: `micropython-wasm3` had already
dropped mipsel outright -- its `CHANGELOG.md` and `cibuildmp.toml` both say so in as many
words, and its `build` selector carries no mipsel identifier at all. [0076] was accurate
when written; the other repo moved, and nothing here can notice that. The claim above is
corrected to name only `micropython-bclibc`, and this is left as the second worked example
of why `CONTRIBUTING.md` makes "never state another repository's status in a living
document" a rule rather than a habit.

**Closed.** The last item this record was holding open was "update the identifier in
`micropython-bclibc`", and that is not cibuildmp's work to hold open
-- a consuming repository adopting a renamed identifier is that repository's own migration,
on its own schedule. Keeping it as an unchecked row here would also be the shape
`CONTRIBUTING.md`'s own "never state another repository's status in a living document" rule
exists to prevent: a claim about someone else's CI that nothing in this repo can re-check,
going stale silently ([0076] is the record of that happening).

What this repo owes them is what it already has: the rename is a **breaking change**, called
that in `CHANGELOG.md` with the old and new identifiers spelled out, so it is discoverable at
the point of upgrade rather than by a failing run.

**Noticed while verifying the pin, and not fixed here:** every one of the fourteen other
`ghcr.io/ballistics-lab/...` pins is one publish behind its own `:latest`. Checked properly
rather than inferred from a digest mismatch — `manylinux_2_28_x86_64`'s `:latest` is index
`e7732177…` and its pin `6afa4abd…` is a different index that is not among its children (and
still pulls, so nothing is broken; a build uses the pin, not the tag). The cause is exactly
the trigger this record removed: a `docker/**` push to `main` republished all fifteen and
moved every `:latest`, with no repin PR behind it. That is [0046]'s own gap demonstrated a
second time, and `bin/update_docker.py --images` is the one-pass fix whenever it is taken.

[0058]: 0058-image-groups-are-toolchains-not-ports.md
[0076]: 0076-the-mipsel-holdout-is-bclibc-and-wasm3-not-a7p.md

**Addendum, 2026-09-01 (second) — the base bump this record blocked has landed.**

All ten `ubuntu`-based images are on `ubuntu:26.04`. This record is closed and stays
closed; the bump is recorded here rather than as a new record because it is the direct
consequence of the decision above ("a major-version bump of a floating tag needs a human
decision before merge, every time"), and this is that human decision being taken with the
blocker removed.

Ten of ten build. Two real builds through the result, because "the image builds" and "a
build in the image works" are different claims and only `verify-docker-images` checks the
first: `natmod` `x64` through the bumped `natmod_host` (gcc **15.2**, up from 13.3) is green
with zero warnings, and a `wasm32` usermod build is green with its `.mjs` passing
`smoke_test.py` under the image's own `node` (**22.x**, up from 18.x).

The bump's blast radius turned out narrower than the gcc jump suggests, and the reason is
this record's own toolchain argument generalised: an image whose toolchain is a pinned
tarball does not move when its base does. `arm_embedded`/`riscv_embedded`/`xtensa_esp`/
`xtensa_lx106` are unchanged ([0025]'s pins), `manylinux_2_41_mipsel`'s cross-gcc stays
Bootlin 14.3.0, and `windows` is unchanged too — apt's mingw-w64 is GCC 13 on both 24.04 and
26.04 (checked in a real `ubuntu:24.04` container) and its `arm64` frontend is the pinned
`llvm-mingw`. Only `natmod_host` and `ppc64le_linux` actually hand the artifact to the
base's own compiler, which is why those two are what a bump has to be judged on.

**Correction, 2026-09-01 (third) — "natmod `x64` ... is green with zero warnings" was true and
irrelevant; `x86` was the arch the bump actually broke, on every tag but the one this repo's own
CI happens to test.**

`natmod_host` serves two arches, not one — `images.x64` and `images.x86` both resolve to it
([0058]). The verification this record's own previous addendum reported ("`natmod` `x64`
through the bumped `natmod_host` ... is green with zero warnings") checked only the native,
no-multilib half. `x86` is the one that exercises the image's `-m32` toolchain — for *most*
supported MicroPython tags, not all, which is the real reason this passed unnoticed here and is
worth spelling out precisely rather than as "not tested."

This split is not new information — [0058] already counted it exactly (`x86 {'': 22,
'i686-linux-gnu-': 2}`, the same section naming `gcc-13-multilib`/`gcc-i686-linux-gnu` as the
two real Debian packages behind it) and its own verification table calls both paths proven
("`gcc -m32` produces ELF32; `i686-linux-gnu-gcc` works"). What that record did not establish,
and stated the opposite of ("nothing about the 32-bit path is fragile"), is that the `''`
(twenty-two tags, including `v1.28.0`) half depends on a hand-pinned gcc version staying in
step with the base image's own default — see [0058]'s own correction, added alongside this one.

**What broke.** `docker/natmod_host.Dockerfile` pinned `gcc-13-multilib` by version — correct on
`ubuntu:24.04`, whose own `build-essential` also resolves to gcc 13. `ubuntu:26.04` moved
`build-essential`'s own default to gcc 15 without this pin following it. On every one of the
twenty-two `cross = ""` tags [0058] already counted (`v1.28.0` among them — upstream's own
`py/dynruntime.mk` confirmed directly at that tag and at `v1.29.0`, where the switch to
`i686-linux-gnu-` actually happens), `-m32` now links against
gcc 15's own `libgcc.a` search path, finds only the 64-bit archive (no `gcc-15-multilib`
installed), and fails —

```
Loading /usr/lib/gcc/x86_64-linux-gnu/15/libgcc.a
LinkError: incompatible arch
make: *** [.../dynruntime.mk:242: build/x86/wasm3_x86.native.mpy] Error 1
```

— but only once the module being linked actually references something from libgcc (soft-float,
64-bit-arithmetic helpers): `mpy_ld.py` loads the archive lazily, only when an undefined symbol
sends it looking, so a module with no such reference (`examples/template`'s natmod, `int a + int
b`) links `x86` clean without ever touching it — verified live, on this very image, on this
project's own `v1.28.0`: no "Loading ... libgcc.a" line appears in that build's log at all.

**Why nothing in this repo's own CI noticed, precisely.** `verify-docker-images.yml`'s
`natmod_host` leg is a bare `docker build` (apt successfully installs `gcc-13-multilib`
regardless of which gcc is default), so it was never going to catch a link-time bug. But
`test-upstream-natmod.yml` and `build-examples.yml` *do* build real `x86` natmod artifacts
through this exact image, every run, and both stayed green throughout — because both pin
`v1.29.0` (`CIBMP_UPSTREAM_ABI_TAG`, `examples/template`'s own `cibuildmp.toml`), the one tag
range where `x86` already uses the *other*, cross-prefixed path (`gcc-i686-linux-gnu` is a
self-contained cross toolchain; its own `libgcc` always matches its own version, so the
`ubuntu:26.04` bump never touches it). Every `x86` build this repo's own CI has ever run passed,
genuinely, and every one of them was proving the wrong half of `dynruntime.mk`'s own `x86` row.
Found only downstream: `micropython-wasm3` pins `v1.28.0` (`-m32`, the broken path) and its
`natmod.yml` builds a real module (`wasm3_mp.c`, which does reference libgcc) — the two
conditions this repo's own fixtures never combined at once.

**First fix attempt, and it does not build: `gcc-13-multilib` → `gcc-multilib`.** The unversioned
metapackage matched what this Dockerfile's own comment already said upstream's `tools/ci.sh`
installs for the identical job, and looked like it would track whatever gcc `build-essential`
resolves to without a version pinned by hand. Checked live rather than trusted: `apt` reports
`gcc-multilib:amd64=4:15.2.0-5ubuntu1` (the metapackage) **Conflicts** `gcc-15-i686-linux-gnu` —
which `gcc-i686-linux-gnu` (unversioned, also resolving to the `15` build on this base) already
pulls in — so the two packages this image has always installed side by side cannot both be
satisfied through the metapackage here. Upstream's own `tools/ci.sh` never combines the two in
one image, so it never meets this conflict; this image always has.

**Actual fix: the real, version-specific package name, computed at build time.**
`gcc-$(gcc -dumpversion | cut -d. -f1)-multilib` is exactly the shape that already worked
(`gcc-13-multilib`), just no longer typed by hand — and the real per-version package, unlike the
metapackage, declares no conflict with `gcc-i686-linux-gnu`. `docker/natmod_host.Dockerfile`'s
own comment carries the full account.

**The regression guard is the image build itself, not a downstream CI job.** The first attempt at
closing the coverage gap added `mpy6.3-v1.28.0-x86` to `test-upstream-natmod.yml`'s
`build-features0` — and it does not catch this incident, checked live rather than assumed:
`features0`'s own `factorial()` links `x86`/`v1.28.0` clean on the very image this bump broke, no
"Loading ... libgcc.a" line at all, for the identical reason `examples/template` never did
either — `mpy_ld.py` loads libgcc.a lazily, only when an actual undefined symbol sends it
looking, and neither module's C ever produces one on this arch. That leg stays (it still proves
`v1.28.0`'s `-m32` toolchain produces a *loadable* `x86` artifact at all), but the real guard is
`docker/natmod_host.Dockerfile`'s own `RUN`, which now compiles and links an explicit 64-bit
multiply (`long long mul64(long long a, long long b) { return a * b; }`, no native i386
instruction for it, so it unconditionally needs `__muldi3` from libgcc) through both of this
image's `x86` toolchains — the `-m32` path this incident broke, and the self-contained
`i686-linux-gnu-` cross path that stayed fine throughout it — before the layer finishes. A future
base bump that breaks either path fails `docker build` itself, everywhere it runs, rather than
staying green while the real link quietly breaks the way this incident did the first time.

**The check itself needed one more pass.** Its first form (`gcc -shared -fPIC ...`) failed
`i686-linux-gnu-gcc` on a missing `crti.o` — a real gap (this image installs the cross compiler
itself but never a full i686 cross sysroot) but not the one worth chasing: `mpy_ld.py` never asks
the system linker for a runnable ELF, shared or not, only for `libgcc.a`'s own member objects, so
real natmod builds never needed a full sysroot here either. Rewritten as
`gcc ... -nostartfiles -nostdlib -Wl,-e,mul64 probe.c -lgcc -o probe` — every crt object a normal
link needs is skipped, an explicit entry point stands in for the also-absent `_start`, and `-lgcc`
is the only library left on the command line, so this fails exactly when `__muldi3` cannot be
resolved from it and nothing else. Verified against the exact failure mode locally first, on a
host with no 32-bit multilib either: `ld: skipping incompatible .../libgcc.a when searching for
-lgcc` — the same error class the real incident hit.

[0055]: 0055-natmod-example-from-upstream-natmod.md

[0031]: 0031-unix-musllinux-libc-axis.md
[0033]: 0033-cibuildmp-never-builds-docker-image-itself.md
[0044]: 0044-unix-native-images-landed.md
[0046]: 0046-pin-staleness-checker.md
[0059]: 0059-ghcr-untagged-cleanup-deletes-referenced-manifests.md

# 0084 — per-identifier toolchain tarballs (Bootlin, uniformly), the end of shared/floating compilers, and what it does to the identifier and to CI cost

Status: Proposed — the architecture is settled through live investigation this session; nothing
below is implemented yet.
Related: [0013], [0031], [0033], [0043], [0044], [0045], [0046], [0052], [0058], [0068], [0082], [0083]

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
identifier** (`v1.29.0-manylinux_2_28-x86_64` → `v1.29.0-manylinux-x86_64`), decided directly in
conversation, not assumed. The floor axis was only *independently selectable* because pypa
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
   it in for `unix` alone). **No compiler.** Measure what this actually costs per invocation
   while proving step 4, since that number is the only thing that would send this back to option
   (a) (a published image), and nothing else about the design changes if it does.
3. **The toolchain fetch, and it runs inside the container, not on the host.** Download,
   sha256-verify, extract, `relocate-sdk.sh`, marked done by a `.installed`-style file, all
   *into a host directory `dockerrun.run()` mounts at its own identical path* — the shape
   `build_esp32.py`'s own `_esp32_container_script()` already has, for the reason [0058] gives
   ("the cache must be populated from inside the container, not on the host"). One mechanism,
   two toolchain kinds it can fetch (native, cross): `unix` only ever needs the native one, but
   it must not assume that, since the `arm_embedded` family needs both in a later phase, and
   since `container_mpy_cross()` needs the *native* one on `PATH` before it can build `mpy-cross`
   at all now that the base ships no compiler.
4. Prove it on one cell by hand, live, the way every claim in this record's own investigation was
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

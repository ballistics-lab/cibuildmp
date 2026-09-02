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

**The fleet collapses from 17 `docker/*.Dockerfile` files toward roughly 3:**

- **One generic base** (Ubuntu, for apt's own breadth covering every port's auxiliary tool need)
  — serves natmod (every arch), every `usermod` port on `arm_embedded`/`riscv_embedded` today,
  and all of `unix` (5 arches × glibc/musl), each fetching its own Bootlin tarball per identifier
  at build time, cached by version (mirroring `usermod/espidf.py`'s own `cache_root()`-keyed
  pattern — not a new mechanism, the existing one generalized).
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

**Phase 0 — generic base image, real for the first time, proven on nothing yet.**
1. Write the real `docker/<generic-base>.Dockerfile` — no toolchain baked in, only what every
   fetch step and every port's own build needs on top of a bare shell (`curl`, `xz-utils`/
   `bzip2` for Bootlin's own `.tar.xz`/`.tar.bz2`, `make`, `python3`, `python3-pyelftools`,
   `git`; `cmake` only if a later phase's port needs it, per `arm_embedded.Dockerfile`'s own
   existing "cmake is here because rp2 needs it, nothing else does" precedent — don't carry it
   into the generic image for `unix` alone).
2. Implement the fetch mechanism this record's own "Not decided" section named: download,
   sha256-verify, `relocate-sdk.sh`, cache-by-version, mirroring `usermod/espidf.py`'s own
   `fetch_esp_idf()`/`cache_root()` shape closely enough that whoever reads both recognizes the
   pattern. One function, two toolchain kinds it can fetch (native, cross) — `unix` only ever
   needs the native one, but the function should not assume that, since natmod/`arm_embedded`
   family both need the cross case in a later phase.
3. Prove it on one cell by hand, live, the way every claim in this record's own investigation
   was proven: fetch `x86-64--glibc--stable-2025.08-1` inside the new base image, build a real
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

**Phase 2 — cut `unix` over, keep pypa reachable until it's proven safe to remove.**
1. `dockerrun.image_for()`/`build_unix.py` point at the new generic image + fetch mechanism for
   `unix` only; every other port's own resolution is untouched.
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

- **The exact `pre_checkout`-shaped fetch mechanism.** Sketched by analogy to `usermod/espidf.py`'s
  own `fetch_esp_idf()`/`cache_root()` pattern in conversation, not designed or implemented.
  Needs: a generic native+cross tarball fetcher (unlike ESP-IDF's own bespoke installer, this is
  the *same* mechanism — download, sha256-verify, extract, cache by version — for every port),
  wired into whichever of `build_common.py`/`orchestrate.py`/a new module owns it.
- **The `x86-64` pre-2021.11 fallback and the `s390x` musl pre-2024.05 fallback** — argued safe
  above (newer-breaks-older, never the reverse), not independently verified live the way every
  other claim in this record was.
- **The generic base image's own real Dockerfile** — not written. Needs every auxiliary tool
  every currently-separate image installs (rp2's own `cmake`, `pyelftools`, `curl`/`xz-utils` for
  the fetch step itself) reconciled into one file, and a real build+fetch+link verified live the
  way this record's own Bootlin-musl proof was, before it replaces anything real.
- **The usermod provenance sidecar's own exact shape** — named as required above, not designed.
- **Migration order and blast radius** — seventeen Dockerfiles, `resources/pinned_docker_images.toml`,
  `resources/pinned_pypa_images.toml` (removed entirely once `unix` no longer uses pypa),
  `dockerrun.image_for()`'s own resolution logic, every doc naming a current image group
  (`docs/reference/vendored-images.md`'s own generated table, [0077]/[0078]'s docs-drift
  machinery), and every test fixture referencing a `manylinux_2_28_*`/`musllinux_1_2_*`
  identifier. Not sequenced here — the user's own next step is a single reference port (`rp2`)
  built and verified end-to-end against the generic-base-plus-Bootlin-fetch shape before any of
  this is generalized or any existing Dockerfile is touched for real.
- **[0083]'s own windows-fully-prebuilt-mingw proposal** — not superseded, but now a special case
  of this record's own broader shape (llvm-mingw is itself exactly the kind of self-contained,
  per-arch tarball this record generalizes to everywhere) rather than a separate one-off decision.

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

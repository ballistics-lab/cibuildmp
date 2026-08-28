# 0050 — natmod builds in a container; the bare-host path and its toolchain resolver are deleted

Status: Implemented

Closes [0049]'s own "still open" item, and with it the last clause of the
premise that record states. Also closes [0032] (`qemu` never wired to
`ensure_image()`), not by planning to but by force: `qemu` was the only other
thing still holding the resolver up.

## What the premise required, and what was left

> cibuildwheel for MicroPython — the same behaviour, but Docker-only and
> isolated, with **no bare-host builds**, and a foreign runner must still be
> able to build through emulation.

[0049] delivered the last clause and measured it green in both directions. The
middle one was still half true: usermod had been Docker-only since [0030], and
natmod had never been. It resolved a toolchain *onto the invoking machine* --
an apt probe, a pinned tarball unpacked into `~/.cache`, or the host gcc's own
32-bit multilib -- and then ran `make` there.

That is the same mutation [0030] ruled out for usermod, and it had a concrete
cost beyond principle: **`x86` could not be built on an arm64 runner at all.**
`action.yml` skipped the i386/multilib setup on non-amd64 hosts, correctly,
because a 32-bit x86 cross-build is not something an arm64 host does. So one of
ten arches was silently unavailable depending on where the job landed, in a
tool whose whole point had just become "the runner does not matter".

## One image, not one per arch

The user's call, and the right one. `unix` gets a native image per (arch, libc)
because a `unix` cell builds *a Linux executable for that architecture*, so an
image native to it is the only honest way to have a real libc floor ([0043]).
natmod produces a `.mpy`: relocatable machine code whose architecture lives in a
header byte, built by cross-compilers in every case. **Nothing in it is native
to anything**, so a native image buys nothing, and one pull per run beats ten.

Settled from the other side too: all four downloaded toolchains ship an
`x86_64`/`linux-x64` binary and no other build at all, so there is no arm64
toolchain to put in an arm64 image even if the shape had called for one.

`x86` looks like the exception and is the opposite of one. It needs 32-bit
multilib, and inside a `linux/amd64` image the host **is** amd64 by
construction, whatever machine is underneath. The arch that was pinned to the
runner is the arch the container frees.

## What the image replaced

Deleted outright: `natmod/toolchains.py` (302 lines), the `--toolchain` flag,
`resources/natmod.toml`'s `[[toolchain]]` table and its per-arch `toolchain`
field, and `ResolvedToolchain`'s last use in `qemu`. Every question that
machinery answered is now answered by `docker/natmod.Dockerfile`:

| the resolver asked | the image answers |
| --- | --- |
| is a compiler for this arch on this machine? | yes, all ten, always |
| if not, which tarball, and is its sha256 right? | baked in, verified at build |
| does its prefix match what `dynruntime.mk` hardcodes? | symlinks make it so |
| where is `-m32` multilib? | in the amd64 base |

The prefix reconciliation is worth naming: xpack ships `riscv-none-elf-*` where
`dynruntime.mk` expects `riscv64-unknown-elf-*`, and Espressif ships
`xtensa-esp-elf-*` against an expected `xtensa-esp32-elf-*`. [0036] found both
live and reconciled them with a `CROSS=` override on every make command line.
The image symlinks them once instead, so a build inside it needs no prefix
logic at all.

## Three things that had to change shape crossing the boundary

Each was found by running a real build, not by reading:

- **`PYTHON=<sys.executable>` cannot cross a mount.** [0012] made `pyelftools`
  and `ar` cibuildmp's own dependencies rather than something a build installs,
  and that flag was how the requirement reached `make` -- `dynruntime.mk`
  assigns `PYTHON` with a plain `=`, so naming cibuildmp's own interpreter wins.
  Inside the image that path is in the *host's* virtualenv and does not exist.
  The requirement moved into the image (`python3-pyelftools`; `ar` comes with
  build-essential) and make gets a plain `PYTHON=python3`, which is the only
  interpreter addressable from both sides.
- **Mount the package root, not the module directory.** A project's own
  Makefile is entitled to reach outside `natmod/`, and the layout this repo
  documents has `natmod/`, `usermod/` and `src/` as siblings --
  `examples/template/natmod/Makefile` compiles `../src/template_core.c`
  precisely to prove both modes share one implementation. Mounting only the
  module made that file not exist, which surfaced as `No rule to make target
  '../src/template_core.c'`: a missing mount reported as a missing rule, three
  layers down.
- **Every path resolved absolute.** Docker refuses a relative `-w` outright and
  cannot bind-mount a relative source. `module_root` is routinely relative on
  the host -- it is `package_dir / module_dir` and `package_dir` defaults to
  `"."` -- which the bare-host `subprocess.run` never cared about.

`pre-build-command` moved into the same image as the compile it precedes.
a7p's own `make fetch-nanopb` is a build step, and running it against a
different set of tools than the compile that follows is the kind of difference
that surfaces as a link error several steps later.

## The pins moved into the Dockerfile, and became checked

`natmod.toml`'s `[[toolchain]]` table held url, version and sha256 for four
third-party tarballs. With the resolver gone its only consumer was a Dockerfile
transcribing it by hand, which is data pretending to be shared. It moved, and
the move fixed a gap it had opened: the first cut of the image fetched those
four tarballs over the network -- into an image every build then runs compilers
out of -- **with no integrity check at all**, while the hashes sat in a table
nothing read. Each entry now carries its sha256 and `sha256sum -c` runs on it.

## qemu, closed by force

[0032] had `qemu` down as "the last port with a published, pinned image and no
caller" for weeks. It survived because it *worked*: `toolchains.resolve()`
found an `arm-none-eabi-` on the runner and `subprocess.run` used it. Deleting
the resolver left it with nothing to stand on, so it is wired to
`ensure_image()` now, `linux/amd64` like the other cross-compiling ports.
Board-to-prefix is a plain map (`MPS2_AN385` → `arm-none-eabi-`, both `VIRT_RV*`
→ `riscv64-unknown-elf-`) rather than a resolution, because the image supplies
exactly those names and nothing else can be in play.

## Verified

- All ten arches built inside the image, 5.7s total, each `.mpy` checked
  against its own identifier by `verify_output()` -- which reads
  `MP_NATIVE_ARCH_*` back out of the header, so this is not merely "make did
  not fail".
- Every toolchain prefix resolves inside the image, including both symlink
  sets; `gcc -m32` produces `EI_CLASS=1, e_machine=3` (EM_386) and plain `gcc`
  produces `EI_CLASS=2, e_machine=62`.
- All four tarball checksums verified at image build.
- 301 unit tests.

## A pre-existing bug this exposed, in the example rather than the tool

Running the whole matrix in one invocation became the normal thing to do, and
the second arch failed with `LinkError: incompatible arch`. The cause is in
`examples/template/natmod/Makefile` and predates all of this:
`dynruntime.mk` forms each object as `$(BUILD)/$(src:.c=.o)`, so a source
*outside* the module directory has its `..` eat the arch component --
`.obj/x64/../src/foo.o` collapses to `.obj/src/foo.o`. The shared core object
was therefore built once, by whichever arch ran first, and silently linked into
every later one.

That Makefile's own comments already document two earlier instances of the same
bug class, on two different axes. This is the third, and the fix is one
directory level (`.obj/$(ARCH)/o`) so the `..` has somewhere to go that is
still under the arch. It matters beyond the example: the layout it affects is
the one this repo tells consumers to use.

## Deleting "old" images from GHCR is mostly a trap

Worth recording because the packages list invites the mistake. Every image
`publish-docker-images.yml` pushes shows **three versions** in GHCR, one tagged
`latest` and two untagged, and the untagged pair looks exactly like superseded
builds. It is not: the tagged digest is an OCI *index*, and those two are its
children.

    sha256:7caab34…  index, tags=[latest]        <- what the pin names
      |- sha256:472baba…  linux/amd64            <- the image itself
      `- sha256:2e394dc…  attestation-manifest   <- provenance/SBOM

GHCR lists every manifest as a "version", so a pin's own contents appear beside
it as if they were leftovers. Deleting them would leave each pinned index
pointing at manifests that no longer exist -- every consumer's build failing on
pull, for all eighteen at once.

The rule that falls out: **an untagged version is only garbage if nothing
references it**, and on this registry that means checking whether the tagged
digest is an index and what it points at, not reading the version list. Both
were checked here through the registry API before anything was deleted.

`natmod` is the one package where an untagged version genuinely was garbage,
and the reason is instructive: a hand `docker push` produces a bare manifest
with no index and no attestation, so its superseded digests really do stand
alone. That is the same property that made the first hand-push land unlinked
and private -- `docker/build-push-action` does considerably more than move
layers, and both consequences were discovered the same day.

## Two process failures, both worth naming

Neither is about natmod, and both cost more than any technical mistake in this
record.

**A path-scoped `git add` split code from its tests.** `DEFAULT_MICROPYTHON`
went to `v1.29.0` in one commit while the two tests asserting the old value
stayed behind, because the commit used `git add -A -- src examples docker`. The
scoping was deliberate once -- an unrelated untracked file was in the tree and
should not be swept in -- and then repeated out of habit into commits where it
only did harm.

**A green local `pytest` proved nothing, because the working tree was dirty.**
The fix for those two tests existed on disk and was reported as "301 passed"
three times, while the *committed* tree failed its own suite. `Tests` had been
red for three consecutive commits and went unnoticed, because the only workflow
being watched was `Build examples` -- the one that was interesting.

The rules that follow, in the order they would have caught it:

- Watch every workflow a push triggers, not the interesting one. A red `Tests`
  is a red repository whatever else is green.
- When the tree is dirty, `pytest` describes the tree, not the commit.
  `git stash && pytest` is the check that matches what CI will run -- and it is
  what confirmed the breakage here, after the fact.
- Scope `git add` by path only for a reason that still applies, and re-check
  `git status` after committing rather than assuming it is empty.

It was found by the user asking why two test files were sitting unstaged.

## Still open

- The image is 3.91GB, of which 3.38GB is one layer holding four toolchains.
  That is larger than any `unix` cell and larger than estimated. Splitting the
  toolchains into separate layers would stop a single bump repulling all of
  them; dropping `xtensa-lx106` (ESP8266, crosstool-NG 4.8.5) would be the
  blunt option. Neither is urgent -- it is one pull per run.
- `action.yml`'s apt step can now go. It exists for natmod's `x86` multilib and
  for `build-essential`, and neither is needed on a host that only launches
  containers. That is 37s off every job in the repo and the `HOST_ARCH`
  branching with it.
- natmod still builds mpy-cross on the host (`cli.py`'s own
  `build_mpy_cross`). usermod hit this in [0044] and answered it with
  `container_mpy_cross()`; natmod has not been checked for whether its `make`
  reaches that binary at all.

## Addendum, 2026-08-27 — the natmod image republished by CI itself; first real CI run

The "Still open" item above ("the published digest predates `gcc-i686-linux-gnu`... no CI
run has ever exercised natmod-in-a-container at all") is closed. `publish-docker-images.yml`
was dispatched (`only: natmod`) against this image's own current Dockerfile content (already
carrying `gcc-i686-linux-gnu`, committed earlier) and, for the first time, actually pushed
through `docker/build-push-action` rather than by hand.

**A second, previously-unknown gap surfaced doing this**: the push failed with `denied:
permission_denied: write_package`, even with `packages: write` in the workflow. A package's
first hand `docker push` (this record's own earlier text) does more damage than "unlinked and
private" -- it also leaves the package with no Actions-write grant for any repository, since
GitHub only auto-grants that at the moment a package is first created *by* a repository's own
Actions run. Fixed the same way the earlier private-visibility gap was (both settings-UI-only,
no REST endpoint for either): the package was connected to this repository ("Connect
Repository") and explicitly granted `Write` under "Manage Actions access". Once both were set,
the exact same workflow dispatch succeeded immediately, no other change needed.

The resulting digest (`sha256:d3f6c431...`) is a real, workflow-published OCI index with
provenance and attestation -- not the bare-manifest shape the prior two hand-pushed digests
had. Content is unchanged (same Dockerfile, same four verified toolchains); only the
publishing path changed, which is why the digest itself differs from a byte-identical build.

`resources/pinned_docker_images.toml`'s own comment above the `natmod` pin was rewritten to
carry this history (superseding, not deleting, the account of the second digest). Confirmed
live, not just by the publish workflow's own "publicly pullable" check: the very next push to
this branch triggered `build-examples.yml` on a fresh runner with no local cache, which
anonymously pulled exactly this digest and built `examples/template` through it successfully
(`Build examples/template (natmod)`, green). That is the first real CI run this project has
ever had exercise natmod-in-a-container end to end.

## Addendum, 2026-08-27 — natmod's own mpy-cross moves into the image; the apt step does not go

The "Still open" `mpy-cross` item is closed: `build_mpy_cross()` (now
`platforms/natmod/build.py`, not `sources.py`) builds it inside the natmod
image, reusing `_natmod_image()`/`_run_in_image()`, at the exact fixed path
`py/dynruntime.mk` hardcodes (`mpy-cross/build/mpy-cross` -- confirmed
against the real file, no override mechanism exists) -- the same fix
[0044]'s own `container_mpy_cross()` already made for `unix`/`windows`/
`webassembly`, for the identical reason: a host-built binary only worked
by coincidence of matching the image's own glibc, and cannot work at all
across an architecture boundary.

The other "still open" claim from this record's original text --
"`action.yml`'s apt step can now go" -- does **not** follow from this fix,
and was wrong even at the time it was written: `usermod`'s own `qemu` and
`esp32` ports build *their* mpy-cross on the host too
(`_HOST_MPY_CROSS_PORTS`, `platforms/usermod/orchestrate.py`), for a
reason unrelated to natmod (`esp32`'s `make` never runs in a container at
all; `qemu` passes no `MICROPY_MPYCROSS=`). `build-essential` stays in
`action.yml` until those two get the same treatment -- a separate,
not-yet-scoped piece of work, since neither port's own build is
containerized the way `unix`/`windows`/`webassembly`'s already are.

[0012]: 0012-pyelftools-ar-own-deps.md
[0030]: 0030-container-approach-natmod-and-docker-vs-qemu.md
[0032]: 0032-unix-docker-default-and-webassembly-wiring.md
[0036]: 0036-m2-toolchain-resolver.md
[0043]: 0043-unix-adopts-cibuildwheel-native-image-model.md
[0044]: 0044-unix-native-images-landed.md
[0049]: 0049-no-matrix-generation-archs-vocabulary.md

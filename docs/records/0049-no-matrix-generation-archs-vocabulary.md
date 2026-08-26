# 0049 — cibuildmp generates no matrix and chooses no host; `--archs auto` does the work instead

Status: Implemented

Supersedes the runner-selection half of [0020] and closes [0045]'s own
still-open `--archs`/`auto` half. [0044]'s "usermod has no per-target `runs-on`
override" item is closed by deletion rather than by adding one.

## The premise this record is measured against

Stated by the user, in one sentence, and worth writing down because every
decision below follows from it rather than from a local preference:

> cibuildwheel for MicroPython — the same behaviour, but Docker-only and
> isolated, with no bare-host builds, and a foreign runner must still be able
> to build through emulation.

Two of those were already true. usermod is Docker-only ([0030]) and every build
passes an explicit `--platform` ([0043]/[0044]), so a non-native target builds
anywhere binfmt is registered. The third was not: **cibuildmp had an opinion
about which host a target should run on, and cibuildwheel has no such concept
at all.**

## What was there, and why it was the wrong shape

`--print-build-matrix` emitted `{only, os}` objects; `.github/actions/cibuildmp-matrix`
wrapped it; `UsermodTarget.default_runner` supplied the `os`, arch-aware since
[0044] so that an `_aarch64` target named `ubuntu-24.04-arm`. natmod had the
same idea plus a `runs-on` config key to override it; usermod had no override
anywhere, which [0044] recorded as still open.

None of it was wrong in isolation, and the arch-awareness was a real
improvement — it is what made the arm64 cells native instead of ~12x emulated.
The problem is what it *is*: a build tool deciding where builds happen.
cibuildwheel does not do this, and not because nobody got around to it. It
generates no matrix, emits no runner and consults the host for exactly one
thing — `Architecture.parse_config()`'s `auto`/`native`/`all`, which chooses
*what to build here*, on this machine, and is re-decided on every machine. The
consumer writes `runs-on` in their own workflow, gives each job `CIBW_ARCHS:
auto`, and the distribution falls out.

Two concrete costs of the shape cibuildmp had:

- **A suggestion the caller could not refuse.** A consumer whose fleet is one
  architecture had no way to say "run everything here". The matrix said
  `ubuntu-24.04-arm` and that was that.
- **The emulated path was structurally unreachable.** Every target ran only on
  the host `default_runner` picked, so the "a foreign runner can still build"
  property — the third clause of the premise, and the one the whole
  container-per-target design exists to deliver — had never been executed by CI
  in either direction. It had one local measurement ([0044], 1041s) and nothing
  else.

## What replaced it

**Deleted:** `--print-build-matrix`, both `default_runner`s, natmod's `runs-on`
key and `Options.runs_on`, and the `cibuildmp-matrix` action. Nothing outside
this repo called any of it — the three consuming repos of [0038] never adopted
the action.

**Added:** `--archs`, extended to usermod, accepting `auto`, `native` and `all`
beside explicit names, plus an `archs:` input on the root action. Keywords work
in `[usermod.<port>] archs` too, and mix with explicit names
(`["auto", "manylinux_2_28_s390x"]` is "what runs here, plus that one"),
because expansion happens in one place inside `usermod_targets()` and every
caller gets it without knowing it exists.

`build-examples.yml` is now the cibuildwheel shape: one job per runner, each
saying `archs: auto`.

## Three things that had to be got right

**Only `unix` has a host-dependent axis.** Its cells are native containers for
their own architecture ([0043]), so "which run here without emulation" is a real
question. No other port's axis is: `windows` cross-compiles to three Windows
arches out of one amd64 image, `qemu`/`esp32` name boards, `webassembly` has no
axis. For those the keywords all mean the full axis — which is natmod's own
recorded argument for having no `auto` ("every natmod arch is a cross-compile,
so none of them depends on what this machine is", [0045]) applied where it also
holds.

**Ask the image, not the tag.** `manylinux_2_39_mipsel` names `mipsel` and runs
in a `linux/amd64` container, because pypa publishes no mipsel image and there
is nothing for it to be native to ([0044]). Matching on the tag's architecture
suffix would call it non-native on the one host it is actually native on, so
`resolve_axis_keyword()` asks `dockerrun.platform_for()` instead. This is
`unix`'s only cell where the two disagree, and it disagrees on the most common
host there is.

**`native` vs `auto` is one entry that can be wrong, affordably.** `auto` adds
the 32-bit sibling a host executes directly — `i686` on `x86_64`, `armv7l` on
`aarch64`. The second is a bet: 32-bit ARM is native on an arm64 host only if
the CPU implements AArch32 at EL0. cibuildwheel carries a runtime check; a
static table is enough here because **the cost of being wrong is bounded to
speed**. A cell wrongly called native still builds, emulated, since
`--platform` is passed either way. That is a different kind of mistake from one
that yields a wrong binary, which is why the same shortcut would be
unacceptable inside `dockerrun`. On the hosts that matter it is measured, not
assumed ([0044]: `armv8l`, 59.5s against the native `aarch64` build's 88.8s).

## What this does not change

**Nothing became unbuildable anywhere.** `--archs` picks a subset to build
*here*; it gates nothing. `dockerrun.run()` still passes `--platform` resolved
from the target, `host_oci_platform()` is still the only place
`platform.machine()` is consulted in that module and its value still never
leaves it, and `_probe_platform()` still refuses only when binfmt is genuinely
missing. The one thing that reads the host for *selection* is this record's own
vocabulary, and [0045] already drew that line: [0043] forbids host architecture
in identifiers, image names and pin keys — facts that must mean the same thing
everywhere — not in a local choice re-made per machine.

**`--print-build-identifiers` now reflects the host when `archs` says `auto`.**
[0045] cautioned against that on the grounds that a matrix generated on one
runner would be consumed on another. That use case was matrix generation, and
it no longer exists; a list that disagreed with what the same invocation would
build would be worse.

## Addendum, 2026-08-26 — proven in both directions, and what it cost

Run [32965518561] is the first to execute the premise's third clause rather
than assert it. Both legs green:

| direction | target | runner |
| --- | --- | --- |
| amd64 image on an arm64 host | `webassembly` | `ubuntu-24.04-arm` |
| arm64 image on an amd64 host | `unix-manylinux_2_28_aarch64` | `ubuntu-latest` |

So "a foreign runner can still build, through emulation" is two green jobs now,
not a claim in a record. `--platform` plus binfmt is the entire mechanism and it
needs nothing else, which is what [0033]'s pull-only design and [0043]'s
per-target platforms were betting on.

**And it is expensive, which changes where it belongs.** One leg measured 18
minutes against roughly three for everything else in the workflow combined —
emulation is 12-20x and there is no version of this job that is not emulated,
that being the point of it. It moved off `push` to a nightly schedule plus
`workflow_dispatch`. The reasoning is worth stating because it generalises: a
job that *proves a property* and a job that *catches regressions* want different
cadences, and this is the first kind. What it would catch per-push is a
regression in `--platform` handling — one small, rarely-touched code path — and
the cost grows with every port added, none of which have landed yet.

Three other things fell out of measuring that run, all in the same commit:

- **`auto` was not filtering the ports without an architecture axis.** Their
  images are `linux/amd64`, so on an arm64 runner `windows`, `webassembly` and
  `qemu` ran emulated exactly like a non-native `unix` cell — and `auto` kept
  selecting them, because the keyword only ever reached `archs`-keyed ports.
  `webassembly` was built three times in one run. The rule is one rule now:
  ask `platform_for()`, per cell for `unix` and per port for everything else.
- **The host mpy-cross is built lazily.** `container_mpy_cross()` replaced it
  for `unix`/`windows`/`webassembly` in [0044]; it was still being compiled on
  the host for every run regardless — seven seconds, and a bare-host build in a
  mode whose whole point is not doing those.
- **Fan out by image, not by target.** `windows`'s three arches come out of one
  amd64 image, so its three-leg fan-out pulled the same 2GB three times instead
  of once. `unix` gains from fanning out (a different image per cell, so pulls
  overlap); `windows` only lost. It joined `examples/template`'s own `ports`
  instead, having gone green three runs running.

`esp32` left the default port set in the same change — not `KNOWN_PORTS`. It is
the one port with no Dockerfile and no pinned image ([0028]), so it is also the
one that cannot satisfy the Docker-only rule every other port now follows; its
build provisions ESP-IDF onto the host, which is the bare-host mutation this
record's premise rules out. `--only` still reaches it.

[32965518561]: https://github.com/ballistics-lab/cibuildmp/actions/runs/32965518561

## The shape costs wall-clock, measured, and is kept anyway

Worth recording precisely, because the number is bad enough that someone will
eventually propose undoing this without knowing it was measured:

| run | workflow shape | wall-clock |
| --- | --- | --- |
| 9908be4 | fourteen parallel legs, one per target | 2m53s |
| 7393e25 | fourteen parallel legs | 3m08s |
| fdb22b8 | fourteen parallel legs | 3m43s |
| **a10ce76** | **one job per runner, `archs: auto`** | **10m56s** |

`build-usermod (ubuntu-latest)` alone is 10m35s of that. The mechanism is
plain: `auto` selects nine targets there across **seven distinct images** --
one per `unix` cell, one for `webassembly`, one shared by all three `windows`
arches -- and seven sequential 32-second pulls is nearly four minutes of
nothing but fetching, before a single compile. Fanning out makes the run the
*maximum* of its legs; looping makes it the *sum*.

**Kept, on the user's call.** The trade being bought is that the workflow
looks exactly like a cibuildwheel workflow -- `runs-on` in the consumer's own
matrix, `archs: auto` in each job, nothing about hosts inside the tool -- and
that is the premise this whole record serves. Eleven minutes on a push is a
real cost and not a hidden one.

It is also worth being clear about what *would* fix it without touching any of
the above, if the cost ever stops being acceptable: **the workflow fanning out
on its own.** Deleting matrix generation from the tool and deleting fan-out
from the workflow were two separate things, and only the first was required.
cibuildwheel users fan out all the time; they write the matrix themselves,
which is exactly the distinction. The one refinement that would need is to fan
out **by image rather than by target** -- `windows`'s three arches share one
image, so three legs pull the same 2GB three times, which is the mistake this
record's own perf commit had already made once and corrected.

## Still open

- **natmod still builds on the bare host.** The premise says "no bare-host
  builds", and usermod satisfies it while natmod does not: [0003]'s
  `host`/`download` toolchain resolution installs and runs cross toolchains on
  whatever machine invokes it. That is a much larger change than this record
  and is not attempted here, but it is the remaining distance to the premise
  and should be recorded as such rather than left implicit.
- Whether `auto` should become the *default* axis for `unix`, rather than the
  nine curated cells `_UNIX_DEFAULT_TARGETS` names. It is cibuildwheel's own
  default and would make a bare `ports = ["unix"]` mean "what this runner can
  do fast". It is deliberately not taken here: the vocabulary had to exist
  before the default could be argued about.

[0003]: 0003-toolchain-resolution-per-target.md
[0020]: 0020-usermod-runner-selection-structural.md
[0030]: 0030-container-approach-natmod-and-docker-vs-qemu.md
[0038]: 0038-m5-adopt-in-three-repos.md
[0043]: 0043-unix-adopts-cibuildwheel-native-image-model.md
[0044]: 0044-unix-native-images-landed.md
[0045]: 0045-only-is-a-filter-not-a-forced-identifier.md

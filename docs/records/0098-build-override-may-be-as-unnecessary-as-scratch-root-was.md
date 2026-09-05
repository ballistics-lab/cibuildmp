# 0098 — `BUILD=` may be as unnecessary for unix/windows/qemu/webassembly as `scratch_root()` was

Status: Proposed — a direction, not decided or implemented. Surfaced while closing [0095]'s own
open question (deleting `scratch_root()`/`CIBMP_SCRATCH_PATH`, this session), not investigated
independently. **Read the addendum below**: the first "not decided here" item was checked live
and turned out to gate on a new record, [0099] — `qemu` can drop `BUILD=` on its own, but
`unix`/`windows`/`webassembly` should wait for [0099] to land first.
Related: [0056], [0060], [0095], [0099]

## The claim

`orchestrate._resolved_build_dir()` still computes a per-identifier `BUILD=` value
(`_BUILD_ROOT / "ports" / port / f"build-{identifier}"`) for four usermod drivers --
`unix`, `windows`, `qemu`, `webassembly` -- and each of their own `*_make_command()`
functions passes it to `make`. `esp32` and `rp2` pass no `BUILD=` at all and use the
port's own unmodified default build directory instead, for a documented reason:
both are CMake-driven, and `esp32_make_command()`/`rp2_make_command()`'s own comments
explain that passing `BUILD=` at all (not merely what it resolves to) leaks
`FROZEN_MANIFEST` through `MAKEFLAGS` into the port's own internal `mpy-cross`
sub-build and breaks it.

The four Make-driven ports have no such danger -- `BUILD=` is an ordinary Makefile
variable for them, which is *why* passing it was safe, not why it was *necessary*.
The actual necessity argument was different, stated directly in
`_resolved_build_dir()`'s own (pre-this-record) comment: a per-identifier directory
"so building unix-manylinux_2_28_x86_64 and unix-manylinux_2_28_aarch64 against the
same checkout in one invocation never has one overwrite the other mid-build."

That argument is exactly the one [0095]'s closing addendum this session found no
longer real for `scratch_root()`, and it applies here for the identical reason:
every `build_<port>()` call gets its own fresh `Container`/overlay ([0095]'s addenda
8-12), so two targets against the same `mpy_dir` never share a writable filesystem at
all, regardless of what `BUILD=` names -- each container's own upper layer is
independent and dies with it. `esp32`/`rp2` are not a special case that tolerates no
override; they are the proof that no port needs one any more, arrived at for an
unrelated (MAKEFLAGS) reason before the real one (container isolation) was ever
checked for the other four.

## What this would mean, concretely

- `unix_make_command()`, `windows_make_command()`, `qemu_make_command()`,
  `webassembly_make_command()` each drop their own `f"BUILD={opts.build_dir.as_posix()}"`
  argument.
- `UnixBuildOptions`, `WindowsBuildOptions`, `QemuBuildOptions`,
  `WebassemblyBuildOptions` each drop their own `build_dir: Path` field.
- `orchestrate._port_build_options()` stops computing `build_dir=_resolved_build_dir(...)`
  for these four ports.
- `orchestrate._resolved_build_dir()` and `_BUILD_ROOT` (this session's own replacement
  for `scratch_root()`) go away entirely -- nothing would call either.
- `build_one()` already has no `build_dir`-keyed cleanup left to remove (this session's
  own [0095] addendum already deleted that rmtree).
- Real test churn: every one of these four ports' own `test_usermod_build_<port>.py`
  constructs its `*BuildOptions` fixture with a `build_dir=` field, and
  `test_usermod_orchestrate.py`'s own build-dir assertions (touched this session, see
  [0095]'s closing addendum) would need re-deriving from each port's own real default
  build path instead.

## Not decided here

- **What each port's own bare default build directory actually is**, read from its
  real `ports/<port>/Makefile`/`py/mkenv.mk` rather than assumed -- not checked yet.
  This matters for two things a per-identifier override currently guarantees for free:
  a build log's own paths staying legible per target (cosmetic, not correctness), and
  whatever the port's own default naming does or does not already scope by board/arch
  on its own (`qemu`'s own board axis, `windows`'s three arches) -- if a port's bare
  default is *itself* arch-scoped already (plausible; `unix`'s own upstream `BUILD`
  default has historically included the port's own variant), dropping the override may
  be a pure simplification; if it is not, per-identifier legibility would be lost
  without functional harm, which is a real but smaller cost than assumed here.
- Whether the four drivers' own `*BuildOptions` dataclasses are worth narrowing at all
  given how much of each port's own test fixture already depends on the field's shape
  -- a real, measurable migration cost this record does not weigh against the (mostly
  cosmetic) benefit of deleting it.
- Whether this is worth doing at all before something else actually needs it. Unlike
  `scratch_root()`/`CIBMP_SCRATCH_PATH`, `BUILD=` is not a dead, misleading *public*
  knob -- it is internal-only, and its only cost today is a few lines of indirection
  slightly wider than `esp32`/`rp2`'s. [0056]'s own "a knob nobody can turn is worse
  than no knob" argument justified deleting a *documented, user-facing* no-op; it does
  not automatically transfer to an internal implementation detail with no such cost.

[0056]: 0056-usermod-with-no-user-c-module.md
[0060]: 0060-rp2-build-driver.md
[0095]: 0095-cache-root-splits-source-from-build-state.md
[0099]: 0099-variant-becomes-a-real-per-target-override-not-an-identifier-axis.md

## Addendum, 2026-09-05 — the first "not decided here" item answered, and it opens a new question: [0099]

Checked live against `github.com/micropython/micropython/tree/v1.29.0/ports/<port>/variants`
(the tag this project's own example config pins), not assumed: `unix`'s real upstream default
is `build-$(VARIANT)`, and `windows`'/`webassembly`'s Makefiles resolve the identical
`BUILD ?= build-$(VARIANT)` line from the shared `py/mkenv.mk` (`qemu`'s own is
`build-$(BOARD)` instead — a real, different line, board-scoped already). That confirms the
"unix's own upstream `BUILD` default has historically included the port's own variant"
guess above — for all three Make ports that carry a `variant`, not just `unix`.

**But it does not, on its own, make dropping the override for `unix`/`windows`/`webassembly`
a pure simplification the way it does for `qemu`.** Grepped across the whole codebase:
`UnixBuildOptions.variant`/`WindowsBuildOptions.variant`/`WebassemblyBuildOptions.variant`
are dataclass fields with a fixed default (`standard`, `standard`, `pyscript`) that **no real
caller ever overrides** — `_port_build_options()` never passes `variant=`, no test ever sets
one, and `boards.py`'s own `_VARIANT_ONLY_PORTS`/`Board.find_variant()` machinery (vendored
for exactly this, D7) has no caller outside its own tests. Since `variant` never actually
varies today, the port's own default naming collapses to one fixed string
(`build-standard`/`build-pyscript`) for every target that port ever builds — not per-target
legible the way `qemu`'s real `BOARD=`-keyed default is. This record's own "cosmetic, not
correctness" framing for the legibility loss undersold the cost for these three ports
specifically: with no per-target print/log anywhere in `orchestrate.build()` and one job
looping over many targets in one log stream being the default ([0009]), today's explicit
`build-<identifier>` naming is currently the *only* thing in a raw `make` log (`Entering
directory ...`) that says which target a given line belongs to. Dropping it before `variant`
is real would remove that with nothing replacing it, for `unix`/`windows`/`webassembly` (not
`qemu`, whose board-keyed default already carries equivalent information).

**[0099] is the follow-on this surfaced**: making `variant` a real, per-target-overridable
option (not a dead field, not folded into the identifier, not a single global key — see that
record's own reasoning for why each of those was rejected). Once it lands, the port's own
`build-$(VARIANT)` default naming genuinely earns its keep — a `coverage` build and a
`standard` build of the same `unix` target land in self-describing, distinct directory
names with no code required to make that happen — which *strengthens* this record's case for
dropping the override on all three ports, not just `qemu`, but only once [0099]'s own real
work lands (including its own open manifest-coupling item), not before. Sequencing, not
reversal: `qemu` can drop `BUILD=` today, independent of any of this; `unix`/`windows`/
`webassembly` should wait for [0099].

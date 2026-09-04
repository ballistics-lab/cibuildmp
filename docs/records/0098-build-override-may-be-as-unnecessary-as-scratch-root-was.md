# 0098 — `BUILD=` may be as unnecessary for unix/windows/qemu/webassembly as `scratch_root()` was

Status: Proposed — a direction, not decided or implemented. Surfaced while closing [0095]'s own
open question (deleting `scratch_root()`/`CIBMP_SCRATCH_PATH`, this session), not investigated
independently.
Related: [0056], [0060], [0095]

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

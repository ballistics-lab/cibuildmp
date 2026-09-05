# 0099 — `variant` becomes a real, per-target-overridable option — not an identifier axis, not a global key

Status: Proposed — design decided in conversation, no code written yet.
Related: [0098], [0052], [0056], [0051], [0015]

## The problem

[0098]'s own investigation into whether `BUILD=` is still necessary found, as a side
effect, that `UnixBuildOptions.variant`/`WindowsBuildOptions.variant`/
`WebassemblyBuildOptions.variant` (`build_unix.py:263`, `build_windows.py:138`,
`build_webassembly.py:25`) are dataclass fields with a fixed default (`"standard"`,
`"standard"`, `"pyscript"`) that **no real code path ever overrides**. Grepped across
`orchestrate.py`, `options.py`, `cli.py` and the entire `tests/` tree: `_port_build_options()`
constructs each `*BuildOptions` without ever passing `variant=`, and no test ever does either.
`boards.py`'s own `_VARIANT_ONLY_PORTS = ("unix", "webassembly", "windows")` and
`Board.find_variant()` already model this as a selectable axis (vendored from mpbuild's board
database, D7) but have no caller anywhere outside their own file and `test_boards.py`/
`test_platform_row_facts.py` — machinery built for a feature that was never wired up.

## The upstream fact, checked live (not assumed)

Verified against `github.com/micropython/micropython/tree/v1.29.0/ports/<port>/variants`
(the tag `examples/template/cibuildmp.toml` pins) — real, upstream-supported, meaningfully
different builds, not a hypothetical axis:

| port | real `variants/*` | what cibuildmp resolves today |
| --- | --- | --- |
| `unix` | `standard`, `coverage`, `longlong`, `minimal`, `nanbox` | always `standard` |
| `windows` | `standard`, `dev` | always `standard` |
| `webassembly` | `standard`, `pyscript` | always `pyscript` (deliberately non-default already — `portinfo.py`'s own docstring) |

`coverage` is what upstream's own test suite builds against; `nanbox`/`longlong` change the
object representation; `minimal` strips features down. These are real, distinct products a
consumer could reasonably want to select — not an internal implementation detail like
[0098]'s own `BUILD=` path.

## The design decision

Two shapes were considered and rejected before landing on the one below:

- **A new identifier axis** (e.g. `v1.29.0-manylinux_2_28_x86_64+coverage`, following [0015]'s
  own precedent of putting a real build-affecting knob into the identifier rather than hiding
  it in `extra-make-args`). Rejected: `unix`'s identifier axis is already the platform tag
  ([0043]), `windows`'s is `arch`; folding variant in as a second axis multiplies the target
  matrix (5 variants × every existing unix cell) and reopens exactly the tree-addressed
  `[usermod.<port>] variant = "..."` shape [0052]'s own Track B proposed, designed in detail,
  and then reverted outright in the same record in favour of the flat model that shipped.
  Reopening Track B for one field is not this record's call to make alone, and nothing about
  `variant` needs it: two builds that differ only by `variant` are not "incompatible" the way
  two different platform tags are ([0043]'s own reason `unix` carries an axis at all), so
  `variant` does not belong in the string whose whole job is naming build compatibility.
- **A single global `variant = "..."` key**, applying uniformly to every target in the run.
  Rejected: it cannot express `unix` and `webassembly` wanting different real defaults
  (`standard` vs `pyscript`) without every consuming project's config re-stating `pyscript`
  explicitly forever, and it silently makes two runs with the same `build`/`skip` selection
  produce differently-shaped artifacts under the identical identifier depending on a knob
  that leaves no trace anywhere a user would look — the exact "invisible knob" problem [0015]
  fixed for natmod's `ARCH_FLAGS=` by making it part of the identifier instead. `variant`
  rejected that fix (previous bullet) for a different reason, but the underlying complaint
  still applies: it cannot be *invisible* either.

**What lands instead: `variant` becomes a fourth `USERMOD_PORT_BASE` key**, resolved through
the exact cascade `user-c-modules`/`manifest`/`extra-make-args`/`extra-cmake-args` already use
(`options.py:504`, `build_options()`'s own `opt()` closure) — global default → matching
`[override."<glob>"]` (each with its own `inherit` rule) → `CIBMP_VARIANT` environment
override. No new mechanism. `[override."*coverage*"] variant = "coverage"` (or any glob a
consumer's own identifiers actually produce) is how a real project opts one target into a
non-default variant, using the same syntax `[override]` already has for everything else.

**Per-port default**, so today's real, live-verified behaviour keeps working with no
config change required: a `default_variant(port)` fact — `"standard"` for `unix`/`windows`,
`"pyscript"` for `webassembly` — the same shape `portinfo.default_manifest(port)` already is,
read via `opt("variant", default=default_variant(target.port))` rather than the fixed default
argument every other `opt(...)` call in `build_options()` uses. Where it lives (a new
`portinfo.py` function vs. a new `default-variant` key in each port's own
`[usermod.<port>]` table in `build-platforms.toml`, D10's "pinned data lives in resources/"
pattern) is implementation, not decided here, but it follows `default_manifest()`'s own
precedent either way.

**Validation gets a caller it never had**: `boards.py`'s `Board.find_variant()` (currently
dead outside its own tests) is exactly the right tool to reject an unknown variant name at
config-load time rather than at `make` failure time — this is the first real consumer that
machinery has ever had.

## A real coupling this surfaces, not fixed here

`portinfo.default_manifest(port)` is a **fixed string per port**, and for the two ports that
matter most it already bakes in today's hardcoded variant: `unix`'s own
`[usermod.unix]` table reads `default-manifest = "variants/standard/manifest.py"`,
`webassembly`'s reads `default-manifest = "variants/pyscript/manifest.py"`
(`build-platforms.toml:361,719`). Once `variant` is a real, overridable value, a target built
with `variant = "coverage"` would still combine against `variants/standard/manifest.py` —
upstream's own `combined_manifest()` call (`manifests.py:40`) `include()`s a manifest path
that no longer matches what was actually compiled. This does not fail loudly: `unix`'s build
would still succeed, just frozen against the wrong variant's own module list. `default_manifest()`
has to become a function of `(port, variant)`, not `port` alone, before `variant` genuinely
ships for `unix`/`webassembly` — **left open, not designed here**, the same way [0098] leaves
its own open items rather than guessing at a fix implemented and verified in the same breath.

## Consequence for [0098]

Cross-referenced there directly (see its own addendum). Short version: once `variant` is a
real, per-identifier-overridable value, upstream's own `BUILD ?= build-$(VARIANT)` default
naming (which [0098]'s own investigation found always collapses to `build-standard`/
`build-pyscript` today, since `variant` never varies) starts actually earning its keep —
a `coverage` build and a `standard` build of the same `unix` target would land in
genuinely different, self-describing directory names with no code needed to make that so.
That strengthens [0098]'s case for dropping the explicit override on `unix`/`windows`/
`webassembly`, but only once this record's own manifest coupling above is resolved — a
legible `build-coverage/` directory next to a binary silently frozen with `standard`'s own
module list would make a real bug look like correct, informative behaviour.

## Not decided here

- Whether `default_manifest()`'s fix (making it `(port, variant)`-keyed) belongs in this
  record's own implementation or is separable follow-up work.
- Exact storage location for `default_variant(port)` (`portinfo.py` function vs.
  `build-platforms.toml` row key).
- Whether `qemu`/`esp32`/`rp2` need anything here at all — they don't: their own axis is a
  real board ([0051]), not a MicroPython `variant`, and `boards.py`'s own
  `_VARIANT_ONLY_PORTS` already excludes them from this by construction.

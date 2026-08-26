# 0051 — one selector for both modes, and an identifier that names what a build is compatible with

Status: Accepted (design; not implemented)

Rewritten twice the same day it was written, before anything was built on it.
The first draft framed this as "usermod cannot build two MicroPython versions",
which is a symptom; the second still treated the selector machinery as a
separate concern. It is not. The identifier, what selects over it, and where
that selection lives are one design, and cibuildmp has all three wrong in ways
that only look separate.

## The rule

cibuildwheel's shape, and the reason its selectors work at all: **the build
identifier is the complete description of one build, and selection is globbing
over it.** `cp313-manylinux_x86_64` names the interpreter and the platform, so
`CIBW_BUILD="cp313-*"` means something. Every axis that can vary is in the
identifier; nothing that varies is anywhere else.

cibuildmp adopted the identifier ([0005]) and the globs ([0045]) and then broke
the rule in both modes, differently.

## What each mode's axis actually is

The axis is **what the artifact is compatible with** -- not which release tag
produced it. Those differ, and that is the whole point:

| mode | axis | the release tag is |
| --- | --- | --- |
| natmod | the `.mpy` **ABI** | whichever release supplies it -- an implementation detail |
| usermod | the **MicroPython release** | the axis itself; a port binary fits nothing else |

natmod's identifier is right (`mpy6.3-natmod-x64`) and [0013] argued it
correctly: a native `.mpy` loads into any runtime with a matching ABI, and 6.3
alone spans v1.23.0 through v1.29.0, so naming the release would claim far
narrower compatibility than the artifact has.

usermod's identifier is `unix-manylinux_2_28_x86_64`. It names the port and the
platform tag and says nothing about which MicroPython it *is*.

## Both failures, from that one rule

**natmod names the axis and selects it backwards.** You give tags; the ABI is
derived from them and deduped:

```python
resolve_micropython_tags(tags, override)   # tags in, one (tag, abi) per ABI out
```

So to build for ABI 6.2 you must already know which release carried it. The
table that answers exactly that -- `[mpy-abi]`, tag → ABI -- ships in
`resources/natmod.toml` and is readable only in the direction that does not
help. `mpy-abi` exists as a config key today and is an *override*: it forces the
ABI attributed to tags you named. The axis being the ABI means the input should
be the ABI:

```toml
mpy-abi = ["6.3", "6.2"]     # the axis, stated
micropython = "v1.29.0"      # optional: pin the checkout, not the compatibility
```

**usermod does not name the axis at all** -- and not only in the identifier. A
real run's own summary:

    unix-manylinux_2_28_aarch64   micropython-unix-manylinux_2_28_aarch64
    unix-musllinux_1_2_aarch64    micropython-unix-musllinux_1_2_aarch64

Identifier, output filename and output directory all omit it. Two runs against
different releases produce identically named files in identically named
directories, and the second silently replaces the first.

Which is why `micropython` is a `str` here while natmod's is a list, and why a
config naming two tags silently builds one. The truncation is not laziness; it
is the only thing standing between that config and silent data loss:

```python
micropython: str                                 # a single tag
identifier = f"{port}-{arch}"                    # no version component
identifier_dir = output_dir / target.identifier  # so two tags share one directory
```

Fix the identifier and the truncation stops being necessary. Add the list
without fixing the identifier and it becomes an overwrite.

## The second axis, and why `--archs` cannot be the primitive

The same rule decides this, so it belongs here rather than beside it.

cibuildwheel has one shape, `{python_tag}-{platform_tag}`, with one architecture
axis -- which is what lets `CIBW_ARCHS` be a flat list. usermod's second axis
has **three** shapes:

| port | axis | identifier |
| --- | --- | --- |
| `unix`, `windows` | `archs` | `unix-manylinux_2_28_x86_64` |
| `qemu`, `esp32` | `boards` | `esp32-ESP32_GENERIC` |
| `webassembly` | none | `webassembly` |

A flat `--archs` cannot address that, and the evidence is the implementation
[0049] landed: the flag had to be split, explicit names reaching only
`archs`-keyed ports and keywords reaching all of them. That split is a
workaround wearing the shape of a feature.

What generalises is the rule itself. The identifier already encodes port and
axis value for all three shapes, so `build`/`skip`/`--only` work uniformly over
them today -- `--only esp32-ESP32_GENERIC` and `skip = "windows-*"` both do the
right thing. The one question a glob cannot express is *"what does this runner
build without emulation"*, which is not about architectures at all: it is
whether an **image's** platform is native here, which is how [0049] implemented
it (`platform_for()`, per cell for `unix`, per port for the rest). Only the name
came from upstream, where the semantics were narrower.

## What upstream's selector actually is, read rather than recalled

`cibuildwheel==4.2.0`, installed and read. This matters because every divergence
this project has paid for came from paraphrasing upstream from memory: [0045]
found `--only` documented in-code as matching upstream semantics when it did
not, and [0049] deleted a `default_runner` concept upstream never had.

**It is one module, `selector.py`, 135 lines, at the package root** -- imported
by `__main__.py`, `options.py`, and every platform module (`linux.py`,
`pyodide.py`, …). One selector for every platform, constructed once in options
and carried through. cibuildmp has `select()` written twice, in
`natmod/targets.py` and `usermod/targets.py`, with the second's docstring
admitting the duplication is deliberate. That is the wrong shape and it is the
reason the two modes drifted into reading `build`/`skip` from opposite tables
([0048]).

Four things it has that cibuildmp does not:

**`EnableGroup` — opt-in is a first-class concept, not an absence.** An
identifier exists in the matrix *always*; groups (`pypy`, `graalpy`,
prereleases, EoL) are filtered out unless enabled, and that filter runs **before
`build`/`skip` and outranks them**:

```python
if EnableGroup.PyPy not in self.enable and is_pypy:
    return False
should_build = selector_matches(self.build_config, build_id)
```

So `build = "*"` never sweeps in PyPy by accident, while `enable = ["pypy"]`
plus `build = "*"` does. **cibuildmp expresses opt-in by keeping cells out of
the default axis** (`_UNIX_DEFAULT_TARGETS`), which is weaker and different: the
cell is unreachable by any glob at all, only by `--only` or by being named in
`archs`. It also conflates two things that are not the same -- "not proven yet"
and "not wanted by default". Every "opt-in cell" the tracker has talked about
for weeks -- the musllinux column before it was proven, the six
emulated-everywhere cells, a MicroPython prerelease tag -- is an `EnableGroup`
in upstream's model and nothing at all in ours.

**`requires_python` — the project declares what it supports, and the matrix
narrows itself.** Upstream reads `requires-python` from the project's own
metadata and drops identifiers outside it before any glob runs. That is the
version behaving as a *constraint on the matrix* rather than as a list the user
must curate, and it is exactly the shape the ABI axis wants: a project says
which MicroPython or which `.mpy` ABI it supports, once, and identifiers outside
that stop existing for it.

**`selector_matches` expands braces.** `cp{36,37}-*` via `bracex`, on
whitespace-separated patterns. cibuildmp uses bare `fnmatch`, so braces are
literal characters that match nothing.

**`--only` clears everything, including groups.** Upstream sets `build_config`,
empties `skip_config`, selects all architectures *and* turns on every enable
group. [0045] implemented the first three; the fourth does not exist here
because groups do not.

## `--platform` is one level too high, and that is what makes the second axis look heterogeneous

The deepest of these, and it dissolves the previous section rather than adding
to it.

`--platform` today means the *build mode*: `natmod` or `usermod`. Upstream's
means the thing being built for -- and every value has its own module:

    cibuildwheel/platforms/   android  ios  linux  macos  pyodide  windows

cibuildmp has six build functions with six option shapes -- `build_unix`,
`build_windows`, `build_qemu`, `build_webassembly`, `build_esp32`, and natmod's
own `build_target` -- and hides all six behind two `--platform` values. **The
ports are the platforms.** `natmod` is one too: one build function, one arch
axis, one artifact kind.

What that buys is not tidiness. Look at the axes once the level is right:

| platform | axis |
| --- | --- |
| `natmod` | `archs` |
| `unix`, `windows` | `archs` |
| `qemu`, `esp32` | `boards` |
| `webassembly` | none |

**Every platform has exactly one axis.** The "second axis has three shapes"
problem above exists *only* because `usermod` bundles five platforms and
pretends they share one, which is also why a flat `--archs` had to be split in
two to work at all. Upstream never faces it because `CIBW_ARCHS` always applies
to the one platform being built. Move `--platform` down a level and the
heterogeneity is not solved, it stops existing.

`natmod`/`usermod` remain a real distinction -- different artifacts (`.mpy`
versus a port binary), different packaging ([0014]'s mip package versus a raw
file) -- but as an internal grouping, not a user-facing axis. Upstream's
`linux.py` and `pyodide.py` differ at least that much and are both platforms.

### And the config tree falls out of it

Upstream's own check, one line:

```python
allowed_option_names = self.default_options.keys() | PLATFORMS | {"overrides"}
```

The top level takes global options, **platform names**, and `overrides`. With
the port as the platform that is exactly what cibuildmp's config becomes:

```toml
micropython = "v1.29.0"      # global
build = "*"

[unix]                       # per-platform, as [tool.cibuildwheel.linux] is
archs = ["auto"]

[esp32]
boards = ["ESP32_GENERIC"]
```

against today's `[usermod.unix]`, which carries a level naming a mode rather
than a platform.

Per-axis-value options are then a real fork worth deciding rather than
inheriting. Nested tables (`[esp32.ESP32_GENERIC]`) read well for a small fixed
set; upstream deliberately chose `[[overrides]]` with a `select` glob instead,
because a glob expresses what a table cannot -- `select = "*-unix-musllinux_1_2_{i686,armv7l}"`,
"all 32-bit", "everything except". natmod already has `[[overrides]]`; usermod
has none.

**`variant` surfaces here too.** `unix` and `webassembly` carry a `variant`
field (`standard`, `pyscript`) that is an option today, not an axis, and is
absent from the identifier. Under this record's own rule that is the same defect
as the missing version: two variants would collide on one identifier and one
output path. Either it is an axis and belongs in the name, or it is genuinely
one-per-build and belongs in an override.

## Shape

1. **natmod:** `mpy-abi` becomes a selector -- a list of ABIs, each resolved to
   the newest tag carrying it by reading `[mpy-abi]` backwards. `micropython`
   stays, demoted to "pin this checkout".
2. **usermod:** `micropython` becomes a list; `UsermodTarget` gains a `tag`;
   `usermod_targets()` takes the product of (tag, port, axis value).
3. **The identifier carries it, always** -- `v1.29.0-unix-manylinux_2_28_x86_64`,
   `v1.29.0-webassembly` -- leading, matching natmod's `mpy6.3-` position so both
   modes read the same left to right. **The output filename and directory follow
   it**, which is the half that stops one release overwriting another.
4. **`--archs` loses its usermod meaning.** Identifier globs are the primitive;
   host-nativeness gets its own keyword under a name that is not "archs".
5. **One `cibuildmp/selector.py` for the mechanism, per-mode tables for the
   data.** The split is not "one module or two" -- it is *what belongs in a
   selector at all*.

   Upstream hardcodes its group predicates inside the shared
   `BuildSelector.__call__` (`fnmatch(build_id, "cp316*")`, `pp3?-*`, `gp*`),
   which is fine for one product with a fixed set of Python implementations and
   is exactly wrong here: a module holding both natmod's `mpy6.*` groups and
   usermod's `unix-*`/`esp32-*` ones would know about both modes, and that is
   the coupling to avoid.

   So `selector_matches` (fnmatch + brace expansion) and `BuildSelector`
   (build/skip, groups, compatibility constraint) are shared and **take their
   groups as data**; which groups exist, the patterns defining them, and what
   the constraint means -- ABI for natmod, release for usermod -- come from
   each mode. Upstream itself parameterises where the thing is data
   (`Architecture.all_archs(platform)` takes the platform and stays one module)
   and hardcodes only where it has one product; cibuildmp needs the former in
   both places.

   This is the split the repo already uses everywhere else: mechanism in code,
   tables in `resources/` ([0010]). Groups are tables. `dockerrun.py` moved to
   the package root in [0050] on the same reasoning -- it stopped belonging to
   one mode the moment both used it. The two `select()` copies go.
6. **`--platform` becomes the port**, `natmod` alongside `unix`/`windows`/
   `qemu`/`webassembly`/`esp32`, each with its own module under a `platforms/`
   tree. `natmod`/`usermod` survive as an internal grouping, not as an axis.
   The config's top level then takes platform names directly (`[unix]`, not
   `[usermod.unix]`), matching upstream's own
   `default_options | PLATFORMS | {"overrides"}`.
7. **Decide per-axis-value config explicitly**: nested tables or
   `[[overrides]]` + `select`. Upstream chose the second for expressiveness;
   usermod has neither today.
8. **Opt-in cells become groups rather than omissions.** The six
   emulated-everywhere `unix` cells stop being absent from the default axis and
   become a group that `build = "*"` does not reach and `enable` does. That
   answers [0044]'s standing descope question by making it a user's choice
   instead of a maintainer's, which is what it should have been.

Not conditional on how many tags are selected. Adding the version only when more
than one is chosen looks conservative -- existing identifiers stay
byte-identical, the way [0015]'s `+0x..` arch-flags suffix does -- and is wrong
for a reason that does not apply there: `arch-flags` genuinely does not exist for
most targets, while a MicroPython version always does. A conditional component
makes `build = "*-v1.29.0"` work in some configs and match nothing in others,
which is worse than not having it. cibuildwheel puts the version in
unconditionally, and that is what makes `CIBW_BUILD` mean anything.

## What it costs

**Every usermod identifier changes**, which is [0038]'s three consuming repos
again, for the second time this session -- [0044] renamed every `unix` one
already. That argues for doing this *before* telling those repos to migrate
rather than after: one migration instead of two, the same reasoning [0038]'s own
tracker row gives for holding off.

Nothing else does. `--only` already resolves against the full matrix ([0045]),
`select()` already globs identifiers, and per-identifier output directories
already exist -- the collision that forced the truncation disappears the moment
the identifier distinguishes the builds.

## Meanwhile

The truncation should not be silent. A config naming two tags and getting one
build, with nothing said, is [0048]'s class exactly -- the config states one
thing and the tool does another -- and one line on stderr costs nothing while
this waits.

[0005]: 0005-one-identifier-namespace.md
[0013]: 0013-micropython-list-dedup-by-abi.md
[0015]: 0015-rv32imc-arch-flags-identifier.md
[0023]: 0023-usermod-identifier-scheme-config-output.md
[0038]: 0038-m5-adopt-in-three-repos.md
[0044]: 0044-unix-native-images-landed.md
[0045]: 0045-only-is-a-filter-not-a-forced-identifier.md
[0048]: 0048-build-skip-live-in-opposite-tables.md
[0049]: 0049-no-matrix-generation-archs-vocabulary.md

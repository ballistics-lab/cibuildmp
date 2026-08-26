# 0051 — the identifier must name what a build is compatible with; neither mode does it right

Status: Accepted (design; not implemented)

Rewritten the same day it was written, before anything was built on it: the
first draft framed this as "usermod cannot build two MicroPython versions",
which is a symptom. The defect is one thing in two places, and stating it as
two problems hid that.

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

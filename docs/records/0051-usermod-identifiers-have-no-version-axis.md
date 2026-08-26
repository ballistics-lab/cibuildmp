# 0051 — usermod identifiers carry no MicroPython version, so it cannot build two and cannot select over one

Status: Accepted (design; not implemented)

## The symptom, and why it is not the problem

`micropython` accepts a list of tags. natmod builds every distinct ABI in it.
usermod takes the first and silently ignores the rest:

```toml
micropython = ["v1.29.0", "v1.22.0"]
```

    natmod   2 target(s): mpy6.3-natmod-x64, mpy6.2-natmod-x64
    usermod  1 target(s): webassembly

Three things make that inevitable rather than merely unimplemented:

```python
micropython: str                                 # a single tag, not a list
identifier = f"{port}-{arch}"                    # no version component
identifier_dir = output_dir / target.identifier  # so two tags share one directory
```

Even if the field held a list, two tags would produce **the same identifier and
the same output path**, and the second build would overwrite the first. The
truncation is not a decision about lists; it is what keeps a broken thing from
being reachable.

## The actual problem: a missing axis, not a missing feature

The user's framing, and it is the right one: **this should be a build selector,
the way cibuildwheel has one.**

Upstream's identifier is the complete description of one build --
`cp313-manylinux_x86_64` -- and the interpreter version is *always* in it. That
is exactly what makes `CIBW_BUILD="cp313-*"` mean something. Every axis that can
vary is in the identifier, and therefore selectable by `build`/`skip`/`--only`.

cibuildmp already does this for natmod: `mpy6.3-natmod-x64` carries the ABI, and
`build = "mpy6.3-*"` filters on it ([0005], [0013]). usermod does not carry
anything version-shaped at all, so:

- two versions cannot be built (they collide),
- one version cannot be *selected* (there is nothing to glob against),
- and a config naming two is silently one.

The inability to build two is a symptom. The missing axis is the defect.

**This also retires an idea worth naming so it is not tried again**: adding the
version to the identifier only when more than one tag is selected. It looks
conservative -- existing single-tag identifiers stay byte-identical, the way
[0015]'s `+0x..` arch-flags suffix does -- and it is wrong here for a reason
that does not apply there. `arch-flags` genuinely does not exist for most
targets; a MicroPython version always does. A conditional component makes
`build = "*-v1.29.0"` work in some configs and match nothing in others, which
is worse than not having it.

## Version or ABI?

natmod's identifier carries the **ABI** (`mpy6.3-`) rather than the release tag,
deliberately: a native `.mpy` loads into any runtime with a matching ABI, and
ABI 6.3 alone spans v1.23.0 through v1.29.0. Naming the release would claim far
narrower compatibility than the artifact has ([0013], and `natmod.toml`'s
`[mpy-abi]` comment).

usermod is the opposite case and takes the **release tag**. Its artifact is a
port binary -- a `micropython` executable, a `.exe`, a firmware image -- built
from one release's source tree. It is not portable across releases in any sense,
so the exact tag is the honest component, and the same reasoning that keeps the
tag out of natmod's identifier puts it into usermod's.

## Shape

1. `UsermodOptions.micropython` becomes a list, as natmod's already is.
2. `UsermodTarget` gains a `tag` field; `usermod_targets()` takes the product of
   (tag, port, axis value).
3. The identifier carries the tag, always: `v1.29.0-unix-manylinux_2_28_x86_64`,
   `v1.29.0-webassembly`. Leading, matching natmod's `mpy6.3-` position, so both
   modes read the same way left to right.
4. `build`/`skip`/`--only` then work over it with no further change -- they glob
   identifiers, and `all_usermod_targets()` is already the full-matrix source
   [0045] made `--only` resolve against.

## What it costs

**Every usermod identifier changes**, which is [0038]'s three consuming repos
again. That is a real cost and it is the second time this session --
[0044] renamed every `unix` identifier already. It argues for doing this
*before* telling those repos to migrate, not after: one migration instead of
two, which is the same reasoning [0038]'s own row in the tracker gives for
holding off.

Nothing else does. `--only` already resolves against the full matrix, `select()`
already globs identifiers, and per-identifier output directories already exist
-- the collision that forced the truncation disappears the moment the identifier
distinguishes the builds.

## Meanwhile

The truncation should not be silent. A config naming two tags and getting one
build, with nothing said, is the same class as [0048] -- the config states one
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

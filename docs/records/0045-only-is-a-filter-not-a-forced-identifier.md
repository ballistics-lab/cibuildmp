# 0045 — `--only` is a filter, not a forced identifier: selector parity with cibuildwheel

Status: Implemented (the `--only` half; the `--archs`/`auto` half is design only)

`cibuildmp`'s selector surface was shaped after cibuildwheel's and is close
enough that the remaining differences read as accidents rather than decisions.
This record separates the two: which divergences are *reasoned* and should stay,
and which are gaps to close. One of them is currently documented in-code as
already matching upstream, and does not.

## What triggered it

Verifying [0044]'s musllinux column. The obvious command:

```console
$ cibuildmp examples/template --only unix-musllinux_1_2_x86_64
cibuildmp: error: --only 'unix-musllinux_1_2_x86_64' matches no usermod target
this config can produce
```

The target exists, its image is published and pinned, and the build works — it
is simply not in that config's axis, because [0044] deliberately kept the
`unix` default to the five previously-defaulted cells rather than all fifteen.
Reaching any of the other ten meant editing a `cibuildmp.toml` to build a cell
once. That is backwards for the flag whose entire purpose is "build exactly this
one thing".

## What cibuildwheel actually does

Read from `main`, not recalled — `cibuildwheel/__main__.py`:

```python
parser.add_argument(
    "--only",
    default=None,
    choices=[v["identifier"] for vv in read_all_configs().values() for v in vv],
    metavar="IDENTIFIER",
    help="""
        Force a single wheel build when given an identifier. Overrides
        CIBW_BUILD/CIBW_SKIP. --platform and --arch cannot be specified
        if this is given.
    """,
)
```

Three properties, each of which cibuildmp lacks:

1. **`choices` is every identifier that exists**, from `read_all_configs()` —
   not the ones this project's config selects. "Matches nothing this config can
   produce" is not a failure mode that exists upstream, because the config is
   not consulted.
2. **Platform and architecture are *derived from* the identifier**, never checked
   against it. `_compute_platform_only()` reads the platform out of the string,
   and passing `--platform` or `--arch` alongside `--only` is a hard
   `ConfigurationError` ("it is computed from `--only`").
3. **It overrides `CIBW_BUILD`/`CIBW_SKIP`**, stated in the help text.

The surrounding vocabulary matters too. `Architecture.parse_config()`
(`architecture.py`) accepts the literal words `auto`, `native`, `all`, `auto64`
and `auto32` alongside explicit names — so "build what this machine can run
natively" and "build everything" are things a user can *say*, not just
enumerate.

## What cibuildmp does

Verified against the running code, both paths (`natmod/cli.py`,
`usermod/cli.py`), which are deliberate copies of each other:

```python
targets = options.targets()
...
if args.only is not None:
    targets = [t for t in targets if t.identifier == args.only]
```

`options.targets()` is `select(all_targets, self.build, self.skip)` — the
config's own axis, already narrowed by `build`/`skip`. `--only` then filters
*that*. So:

- the candidate set is what the config selected, not what exists;
- `build`/`skip` have already been applied by the time `--only` is reached, so
  it cannot override them;
- nothing is derived from the identifier.

**And the code says otherwise.** `natmod/cli.py` carries this comment above
that filter, with `usermod/cli.py` pointing at it as its own justification:

> `--only` overrides build/skip, matching cibuildwheel's own semantics for the
> flag

It does not override build/skip. A target removed by `skip` is gone before
`--only` sees the list. There *was* a test named `test_only_overrides_skip`,
and it passed — against code that could not do it: the config it built put
`skip` inside `[natmod]`, where natmod never reads it, so the selector was
never applied and the assertion proved nothing. That placement asymmetry is its
own bug ([0048]); the test is rewritten and now fails without this record's
change. A divergence
documented as parity is worse than an open one, because it stops anyone
looking — which is why this record exists rather than a one-line fix.

## Which divergences are reasoned, and stay

Not everything here should converge, and two things should explicitly not:

- **`--platform` means something else.** Upstream it selects the OS
  (`linux`/`macos`/`windows`); here it selects the *mode*
  (`natmod`/`usermod`), with `CIBMP_PLATFORM` as its env form. Upstream's rule
  "`--platform` cannot be given with `--only`, it is computed" does not transfer
  as written — but the *idea* does, and it is worth taking: a mode is
  recoverable from an identifier (`unix-…` is usermod, `mpy6.3-natmod-…` is
  natmod), so `--only` could remove the need for `--platform` in exactly the
  cases where `detect_mode()` currently gives up and asks.
- **natmod's `--archs` has no `auto`, on purpose.** Its own help says why:
  "every natmod arch is a cross-compile, so none of them depends on what this
  machine is." That is correct and should not grow an `auto` for symmetry's
  sake. `all` it already accepts.

## What parity would mean, concretely

1. **`--only` resolves against the full matrix.** For `unix` that list already
   exists and is already derived from data rather than config:
   `dockerrun.unix_targets()` returns all fifteen cells regardless of what the
   config selects — cibuildmp's own `read_all_configs()`. The other ports'
   full axes come from `targets.py`'s `_PORT_AXES`. So this is a change of
   *which* list is filtered, not new machinery.
2. **`--only` bypasses `build`/`skip` and the configured axis**, as its help
   already claims. Concretely: build the candidate list from the full matrix,
   apply `--only`, and skip `select()` entirely for that invocation.
3. **The error message names what exists.** "matches no target this config can
   produce" should become "is not a known identifier — known: …", since after
   (1) the config is no longer the reason a name fails.
4. **usermod gains an `--archs` equivalent, with the `auto`/`all`/`native`
   vocabulary.** It has none today: the axis is config-only plus a generic env
   override, so "build everything" and "build what runs natively here" cannot be
   expressed at all. This is where [0043]'s own unmeasured question lands —
   whether native-only is the honest default — and the vocabulary has to exist
   before that question can even be answered by a flag.

## The one thing to be careful about

`native`/`auto` make a *selection* depend on the host, and [0043] is emphatic
that host architecture appears nowhere. Those are not in conflict, but the
distinction has to be argued rather than assumed: 0043 forbids host arch in
**identifiers, image names and pin keys** — facts that must mean the same thing
everywhere — while cibuildwheel's `auto_archs()` uses it for **which subset to
build here**, which is a local choice and is re-decided on every machine.
`targets.py` also holds itself to "nothing here touches the filesystem or
network" so that `--print-build-identifiers` stays pure; `platform.machine()`
does not break that rule, but a host-dependent identifier *list* would surprise
anyone generating a CI matrix on one runner to consume on another. If `auto`
lands, `--print-build-identifiers` should almost certainly keep expanding to the
full configured set rather than to the host's subset.

## What landed

Points 1-3 above, both modes, verified live rather than only unit-tested:

| invocation | before | now |
| --- | --- | --- |
| `--only unix-musllinux_1_2_s390x` (opt-in cell) | "matches no usermod target this config can produce" | builds it |
| `--only qemu` from a `ports = ["unix"]` config | same error | builds it |
| `--only mpy6.3-natmod-xtensawin` with `archs = ["x64"]` | "matches no target" | builds it |
| `--only mpy6.3-natmod-x64` with `skip = "mpy6.3-natmod-x64"` | silently nothing | builds it |
| `--only mpy6.3-natmod-sparc` | "matches no target this config can produce" | "is not a known identifier. Known: …" |

The mechanism is `all_usermod_targets()` / `Options.all_targets()` -- the full
matrix, independent of config -- with `--only` resolved against that instead of
against `options.targets()`. `unix`'s own full axis comes from
`dockerrun.unix_targets()`, which already reads the pin table's
`[image.<arch>]` keys, so no second copy of the matrix was created.

The two natmod-specific carve-outs are argued in `Options.all_targets()`'s own
docstring rather than left implicit: `tag_groups()` and `arch_flags` stay,
because an ABI slot comes from a real MicroPython checkout and an
`arch-flags` list is a statement about which identifiers *exist*, not a filter
over a fixed set. `archs`, `build` and `skip` are selection and are bypassed.

Four new cases cover the behaviours that had none before -- reaching an opt-in
cell, reaching an unlisted port, overriding `archs`, overriding `skip` -- plus
the reworded error. The two existing tests that encoded the old semantics were
rewritten rather than deleted, and say so.

## Still open

The `--archs`/`auto` half (point 4). It is a real design question that [0043]
already parked, and this record only gives it a place to live; the caution
above about `native` and `--print-build-identifiers` applies to whoever takes
it. Also unchecked: whether `--print-build-matrix`'s own `{only, os}` objects
need a different shape now that `--only` no longer depends on the config.

[0043]: 0043-unix-adopts-cibuildwheel-native-image-model.md
[0044]: 0044-unix-native-images-landed.md
[0048]: 0048-build-skip-live-in-opposite-tables.md

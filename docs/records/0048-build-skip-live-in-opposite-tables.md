# 0048 — `build`/`skip` live in opposite tables in the two modes, and a misplaced one is silent

Status: Accepted (bug; not fixed here)

Found while implementing [0045], and specifically *because* of it: a test named
`test_only_overrides_skip` was passing against code that could not override
`skip`. It was passing for a reason that turned out to be a bug of its own.

## The behaviour

Verified live, four runs against a real config:

| where `skip` is written | natmod | usermod |
| --- | --- | --- |
| top level, above `[natmod]`/`[usermod]` | **applied** | **silently ignored** |
| inside the mode's own table | **silently ignored** | **applied** |

The same key means the same thing in both modes and is read from opposite
places, and putting it in the other one produces no error, no warning, and no
diagnostic of any kind — just a target you asked to skip getting built.

## Why

`natmod/options.py`'s `Options.load()` resolves global keys through a local
`opt()` that reads the **top-level** table:

```python
def opt(key, default=None):
    env_value = environ.get("CIBMP_" + key.replace("-", "_").upper())
    if env_value is not None:
        return env_value
    return raw.get(key, default)
...
build=parse_selector(opt("build", "*")),
skip=parse_selector(opt("skip", "")),
```

`usermod/options.py` reads the **mode table**:

```python
build=parse_selector(usermod.get("build", "*")),
skip=parse_selector(usermod.get("skip", "")),
```

Neither is unreasonable alone. Together they are a trap, and one line above the
natmod pair makes it worse:

```python
archs_value = opt("archs") or natmod.get("archs") or list(NATMOD_ARCHS)
```

`archs` accepts **both** placements. So a natmod user who writes
`[natmod] archs = [...]` — which works — has every reason to expect
`[natmod] skip = "..."` next to it to work too. It does not.

## What it cost already

`tests/test_cli.py::test_only_overrides_skip` built its config as
`CONFIG + '\nskip = "*-armv6m"\n'`, where `CONFIG` ends inside `[natmod]`. The
skip therefore landed in the mode table, was never read, and the test asserted
that `--only` overrode a selector that was never applied. It passed for years
of commits while testing nothing, and it was the *only* coverage of that
interaction — which is how [0045] came to describe the override as missing while
a green test claimed it worked. Both are now written with the selector where it
is actually read, and say so.

That is the real damage here: not a user hitting it, but a test that looked like
coverage and was not.

## What to do

Not fixed in this record, because "which placement is correct" is a decision
rather than a repair:

- **Accept both, everywhere.** Cheapest, matches what `archs` already does for
  natmod, breaks nothing. Also entrenches an ambiguity.
- **Pick one and diagnose the other.** cibuildwheel has no equivalent question
  — it is single-mode, so `build`/`skip` are simply top level (`CIBW_BUILD` /
  `CIBW_SKIP`, [tool.cibuildwheel]). By that argument top level wins, since
  `micropython`, `output-dir` and `build`/`skip` are all invocation-wide rather
  than mode-specific. usermod would then need a deprecation path, since its
  current placement is the working one for every existing usermod config.
- **Whichever is chosen, the wrong placement must not be silent.** An unknown
  key inside `[natmod]`/`[usermod]` is cheap to detect and is the part that
  turns a typo into a wrong build.

Worth checking at the same time: which *other* keys have this split. `archs` is
already known to be dual-read for natmod; nothing has audited the rest.

[0045]: 0045-only-is-a-filter-not-a-forced-identifier.md

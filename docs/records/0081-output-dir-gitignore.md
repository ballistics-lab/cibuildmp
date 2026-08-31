# 0081. `output-dir` gets its own `.gitignore` the first time cibuildmp writes into it

- Status: Implemented
- Related: [0014]

## The gap

`output-dir` (`mpyhouse` by default) is build output — every identifier's
`.mpy`/binary plus, once `version` is set, its `package.json` ([0014]). A
project adopting cibuildmp had to remember to add a matching entry to its
own top-level `.gitignore` by hand; nothing about cibuildmp itself hinted
that this directory is disposable, and a fresh checkout would happily `git
add` a whole build tree the first time someone forgot.

## What shipped

Both `natmod/build.py`'s `build_target()` and `usermod/orchestrate.py`'s
`build_one()`, right before creating that target's own `identifier_dir`,
now write `output_dir/.gitignore` (one line, `*`) — but only if that file
does not already exist. Checked live against a real project (`a7p`): an
`output-dir` that already existed from earlier runs, with no `.gitignore`
of its own, gained one on the very next build.

Deliberately keyed on "does `.gitignore` already exist", not "did cibuildmp
just create `output-dir` this run" — the latter would need tracking
`output_dir.exists()` before the `mkdir(parents=True, exist_ok=True)` that
already happens, for no real benefit: a directory that already existed
without a `.gitignore` (this project's own history before this record, or
anyone who adopts cibuildmp against a pre-existing output path) equally
wants one, and the existence check already makes the write idempotent and
side-effect-free on every later build. Never overwrites one already there
either way, in case a caller wants something else in it (a real
`!keep-this` exception, say).

## Why the same few lines twice, not one shared function

natmod's `build.py` imports nothing from this project's own shared
top-level modules today; usermod's `orchestrate.py` already reaches into
`report`/`sources` for its own reasons. Neither `report.py` (scoped
specifically to the JSON build report) nor `sources.py` (scoped
specifically to provisioning MicroPython/mpy-cross) is the right home for
five lines of `.gitignore`-writing, and natmod stays the base every
platform module imports from, never the reverse (`natmod/options.py`'s own
`_USERMOD_OVERRIDE_OPTION_KEYS_MIRROR` comment makes the same call for the
same reason) — not enough here to justify a new shared module just to avoid
duplicating a five-line, single-purpose block once.

[0014]: 0014-mip-package-per-identifier.md

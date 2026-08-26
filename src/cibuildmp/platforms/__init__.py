"""The family registry -- how `cli.py` finds the code that implements a
given `--platform` name, without ever naming `natmod`/`usermod` itself.

Phase H of record 0051 (the "the ports are the platforms" redesign)
physically merged `natmod/` and `usermod/` under this package, mirroring
cibuildwheel's own `platforms/` tree. What is deliberately *not* mirrored
is cibuildwheel's literal one-module-per-platform-name shape: cibuildmp's
five usermod ports (`unix`/`windows`/`qemu`/`webassembly`/`esp32`) already
share one real implementation (`usermod/build.py`'s own `_BUILD_FN` data
table, `usermod/options.py`'s `SCHEMAS`, `usermod/targets.py`'s
`_PORT_AXES` -- keyed dicts, not five independently-authored pipelines),
so splitting them into five files would fight that structure for a shape
cibuildmp does not actually have. `natmod` is the sixth name and the only
one genuinely alone.

Two distinct modules cover six names today because two is how many
genuinely distinct implementations exist -- not six, and not one. This
registry is what lets `cli.py`'s own dispatch code stay ignorant of that
number: it groups whatever platforms are active by which module
implements them (`_group_by_family()`, in `cli.py`) and calls each module
exactly once, uniformly, whether one platform is active or five. Adding a
third family -- zephyr ([0022], deliberately not scheduled: a `west`+SDK
provisioning story and a `.conf`/`.overlay` board convention unlike any of
the current six), or any of upstream MicroPython's own ~20 real ports,
most of which are genuinely distinct platforms rather than variations of
the current six -- is one new module plus new entries here, zero changes
to `cli.py`'s own dispatch code. That is the actual requirement this
design exists to satisfy, corrected mid-design after an earlier
two-hardcoded-branch sketch did not generalize past today's exact two
implementations.
"""

from __future__ import annotations

from typing import Any, Protocol

from . import natmod, usermod
from .usermod.targets import KNOWN_PORTS


class PlatformModule(Protocol):
    """Documentation only, not enforced through isinstance/runtime checks
    -- the same PEP 544 module-as-Protocol shape cibuildwheel's own
    `platforms/__init__.py` uses. Every family module exposes exactly
    these three functions. `ports` is always the subset of that family's
    own platform names active this invocation -- for `natmod`, always and
    only `["natmod"]`, kept as a real parameter rather than a special case
    so `cli.py`'s own dispatch loop never has to know natmod is different.

    `validate_family_table()` is the third function, added when usermod
    gained a real family-level config tier (`[usermod]`, record 0051's
    ninth addendum -- shared defaults for every port in the family, sibling
    to `[natmod]`, not a selector). It exists specifically so `cli.py`
    never has to name `usermod` to call its own validation: every
    registered family gets called once, unconditionally, from
    `active_platforms()`'s own preamble, *before* it is known which
    platforms end up active this invocation -- a stale family table naming
    a port that no longer selects anything (the old `[usermod] ports =
    [...]`) must still be caught even when nothing else would ever load
    that family's own config far enough to see it (record 0048's own bug
    class: a misplaced/stale key silently doing nothing). `natmod`'s own
    implementation is a no-op -- its one platform already *is* its only
    family, so `[natmod]`'s own validation already happens inside
    `resolve_options()`, with nothing extra for a separate family tier to
    check. `error` is always the caller's `ConfigError` (natmod's own,
    the class every other `active_platforms()`-time failure already
    raises) -- not each family's native exception class, so `main()`'s
    existing `except ConfigError` catch does not need widening for a
    failure that happens before any family has been dispatched to.

    Exception handling is deliberately *not* part of this contract: each
    family module fully owns catching, printing and returning 2 for its
    own error hierarchy (`natmod.options.ConfigError` and friends vs.
    `usermod.options.UsermodConfigError` and friends -- nothing catches
    either polymorphically today, and unifying them would be a real,
    separate redesign with no caller driving it). One rule every family
    module's own `run()` must still uphold: a matched `[[overrides]]`
    entry's key is only validated against the specific platform a target
    resolves to once `build_options()` actually runs (Phase G's tier-2
    validation) -- so any dry-run/preview code path that calls
    `build_options()` per target needs its own `try/except` around that
    call, distinct from the outer `targets()`-level catch, or a config
    mistake that `targets()` could not have caught surfaces as a raw
    traceback instead of a clean CLI error. `natmod`'s own `run()` already
    has this; the next family module that grows a richer dry-run preview
    should not have to rediscover it by shipping the bug again.
    """

    def resolve_options(
        self, args: Any, package_dir: Any, config_file: Any, preread: Any, *, ports: list[str]
    ) -> Any: ...

    def run(
        self, args: Any, package_dir: Any, config_file: Any, preread: Any, *, ports: list[str]
    ) -> int: ...

    def validate_family_table(self, raw: dict, *, error: type[Exception]) -> None: ...


# Every name --platform accepts, mapped to the module that actually
# implements it. Built from KNOWN_PORTS rather than hand-listed a second
# time next to cli.py's own ALL_PLATFORMS -- two hand-maintained lists of
# the same six names is exactly the kind of drift record 0048's own bug
# class was about.
PLATFORM_FAMILY: dict[str, PlatformModule] = {
    "natmod": natmod,
    **{port: usermod for port in KNOWN_PORTS},
}

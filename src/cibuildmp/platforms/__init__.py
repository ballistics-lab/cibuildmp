"""The family registry -- how `cli.py`'s own coordinator finds the code
that implements each platform family, without ever branching on `natmod`/
`usermod` by name.

Phase H of record 0051 (the "the ports are the platforms" redesign)
physically merged `natmod/` and `usermod/` under this package, mirroring
cibuildwheel's own `platforms/` tree. What is deliberately *not* mirrored
is cibuildwheel's literal one-module-per-platform-name shape: cibuildmp's
six usermod ports (`unix`/`windows`/`qemu`/`webassembly`/`esp32`/`rp2`)
share one real dispatch (`usermod/orchestrate.py`'s own `_BUILD_FN` data
table, `usermod/targets.py`'s own `all_usermod_targets()`, reading every
port's own rows uniformly) over one `build_<port>.py` module per port
(`usermod/build_common.py` for what they share) -- keyed data, not
independently-authored pipelines with nothing in common. `natmod` is the
seventh name and the only one genuinely alone.

There is no more per-platform *activation* at all (record 0052's own
live-caught retraction, folded into the same round that removed `archs`/
`boards` axis config): every family is always in scope, on every
invocation -- `cli.py`'s own coordinator resolves both, unconditionally,
and each family's own `build`/`skip` glob-matching against its own real
identifiers is the only thing that decides what actually gets built. That
collapses what `FAMILIES` needs to be: a fixed, two-element tuple, not a
dict keyed by every platform name a `--platform` flag used to accept
(`--platform` does not exist any more either). Adding a third family --
zephyr ([0022], deliberately not scheduled), or any of upstream
MicroPython's own ~20 real ports, most of which are genuinely distinct
platforms rather than variations of the current six -- is one new module
plus one new tuple entry, zero changes to `cli.py`'s own coordinator.
"""

from __future__ import annotations

from typing import Any, Protocol

from . import natmod, usermod


class PlatformModule(Protocol):
    """Documentation only, not enforced through isinstance/runtime checks
    -- the same PEP 544 module-as-Protocol shape cibuildwheel's own
    `platforms/__init__.py` uses. Every family module exposes exactly
    these five names.

    `validate_family_table()` exists so `cli.py` never has to name
    `usermod` to call its own validation: every registered family gets
    called once, unconditionally, before any target resolution happens --
    a stale family table (the old `[usermod] ports = [...]`) must still
    be caught even on an invocation where this family's own `targets()`
    would otherwise select nothing and never load its own config far
    enough to see it (record 0048's own bug class: a misplaced/stale key
    silently doing nothing). `natmod`'s own implementation is a no-op --
    its one platform already *is* its only family, so there is no
    separate family-level table for a stale key to hide in. `error` is
    always the caller's `ConfigError` (natmod's own, the class every
    other startup-time failure already raises) -- not each family's
    native exception class, so `cli.py`'s own top-level `except
    ConfigError` does not need widening for a failure that happens before
    any family-specific resolution begins.

    `resolve_options()` loads config and applies this family's own
    CLI overrides (`--build`/`--skip`, `--output-dir` for natmod);
    `.targets()` on the result raises `LOAD_ERRORS` (a module-level
    tuple, not part of the Protocol itself -- exception handling is
    deliberately *not* unified, see below) if the config is broken in
    a way `resolve_options()` alone did not already catch.

    `run_resolved()` is given an already-resolved, already-nonempty
    target list -- `cli.py`'s own coordinator makes the joint "is
    *everything*, across every family, empty" decision once, since a
    per-family "no targets" check would misfire the instant a config only
    configures one family's own `build`/`skip` (the ordinary case) and
    leaves the other's naturally selecting nothing.

    Exception handling is deliberately *not* unified across families:
    each owns its own hierarchy (`natmod.options.ConfigError`/
    `UnknownArchError`/... vs. `usermod.options.UsermodConfigError`/...) --
    nothing catches either polymorphically, and unifying them would be a
    real, separate redesign with no caller driving it. `LOAD_ERRORS`/
    `BUILD_ERRORS` (module-level tuples, not part of this Protocol) are
    what let `cli.py`'s own coordinator catch each family's own errors
    without importing its exception classes by name. One rule every
    family module's own `run_resolved()` must still uphold: a matched
    `[override]` entry's key is only validated against the specific
    platform a target resolves to once `build_options()` actually runs
    (Phase G's tier-2 validation) -- so a `--dry-run` preview that calls
    `build_options()` per target needs its own `try/except` around that
    call, distinct from the outer `targets()`-level catch, or a config
    mistake that `targets()` could not have caught surfaces as a raw
    traceback instead of a clean CLI error. `natmod`'s own `run_resolved()`
    already has this; the next family module that grows a richer preview
    should not have to rediscover it by shipping the bug again.
    """

    def resolve_options(
        self, args: Any, package_dir: Any, config_file: Any, preread: Any
    ) -> Any: ...

    def run_resolved(self, args: Any, options: Any, targets: list[Any]) -> int: ...

    def validate_family_table(self, raw: dict, *, error: type[Exception]) -> None: ...


# The two family implementations, always both resolved -- there is no
# platform-name-keyed registry any more (nothing looks one up by name:
# `--platform`/`--only` do not exist, and every real identifier already
# carries which family it belongs to, via each Target's/UsermodTarget's
# own `.port`).
FAMILIES: tuple[PlatformModule, ...] = (natmod, usermod)

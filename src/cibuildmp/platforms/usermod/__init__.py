"""usermod: `unix`/`windows`/`qemu`/`webassembly`/`esp32`/`rp2` -- the six
usermod ports with a real `build_<port>()` driver, one module per port
(`usermod/build_<port>.py`, plus shared `build_common.py` -- see
docs/records/0061-usermod-build-drivers-split-per-port.md). See
docs/BACKLOG.md, "Later -- usermod".

Also usermod's own half of the CLI dispatch (Phase H, record 0051; the
`--platform`/`--only`/`--archs`/`--enable` retraction folded into this
same round). `cli.py`'s own coordinator always resolves this family
alongside natmod's, every invocation -- there is no more activation
concept (table presence, `--platform`) narrowing which ports are in
scope; `all_usermod_targets()` (`targets.py`) already enumerates every
real row every port has, and `build`/`skip` glob-matching the identifier
is the only thing left that decides what actually gets built. Driven by
`UsermodOptions`/`orchestrate.build()` instead of `options.Options`/
`build.build_target()`. Kept in its own module rather than inlined into
`cli.py` so that file does not grow a second, differently-shaped copy of
the same dispatch logic.

There is no `--toolchain` flag on either family any more: record 0050
deleted natmod's host toolchain resolver outright, and every build of
either family runs in a pulled image whose own contents are the toolchain.
This paragraph used to say the flag was "natmod-specific and stays that
way", which outlived the flag itself.

`--archs auto`/`native`/`all` (record 0049) and `--enable`/`GROUPS`
(record 0051 point 8) are both retracted, live, in the same session that
removed `archs`/`boards` axis config and table-presence activation: both
were host- or opt-in-convenience layers sitting on top of an axis concept
that no longer exists. Everything either one could reach, an ordinary
`build`/`skip` glob against the real identifier (or an
`[override."<glob>"]` entry) already reaches directly -- see the README
for the full identifier list and glob syntax.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ...sources import SourceError
from ...stepsummary import write_step_summary
from . import orchestrate
from .build_common import UsermodBuildError
from .options import USERMOD_TOP_LEVEL_KEYS, UsermodConfigError, UsermodOptions
from .targets import UsermodTarget

# This family's own half of the `PlatformModule` contract's `OPTION_KEYS`
# -- see `natmod/__init__.py`'s own identical declaration (record 0075).
OPTION_KEYS: frozenset[str] = USERMOD_TOP_LEVEL_KEYS

# Every exception UsermodOptions.load()/.targets() can raise -- what
# cli.py's own coordinator catches around "load config, resolve targets"
# for this family, uniformly with natmod's own equivalent tuple. Declared
# here, not re-derived at each call site, so the two stay in sync by
# construction rather than by convention.
LOAD_ERRORS: tuple[type[Exception], ...] = (UsermodConfigError,)

# Every exception a real build (or the per-target build_options()
# resolution a --dry-run preview also runs) can raise -- UsermodConfigError
# belongs here as much as the build-specific two: a matched [override]
# entry's own key is only checked against the matched identifier's own
# platform once a target actually resolves (Phase G's tier-2 validation),
# so an error LOAD_ERRORS's own targets() catch could not have caught is a
# real possibility on the very first target either path resolves.
BUILD_ERRORS: tuple[type[Exception], ...] = (
    SourceError,
    UsermodBuildError,
    UsermodConfigError,
)


def _plan_line(index: int, total: int, target: UsermodTarget) -> str:
    counter = f"[{index:>{len(str(total))}}/{total}]"
    return f"{counter} {target.identifier}"


def resolve_options(
    args: Any,
    package_dir: Path,
    config_file: Path | None,
    preread: tuple[Path | None, dict[str, Any]],
) -> UsermodOptions:
    """Load config and apply the CLI `--build`/`--skip` overrides every
    caller needs -- the same shape `natmod/__init__.py`'s own
    `resolve_options()` has."""
    options = UsermodOptions.load(package_dir, config_file, preread=preread)
    if args.build is not None:
        options.build = args.build.split()
    if args.skip is not None:
        options.skip = args.skip.split()
    return options


def run_resolved(
    args: Any, options: UsermodOptions, targets: list[UsermodTarget]
) -> int:
    """`--dry-run`/build for an already-resolved, already-nonempty target
    list -- the part of `run()` below that is genuinely usermod-specific.
    Loading, target resolution, `--print-build-identifiers` and the
    joint "no targets selected" decision all moved to `cli.py`'s own
    coordinator (Phase J), since none of those can be decided per family
    any more once every family is always in scope."""
    total = len(targets)
    if args.dry_run:
        print(f"cibuildmp: {total} usermod target(s)")
        for index, target in enumerate(targets, 1):
            print("  " + _plan_line(index, total, target))
        return 0

    print(f"cibuildmp: {total} usermod target(s)")
    try:
        results = orchestrate.build(options, targets, keep_going=args.keep_going)
    except BUILD_ERRORS as exc:
        if args.debug_traceback:
            raise
        print(f"cibuildmp: error: {exc}", file=sys.stderr)
        return 2

    total_duration = sum(r.duration for r in results)
    print(
        f"\ncibuildmp: {len(results)} usermod target(s) built in {total_duration:.1f}s"
    )
    for result in results:
        print(f"  {result.identifier}: {result.output.name} ({result.size} bytes)")
    write_step_summary(
        results,
        total_duration,
        build=options.build,
        skip=options.skip,
        overrides=options.overrides,
        override_error=UsermodConfigError,
    )
    # Only reachable with fewer results than targets when args.keep_going
    # let `orchestrate.build()` attempt every target instead of raising at
    # the first failure (BUILD_ERRORS above would have caught that
    # instead) -- see orchestrate.build()'s own keep_going docstring.
    failed = total - len(results)
    if failed:
        print(
            f"cibuildmp: {failed}/{total} target(s) failed -- see the report above",
            file=sys.stderr,
        )
        return 1
    return 0


def run(
    args: Any,
    package_dir: Path,
    config_file: Path | None,
    preread: tuple[Path | None, dict[str, Any]],
) -> int:
    """Full single-family flow: resolve, select targets,
    `--print-build-identifiers`/no-targets-selected/`run_resolved()`. Used
    directly by tests and any other caller that wants usermod alone
    without going through `cli.py`'s own coordinator, which instead calls
    `resolve_options()`/`run_resolved()` separately so it can merge this
    family's own targets with natmod's before making either of those two
    decisions."""
    try:
        options = resolve_options(args, package_dir, config_file, preread)
        targets = options.targets()
    except LOAD_ERRORS as exc:
        if args.debug_traceback:
            raise
        print(f"cibuildmp: error: {exc}", file=sys.stderr)
        return 2

    if args.print_build_identifiers:
        identifiers = [t.identifier for t in targets]
        if args.json:
            print(json.dumps(identifiers))
        else:
            for identifier in identifiers:
                print(identifier)
        return 0

    if not targets:
        if args.allow_empty:
            print("cibuildmp: no targets selected")
            return 0
        print(
            "cibuildmp: error: no targets selected. Pass --allow-empty if that "
            "is expected.",
            file=sys.stderr,
        )
        return 2

    return run_resolved(args, options, targets)

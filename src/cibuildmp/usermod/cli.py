"""usermod's own half of the CLI dispatch. `cli.py`'s `main()` calls
into `run()` once build mode is resolved to `"usermod"` (`cli.py`'s own
`detect_mode()`), mirroring the natmod flow --dry-run/--only/
--print-build-identifiers/--allow-empty/build --
but driven by `UsermodOptions`/`orchestrate.build()` instead of
`options.Options`/`build.build_target()`. Kept in its own module rather
than inlined into `cli.py` so that file does not grow a second,
differently-shaped copy of the same dispatch logic.

Not wired here, deliberately, same as `usermod/options.py`'s and
`usermod/orchestrate.py`'s own docstrings already flag:
- `--toolchain` is natmod-specific and stays that way: toolchain
  resolution always goes through whatever each `build_<port>()` already
  does internally, with no `auto`/`host`/`download` override.

`--archs` *was* on that list and no longer is (record 0049). It is how
work is spread across runners now that cibuildmp generates no matrix and
picks no host: `auto`/`native`/`all` beside explicit names, applied to
every selected port with an `archs` axis.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..natmod.sources import SourceError
from ..natmod.stepsummary import write_step_summary
from ..natmod.toolchains import ToolchainError
from . import orchestrate
from .build import UsermodBuildError
from .options import UsermodConfigError, UsermodOptions
from .targets import (
    UnknownAxisError,
    UnknownPortError,
    UsermodTarget,
    all_usermod_targets,
    axis_key,
)


def _plan_line(index: int, total: int, target: UsermodTarget) -> str:
    counter = f"[{index:>{len(str(total))}}/{total}]"
    return f"{counter} {target.identifier}"


def run(
    args: Any,
    package_dir: Path,
    config_file: Path | None,
    preread: tuple[Path | None, dict[str, Any]],
) -> int:
    try:
        options = UsermodOptions.load(package_dir, config_file, preread=preread)
        if args.archs is not None:
            # Applied to every selected port with an `archs` axis, which
            # is `unix` and `windows`. `qemu`/`esp32` are keyed by board
            # and `webassembly` has no axis, so there is nothing for an
            # arch list to mean there -- and the keywords are no-ops for
            # `windows` anyway, whose three arches all cross-compile from
            # one amd64 image (record 0049).
            values = [a.strip() for a in args.archs.split(",") if a.strip()]
            for port in options.ports:
                if axis_key(port) == "archs":
                    options.axis_overrides[port] = values
        targets = options.targets()
    # UsermodConfigError belongs here as much as the other two and was
    # simply never added: until record 0048 it had one raise site (a
    # `[usermod.<port>]` table for a port with no axis yet), so nobody
    # had hit it from the CLI and it surfaced as a raw traceback. It has
    # several raise sites now -- every misplaced or misspelt key -- and a
    # config mistake is the most ordinary error this tool has.
    except (UnknownPortError, UnknownAxisError, UsermodConfigError) as exc:
        if args.debug_traceback:
            raise
        print(f"cibuildmp: error: {exc}", file=sys.stderr)
        return 2

    if args.only is not None:
        # **0045**: resolved against every identifier that exists, not the
        # ones this config selects -- and bypassing `build`/`skip`
        # entirely, which is what this flag's own help has always claimed
        # and did not do. `options.targets()` above has already applied
        # them, so filtering *that* could never override anything.
        #
        # cibuildwheel's own shape: its `--only` takes `choices` from
        # `read_all_configs()` and its help says "Overrides
        # CIBW_BUILD/CIBW_SKIP". "Your config does not select that" is not
        # an answer the flag should be able to give.
        known = all_usermod_targets()
        targets = [t for t in known if t.identifier == args.only]
        if not targets:
            print(
                f"cibuildmp: error: --only {args.only!r} is not a known usermod "
                f"identifier. Known: "
                f"{', '.join(t.identifier for t in known)}",
                file=sys.stderr,
            )
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

    total = len(targets)
    if args.dry_run:
        print(
            f"cibuildmp: {total} usermod target(s) against MicroPython {options.micropython}"
        )
        for index, target in enumerate(targets, 1):
            print("  " + _plan_line(index, total, target))
        return 0

    print(
        f"cibuildmp: {total} usermod target(s) against MicroPython {options.micropython}"
    )
    try:
        results = orchestrate.build(options, targets)
    except (SourceError, ToolchainError, UsermodBuildError) as exc:
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
    write_step_summary(results, total_duration)
    return 0

"""usermod's own half of the CLI dispatch. `cli.py`'s `main()` calls
into `run()` once build mode is resolved to `"usermod"` (`cli.py`'s own
`detect_mode()`), mirroring the natmod flow --dry-run/--only/
--print-build-identifiers/--print-build-matrix/--allow-empty/build --
but driven by `UsermodOptions`/`orchestrate.build()` instead of
`options.Options`/`build.build_target()`. Kept in its own module rather
than inlined into `cli.py` so that file does not grow a second,
differently-shaped copy of the same dispatch logic.

Not wired here, deliberately, same as `usermod/options.py`'s and
`usermod/orchestrate.py`'s own docstrings already flag:
- `--archs`/`--toolchain` are natmod-specific and stay that way -- a
  usermod target's axis (arch/board) is config-only for now
  (`[usermod.<port>]`), and toolchain resolution always goes through
  whatever each `build_<port>()` already does internally (apt probe,
  `shutil.which()`, or a pinned download), no `auto`/`host`/`download`
  override yet.
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
from .options import UsermodOptions
from .targets import UnknownAxisError, UnknownPortError, UsermodTarget


def _plan_line(index: int, total: int, target: UsermodTarget) -> str:
    counter = f"[{index:>{len(str(total))}}/{total}]"
    return f"{counter} {target.identifier:<28} runs-on={target.default_runner}"


def run(
    args: Any,
    package_dir: Path,
    config_file: Path | None,
    preread: tuple[Path | None, dict[str, Any]],
) -> int:
    try:
        options = UsermodOptions.load(package_dir, config_file, preread=preread)
        targets = options.targets()
    except (UnknownPortError, UnknownAxisError) as exc:
        if args.debug_traceback:
            raise
        print(f"cibuildmp: error: {exc}", file=sys.stderr)
        return 2

    if args.only is not None:
        # Same --only semantics as natmod's own (cli.main()): the caller
        # already decided what this invocation is for.
        targets = [t for t in targets if t.identifier == args.only]
        if not targets:
            print(
                f"cibuildmp: error: --only {args.only!r} matches no usermod "
                f"target this config can produce",
                file=sys.stderr,
            )
            return 2

    if args.print_build_matrix:
        print(
            json.dumps(
                [{"only": t.identifier, "os": t.default_runner} for t in targets]
            )
        )
        return 0

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

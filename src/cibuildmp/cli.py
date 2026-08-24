"""Command line interface."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from . import __version__
from .build import BuildError, BuildResult, build_target
from .options import BuildOptions, ConfigError, Options
from .sources import (
    SourceError,
    build_mpy_cross,
    cache_root,
    fetch_micropython,
    read_mpy_abi,
)
from .targets import (
    LATEST_KNOWN_ABI,
    NATMOD_ARCHS,
    Target,
    UnknownArchError,
    is_abi_known,
)
from .toolchains import ResolvedToolchain, ToolchainError, resolve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cibuildmp",
        description="Build MicroPython native C extensions across every target "
        "a module supports, from one declarative config.",
        epilog="Most options are supplied via cibuildmp.toml or CIBMP_* environment "
        "variables. See docs/BACKLOG.md for the design and what is implemented.",
    )
    parser.add_argument(
        "package_dir",
        nargs="?",
        default=".",
        type=Path,
        help='Directory containing the module and its config (default: ".")',
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"cibuildmp {__version__}",
    )
    parser.add_argument(
        "--config-file",
        type=Path,
        default=None,
        help="Config file to use instead of <package_dir>/cibuildmp.toml",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Where to collect built .mpy files (overrides the config)",
    )
    parser.add_argument(
        "--only",
        default=None,
        metavar="IDENTIFIER",
        help="Build exactly this one identifier, overriding the config's own "
        "build/skip selectors. Opt into a job-per-target CI layout with this; "
        "the default is one invocation building every selected target.",
    )
    parser.add_argument(
        "--archs",
        default=None,
        help="Comma-separated list of architectures to build, or 'all'. Overrides "
        "the config's own archs. There is no 'auto': every natmod arch is a "
        "cross-compile, so none of them depends on what this machine is.",
    )
    parser.add_argument(
        "--toolchain",
        default="auto",
        choices=["auto", "host", "download"],
        help="How to obtain each target's cross toolchain. auto (default) uses "
        "one already on PATH and downloads a pinned tarball otherwise; host "
        "refuses to download; download ignores what is on PATH.",
    )
    parser.add_argument(
        "--clean-cache",
        action="store_true",
        help="Delete cibuildmp's cache (MicroPython checkouts, mpy-cross builds "
        "and downloaded toolchains) and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved build plan and exit without building",
    )
    parser.add_argument(
        "--print-build-identifiers",
        action="store_true",
        help="Print the identifiers this config selects, one per line, then exit",
    )
    parser.add_argument(
        "--print-build-matrix",
        action="store_true",
        help="Print a JSON array of {only, os} objects, then exit. Feed it to a "
        "GitHub Actions `strategy.matrix.include` via fromJSON() to get one job "
        "per target. Only worth it when targets need different runners.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="With --print-build-identifiers, emit a JSON array instead of lines",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Do not report an error code if no target is selected",
    )
    parser.add_argument(
        "--debug-traceback",
        action="store_true",
        default=os.environ.get("CIBMP_DEBUG_TRACEBACK", "") not in {"", "0"},
        help="Print a full traceback for all errors",
    )
    parser.add_argument(
        "--platform",
        default="natmod",
        choices=["natmod"],
        help="Build mode. Only natmod is implemented; usermod is planned "
        "(see docs/BACKLOG.md).",
    )
    return parser


def _plan_line(
    index: int,
    total: int,
    options: BuildOptions,
    chain: ResolvedToolchain | None = None,
) -> str:
    make = ["make", "-C", options.module_dir, f"ARCH={options.target.arch}"]
    make += options.extra_make_args
    make.append(options.make_target)
    # The prefix actually in play, which is not always the one dynruntime.mk
    # hardcodes -- showing target.cross here would contradict the CROSS=
    # override sitting in the same line's make command.
    prefix = chain.prefix if chain is not None else options.target.cross
    # Right-align the counter so the columns after it stay put once the
    # index gains a digit ([10/10] is wider than [9/10]).
    counter = f"[{index:>{len(str(total))}}/{total}]"
    return (
        f"{counter} {options.target.identifier:<28} "
        f"CROSS={prefix or '(host)':<22} {' '.join(make)}"
    )


def build(options: Options, targets: list[Target], *, toolchain: str = "auto") -> int:
    """Build every selected target in one invocation.

    Sequential and in-process on purpose (D9), the same shape cibuildwheel
    uses for the Python versions inside one runner. Fetching MicroPython and
    building mpy-cross are identical for every natmod arch *sharing an ABI*,
    so doing them once per ABI group here is strictly cheaper than paying
    for them in each of ten matrix legs -- and unlike cibuildwheel, no
    natmod target needs a runner any other target cannot use, so nothing
    forces a fan-out. Callers who want one anyway (failure isolation,
    wall-clock) opt in with --only.

    Grouped by MicroPython tag (**D13**): almost always one group, since
    that is the common case, but `tag_groups()` can hand back more than one
    when `micropython` spans an ABI boundary, and each needs its own
    checkout and its own mpy-cross.
    """
    resolved = [options.build_options(t) for t in targets]
    total = len(resolved)

    # Toolchains are resolved before the plan is printed, not after: where a
    # toolchain's prefix is not the one dynruntime.mk hardcodes, resolution
    # adds a CROSS= override, and a plan printed first would show a make
    # command that is not the one about to run.
    print(f"cibuildmp: resolving toolchains for {total} target(s)")
    chains = []
    for build_options in resolved:
        chain = resolve(build_options.target.arch, strategy=toolchain)
        chains.append(chain)
        build_options.extra_make_args = [
            *chain.make_overrides,
            *build_options.extra_make_args,
        ]

    tags = ", ".join(tag for tag, _abi in options.tag_groups())
    print(f"\ncibuildmp: {total} target(s) against MicroPython {tags}")
    for index, (build_options, chain) in enumerate(
        zip(resolved, chains, strict=True), 1
    ):
        print("  " + _plan_line(index, total, build_options, chain))
        print(f"        {chain.describe()}")

    seen_names: set[str] = set()
    results: list[BuildResult] = []
    index = 0
    # Preserves first-appearance order (options.targets() emits one ABI
    # group at a time), not sorted -- a later tag never jumps ahead of an
    # earlier one just because it sorts first.
    build_tags = list(dict.fromkeys(bo.target.tag for bo in resolved))
    for tag in build_tags:
        group = [
            (bo, chain)
            for bo, chain in zip(resolved, chains, strict=True)
            if bo.target.tag == tag
        ]
        abi = group[0][0].target.abi  # one ABI per tag group, by construction

        # Shared setup, paid once per ABI group rather than once per target
        # in it -- see build()'s own docstring and D9.
        print(f"\ncibuildmp: preparing MicroPython {tag}")
        mpy_dir = fetch_micropython(tag, submodules=options.micropython_submodules)
        build_mpy_cross(mpy_dir)

        # The checkout is authoritative about the ABI; targets.MPY_ABI's
        # table is only a way to answer the question without one. A
        # disagreement means the identifiers already printed are wrong, so
        # it stops here rather than producing files labelled with an ABI
        # they do not have.
        actual_abi = read_mpy_abi(mpy_dir)
        if actual_abi != abi:
            raise SourceError(
                f"MicroPython {tag} has .mpy ABI {actual_abi}, but the "
                f"identifiers were built assuming {abi}. Set `mpy-abi = "
                f'"{actual_abi}"` in the config, or report the stale entry in '
                f"cibuildmp.targets.MPY_ABI."
            )

        print(f"\ncibuildmp: building {len(group)} target(s) for MicroPython {tag}")
        for build_options, chain in group:
            index += 1
            print("\n  " + _plan_line(index, total, build_options, chain))
            module_root = options.package_dir / build_options.module_dir
            output_dir = options.package_dir / build_options.output_dir
            result = build_target(
                build_options,
                chain,
                mpy_dir,
                module_root,
                output_dir,
                seen_names,
            )
            results.append(result)
            print(f"        done in {result.duration:.1f}s -> {result.output}")

    total_duration = sum(r.duration for r in results)
    print(f"\ncibuildmp: {total} target(s) built in {total_duration:.1f}s")
    for result in results:
        print(f"  {result.identifier}: {result.output.name} ({result.size} bytes)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.clean_cache:
        root = cache_root()
        if not root.exists():
            print(f"cibuildmp: nothing to clean ({root} does not exist)")
            return 0
        shutil.rmtree(root)
        print(f"cibuildmp: removed {root}")
        return 0

    try:
        options = Options.load(args.package_dir, args.config_file)
        if args.output_dir is not None:
            options.output_dir = args.output_dir
        if args.archs is not None:
            options.archs = (
                list(NATMOD_ARCHS)
                if args.archs.strip() == "all"
                else [a.strip() for a in args.archs.split(",") if a.strip()]
            )
        targets = options.targets()
    except (ConfigError, UnknownArchError, SourceError) as exc:
        if args.debug_traceback:
            raise
        print(f"cibuildmp: error: {exc}", file=sys.stderr)
        return 2

    if args.only is not None:
        # --only overrides build/skip, matching cibuildwheel's own semantics
        # for the flag: the caller has already decided what this invocation
        # is for, and a matrix leg that reached here was selected when the
        # matrix was generated.
        targets = [t for t in targets if t.identifier == args.only]
        if not targets:
            print(
                f"cibuildmp: error: --only {args.only!r} matches no target this "
                f"config can produce",
                file=sys.stderr,
            )
            return 2

    if args.print_build_matrix:
        print(
            json.dumps(
                [
                    {"only": bo.target.identifier, "os": bo.runs_on}
                    for bo in (options.build_options(t) for t in targets)
                ]
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

    unknown_tags = [tag for tag in options.micropython if not is_abi_known(tag)]
    if unknown_tags:
        print(
            f"cibuildmp: warning: no recorded .mpy ABI for MicroPython "
            f"{', '.join(unknown_tags)}; assuming {LATEST_KNOWN_ABI}. The ABI "
            f"actually encoded in each built .mpy is verified against its "
            f"identifier, so a wrong guess fails the build rather than shipping.",
            file=sys.stderr,
        )

    if args.dry_run:
        total = len(targets)
        tags = ", ".join(tag for tag, _abi in options.tag_groups())
        print(f"cibuildmp: {total} target(s) against MicroPython {tags}")
        for index, target in enumerate(targets, 1):
            print("  " + _plan_line(index, total, options.build_options(target)))
        return 0

    try:
        return build(options, targets, toolchain=args.toolchain)
    except (SourceError, ToolchainError, BuildError) as exc:
        if args.debug_traceback:
            raise
        print(f"cibuildmp: error: {exc}", file=sys.stderr)
        return 2

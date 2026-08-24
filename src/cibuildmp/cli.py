"""Command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .options import BuildOptions, ConfigError, Options
from .sources import SourceError, build_mpy_cross, fetch_micropython, read_mpy_abi
from .targets import Target, UnknownArchError, is_abi_known


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cibuildmp",
        description="Build MicroPython native C extensions across every target "
        "a module supports, from one declarative config.",
    )
    parser.add_argument(
        "package_dir",
        nargs="?",
        default=".",
        type=Path,
        help='Directory containing the module and its config (default: ".")',
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
        "--platform",
        default="natmod",
        choices=["natmod"],
        help="Build mode. Only natmod is implemented; usermod is planned "
        "(see docs/BACKLOG.md).",
    )
    return parser


def _plan_line(index: int, total: int, options: BuildOptions) -> str:
    make = ["make", "-C", options.module_dir, f"ARCH={options.target.arch}"]
    make += options.extra_make_args
    make.append(options.make_target)
    # Right-align the counter so the columns after it stay put once the
    # index gains a digit ([10/10] is wider than [9/10]).
    counter = f"[{index:>{len(str(total))}}/{total}]"
    return (
        f"{counter} {options.target.identifier:<28} "
        f"CROSS={options.target.cross or '(host)':<22} {' '.join(make)}"
    )


def build(options: Options, targets: list[Target]) -> int:
    """Build every selected target in one invocation.

    Sequential and in-process on purpose (D9), the same shape cibuildwheel
    uses for the Python versions inside one runner. Fetching MicroPython and
    building mpy-cross are identical for every natmod arch, so doing them
    once here is strictly cheaper than paying for them in each of ten matrix
    legs -- and unlike cibuildwheel, no natmod target needs a runner any
    other target cannot use, so nothing forces a fan-out. Callers who want
    one anyway (failure isolation, wall-clock) opt in with --only.
    """
    resolved = [options.build_options(t) for t in targets]
    total = len(resolved)

    print(
        f"cibuildmp: {total} target(s) against MicroPython {options.micropython} "
        f"(.mpy ABI {options.abi})"
    )
    for index, build_options in enumerate(resolved, 1):
        print("  " + _plan_line(index, total, build_options))

    # Shared setup, paid once for the whole invocation rather than once per
    # matrix leg -- see build()'s own docstring and D9.
    print("\ncibuildmp: preparing MicroPython")
    mpy_dir = fetch_micropython(
        options.micropython, submodules=options.micropython_submodules
    )
    build_mpy_cross(mpy_dir)

    # The checkout is authoritative about the ABI; targets.MPY_ABI's table
    # is only a way to answer the question without one. A disagreement means
    # the identifiers already printed are wrong, so it stops here rather
    # than producing files labelled with an ABI they do not have.
    actual_abi = read_mpy_abi(mpy_dir)
    if actual_abi != options.abi:
        raise SourceError(
            f"MicroPython {options.micropython} has .mpy ABI {actual_abi}, but the "
            f"identifiers were built assuming {options.abi}. Set `mpy-abi = "
            f'"{actual_abi}"` in the config, or report the stale entry in '
            f"cibuildmp.targets.MPY_ABI."
        )

    # M2-M3 land here, inside the loop: resolve each target's toolchain, run
    # make, then collect and verify the output.
    sys.stdout.flush()  # keep the output above ahead of the stderr note below
    print(
        "\ncibuildmp: the per-target build is not implemented yet (M1 ships "
        "MicroPython and mpy-cross provisioning). Re-run with --dry-run to get "
        "the plan as a success.",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        options = Options.load(args.package_dir, args.config_file)
        if args.output_dir is not None:
            options.output_dir = args.output_dir
        targets = options.targets()
    except (ConfigError, UnknownArchError, SourceError) as exc:
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
        print("cibuildmp: error: no targets selected", file=sys.stderr)
        return 2

    if not is_abi_known(options.micropython):
        print(
            f"cibuildmp: warning: no recorded .mpy ABI for MicroPython "
            f"{options.micropython}; assuming {options.abi}. The ABI actually "
            f"encoded in each built .mpy is verified against its identifier, so "
            f"a wrong guess fails the build rather than shipping.",
            file=sys.stderr,
        )

    if args.dry_run:
        total = len(targets)
        print(
            f"cibuildmp: {total} target(s) against MicroPython "
            f"{options.micropython} (.mpy ABI {options.abi})"
        )
        for index, target in enumerate(targets, 1):
            print("  " + _plan_line(index, total, options.build_options(target)))
        return 0

    try:
        return build(options, targets)
    except SourceError as exc:
        print(f"cibuildmp: error: {exc}", file=sys.stderr)
        return 2

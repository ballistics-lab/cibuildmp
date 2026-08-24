"""Command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .options import ConfigError, Options
from .targets import UnknownArchError, is_abi_known


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
        help="Build exactly this one identifier, ignoring build/skip selectors",
    )
    parser.add_argument(
        "--print-build-identifiers",
        action="store_true",
        help="Print the identifiers this config selects, then exit. Use --json "
        "to feed a GitHub Actions matrix via fromJSON().",
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        options = Options.load(args.package_dir, args.config_file)
    except (ConfigError, UnknownArchError) as exc:
        print(f"cibuildmp: error: {exc}", file=sys.stderr)
        return 2

    if args.output_dir is not None:
        options.output_dir = args.output_dir

    try:
        targets = options.targets()
    except UnknownArchError as exc:
        print(f"cibuildmp: error: {exc}", file=sys.stderr)
        return 2

    if args.only is not None:
        # --only bypasses build/skip on purpose: it is what a matrix leg
        # passes back in, and that leg was already selected when the matrix
        # was generated.
        targets = [t for t in targets if t.identifier == args.only]
        if not targets:
            print(
                f"cibuildmp: error: --only {args.only!r} matches no target this "
                f"config can produce",
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

    # M1-M3 land here: fetch MicroPython, build mpy-cross, resolve each
    # target's toolchain, run make, collect and verify the outputs.
    print(
        "cibuildmp: building is not implemented yet (M0 ships selection only).\n"
        "Selected targets:",
        file=sys.stderr,
    )
    for target in targets:
        build_options = options.build_options(target)
        make = ["make", "-C", build_options.module_dir, f"ARCH={target.arch}"]
        make += build_options.extra_make_args
        make.append(build_options.make_target)
        print(
            f"  {target.identifier:<28} CROSS={target.cross or '(host)':<22} {' '.join(make)}",
            file=sys.stderr,
        )
    return 1

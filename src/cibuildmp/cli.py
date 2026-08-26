"""Command line interface -- the parts genuinely shared by both build
modes, and nothing else.

What lives here: the one argument parser (both modes are reached through
the same `cibuildmp` command), `detect_mode()`, and the preamble
`main()` has to run before either mode can be chosen at all
(`--clean-cache`, reading the config once, validating `CIBMP_PLATFORM`).
Once mode is resolved, `main()` hands off to `natmod/cli.py`'s `run()`
or `usermod/cli.py`'s `run()` through the identical signature.

natmod's own dispatch used to be written inline here while usermod's
already had its own module, which made the two look asymmetric for no
reason other than which one was written first -- natmod's `build()` and
its --dry-run/--only/--print-* handling now live in `natmod/cli.py`
alongside the rest of natmod.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from . import __version__
from .natmod import cli as natmod_cli
from .natmod.options import ConfigError, read_config
from .natmod.sources import cache_root
from .usermod import cli as usermod_cli


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
        default=None,
        choices=["natmod", "usermod"],
        help="Build mode. Auto-detected by default from which top-level table "
        "the config has -- [natmod] or [usermod] -- the same way cibuildwheel "
        "infers its own platform from the host. Only needed when a config "
        "defines both tables, to say which one this invocation is for. Also "
        "settable via CIBMP_PLATFORM -- the same generic env-override every "
        "cibuildmp.toml key already has (options.py's own opt()), not a "
        "dedicated action.yml input: a caller sets it directly on the "
        "`uses: cibuildmp` step's own env:, the same shape CIBMP_VERSION "
        "already uses, matching cibuildwheel's own CIBW_BUILD (an env var,"
        " never an action.yml input either).",
    )
    return parser


def detect_mode(raw: dict, explicit: str | None) -> str | None:
    """The build mode for this invocation: `explicit` (--platform) if
    given, otherwise inferred from which top-level table `raw` has.

    Returns None when inference is genuinely ambiguous (both [natmod]
    and [usermod] present, no --platform) -- main() turns that into an
    error rather than silently guessing. Neither table present defaults
    to natmod, preserving every existing config's behaviour untouched: a
    repo following the conventional natmod/ layout with no config at all
    already builds natmod today, and must keep doing so.
    """
    if explicit is not None:
        return explicit
    has_natmod = "natmod" in raw
    has_usermod = "usermod" in raw
    if has_natmod and has_usermod:
        return None
    return "usermod" if has_usermod else "natmod"


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
        preread = read_config(args.package_dir, args.config_file)
    except ConfigError as exc:
        if args.debug_traceback:
            raise
        print(f"cibuildmp: error: {exc}", file=sys.stderr)
        return 2

    platform_env = os.environ.get("CIBMP_PLATFORM")
    if platform_env and platform_env not in {"natmod", "usermod"}:
        print(
            f"cibuildmp: error: CIBMP_PLATFORM={platform_env!r} is not "
            f"'natmod' or 'usermod'",
            file=sys.stderr,
        )
        return 2

    mode = detect_mode(preread[1], args.platform or platform_env or None)
    if mode is None:
        print(
            "cibuildmp: error: config has both [natmod] and [usermod] -- pass "
            "--platform natmod or --platform usermod to say which one this "
            "invocation is for",
            file=sys.stderr,
        )
        return 2

    dispatch = usermod_cli.run if mode == "usermod" else natmod_cli.run
    return dispatch(args, args.package_dir, args.config_file, preread)

"""Command line interface -- the parts genuinely shared across every
platform, and nothing else.

What lives here: the one argument parser (every platform is reached
through the same `cibuildmp` command), `active_platforms()`, and the
preamble `main()` has to run before any platform can be chosen at all
(`--clean-cache`, reading the config once, validating
`CIBMP_PLATFORM`/`--platform`). Once the active platform set is resolved,
`main()` hands off to `natmod/cli.py`'s `run()` and/or `usermod/cli.py`'s
`run()` through the identical four-argument signature -- more than one at
once is a real, supported case now (Phase F, record 0051 points 4/6:
cibuildmp's six platforms are Docker images on one host, not OS-bound the
way cibuildwheel's own platforms are, so nothing forces one platform per
invocation).

natmod's own dispatch used to be written inline here while usermod's
already had its own module, which made the two look asymmetric for no
reason other than which one was written first -- natmod's `build()` and
its --dry-run/--only/--print-* handling now live in `natmod/cli.py`
alongside the rest of natmod.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from . import __version__
from .natmod import cli as natmod_cli
from .natmod import targets as natmod_targets
from .natmod.options import ConfigError, Options, read_config
from .natmod.sources import cache_root
from .usermod import cli as usermod_cli
from .usermod.options import UsermodConfigError, UsermodOptions
from .usermod.targets import KNOWN_PORTS, all_usermod_targets

# Every platform this invocation can build, natmod first (matching every
# existing zero-config repo's own expectation, and print/merge order
# below). `platforms/` as its own package -- one module per entry here --
# is Phase H's job; for now this is just the ordered name list.
ALL_PLATFORMS: tuple[str, ...] = ("natmod", *KNOWN_PORTS)


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
        help="Comma-separated list of architectures to build, overriding the "
        "config's own. usermod also accepts the words auto, native and all: "
        "native is this machine's own architecture, auto adds the 32-bit "
        "sibling it can run directly, all is every cell. natmod accepts only "
        "all -- every natmod arch is a cross-compile, so none of them depends "
        "on what this machine is. Nothing is unbuildable either way: a "
        "non-native cell builds under emulation, this only picks what to "
        "build here.",
    )
    parser.add_argument(
        "--enable",
        action="append",
        default=[],
        metavar="GROUP",
        help="Reach an opt-in group build/skip alone would not -- a target "
        "belonging to an unenabled group is excluded before build/skip is "
        "even checked. Repeatable. Only usermod defines any groups today "
        "(unix-emulated-everywhere: ppc64le/s390x/riscv64, both libcs). "
        "Matches upstream's own --enable/CIBW_ENABLE shape.",
    )
    parser.add_argument(
        "--clean-cache",
        action="store_true",
        help="Delete cibuildmp's cache (MicroPython checkouts, mpy-cross builds "
        "and any downloaded sources) and exit",
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
        metavar="PLATFORM[,PLATFORM...]",
        help="Build only these platforms (comma- or space-separated), out of "
        f"{', '.join(ALL_PLATFORMS)}. Auto-detected by default from which "
        "top-level tables the config has -- [natmod], [unix], ... -- the "
        "same way cibuildwheel infers its own platform from the host, "
        "generalised to six platforms and to more than one active at once "
        "(cibuildmp's platforms are Docker images on one host, not "
        "OS-bound the way cibuildwheel's own are, so nothing forces one "
        "per invocation). Also settable via CIBMP_PLATFORM -- the same "
        "generic env-override every cibuildmp.toml key already has, not a "
        "dedicated action.yml input: a caller sets it directly on the "
        "`uses: cibuildmp` step's own env:, the same shape CIBMP_VERSION "
        "already uses, matching cibuildwheel's own CIBW_BUILD (an env var,"
        " never an action.yml input either).",
    )
    return parser


def _parse_platform_names(value: str) -> list[str]:
    """`--platform`/`CIBMP_PLATFORM`'s own value: comma- or whitespace-
    separated platform names. Every name must be one of `ALL_PLATFORMS` --
    in particular, the old single-mode spelling `usermod` is rejected now
    (it was never a platform, only the mode name Phase F retired); `natmod`
    still works, since it is a real platform name today.
    """
    names = [v.strip() for v in value.replace(",", " ").split() if v.strip()]
    unknown = [n for n in names if n not in ALL_PLATFORMS]
    if unknown:
        raise ConfigError(
            f"--platform/CIBMP_PLATFORM: unknown platform(s) "
            f"{', '.join(sorted(unknown))}. Known: {', '.join(ALL_PLATFORMS)}."
        )
    return names


def _reject_legacy_usermod_table(raw: dict) -> None:
    """`[usermod]` (and therefore `[usermod.<port>]`, which always nests
    under it in TOML) no longer exists, as of Phase F -- every port is its
    own top-level table now, sibling to `[natmod]`, and `ports = [...]` is
    gone in favour of table presence. A lingering `[usermod]` is loud and
    specific, not folded into a generic "unknown key" error -- this is the
    one real breaking change point 6 (record 0051) always was, and every
    existing usermod config needs to migrate, not guess why it broke.
    """
    if "usermod" in raw:
        raise ConfigError(
            "[usermod] no longer exists. Every usermod port is its own "
            "top-level table now, sibling to [natmod]: [unix], [windows], "
            "[qemu], [webassembly], [esp32]. There is no more `ports = "
            "[...]` list -- writing a platform's own table (even an empty "
            "one) is what selects it, the same rule [natmod]'s own "
            "presence already followed. See "
            "docs/records/0051-usermod-identifiers-have-no-version-axis.md's "
            "Phase F note for the exact migration."
        )


# Top-level tables that are not platforms and never were -- `[publish]`
# (natmod's own extra-files) -- so `_reject_unknown_tables()` below does
# not mistake a legitimate non-platform table for a typo'd platform name.
_NON_PLATFORM_TABLES: frozenset[str] = frozenset({"publish"})


def _reject_unknown_tables(raw: dict) -> None:
    """A top-level table whose name is neither a known platform nor a
    known non-platform table (`[publish]`) is almost certainly a typo --
    `[stm32]` for a port that does not exist, `[usermdo]` for `[usermod]`
    (itself rejected separately, see `_reject_legacy_usermod_table()`).
    Presence-based platform selection has no other place to catch this:
    unlike the old `ports = [...]` list (validated against `KNOWN_PORTS`
    by `usermod_targets()`), an unrecognised table name is otherwise
    simply never selected, silently, rather than reported.
    """
    unknown = sorted(
        key
        for key, value in raw.items()
        if isinstance(value, dict)
        and key not in ALL_PLATFORMS
        and key not in _NON_PLATFORM_TABLES
    )
    if unknown:
        raise ConfigError(
            f"unknown table(s) at the top level: "
            f"{', '.join(f'[{k}]' for k in unknown)}. Known platform tables: "
            f"{', '.join(ALL_PLATFORMS)}."
        )


def active_platforms(raw: dict, explicit: list[str] | None) -> list[str]:
    """The platforms this invocation builds.

    `explicit` (`--platform`/`CIBMP_PLATFORM`, already parsed and
    validated by `_parse_platform_names()`) wins outright when given,
    regardless of which tables `raw` has -- matching today's
    "`--platform natmod` forces natmod even without `[natmod]` present"
    behaviour, generalised to a list.

    Otherwise: every one of the six platform tables `raw` actually has,
    in `ALL_PLATFORMS` order. No table present at all still means exactly
    `["natmod"]` -- the zero-config behaviour every existing natmod-only
    repo already depends on, unchanged.

    Two or more platforms active at once is no longer ambiguous or an
    error -- that was the entire point of record 0051's redesign:
    cibuildmp's six platforms are Docker images on one host, not
    OS-bound like cibuildwheel's own, so nothing forces one platform per
    invocation.
    """
    _reject_legacy_usermod_table(raw)
    _reject_unknown_tables(raw)
    if explicit is not None:
        return explicit
    return [p for p in ALL_PLATFORMS if p in raw] or ["natmod"]


def _known_identifiers(
    args: argparse.Namespace,
    package_dir: Path,
    config_file: Path | None,
    preread: tuple[Path | None, dict],
    natmod_active: bool,
    usermod_ports: list[str],
) -> tuple[set[str], set[str]]:
    """Every identifier each active side can name, for narrowing `--only`
    to a single side below. Load errors are swallowed here -- narrowing
    is a best-effort convenience, and a genuinely broken config still
    gets its own real error from that side's own `run()`."""
    natmod_ids: set[str] = set()
    usermod_ids: set[str] = set()
    if natmod_active:
        try:
            natmod_ids = {
                t.identifier
                for t in Options.load(
                    package_dir, config_file, preread=preread
                ).all_targets()
            }
        except ConfigError:
            pass
    if usermod_ports:
        try:
            tags = UsermodOptions.load(
                package_dir, config_file, preread=preread, ports=usermod_ports
            ).micropython
            usermod_ids = {t.identifier for t in all_usermod_targets(tags)}
        except UsermodConfigError:
            pass
    return natmod_ids, usermod_ids


def _print_build_identifiers(
    args: argparse.Namespace,
    package_dir: Path,
    config_file: Path | None,
    preread: tuple[Path | None, dict],
    natmod_active: bool,
    usermod_ports: list[str],
) -> int:
    """`--print-build-identifiers` across more than one active platform,
    merged into exactly one document. Naive sequential dispatch (each
    side's own `run()` printing its own block) would emit two separate
    JSON arrays under `--json` -- invalid as a single document, and
    exactly what `cibuildmp-matrix`'s own `json.loads()` (record 0048)
    would choke on. This bypasses both `run()`s for this one flag rather
    than teaching them to cooperate; Phase H's unified dispatch loop
    replaces this wholesale."""
    identifiers: list[str] = []
    if natmod_active:
        options = Options.load(package_dir, config_file, preread=preread)
        if args.output_dir is not None:
            options.output_dir = args.output_dir
        if args.archs is not None:
            options.archs = (
                list(natmod_targets.NATMOD_ARCHS)
                if args.archs.strip() == "all"
                else [a.strip() for a in args.archs.split(",") if a.strip()]
            )
        targets = options.targets()
        if args.only is not None:
            targets = [t for t in targets if t.identifier == args.only] or [
                t for t in options.all_targets() if t.identifier == args.only
            ]
        identifiers += [t.identifier for t in targets]
    if usermod_ports:
        uoptions = UsermodOptions.load(
            package_dir, config_file, preread=preread, ports=usermod_ports
        )
        if args.enable:
            uoptions.enable = uoptions.enable | frozenset(args.enable)
        targets = uoptions.targets()
        if args.only is not None:
            targets = [t for t in targets if t.identifier == args.only]
        identifiers += [t.identifier for t in targets]
    if args.json:
        print(json.dumps(identifiers))
    else:
        for identifier in identifiers:
            print(identifier)
    return 0


def _run_multi_platform(
    args: argparse.Namespace,
    package_dir: Path,
    config_file: Path | None,
    preread: tuple[Path | None, dict],
    natmod_active: bool,
    usermod_ports: list[str],
) -> int:
    """The interim bridge for more than one active platform in one
    invocation -- not a unified dispatch loop (Phase H's own job); it
    runs each side's existing `run()` for the default/`--dry-run`/real-
    build paths (combined exit code is the worse of the two), but
    special-cases `--only` and `--print-build-identifiers`, whose
    *contract* would silently break under naive sequential dispatch.
    """
    if args.only is not None:
        natmod_ids, usermod_ids = _known_identifiers(
            args, package_dir, config_file, preread, natmod_active, usermod_ports
        )
        if args.only in natmod_ids and args.only not in usermod_ids:
            usermod_ports = []
        elif args.only in usermod_ids and args.only not in natmod_ids:
            natmod_active = False
        # A value matching neither (or, in principle, both) side leaves
        # both active -- each side's own run() reports its own "not a
        # known identifier" error below. Phase H's unified loop removes
        # this rough edge by construction.

    if args.print_build_identifiers:
        return _print_build_identifiers(
            args, package_dir, config_file, preread, natmod_active, usermod_ports
        )

    rc = 0
    if natmod_active:
        rc = natmod_cli.run(args, package_dir, config_file, preread) or rc
    if usermod_ports:
        urc = usermod_cli.run(
            args, package_dir, config_file, preread, ports=usermod_ports
        )
        rc = urc if urc != 0 else rc
    return rc


def main(argv: list[str] | None = None) -> int:
    # Every `print()` in this tool is progress output, and until this line
    # existed none of it *was* progress output on CI. Python block-buffers
    # stdout whenever it is not a tty, so a build's own narration
    # ("downloaded micropython.tar.xz", "mpy-cross: building", the
    # per-target result lines) sat in a 8KiB buffer until interpreter exit
    # and then arrived all at once, at the very end -- while `make`, an
    # ordinary subprocess inheriting the same fd, wrote straight through
    # and got interleaved ahead of all of it.
    #
    # Read off a real run rather than reasoned about: in run 32958683512
    # every one of cibuildmp's own lines carries the timestamp
    # `10:34:25.606`, including "downloaded micropython.tar.xz (104 MiB)",
    # which describes something that finished ninety seconds earlier and
    # is printed *after* the final `LINK`. Anything this tool says about
    # what it is currently doing is worthless under that ordering, which
    # makes line buffering a precondition for the probe reporting in
    # `usermod/dockerrun.py` rather than a cosmetic fix -- and part of
    # what record 0047 is about.
    #
    # Line buffering, not `flush=True` per call site: the property wanted
    # is of the stream, and scattering flushes leaves the next `print()`
    # anyone adds silently wrong again. `reconfigure()` is guarded because
    # stdout can be a plain object with no such method (pytest's own
    # capture, an embedding host), and buffering is never worth an
    # exception.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True)  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            pass

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

    raw_platform = args.platform or os.environ.get("CIBMP_PLATFORM")
    try:
        explicit = _parse_platform_names(raw_platform) if raw_platform else None
        platforms = active_platforms(preread[1], explicit)
    except ConfigError as exc:
        if args.debug_traceback:
            raise
        print(f"cibuildmp: error: {exc}", file=sys.stderr)
        return 2

    natmod_active = "natmod" in platforms
    usermod_ports = [p for p in platforms if p != "natmod"]

    if len(platforms) <= 1:
        # Byte-for-byte today's dispatch shape.
        if natmod_active:
            return natmod_cli.run(args, args.package_dir, args.config_file, preread)
        return usermod_cli.run(
            args, args.package_dir, args.config_file, preread, ports=usermod_ports
        )

    return _run_multi_platform(
        args, args.package_dir, args.config_file, preread, natmod_active, usermod_ports
    )

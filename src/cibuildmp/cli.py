"""Command line interface -- the parts genuinely shared across every
platform, and nothing else.

What lives here: the one argument parser (every platform is reached
through the same `cibuildmp` command), `active_platforms()`, and the
preamble `main()` has to run before any platform can be chosen at all
(`--clean-cache`, reading the config once, validating
`CIBMP_PLATFORM`/`--platform`). Once the active platform set is resolved,
`main()` hands off to whichever `platforms/` module (a "family") actually
implements each active platform, through `PLATFORM_FAMILY` -- more than
one platform at once is a real, supported case (Phase F, record 0051
points 4/6: cibuildmp's six platforms are Docker images on one host, not
OS-bound the way cibuildwheel's own platforms are, so nothing forces one
platform per invocation), and more than one *family* at once is exactly
as supported, and costs nothing extra: this module never names `natmod`
or `usermod` anywhere below, only `PLATFORM_FAMILY`/`_group_by_family()`
(Phase H) -- the actual requirement a future third family (zephyr,
[0022]; any of upstream's own ~20 real ports) needs this dispatch to
satisfy, since none of it should have to change to add one.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from . import __version__
from .platforms import PLATFORM_FAMILY, PlatformModule
from .platforms.natmod.options import ConfigError, read_config
from .platforms.usermod.options import UsermodConfigError
from .sources import cache_root

# Every platform this invocation can build, natmod first (matching every
# existing zero-config repo's own expectation, and print/merge order
# below). Derived from PLATFORM_FAMILY's own key order rather than
# hand-listed a second time next to it -- see platforms/__init__.py's own
# comment on why that would drift the way record 0048's bug class did.
ALL_PLATFORMS: tuple[str, ...] = tuple(PLATFORM_FAMILY)


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
    if not names:
        # A separators-only value ("--platform ,") named zero platforms.
        # Falling through used to silently dispatch to usermod with an
        # empty port list ("no targets selected"), an accident of which
        # branch happened to sit in the `else` rather than a considered
        # default -- loud now, matching every other malformed-input error
        # in this function (Phase H).
        raise ConfigError(
            f"--platform/CIBMP_PLATFORM: no platform name found in {value!r}."
        )
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


def _group_by_family(platforms: list[str]) -> dict[PlatformModule, list[str]]:
    """Every active platform, grouped by which module actually implements
    it, in first-appearance order. The one place any of the functions
    below ever asks "which platforms share an implementation" -- every
    caller iterates the result and calls each family's own
    `resolve_options()`/`run()` exactly once, whether one platform is
    active or five (cibuildwheel's own real contract: `platform_module.
    build()` is called once per platform, never per identifier -- adopted
    here as once per *family*, since two of cibuildmp's own modules
    already cover six platform names). Adding a third family costs one
    new module plus a `PLATFORM_FAMILY` entry; nothing below this line
    changes."""
    grouped: dict[PlatformModule, list[str]] = {}
    for p in platforms:
        grouped.setdefault(PLATFORM_FAMILY[p], []).append(p)
    return grouped


def _known_identifiers(
    args: argparse.Namespace,
    package_dir: Path,
    config_file: Path | None,
    preread: tuple[Path | None, dict],
    platforms: list[str],
) -> dict[PlatformModule, set[str]]:
    """Every identifier each active family can name, keyed by family
    module -- for narrowing `--only` to a single family below. Load
    errors are swallowed here -- narrowing is a best-effort convenience,
    and a genuinely broken config still gets its own real error from that
    family's own `run()`."""
    ids: dict[PlatformModule, set[str]] = {}
    for family, ports in _group_by_family(platforms).items():
        try:
            options = family.resolve_options(
                args, package_dir, config_file, preread, ports=ports
            )
            ids[family] = {t.identifier for t in options.all_targets()}
        except (ConfigError, UsermodConfigError):
            ids[family] = set()
    return ids


def _print_build_identifiers(
    args: argparse.Namespace,
    package_dir: Path,
    config_file: Path | None,
    preread: tuple[Path | None, dict],
    platforms: list[str],
) -> int:
    """`--print-build-identifiers` across more than one active platform,
    merged into exactly one document. Naive sequential dispatch (each
    family's own `run()` printing its own block) would emit two separate
    JSON arrays under `--json` -- invalid as a single document, and
    exactly what `cibuildmp-matrix`'s own `json.loads()` (record 0048)
    would choke on. This bypasses every family's own `run()` for this one
    flag rather than teaching them to cooperate.

    `--only` is resolved the same way every family's own `run()` already
    resolves it -- against `all_targets()` wholesale, never layered onto
    the build/skip-filtered `targets()` list (**0045**). Before Phase H
    this function had its own, inconsistent copy of that rule: natmod's
    branch fell back to `all_targets()` only when the `targets()` filter
    came up empty, and usermod's branch had no fallback at all, silently
    printing nothing for an identifier `skip` had excluded. One rule now,
    matching what both `run()`s already agreed on.
    """
    identifiers: list[str] = []
    for family, ports in _group_by_family(platforms).items():
        options = family.resolve_options(
            args, package_dir, config_file, preread, ports=ports
        )
        targets = (
            [t for t in options.all_targets() if t.identifier == args.only]
            if args.only is not None
            else options.targets()
        )
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
    platforms: list[str],
) -> int:
    """The bridge for more than one active platform in one invocation.
    Every family active this invocation runs exactly once
    (`_group_by_family()`), for the default/`--dry-run`/real-build paths
    (combined exit code is the worse of any of them), but `--only` and
    `--print-build-identifiers` are special-cased, since naive per-family
    dispatch would silently break each one's own contract (see their own
    docstrings)."""
    if args.only is not None:
        ids = _known_identifiers(args, package_dir, config_file, preread, platforms)
        matches = [family for family, known in ids.items() if args.only in known]
        if len(matches) == 1:
            keep = matches[0]
            platforms = [p for p in platforms if PLATFORM_FAMILY[p] is keep]
        # A value matching zero or more than one family leaves every
        # platform active -- each family's own run() reports its own
        # "not a known identifier" error below.

    if args.print_build_identifiers:
        return _print_build_identifiers(args, package_dir, config_file, preread, platforms)

    rc = 0
    for family, ports in _group_by_family(platforms).items():
        frc = family.run(args, package_dir, config_file, preread, ports=ports)
        rc = frc if frc != 0 else rc
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

    if len(platforms) == 1:
        # Byte-for-byte today's dispatch shape -- skips
        # _run_multi_platform's own --only narrowing step (a second
        # config load) for the overwhelmingly common single-platform
        # case. `platforms` is never empty here: active_platforms()
        # always returns at least ["natmod"], and _parse_platform_names()
        # now rejects an explicit value naming zero platforms outright.
        family = PLATFORM_FAMILY[platforms[0]]
        return family.run(
            args, args.package_dir, args.config_file, preread, ports=platforms
        )

    return _run_multi_platform(args, args.package_dir, args.config_file, preread, platforms)

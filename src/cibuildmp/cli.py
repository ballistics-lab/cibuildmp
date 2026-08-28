"""Command line interface -- the parts genuinely shared across every
platform, and nothing else.

What lives here: the one argument parser (every platform is reached
through the same `cibuildmp` command), and the coordinator (`_run()`) that
resolves both families on every invocation, merges `--print-build-
identifiers`, makes the one joint "nothing at all was selected" decision,
and dispatches whichever families ended up with a nonzero target list.
This module never names `natmod`/`usermod` anywhere below -- only
`platforms.FAMILIES` -- which is the actual requirement a future third
family (zephyr, [0022]; any of upstream's own ~20 real ports) needs this
dispatch to satisfy, since none of it should have to change to add one.

There is no more platform *activation* concept at all (record 0052's own
live-caught retraction): every family is always in scope, on every
invocation, and `build`/`skip` glob-matching each family's own real
identifiers is the only thing that decides what actually gets built. An
empty config selects nothing from either family -- the zero-config
default used to mean "natmod, with build narrowed to the newest known
ABI"; it means nothing at all now, the same retraction natmod's own
default-build narrowing already got. `--platform`/`--only`/`--enable`/
`--archs` are gone with it: everything any of them could reach, an
ordinary `build`/`skip` glob (or an `--build`/`--skip` CLI override, or an
`[override."<glob>"]` entry) already reaches directly against the real
identifier -- see the README for the full identifier list and glob
syntax.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .platforms import FAMILIES, PlatformModule
from .platforms.natmod.options import ConfigError, read_config
from .sources import cache_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cibuildmp",
        description="Build MicroPython native C extensions across every target "
        "a module supports, from one declarative config.",
        epilog="Most options are supplied via cibuildmp.toml or CIBMP_* environment "
        "variables. See docs/0000-TRACKER.md for the design and what is implemented.",
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
        help="Where to collect built .mpy files (overrides the config, natmod only "
        "-- usermod's own output-dir is config/CIBMP_OUTPUT_DIR only)",
    )
    parser.add_argument(
        "--build",
        default=None,
        metavar="GLOB[ GLOB...]",
        help="Override the config's own build selector -- space-separated glob(s) "
        "matched against the real identifier, the same syntax build/CIBMP_BUILD "
        'accept (e.g. --build "*manylinux*" or --build "mpy6.3-*"). Replaces the '
        "old --only/--platform: name exactly what you want with a glob specific "
        "enough to match one identifier, or as broad as any other build value.",
    )
    parser.add_argument(
        "--skip",
        default=None,
        metavar="GLOB[ GLOB...]",
        help="Override the config's own skip selector -- same glob syntax as "
        "--build/skip/CIBMP_SKIP.",
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
    return parser


# The two top-level tables every platform used to gate activation with
# (before that, carry a per-port axis) -- neither concept exists any more,
# so a config still writing one of these six gets a specific error naming
# the real replacement, the same courtesy every other retired config
# surface in this project gets (record 0048's own "a misplaced/stale key
# must never silently do nothing"). `[usermod]`/`[publish]`/`[override]`
# are the only tables left with any meaning at all -- shared defaults for
# every usermod port, natmod's own extra-files list, and the shared
# per-target override list, respectively.
_RETIRED_PLATFORM_TABLES: frozenset[str] = frozenset(
    {"natmod", "unix", "windows", "qemu", "webassembly", "esp32"}
)
_KNOWN_TABLES: frozenset[str] = frozenset({"usermod", "publish", "override"})


def _validate_top_level_tables(raw: dict) -> None:
    """A top-level table whose name is neither one of the three still-
    meaningful ones nor one of the six retired platform names is almost
    certainly a typo (`[stm32]` for a port this project has no build
    driver for yet, `[usermdo]` for `[usermod]`)."""
    retired = sorted(_RETIRED_PLATFORM_TABLES & raw.keys())
    if retired:
        raise ConfigError(
            f"[{retired[0]}] no longer exists -- every platform is always in "
            "scope now, selected purely by build/skip glob-matching its own "
            "real identifiers (see the README for the full identifier list). "
            "Move any module-dir/user-c-modules/manifest/extra-make-args/"
            "make-target/pre-build-command/arch-flags value to the top level "
            "(or [usermod] for a usermod-wide default), and narrow with "
            'build/skip (e.g. build = "*-x64") or [override."<glob>"] '
            "instead."
        )
    unknown = sorted(
        key
        for key, value in raw.items()
        if isinstance(value, dict) and key not in _KNOWN_TABLES
    )
    if unknown:
        raise ConfigError(
            f"unknown table(s) at the top level: "
            f"{', '.join(f'[{k}]' for k in unknown)}."
        )


def _resolve_all(
    args: argparse.Namespace,
    package_dir: Path,
    config_file: Path | None,
    preread: tuple[Path | None, dict],
) -> list[tuple[PlatformModule, Any, list]] | int:
    """Every family's own config, resolved and narrowed to its own
    selected targets -- every family, unconditionally, every invocation.
    Returns the error's own exit code (already printed) instead of the
    list on the first family that fails to load.

    Two-phase, not one: `build`/`skip`/`[override]` are shared, top-level
    config now, and each family's own reachability audit (inside
    `.targets()`) needs to know every *other* active family's own real
    identifiers to tell "meant for the other family" apart from "a typo"
    (`Options.targets()`'s own `foreign_identifiers` docstring has the
    full reasoning). That needs every family's own `all_targets()` before
    any of them can safely call `.targets()`, so `resolve_options()` runs
    for every family first, then `.targets()` for every family second --
    still zero hardcoded family names, just two passes over the same
    `FAMILIES` tuple instead of one.
    """
    loaded: list[tuple[PlatformModule, Any, list[str]]] = []
    for family in FAMILIES:
        try:
            options = family.resolve_options(args, package_dir, config_file, preread)
        except family.LOAD_ERRORS as exc:  # type: ignore[attr-defined]
            if args.debug_traceback:
                raise
            print(f"cibuildmp: error: {exc}", file=sys.stderr)
            return 2
        loaded.append((family, options, [t.identifier for t in options.all_targets()]))

    resolved: list[tuple[PlatformModule, Any, list]] = []
    for index, (family, options, _own_identifiers) in enumerate(loaded):
        foreign = [i for j, (_, _, ids) in enumerate(loaded) if j != index for i in ids]
        try:
            targets = options.targets(foreign_identifiers=foreign)
        except family.LOAD_ERRORS as exc:  # type: ignore[attr-defined]
            if args.debug_traceback:
                raise
            print(f"cibuildmp: error: {exc}", file=sys.stderr)
            return 2
        resolved.append((family, options, targets))
    return resolved


def _run(
    args: argparse.Namespace,
    package_dir: Path,
    config_file: Path | None,
    preread: tuple[Path | None, dict],
) -> int:
    resolved = _resolve_all(args, package_dir, config_file, preread)
    if isinstance(resolved, int):
        return resolved

    if args.print_build_identifiers:
        identifiers = [t.identifier for _, _, targets in resolved for t in targets]
        if args.json:
            print(json.dumps(identifiers))
        else:
            for identifier in identifiers:
                print(identifier)
        return 0

    total = sum(len(targets) for _, _, targets in resolved)
    if total == 0:
        if args.allow_empty:
            print("cibuildmp: no targets selected")
            return 0
        print(
            "cibuildmp: error: no targets selected. Pass --allow-empty if that "
            "is expected.",
            file=sys.stderr,
        )
        return 2

    rc = 0
    for family, options, targets in resolved:
        if not targets:
            # This family's own build/skip simply matched nothing --
            # the ordinary case for a config that only configures the
            # other family, not a per-family error (the joint check
            # above already ruled out "nothing at all was selected").
            continue
        frc = family.run_resolved(args, options, targets)
        rc = frc if frc != 0 else rc
    return rc


def _clear_readonly_and_retry(func: Any, path: str, _exc: Any) -> None:
    """`shutil.rmtree()` error handler: a real, live failure --
    `autom4te.cache` (autoconf, `ports/unix`'s own libffi build under
    `MICROPY_STANDALONE=1`) creates entries some platforms leave without
    the owner write bit, so a plain `os.unlink`/`os.rmdir` refuses with
    `PermissionError` even though this process owns the cache tree
    outright and can simply reclaim write access first.

    An earlier version of this handler chmod'd only `path` itself and
    still failed live in CI -- caught, not assumed fixed. Removing an
    entry needs write+execute on the directory *containing* it, not on
    the entry: `os.unlink(".../autom4te.cache/requests")` fails on
    `autom4te.cache`'s own missing write bit, not on `requests`, which is
    just a plain file. Chmodding both `path` and its parent, ignoring
    whichever one does not apply (`os.chmod` on a file that already had
    the right bits, or on a parent already writable, is a harmless no-op)
    means this handler does not have to know which of shutil's own
    internal calls (`unlink`, `rmdir`, `scandir`, ...) is retrying, only
    that reclaiming access to both ends of the failing path is always
    safe within a cache tree this process owns outright.
    """
    for target in (path, os.path.dirname(path)):
        try:
            os.chmod(target, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
        except OSError:
            pass
    func(path)


def _rmtree_writable(root: Path) -> None:
    """`shutil.rmtree(root)`, tolerating read-only entries under it --
    see `_clear_readonly_and_retry()`. `onexc` (the exception instance)
    replaced `onerror` (a `sys.exc_info()` triple) in Python 3.12 and the
    old name is deprecated since; this project supports 3.11 onward
    (`pyproject.toml`), so both are wired to the same handler -- its
    third parameter is unused either way, so one function satisfies both
    call shapes without actually branching on which fields it receives.
    """
    if sys.version_info >= (3, 12):
        shutil.rmtree(root, onexc=_clear_readonly_and_retry)
    else:
        shutil.rmtree(root, onerror=_clear_readonly_and_retry)


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
        _rmtree_writable(root)
        print(f"cibuildmp: removed {root}")
        return 0

    try:
        preread = read_config(args.package_dir, args.config_file)
        _validate_top_level_tables(preread[1])
        for family in FAMILIES:
            family.validate_family_table(preread[1], error=ConfigError)
    except ConfigError as exc:
        if args.debug_traceback:
            raise
        print(f"cibuildmp: error: {exc}", file=sys.stderr)
        return 2

    return _run(args, args.package_dir, args.config_file, preread)

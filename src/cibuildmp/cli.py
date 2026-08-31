"""Command line interface -- the parts genuinely shared across every
platform, and nothing else.

What lives here: the one argument parser (every platform is reached
through the same `cibuildmp` command), and the coordinator (`_run()`) that
resolves both families on every invocation, merges `--print-build-
identifiers`, makes the one joint "nothing at all was selected" decision,
and dispatches whichever families ended up with a nonzero target list.
No *dispatch* in this module names `natmod`/`usermod` -- it iterates
`platforms.FAMILIES` -- which is the requirement a future third family
(zephyr, [0022]; any of upstream's own ~20 real ports) needs to satisfy:
adding one should touch no logic here. The imports are a different
matter and are not family-agnostic: `read_config`/`ConfigError` live in
`platforms/natmod/options.py` and are imported from there by this module
and by `usermod/options.py` alike, because natmod's options module is
the shared base every platform imports from. A third family would import
them the same way; it would not need this file's own logic changed.

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
from .options import check_known_keys, known_option_names
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
        "--keep-going",
        action="store_true",
        help="Build every selected target even if an earlier one fails, instead "
        "of stopping at the first failure (the default). Every attempted "
        "target's own outcome, including failures, is written to a JSON "
        "report either way -- see CIBMP_REPORT_PATH.",
    )
    parser.add_argument(
        "--debug-traceback",
        action="store_true",
        default=os.environ.get("CIBMP_DEBUG_TRACEBACK", "") not in {"", "0"},
        help="Print a full traceback for all errors",
    )
    return parser


# `[natmod]`/`[unix]`/`[windows]`/`[qemu]`/`[webassembly]`/`[esp32]`/
# `[usermod]` all used to be real, meaningful top-level tables (activation
# gates, then per-port axes, then -- `[usermod]` alone -- shared defaults)
# across records 0048-0052/0074. None of that history gets a dedicated
# migration message any more: every one of them is just an unrecognised
# top-level table today, the same as a typo like `[stm32]`. `[publish]`/
# `[override]` are the only tables left with any meaning at all --
# natmod's own extra-files list, and the shared per-target override list,
# respectively.
_KNOWN_TABLES: frozenset[str] = frozenset({"publish", "override"})


def _is_table(value: Any) -> bool:
    """Whether a top-level value is TOML *table* syntax rather than a
    scalar option -- what decides which of the two validators below owns
    a key.

    A dict is `[name]`; a non-empty list of dicts is `[[name]]`, an array
    of tables. Neither of this project's own two real tables uses that
    second form -- `[override]` is keyed directly by its own glob
    (`[override."<glob>"]`, deliberately unlike cibuildwheel's own
    `[[tool.cibuildwheel.overrides]]`), so both parse to plain dicts --
    but a `dict`-only test would send a stray `[[stm32]]` to the scalar
    keyset check instead of the table check, reporting "unknown key"
    for something that is a table. `and value` matters: an empty list is
    `extra-make-args = []`, a real scalar option, and an array of tables
    is never empty.
    """
    if isinstance(value, dict):
        return True
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, dict) for item in value)
    )


def _validate_top_level_tables(raw: dict) -> None:
    """A top-level table whose name is not one of the two still-meaningful
    ones is almost certainly a typo (`[stm32]` for a port this project has
    no build driver for yet, `[overide]` for `[override]`) or a config
    written against an old, retired version of this schema -- either way,
    naming it is enough; there is no per-name migration story to tell."""
    unknown = sorted(
        key
        for key, value in raw.items()
        if _is_table(value) and key not in _KNOWN_TABLES
    )
    if unknown:
        raise ConfigError(
            f"unknown table(s) at the top level: "
            f"{', '.join(f'[{k}]' for k in unknown)}."
        )


def _validate_top_level_keys(raw: dict) -> None:
    """The scalar counterpart of `_validate_top_level_tables()` above, and
    the gap record 0074 found while checking a claim about it: neither
    family's own `load()` ever validated the top-level scalar keyset at
    all, so `micropyton = "v1.29.0"` (or any other key no family reads)
    was silently absent rather than flagged -- the config looked accepted
    and the option simply never applied.

    `known_option_names()`/`check_known_keys()` (`options.py`) already
    existed for exactly this and were dead code until this call site;
    `check_known_keys()` brings the same `difflib` close-match suggestion
    cibuildwheel's own `_validate_global_option()` gives.

    Unioned from `FAMILIES` rather than a list written out here, for the
    same reason `_resolve_all()` iterates it: `cli.py` does not know the
    name `natmod` or `usermod`, and a third family must not need an edit
    in this file to have its own keys accepted.

    Table-valued keys are skipped, not passed through: `[publish]` and
    `[override]` are real config that no family's own `OPTION_KEYS`
    contains, and `_validate_top_level_tables()` above is what judges
    those."""
    known = known_option_names({f.__name__: f.OPTION_KEYS for f in FAMILIES})
    scalars = {k: v for k, v in raw.items() if not _is_table(v)}
    check_known_keys(scalars, known, where="cibuildmp.toml", error=ConfigError)


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
        _validate_top_level_keys(preread[1])
    except ConfigError as exc:
        if args.debug_traceback:
            raise
        print(f"cibuildmp: error: {exc}", file=sys.stderr)
        return 2

    return _run(args, args.package_dir, args.config_file, preread)

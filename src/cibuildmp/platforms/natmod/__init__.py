"""natmod: the platform family for `dynruntime.mk`-based native modules --
one build per ARCH, no MicroPython port build of its own.

Also natmod's own half of CLI dispatch (Phase H, record 0051; the
`--platform`/`--only`/`--archs` retraction folded into this same round).
This module implements the `PlatformModule` contract every entry in
`platforms.FAMILIES` satisfies -- `resolve_options()` (load config, apply
CLI overrides) and `run_resolved()` (the actual `--dry-run`/build
dispatch, given an already-resolved, already-nonempty target list).
`cli.py`'s own coordinator always resolves this family alongside
usermod's, every invocation -- there is no more activation concept
narrowing whether natmod is in scope; `build`/`skip` glob-matching the
identifier is the only thing that decides what actually gets built.
`build_all()` lives here too -- everything downstream of "this invocation
is a natmod build". What stays in `cli.py` is only what is genuinely
shared across every family: the one argument parser and the
cache-clean/config-read preamble that has to run before any family can be
resolved.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from ... import report
from ...sources import (
    SourceError,
    fetch_micropython,
    read_mpy_abi,
)
from ...stepsummary import write_step_summary
from .build import BuildError, BuildResult, build_mpy_cross, build_target
from .options import BuildOptions, ConfigError, Options
from .targets import Target, UnknownArchError, UnknownTagError


def _plan_line(index: int, total: int, options: BuildOptions) -> str:
    make = ["make", "-C", options.module_dir, f"ARCH={options.target.arch}"]
    make += options.extra_make_args
    make.append(options.make_target)
    # **No `CROSS=` column.** It showed "the prefix actually in play,
    # which is not always the one dynruntime.mk hardcodes" -- true while
    # a resolver could override it, and false in two ways once record
    # 0050 deleted that: cibuildmp sets no `CROSS` at all now (the image
    # supplies every prefix under the name dynruntime.mk expects), and
    # the table it was read from went stale the moment MicroPython
    # v1.29.0 changed `x86` from an empty prefix to `i686-linux-gnu-`.
    # It printed `CROSS=(host)` for a build with no host in it, next to a
    # make command containing no `CROSS=`.
    # Right-align the counter so the columns after it stay put once the
    # index gains a digit ([10/10] is wider than [9/10]).
    counter = f"[{index:>{len(str(total))}}/{total}]"
    return f"{counter} {options.target.identifier:<28} {' '.join(make)}"


def build_all(
    options: Options, targets: list[Target], *, keep_going: bool = False
) -> int:
    """Build every selected target in one invocation.

    Named `build_all` rather than the bare `build` this function had as
    `natmod/cli.py`'s own top-level orchestrator (Phase H): once its
    content moved into this package's own `__init__.py`, `build` would
    have collided with the `build` *submodule* (`build.py`, holding
    `build_target()`/`BuildError`/`BuildResult`) already imported into
    this same namespace above -- the later `def build(...)` would have
    silently shadowed the submodule reference, breaking any `from
    cibuildmp.platforms.natmod import build` that meant the module.

    Sequential and in-process on purpose (D9), the same shape cibuildwheel
    uses for the Python versions inside one runner. Fetching MicroPython and
    building mpy-cross are identical for every natmod arch *sharing an ABI*,
    so doing them once per ABI group here is strictly cheaper than paying
    for them in each of ten matrix legs -- and unlike cibuildwheel, no
    natmod target needs a runner any other target cannot use, so nothing
    forces a fan-out. Callers who want one anyway (failure isolation,
    wall-clock) opt in with --only.

    Grouped by MicroPython tag (**D13**): one group per distinct ABI the
    already-selected `targets` actually span -- almost always one, since
    `build`'s own default (record 0052, A2) narrows to the newest known
    ABI unless a config's own `build`/`skip` opens it up wider, but never
    fewer groups than the selection genuinely spans, and each needs its
    own checkout and its own mpy-cross.

    `keep_going` ([0063]): False (the default) preserves this function's
    original behaviour exactly -- a group's own SourceError (a bad fetch,
    an ABI mismatch) or a target's own BuildError propagates straight out,
    uncaught, to `run_resolved()`'s own catch, and nothing later is
    attempted. True is a real, deliberate divergence from cibuildwheel
    (checked live against a real 4.2.0 install, `platforms/linux.py`'s own
    `build()`: it is unconditionally fail-fast too, with no keep-going
    concept at all) -- added for a `--build` glob wide enough to span the
    whole real matrix, where a coverage sweep needs every target's own
    outcome, not just the first failure. Either way, every target actually
    attempted -- success or failure -- lands in the JSON report this
    function always writes (`report.write_report()`, in a `finally`)
    before returning or letting the exception through.
    """
    resolved = [options.build_options(t) for t in targets]
    total = len(resolved)

    # `build/<arch>*/` is cibuildmp's own scratch space (collect_output()
    # globs it, then immediately copies the .mpy into output_dir -- nothing
    # downstream ever reads it again), not something a Makefile owner is
    # expected to manage across runs. Left alone, a directory from a
    # *previous* invocation can outlive this one: two arches that share a
    # name prefix (`xtensa` / `xtensawin`) make collect_output()'s own
    # `build/{arch}*/` glob genuinely ambiguous once the shorter arch's
    # fresh directory exists alongside the longer arch's stale one, found
    # for real running this exact matrix twice in a row without cleaning in
    # between. One rmtree per distinct module_root, before anything builds,
    # keeps every run's `build/` the product of only that run.
    for module_root in dict.fromkeys(
        options.package_dir / bo.module_dir for bo in resolved
    ):
        shutil.rmtree(module_root / "build", ignore_errors=True)

    # No toolchain resolution step any more (record 0049). It existed to
    # answer "is a usable compiler for this arch on this machine, and if
    # not where do we get one" -- apt probe, pinned tarball, host
    # multilib -- and to reconcile a prefix the tarball ships with the
    # one dynruntime.mk hardcodes. Every one of those questions is
    # answered by `docker/natmod.Dockerfile` now: the image has all ten
    # arches' compilers under exactly the names dynruntime.mk expects,
    # so there is nothing to probe, nothing to download and no `CROSS=`
    # override to add.
    # The tags this specific selection actually spans, not tag_groups()'s
    # own full domain (record 0052, A2 -- that now always lists every
    # known ABI, most of which build/skip has already narrowed away by
    # the time targets reaches here).
    tags = ", ".join(dict.fromkeys(bo.target.tag for bo in resolved))
    print(f"\ncibuildmp: {total} target(s) against MicroPython {tags}")
    for index, build_options in enumerate(resolved, 1):
        print("  " + _plan_line(index, total, build_options))

    # Resolved once, not per target: the same files and version apply to
    # every identifier's own package.json (D14). Checked up front so a
    # missing extra-files entry fails before any target builds, not after
    # the first one succeeds.
    extra_files = [options.package_dir / f for f in options.extra_files()]
    for extra in extra_files:
        if not extra.is_file():
            raise BuildError(f"extra-files entry not found: {extra}")

    results: list[BuildResult] = []
    entries: list[report.ReportEntry] = []
    index = 0
    # Preserves first-appearance order (options.targets() emits one ABI
    # group at a time), not sorted -- a later tag never jumps ahead of an
    # earlier one just because it sorts first.
    build_tags = list(dict.fromkeys(bo.target.tag for bo in resolved))
    try:
        for tag in build_tags:
            group = [bo for bo in resolved if bo.target.tag == tag]
            abi = group[0].target.abi  # one ABI per tag group, by construction

            # Shared setup, paid once per ABI group rather than once per
            # target in it -- see build()'s own docstring and D9.
            print(f"\ncibuildmp: preparing MicroPython {tag}")
            group_start = time.time()
            try:
                mpy_dir = fetch_micropython(
                    tag, submodules=options.micropython_submodules
                )
                # Any arch in this tag group's own image builds mpy-cross
                # identically (see build_mpy_cross()'s own docstring -- it
                # is a host tool, portable across every natmod
                # toolchain-group image alike), so the first one picks
                # which already-required image pays for it rather than
                # pulling a fifth image just for this.
                build_mpy_cross(mpy_dir, group[0].target.arch)

                # The checkout is authoritative about the ABI;
                # targets.MPY_ABI's table (resources/build-platforms.toml,
                # record 0052 Track C) is only a way to answer the
                # question without one. A disagreement means the
                # identifiers already printed are wrong, so it stops here
                # rather than producing files labelled with an ABI they do
                # not have.
                actual_abi = read_mpy_abi(mpy_dir)
                if actual_abi != abi:
                    raise SourceError(
                        f"MicroPython {tag} has .mpy ABI {actual_abi}, but the "
                        f"identifiers were built assuming {abi} -- refresh the "
                        f"stale entry with bin/refresh_natmod_archs.py {tag}."
                    )
            except BUILD_ERRORS as exc:
                if not keep_going:
                    raise
                duration = time.time() - group_start
                print(f"cibuildmp: error: {exc}", file=sys.stderr)
                for build_options in group:
                    index += 1
                    entries.append(
                        report.entry_for_error(build_options.identifier, duration, exc)
                    )
                continue

            print(f"\ncibuildmp: building {len(group)} target(s) for MicroPython {tag}")
            for build_options in group:
                index += 1
                print("\n  " + _plan_line(index, total, build_options))
                # `{micropython}` -- a literal placeholder, substituted here
                # with `mpy_dir` itself -- lets `module-dir` name a path
                # *inside the pinned checkout* directly, the natmod mirror of
                # usermod's own `user-c-modules` placeholder (record 0071).
                # `mpy_dir` is already fetched by this point in the loop, for
                # every tag group uniformly. Record 0055's own option 2
                # ("`make-target = "all"` plus a fallback in
                # `collect_output()`") is what this exists to serve --
                # pointing straight at `{micropython}/examples/natmod/<mod>`
                # with no vendored copy. Not resolved any earlier (the
                # pre-loop `build/` cleanup above, or a `--dry-run` preview's
                # own `_plan_line()`): neither has a real `mpy_dir` to
                # substitute with yet, so both still show the literal
                # placeholder -- known, not a bug (docs/records/0072).
                module_dir = build_options.module_dir.replace(
                    "{micropython}", mpy_dir.as_posix()
                )
                module_root = options.package_dir / module_dir
                output_dir = options.package_dir / build_options.output_dir
                start = time.time()
                try:
                    result = build_target(
                        build_options,
                        mpy_dir,
                        module_root,
                        output_dir,
                        package_dir=options.package_dir,
                        extra_files=extra_files,
                        name=options.name,
                        version=options.version,
                    )
                except BUILD_ERRORS as exc:
                    duration = time.time() - start
                    print(
                        f"        FAILED after {duration:.1f}s: {exc}", file=sys.stderr
                    )
                    entries.append(
                        report.entry_for_error(build_options.identifier, duration, exc)
                    )
                    if not keep_going:
                        raise
                    continue
                results.append(result)
                entries.append(report.entry_for_result(result))
                print(f"        done in {result.duration:.1f}s -> {result.output}")
    finally:
        # Always, keep_going or not, fail-fast or not -- see the
        # docstring's own keep_going paragraph.
        report.write_report(entries, total_duration=sum(e.duration for e in entries))

    total_duration = sum(r.duration for r in results)
    print(f"\ncibuildmp: {total} target(s) built in {total_duration:.1f}s")
    for result in results:
        print(f"  {result.identifier}: {result.output.name} ({result.size} bytes)")
    write_step_summary(
        results,
        total_duration,
        build=options.build,
        skip=options.skip,
        overrides=options.overrides,
        override_error=ConfigError,
    )
    failed = len(entries) - len(results)
    if failed:
        print(
            f"cibuildmp: {failed}/{len(entries)} target(s) failed -- see the report "
            "above",
            file=sys.stderr,
        )
        return 1
    return 0


def validate_family_table(
    raw: dict[str, Any], *, error: type[Exception] = ConfigError
) -> None:
    """No-op -- part of the `PlatformModule` contract (`platforms/__init__.py`'s
    own docstring has the full reasoning), satisfied trivially here:
    natmod's one platform already *is* its only family, so there is no
    separate family-level table for a stale/misplaced key to hide in."""
    return


# Every exception Options.load()/.targets() can raise -- what cli.py's own
# coordinator catches around "load config, resolve targets" for this
# family, uniformly with usermod's own equivalent tuple.
LOAD_ERRORS: tuple[type[Exception], ...] = (
    ConfigError,
    UnknownArchError,
    UnknownTagError,
    SourceError,
)

# Every exception a real build (or the per-target build_options()
# resolution a --dry-run preview also runs) can raise.
BUILD_ERRORS: tuple[type[Exception], ...] = (ConfigError, SourceError, BuildError)


def resolve_options(
    args: Any,
    package_dir: Path,
    config_file: Path | None,
    preread: tuple[Path | None, dict[str, Any]],
) -> Options:
    """Load config and apply every CLI override `run_resolved()` and
    `cli.py`'s own `--print-build-identifiers` need -- `--output-dir` and
    `--build`/`--skip`, the same shape `usermod/__init__.py`'s own
    `resolve_options()` has."""
    options = Options.load(package_dir, config_file, preread=preread)
    if args.output_dir is not None:
        options.output_dir = args.output_dir
    if args.build is not None:
        options.build = args.build.split()
    if args.skip is not None:
        options.skip = args.skip.split()
    return options


def run_resolved(args: Any, options: Options, targets: list[Target]) -> int:
    """`--dry-run`/build for an already-resolved, already-nonempty target
    list -- the part of `run()` below that is genuinely natmod-specific.
    Loading, target resolution, `--print-build-identifiers` and the
    joint "no targets selected" decision all moved to `cli.py`'s own
    coordinator (Phase J), since none of those can be decided per family
    any more once every family is always in scope.

    No unknown-tag warning here (record 0052, Track C): every tag
    `targets` could possibly carry already passed through `abi_for_tag()`
    inside `options.targets()`, which raises `UnknownTagError` -- caught
    by whichever caller resolved `targets` -- instead of silently falling
    back to a guessed ABI. Reaching this function means every tag in play
    is a real, recorded fact.
    """
    if args.dry_run:
        total = len(targets)
        # This selection's own tags, not tag_groups()'s full domain.
        tags = ", ".join(dict.fromkeys(t.tag for t in targets))
        print(f"cibuildmp: {total} target(s) against MicroPython {tags}")
        try:
            for index, target in enumerate(targets, 1):
                print("  " + _plan_line(index, total, options.build_options(target)))
        except ConfigError as exc:
            # build_options() can still raise here -- a matched
            # [override] entry's own key is only checked against the
            # matched identifier's own platform once a target is actually
            # resolved (Phase G's tier-2 validation), so an error that
            # `targets()` above could not have caught is a real
            # possibility on the very first target this loop resolves.
            if args.debug_traceback:
                raise
            print(f"cibuildmp: error: {exc}", file=sys.stderr)
            return 2
        return 0

    try:
        return build_all(options, targets, keep_going=args.keep_going)
    except BUILD_ERRORS as exc:
        if args.debug_traceback:
            raise
        print(f"cibuildmp: error: {exc}", file=sys.stderr)
        return 2


def run(
    args: Any,
    package_dir: Path,
    config_file: Path | None,
    preread: tuple[Path | None, dict[str, Any]],
) -> int:
    """Full single-family flow: resolve, select targets,
    `--print-build-identifiers`/no-targets-selected/`run_resolved()`. Used
    directly by tests and any other caller that wants natmod alone
    without going through `cli.py`'s own coordinator, which instead calls
    `resolve_options()`/`run_resolved()` separately so it can merge this
    family's own targets with usermod's before making either of those two
    decisions."""
    try:
        options = resolve_options(args, package_dir, config_file, preread)
        targets = options.targets()
    except LOAD_ERRORS as exc:
        if args.debug_traceback:
            raise
        print(f"cibuildmp: error: {exc}", file=sys.stderr)
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

    return run_resolved(args, options, targets)

"""natmod: the platform family for `dynruntime.mk`-based native modules --
one build per ARCH, no MicroPython port build of its own.

Also natmod's own half of CLI dispatch (Phase H, record 0051): this
module implements the `PlatformModule` contract every entry in
`platforms.PLATFORM_FAMILY` satisfies -- `resolve_options()` (load config,
apply CLI overrides) and `run()` (the actual `--dry-run`/`--only`/
`--print-build-identifiers`/`--allow-empty`/build dispatch). `cli.py`'s
own `main()` never calls into this module by name: it looks natmod up in
`PLATFORM_FAMILY` like every other platform and calls the same two
functions, uniformly. `build_all()` lives here too -- everything
downstream of "this invocation is a natmod build". What stays in `cli.py`
is only what is genuinely shared across every family: the one argument
parser, `active_platforms()`, and the cache-clean/config-read/platform-
resolve preamble that has to run before any family can be chosen.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

from ...sources import (
    SourceError,
    build_mpy_cross,
    fetch_micropython,
    read_mpy_abi,
)
from ...stepsummary import write_step_summary
from .build import BuildError, BuildResult, build_target
from .options import BuildOptions, ConfigError, Options
from .targets import NATMOD_ARCHS, Target, UnknownArchError, UnknownTagError


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


def build_all(options: Options, targets: list[Target]) -> int:
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
    index = 0
    # Preserves first-appearance order (options.targets() emits one ABI
    # group at a time), not sorted -- a later tag never jumps ahead of an
    # earlier one just because it sorts first.
    build_tags = list(dict.fromkeys(bo.target.tag for bo in resolved))
    for tag in build_tags:
        group = [bo for bo in resolved if bo.target.tag == tag]
        abi = group[0].target.abi  # one ABI per tag group, by construction

        # Shared setup, paid once per ABI group rather than once per target
        # in it -- see build()'s own docstring and D9.
        print(f"\ncibuildmp: preparing MicroPython {tag}")
        mpy_dir = fetch_micropython(tag, submodules=options.micropython_submodules)
        build_mpy_cross(mpy_dir)

        # The checkout is authoritative about the ABI; targets.MPY_ABI's
        # table (resources/build-platforms.toml, record 0052 Track C) is
        # only a way to answer the question without one. A disagreement
        # means the identifiers already printed are wrong, so it stops
        # here rather than producing files labelled with an ABI they do
        # not have.
        actual_abi = read_mpy_abi(mpy_dir)
        if actual_abi != abi:
            raise SourceError(
                f"MicroPython {tag} has .mpy ABI {actual_abi}, but the "
                f"identifiers were built assuming {abi} -- refresh the stale "
                f"entry with bin/refresh_natmod_archs.py {tag}."
            )

        print(f"\ncibuildmp: building {len(group)} target(s) for MicroPython {tag}")
        for build_options in group:
            index += 1
            print("\n  " + _plan_line(index, total, build_options))
            module_root = options.package_dir / build_options.module_dir
            output_dir = options.package_dir / build_options.output_dir
            result = build_target(
                build_options,
                mpy_dir,
                module_root,
                output_dir,
                package_dir=options.package_dir,
                extra_files=extra_files,
                version=options.version,
            )
            results.append(result)
            print(f"        done in {result.duration:.1f}s -> {result.output}")

    total_duration = sum(r.duration for r in results)
    print(f"\ncibuildmp: {total} target(s) built in {total_duration:.1f}s")
    for result in results:
        print(f"  {result.identifier}: {result.output.name} ({result.size} bytes)")
    write_step_summary(results, total_duration)
    return 0


def validate_family_table(
    raw: dict[str, Any], *, error: type[Exception] = ConfigError
) -> None:
    """No-op -- part of the `PlatformModule` contract (`platforms/__init__.py`'s
    own docstring has the full reasoning), satisfied trivially here:
    natmod's one platform already *is* its only family, so there is no
    separate family-level table (no `[natmod-family]` alongside
    `[natmod]`) for a stale/misplaced key to hide in. `[natmod]`'s own
    keys are validated where they always have been, inside
    `resolve_options()` below."""
    return


def resolve_options(
    args: Any,
    package_dir: Path,
    config_file: Path | None,
    preread: tuple[Path | None, dict[str, Any]],
    *,
    ports: list[str],
) -> Options:
    """Load config and apply every CLI override that both `run()` and
    `cli.py`'s own `--print-build-identifiers`/`--only` narrowing need --
    previously duplicated between the two (`cli.py`'s own
    `_print_build_identifiers()` and this module's `run()`, both applying
    `--output-dir`/`--archs` the same way, Phase H).
    """
    assert ports == ["natmod"], (
        f"natmod is always exactly one platform, got ports={ports!r}"
    )
    options = Options.load(package_dir, config_file, preread=preread)
    if args.output_dir is not None:
        options.output_dir = args.output_dir
    if args.archs is not None:
        options.archs = (
            list(NATMOD_ARCHS)
            if args.archs.strip() == "all"
            else [a.strip() for a in args.archs.split(",") if a.strip()]
        )
    return options


def run(
    args: Any,
    package_dir: Path,
    config_file: Path | None,
    preread: tuple[Path | None, dict[str, Any]],
    *,
    ports: list[str],
) -> int:
    try:
        options = resolve_options(args, package_dir, config_file, preread, ports=ports)
        targets = options.targets()
    except (ConfigError, UnknownArchError, UnknownTagError, SourceError) as exc:
        if args.debug_traceback:
            raise
        print(f"cibuildmp: error: {exc}", file=sys.stderr)
        return 2

    if args.only is not None:
        # --only overrides archs/build/skip and is resolved against every
        # identifier this config can name, not the ones it selects
        # (**0045**). The comment that used to sit here claimed exactly
        # this as already-matching cibuildwheel semantics, and it was not:
        # `options.targets()` above has already applied `build`/`skip`, so
        # filtering *that* list could never override them, and a target
        # dropped by `skip` was gone before this line ran. A divergence
        # documented as parity is worse than an open one.
        known = options.all_targets()
        targets = [t for t in known if t.identifier == args.only]
        if not targets:
            print(
                f"cibuildmp: error: --only {args.only!r} is not a known "
                f"identifier. Known: "
                f"{', '.join(t.identifier for t in known)}",
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
        if args.allow_empty:
            print("cibuildmp: no targets selected")
            return 0
        print(
            "cibuildmp: error: no targets selected. Pass --allow-empty if that "
            "is expected.",
            file=sys.stderr,
        )
        return 2

    # No unknown-tag warning here any more (record 0052, Track C): every
    # tag `targets` above could possibly carry already passed through
    # `abi_for_tag()` inside `options.targets()`, which now raises
    # `UnknownTagError` -- caught above -- instead of silently falling
    # back to a guessed ABI. Reaching this line means every tag in play
    # is a real, recorded fact.

    if args.dry_run:
        total = len(targets)
        # Same reasoning as build()'s own tags line: this selection's own
        # tags, not tag_groups()'s full domain.
        tags = ", ".join(dict.fromkeys(t.tag for t in targets))
        print(f"cibuildmp: {total} target(s) against MicroPython {tags}")
        try:
            for index, target in enumerate(targets, 1):
                print("  " + _plan_line(index, total, options.build_options(target)))
        except ConfigError as exc:
            # build_options() can still raise here -- a matched
            # [[overrides]] entry's own key is only checked against the
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
        return build_all(options, targets)
    except (ConfigError, SourceError, BuildError) as exc:
        if args.debug_traceback:
            raise
        print(f"cibuildmp: error: {exc}", file=sys.stderr)
        return 2

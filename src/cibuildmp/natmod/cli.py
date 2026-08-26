"""natmod's own half of the CLI dispatch.

The mirror image of `usermod/cli.py`, and created for the same reason its
docstring already gives: `cli.py`'s `main()` resolves build mode
(`detect_mode()`) and then hands off, rather than carrying one mode's
dispatch inline while the other lives in its own module. `main()` now
calls `natmod_cli.run(...)` and `usermod_cli.run(...)` through the
identical four-argument signature, so the two halves are symmetric at the
call site and neither is the privileged "default" one that happens to be
written in the dispatcher.

`build()` lives here too, with the `--dry-run`/`--only`/
`--print-build-identifiers`/`--print-build-matrix`/`--allow-empty`
handling that feeds it -- everything downstream of "this invocation is a
natmod build". What stays in `cli.py` is only what is genuinely shared:
the argument parser (one CLI, both modes), `detect_mode()`, and the
cache-clean/config-read/mode-resolve preamble that has to run before
either half can be chosen.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

from .build import BuildError, BuildResult, build_target
from .options import BuildOptions, ConfigError, Options
from .sources import (
    SourceError,
    build_mpy_cross,
    fetch_micropython,
    read_mpy_abi,
)
from .stepsummary import write_step_summary
from .targets import (
    LATEST_KNOWN_ABI,
    NATMOD_ARCHS,
    Target,
    UnknownArchError,
    is_abi_known,
)
from .toolchains import ResolvedToolchain, ToolchainError, resolve


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


def run(
    args: Any,
    package_dir: Path,
    config_file: Path | None,
    preread: tuple[Path | None, dict[str, Any]],
) -> int:
    try:
        options = Options.load(package_dir, config_file, preread=preread)
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

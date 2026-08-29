#!/usr/bin/env python3
"""Plan `test-all-platforms.yml`'s own job matrix: every identifier a real
`build`/`skip` selection resolves to, in the order cibuildmp itself finds
them, packed into at most `--max-buckets` (default 20) buckets so no CI run
ever queues more concurrent jobs than that against the account's own shared
concurrency budget -- the bottleneck a real run measured directly ([0044]'s
own 2026-08-29 addendum: 30/238 legs finished in the first eight minutes of
a one-job-per-identifier run, then nothing progressed for 35+ more).

    PYTHONPATH=src python3 bin/plan_test_matrix.py examples/template \\
        --build "v1.29.0-* v1.28.0-* mpy6.3-v1.29.0-* mpy6.3-v1.28.0-*" \\
        --skip "v1.28.0-qemu-NETDUINO2" \\
        --max-buckets 20

Prints one JSON object to stdout: `identifiers` (the full ordered list --
what a caller's own final summary should order its rows by, see
[0065]) and `buckets` (each `{label, runner, build}`, `build` already a
space-separated `--build` value ready to hand a `cibuildmp` invocation).

Deliberately **not** stdlib-only, unlike every other script in this
directory (`refresh_*.py`/`update_docker.py`'s own header comments are
explicit about that choice) -- this script's entire job is to mirror
cibuildmp's own real target resolution exactly, and reimplementing that by
re-parsing identifier strings with regexes is precisely the "resembles
upstream/itself and drifts" failure mode CLAUDE.md's own first rule is
about, just aimed at this project's own internals instead of cibuildwheel's.
Imports `cibuildmp` straight from `src/` (`PYTHONPATH=src`, no install
step) rather than an installed package -- confirmed live that this needs
neither of the project's own two runtime deps (`pyelftools`, `ar`): target
resolution never imports `platforms/natmod/build.py`'s own elftools use,
only `.targets()`/`dockerrun.image_for()`, both pure.

Weights are a static, coarse table (seconds per identifier, keyed by image
group name), seeded from one real run's own measured per-image averages
([0044]'s own 2026-08-29 addendum, run [33220563659]) -- not a live
history. Nothing yet records a genuine per-identifier duration history to
refine this from (the JSON report [0063] added *would* let a future
version do that, from enough real runs' own reports; not attempted here).

[0044]: docs/records/0044-unix-native-images-landed.md
[0063]: docs/records/0063-keep-going-and-json-build-report.md
[0065]: docs/records/0065-bucketed-test-matrix-planning.md
[33220563659]: https://github.com/ballistics-lab/cibuildmp/actions/runs/33220563659
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cibuildmp import cli, dockerrun
from cibuildmp.platforms import natmod as natmod_family
from cibuildmp.platforms.natmod.options import read_config

# Seconds per identifier, by image group name (dockerrun.image_for()'s own
# return value, last path segment, digest stripped) -- seeded from
# run 33220563659's own real per-(image, tag) averages, blended across tags
# and, for arm_embedded, across the three ports that share it (rp2's own
# 192s dominates its 93-identifier weight; qemu/natmod's much cheaper
# legs on the same image would be over-weighted by rp2's own average, but
# under-weighting them costs far less than a lopsided bucket would).
_WEIGHTS: dict[str, float] = {
    "esp_idf_base": 268,
    "arm_embedded": 180,
    "riscv_embedded": 80,
    "windows": 95,
    "webassembly": 130,
    "natmod_host": 60,
    "xtensa_esp": 70,
    "xtensa_lx106": 55,
    "ppc64le_linux": 85,
}
# unix's own emulated-everywhere cells (ppc64le/s390x/riscv64, both libcs) --
# real QEMU execution, not just an emulated compile, ~15-20 real minutes
# each (record 0044's own addendum). Matched by arch suffix, not image name:
# unix's image *is* the target (record 0043/0044), so there is no shared
# group name to key these on the way arm_embedded/esp_idf_base have one.
_EMULATED_UNIX_SUFFIXES = ("_ppc64le", "_s390x", "_riscv64")
_EMULATED_UNIX_WEIGHT = 1050.0
# Every unix native image (fifteen of them, one per cell) and anything this
# table has never seen (a future port) -- close to the measured range for
# every unmatched cell in the real run (100-150s).
_DEFAULT_WEIGHT = 125.0

# unix identifiers are the only ones ever native to GitHub's own arm64
# runner (record 0044's own measurement: AArch32-at-EL0 covers armv7l too)
# -- every other port's image is linux/amd64 regardless of target arch
# (record 0058), so classifying by suffix here, rather than walking every
# port's own axis, stays correct as ports are added.
_ARM64_UNIX_SUFFIXES = ("_aarch64", "_armv7l")


@dataclass
class _Entry:
    identifier: str
    weight: float
    runner: str
    group: tuple[str | None, str]  # (image, tag) -- batching's own unit


def _image_short_name(image: str | None) -> str | None:
    if image is None:
        return None
    return image.rsplit("/", 1)[-1].split("@", 1)[0]


def _weight_for(image: str | None, identifier: str) -> float:
    name = _image_short_name(image)
    if name in _WEIGHTS:
        return _WEIGHTS[name]
    if identifier.endswith(_EMULATED_UNIX_SUFFIXES):
        return _EMULATED_UNIX_WEIGHT
    return _DEFAULT_WEIGHT


def _runner_for(port: str, identifier: str) -> str:
    if port == "unix" and identifier.endswith(_ARM64_UNIX_SUFFIXES):
        return "ubuntu-24.04-arm"
    return "ubuntu-latest"


def resolve_entries(
    package_dir: Path, build: str | None, skip: str | None
) -> list[_Entry]:
    """Every identifier a real `build`/`skip` selection resolves to, in
    `cli.py`'s own coordinator order (natmod first, then usermod; within
    each, one tag group at a time) -- the same order `--print-build-
    identifiers` itself would print, since that is exactly what this
    walks. Raises the parser's own SystemExit for a config/selection error
    -- a broken plan should fail the `plan` job loudly, not silently
    produce an empty matrix.
    """
    parser = cli.build_parser()
    argv = [str(package_dir)]
    if build:
        argv += ["--build", build]
    if skip:
        argv += ["--skip", skip]
    args = parser.parse_args(argv)

    preread = read_config(args.package_dir, args.config_file)
    resolved = cli._resolve_all(args, args.package_dir, args.config_file, preread)
    if isinstance(resolved, int):
        sys.exit(resolved)

    entries: list[_Entry] = []
    for family, _options, targets in resolved:
        is_natmod = family is natmod_family
        for target in targets:
            port = "natmod" if is_natmod else target.port
            axis_target = target.arch if is_natmod else (target.arch or None)
            image = dockerrun.image_for(port, axis_target)
            entries.append(
                _Entry(
                    identifier=target.identifier,
                    weight=_weight_for(image, target.identifier),
                    runner=_runner_for(port, target.identifier),
                    group=(image, target.tag),
                )
            )
    return entries


def _pack_one_runner(entries: list[_Entry], n_buckets: int) -> list[list[_Entry]]:
    """LPT bin-packing (largest-first, into the currently lightest bucket)
    over chunks, not individual entries -- a "chunk" is every entry sharing
    one `(image, tag)` (`_Entry.group`), in first-appearance order, so
    batching an oversized port never scatters it across buckets one
    identifier at a time and losing the point of batching (a shared
    MicroPython checkout/mpy-cross/image pull per group, [0063]'s own
    keep_going docstring) -- weight alone cannot stand in for this: most
    of unix's fifteen native cells share the same default weight while
    every one of them is still a genuinely distinct image. A chunk
    heavier than ~1.5x this runner's own fair per-bucket share is first
    split into near-equal, still-contiguous sub-chunks (same group,
    several buckets), so one huge port (esp32's 83 identifiers, rp2's 74)
    does not have to land in a single bucket.
    """
    n_buckets = max(1, min(n_buckets, len(entries)))
    total = sum(e.weight for e in entries) or 1.0
    target = total / n_buckets

    chunk_by_group: dict[tuple[str | None, str], list[_Entry]] = {}
    for entry in entries:
        chunk_by_group.setdefault(entry.group, []).append(entry)
    chunks = list(chunk_by_group.values())

    split_chunks: list[list[_Entry]] = []
    for chunk in chunks:
        chunk_weight = sum(e.weight for e in chunk)
        pieces = round(chunk_weight / target) if chunk_weight > target * 1.5 else 1
        pieces = max(1, min(pieces, len(chunk)))
        if pieces == 1:
            split_chunks.append(chunk)
            continue
        size = -(-len(chunk) // pieces)  # ceil division
        for i in range(0, len(chunk), size):
            split_chunks.append(chunk[i : i + size])

    buckets: list[list[_Entry]] = [[] for _ in range(n_buckets)]
    weights = [0.0] * n_buckets
    for chunk in sorted(split_chunks, key=lambda c: -sum(e.weight for e in c)):
        i = min(range(n_buckets), key=lambda i: weights[i])
        buckets[i] += chunk
        weights[i] += sum(e.weight for e in chunk)

    return [b for b in buckets if b]


def make_buckets(entries: list[_Entry], max_buckets: int) -> list[dict[str, object]]:
    """Partition by runner first -- a job has exactly one `runs-on`, so an
    arm64-native identifier and an amd64-native one can never share a
    bucket -- then split `max_buckets` across runners proportionally to
    each one's own share of total estimated weight (never fewer than one
    bucket for a non-empty runner, never more than `max_buckets` total).
    """
    by_runner: dict[str, list[_Entry]] = {}
    for e in entries:
        by_runner.setdefault(e.runner, []).append(e)

    total_weight = sum(e.weight for e in entries) or 1.0
    runners = sorted(by_runner, key=lambda r: -sum(e.weight for e in by_runner[r]))
    counts = {
        r: max(
            1, round(sum(e.weight for e in by_runner[r]) / total_weight * max_buckets)
        )
        for r in runners
    }
    while sum(counts.values()) > max_buckets:
        r = max(counts, key=lambda r: counts[r])
        counts[r] -= 1
    while sum(counts.values()) < max_buckets and any(
        counts[r] < len(by_runner[r]) for r in runners
    ):
        r = max(
            (r for r in runners if counts[r] < len(by_runner[r])),
            key=lambda r: sum(e.weight for e in by_runner[r]) / counts[r],
        )
        counts[r] += 1

    result: list[dict[str, object]] = []
    for r in runners:
        packed = _pack_one_runner(by_runner[r], counts[r])
        width = len(str(len(packed)))
        runner_label = "arm64" if r == "ubuntu-24.04-arm" else "amd64"
        for index, bucket in enumerate(packed, 1):
            result.append(
                {
                    "label": f"{runner_label}-{index:0{width}}",
                    "runner": r,
                    "build": " ".join(e.identifier for e in bucket),
                    "estimated_seconds": round(sum(e.weight for e in bucket)),
                }
            )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("package_dir", nargs="?", default=".", type=Path)
    parser.add_argument("--build", default=None)
    parser.add_argument("--skip", default=None)
    parser.add_argument("--max-buckets", type=int, default=20)
    args = parser.parse_args(argv)

    entries = resolve_entries(args.package_dir, args.build, args.skip)
    buckets = make_buckets(entries, args.max_buckets)
    json.dump(
        {"identifiers": [e.identifier for e in entries], "buckets": buckets},
        sys.stdout,
        indent=2,
    )
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

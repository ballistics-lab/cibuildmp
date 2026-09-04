"""A JSON build report -- every attempted target's own outcome, written once
per invocation, success and failure alike.

Exists for `--keep-going` ([0063]): a fail-fast run's own stdout and step
summary already say which target failed and stop there, but a keep-going
sweep across a wide `--build` glob needs something a caller can parse
*afterwards* to know which of many targets failed and which of the rest
still succeeded -- `$GITHUB_STEP_SUMMARY` only ever sees one job's own
results (`stepsummary.py`'s own module docstring), and `write_step_summary()`
only takes successes (its `_Result` protocol has no `error` field at all,
and never will -- a real build's own output/size do not exist for a target
that never finished).

Written on every invocation, not gated on `--keep-going` -- a plain
fail-fast run gets a one-entry-short report the moment something fails
(whatever built before the failure, plus the failure itself), which is
already useful on its own and costs nothing extra to produce.

One JSON file per invocation, named from a UTC timestamp plus a short
random suffix (not overwritten, not appended to -- unlike
`$GITHUB_STEP_SUMMARY`, nothing names one report file across more than one
`cibuildmp` invocation, so there is no multiple-calls-per-step problem
`stepsummary.py`'s own `open(path, "a")` exists to solve). Directory
defaults to `<package_dir>/<output_dir>/reports` (it was
`cache_root() / "reports"` until [0095] -- see `report_dir()` for why that
was the wrong root), overridable with `CIBMP_REPORT_PATH` -- the same
one-env-var-per-path-setting shape `CIBMP_CACHE_PATH` already has
(`sources.cache_root()`), not the `opt()`/`cibuildmp.toml` cascade: this
is a runtime/CI knob about *where output lands*, not a per-project build
setting, the same category `CIBMP_DISABLE_GITHUB_STEP_SUMMARY`
(`stepsummary.py`) already lives in.

Both `BuildResult` (natmod, `platforms/natmod/build.py`) and
`UsermodBuildResult` (usermod, `platforms/usermod/orchestrate.py`) already
expose the four fields `entry_for_result()` needs (`identifier`, `output`,
`size`, `duration`) -- duck-typed here via the same `_Result` protocol
shape `stepsummary.py` already uses, rather than importing either
dataclass, so this module depends on neither family.

[0063]: docs/records/0063-keep-going-and-json-build-report.md
[0095]: docs/records/0095-cache-root-splits-source-from-build-state.md
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol


class _Result(Protocol):
    @property
    def identifier(self) -> str: ...

    @property
    def output(self) -> Path: ...

    @property
    def size(self) -> int: ...

    @property
    def duration(self) -> float: ...


@dataclass(frozen=True)
class ReportEntry:
    identifier: str
    duration: float
    error: str | None = None
    output_dir: str | None = None
    size: int | None = None
    files: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "duration": self.duration,
            "error": self.error,
            "output_dir": self.output_dir,
            "size": self.size,
            "files": list(self.files),
        }


def entry_for_result(result: _Result) -> ReportEntry:
    """A successful entry -- `output_dir`/`files` describe the whole
    directory the target's output lives in (`output_dir/<identifier>/`,
    both families), not just the one file `result.output` names -- D14's
    packaging step (natmod's own `package.json`) and usermod's frozen
    manifest can both leave more than one file there."""
    output_dir = result.output.parent
    try:
        files = tuple(sorted(p.name for p in output_dir.iterdir()))
    except OSError:
        files = ()
    return ReportEntry(
        identifier=result.identifier,
        duration=result.duration,
        output_dir=str(output_dir),
        size=result.size,
        files=files,
    )


def entry_for_error(
    identifier: str, duration: float, error: BaseException
) -> ReportEntry:
    return ReportEntry(identifier=identifier, duration=duration, error=str(error))


def report_dir(package_dir: Path, output_dir: Path) -> Path:
    """Where the JSON build report goes.

    Under the build's own output directory since [0095], not under
    `cache_root()`. A report is **output** -- written host-side by
    cibuildmp's own Python after every container has exited, never by a
    container -- and `cache_root()` is fetched input a CI job may restore
    from an earlier run. Rooting reports there put the newest run's own
    result in the one directory a cache restore can overwrite with an
    older run's, and split cibuildmp's two host-written outputs across two
    roots for no reason anyone could state.

    `output_dir` is resolved against `package_dir` (never the process's
    own cwd) exactly as `usermod.orchestrate.build_one()` and
    `natmod/cli.py` already resolve it for the artifacts themselves --
    that join is not a detail to re-derive per call site, a real Docker
    action run having already caught the unjoined version writing to
    `<repo-root>/mpyhouse`.

    `CIBMP_REPORT_PATH` still wins outright, unchanged: [0063] added it
    for exactly the case where the report has to land somewhere neither
    default reaches (a runner step that uploads it separately).
    """
    env = os.environ.get("CIBMP_REPORT_PATH")
    if env:
        return Path(env).expanduser()
    return package_dir / output_dir / "reports"


def write_report(
    entries: Sequence[ReportEntry],
    *,
    total_duration: float,
    package_dir: Path,
    output_dir: Path,
) -> Path:
    """Write `entries` (in build order, successes and failures both) as one
    JSON file under `report_dir()`, creating it if needed, and return the
    path written. Never raises for an empty `entries` -- a group-level
    failure under `--keep-going` (a bad fetch, before any target in that
    group even started) can leave a report with zero results and one
    failure, or a truly empty run reaches this with nothing at all."""
    directory = report_dir(package_dir, output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"report-{stamp}-{uuid.uuid4().hex[:8]}.json"
    failed = sum(1 for e in entries if e.error is not None)
    payload = {
        "generated_at": now.isoformat(),
        "total_duration": total_duration,
        "built": len(entries) - failed,
        "failed": failed,
        "results": [e.as_dict() for e in entries],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path

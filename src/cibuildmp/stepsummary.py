"""A real GitHub Actions job summary -- the way cibuildwheel's own action
already does it: an HTML table of what got built, visible directly on the
Action run's own Summary page, not just buried in raw log lines
([0029], the user's own explicit ask).

[0047]'s own 2026-08-28 addendum found this only had parity of *intent*
with cibuildwheel's own `Logger._github_step_summary` (`logger.py`), not
of content or shape -- this module now matches column-for-column: an
optional resolved-options block, then Output/Size/Build identifier/Time/
SHA256, then a right-aligned "N built in <duration>" footer. Two
deliberate departures, both argued in the addendum and kept here:

- **`open(path, "a")` -- append, not upstream's own truncating
  `write_text()`.** `$GITHUB_STEP_SUMMARY` names one file per *step*, and
  upstream's truncate is safe because one step runs cibuildwheel exactly
  once. cibuildmp is invoked more than once per step in real workflows
  (`build-examples.yml`'s own per-runner globs run this composite action
  three times inside one job) -- truncating would silently keep only the
  last table.
- **Sizes/durations are hand-formatted, not `humanize.naturalsize`/
  `naturaldelta`.** `pyproject.toml`'s own comment is explicit: stdlib
  only, `pyelftools`/`ar` are the two deliberate exceptions, both load-
  bearing for linking a `.mpy` ([0012]). A formatting-only dependency
  does not clear that bar.

A standalone module, not folded into either `cli.py` -- `cli.py` already
imports `platforms/usermod/__init__.py` for dispatch, so a shared helper living in either
one would make the other import it back, a circular import. Both
`BuildResult` (natmod, `build.py`) and `UsermodBuildResult` (usermod,
`orchestrate.py`) already expose the same four fields this needs
(`identifier`, `output`, `size`, `duration`) -- duck-typed here rather
than importing either dataclass, so this module depends on neither.
`matching_overrides()` (this project's own top-level `options.py`, not
either family's) is the one shared import the options block needs, and
introduces no cycle: neither family module imports `stepsummary` back.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from .options import matching_overrides


class _Result(Protocol):
    @property
    def identifier(self) -> str: ...

    @property
    def output(self) -> Path: ...

    @property
    def size(self) -> int: ...

    @property
    def duration(self) -> float: ...


def _natural_size(num_bytes: int) -> str:
    """Decimal (SI) byte count, one decimal place once it crosses 1000 --
    the same shape `humanize.naturalsize()` renders (e.g. "696.9 kB" for
    696984), without the dependency (see module docstring)."""
    if num_bytes < 1000:
        return f"{num_bytes} Byte" if num_bytes == 1 else f"{num_bytes} Bytes"
    value = float(num_bytes)
    for unit in ("kB", "MB", "GB", "TB"):
        value /= 1000
        if value < 1000:
            return f"{value:.1f} {unit}"
    return f"{value:.1f} PB"


def _natural_duration(seconds: float) -> str:
    """ "N seconds"/"N minutes, N seconds"/... -- `humanize.naturaldelta()`'s
    shape for a positive duration, without the dependency (see module
    docstring). Sub-minute durations keep one decimal place -- a real
    build is rarely under a second, and rounding to whole seconds there
    would make every fast target read as "0 seconds"."""
    if seconds < 60:
        return f"{seconds:.1f} second" + ("" if seconds == 1 else "s")
    minutes, rest = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours} hour" + ("" if hours == 1 else "s"))
    if minutes:
        parts.append(f"{minutes} minute" + ("" if minutes == 1 else "s"))
    if not hours and rest:
        parts.append(f"{rest} second" + ("" if rest == 1 else "s"))
    return ", ".join(parts)


def _sha256(path: Path) -> str | None:
    """`None` for anything that cannot be read (e.g. `--dry-run`'s own
    preview path, or a test double with no real file) rather than raising
    -- a missing digest degrades the cell, it does not break the summary."""
    try:
        with open(path, "rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()
    except OSError:
        return None


def _options_block(
    build: Sequence[str],
    skip: Sequence[str],
    overrides: Sequence[Mapping[str, Any]],
    results: Sequence[_Result],
    override_error: type[Exception],
) -> str:
    """ "what was this run *asked* to do" -- the piece [0047]'s addendum
    calls the most valuable missing part of the old summary. Not a real
    YAML dump of `Options.summary()` the way upstream's is (no such
    renderer exists here yet, and building one is its own piece of work
    the addendum leaves open) -- just `build`/`skip` as configured, plus
    every `[override]` whose `select` actually matched one of this run's
    own built identifiers, deduplicated by that glob."""
    lines = [
        f"build: {' '.join(build) or '(none)'}",
        f"skip: {' '.join(skip) or '(none)'}",
    ]
    matched: dict[str, Mapping[str, Any]] = {}
    for result in results:
        for override in matching_overrides(
            overrides, result.identifier, error=override_error
        ):
            matched.setdefault(str(override["select"]), override)
    if matched:
        lines.append("")
        lines.append("overrides matched:")
        for select, override in matched.items():
            keys = ", ".join(k for k in override if k != "select")
            lines.append(f"  {select!r}: {keys}" if keys else f"  {select!r}")
    return "\n".join(lines)


def write_step_summary(
    results: Sequence[_Result],
    total_duration: float,
    *,
    build: Sequence[str] = (),
    skip: Sequence[str] = (),
    overrides: Sequence[Mapping[str, Any]] = (),
    override_error: type[Exception] = ValueError,
) -> None:
    """Append an HTML build table to `$GITHUB_STEP_SUMMARY`.

    A no-op whenever that env var is unset -- every local run, and any CI
    system that isn't GitHub Actions (matches cibuildwheel's own behaviour
    of never requiring GitHub Actions specifically). Runs *in addition to*
    the caller's own plain-text stdout summary, not instead of it -- that
    stays what a local run or a non-GitHub CI system sees.

    Also a no-op when CIBMP_DISABLE_GITHUB_STEP_SUMMARY is set -- a caller
    that fans out across many jobs against the same `$GITHUB_STEP_SUMMARY`
    convention (a matrix leg, one per real identifier) gets one native
    per-target table per leg whether it wants that or a single aggregated
    summary built some other way; this is the escape hatch for the latter.
    Same ad hoc os.environ.get(...) not in {"", "0"} parsing as
    CIBMP_DEBUG_TRACEBACK (cli.py) -- a behaviour toggle, not a
    `cibuildmp.toml` config key, so it deliberately skips options.py's own
    `opt()`.

    `build`/`skip`/`overrides` are optional and render nothing (no
    `<details>` block at all) when omitted -- a caller with no
    `Options`/`UsermodOptions` at hand (a test, a future caller) still
    gets a valid table.
    """
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    if os.environ.get("CIBMP_DISABLE_GITHUB_STEP_SUMMARY", "") not in {"", "0"}:
        return

    lines = ["### cibuildmp", ""]

    if build or skip or overrides:
        lines += [
            "<details>",
            "<summary>Build options</summary>",
            "",
            "```",
            _options_block(build, skip, overrides, results, override_error),
            "```",
            "",
            "</details>",
            "",
        ]

    lines.append(
        "<table><tr>"
        '<th align="left">Output</th>'
        '<th align="left">Size</th>'
        '<th align="left">Build identifier</th>'
        '<th align="left">Time</th>'
        '<th align="left">SHA256</th>'
        "</tr>"
    )
    for result in results:
        digest = _sha256(result.output) or "&mdash;"
        lines.append(
            "<tr>"
            f"<td nowrap><samp>{result.output.name}</samp></td>"
            f"<td nowrap>{_natural_size(result.size)}</td>"
            f"<td nowrap><samp>{result.identifier}</samp></td>"
            f"<td nowrap>{_natural_duration(result.duration)}</td>"
            f"<td nowrap><samp>{digest}</samp></td>"
            "</tr>"
        )
    lines.append("</table>")
    lines.append("")

    n = len(results)
    lines.append(
        f'<div align="right"><sup>{n} target{"" if n == 1 else "s"} built in '
        f"{_natural_duration(total_duration)}</sup></div>"
    )
    lines.append("")
    lines.append("---")

    with open(path, "a") as f:
        f.write("\n".join(lines) + "\n")

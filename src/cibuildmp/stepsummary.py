"""A real GitHub Actions job summary -- the way cibuildwheel's own action
already does it: a Markdown table of what got built, visible directly on
the Action run's own Summary page, not just buried in raw log lines
(docs/BACKLOG.md's own D29, the user's own explicit ask).

A standalone module, not folded into either `cli.py` -- `cli.py` already
imports `usermod.cli` for dispatch, so a shared helper living in either
one would make the other import it back, a circular import. Both
`BuildResult` (natmod, `build.py`) and `UsermodBuildResult` (usermod,
`orchestrate.py`) already expose the same three fields this needs
(`identifier`, `output`, `size`) -- duck-typed here rather than importing
either dataclass, so this module depends on neither.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol


class _Result(Protocol):
    @property
    def identifier(self) -> str: ...

    @property
    def output(self) -> Path: ...

    @property
    def size(self) -> int: ...


def write_step_summary(results: Sequence[_Result], total_duration: float) -> None:
    """Append a Markdown table of `results` to `$GITHUB_STEP_SUMMARY`.

    A no-op whenever that env var is unset -- every local run, and any CI
    system that isn't GitHub Actions (matches cibuildwheel's own behaviour
    of never requiring GitHub Actions specifically). Runs *in addition to*
    the caller's own plain-text stdout summary, not instead of it -- that
    stays what a local run or a non-GitHub CI system sees.
    """
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return

    lines = [
        f"### cibuildmp: {len(results)} target(s) built in {total_duration:.1f}s",
        "",
        "| Identifier | File | Size |",
        "| --- | --- | ---: |",
    ]
    for result in results:
        lines.append(
            f"| `{result.identifier}` | `{result.output.name}` | "
            f"{result.size:,} bytes |"
        )

    with open(path, "a") as f:
        f.write("\n".join(lines) + "\n")

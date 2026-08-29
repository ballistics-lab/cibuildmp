#!/usr/bin/env python3
"""Build `test-all-platforms.yml`'s own step-summary table from every
bucket's own JSON build report ([0063]), read straight off the artifacts
`test-platforms.yml`'s own build job uploads.

    python3 bin/render_test_summary.py reports/ identifiers.json

`reports/` holds one or more `report-*.json` files (one per bucket,
[0063]'s own `report.write_report()` shape: `{"results": [{"identifier",
"duration", "error", ...}, ...]}`). `identifiers.json` is `plan_test_
matrix.py`'s own `identifiers` array -- the full, ordered list every
bucket's own selection was carved out of, and the order this table's own
rows are printed in ([0065]'s own explicit requirement: the same order
cibuildmp itself finds them, not upload-completion order, and no longer
the old `aggregate-results`'s own `sort`).

An identifier with no matching report entry at all (its own bucket's job
never got far enough to write one -- a runner failure, a checkout
failure, anything before `orchestrate.build()`/`build_all()`'s own
`try`/`finally`) still gets its own row, marked distinctly from a real
build failure rather than silently vanishing from the table.

[0063]: docs/records/0063-keep-going-and-json-build-report.md
[0065]: docs/records/0065-bucketed-test-matrix-planning.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_results(reports_dir: Path) -> dict[str, dict]:
    by_identifier: dict[str, dict] = {}
    for report_file in sorted(reports_dir.glob("**/*.json")):
        payload = json.loads(report_file.read_text())
        for result in payload.get("results", []):
            by_identifier[result["identifier"]] = result
    return by_identifier


def render(identifiers: list[str], by_identifier: dict[str, dict]) -> str:
    built = sum(
        1
        for i in identifiers
        if i in by_identifier and by_identifier[i]["error"] is None
    )
    failed_rows: list[tuple[str, str]] = []

    lines = ["### Test platforms", "", f"{built}/{len(identifiers)} passed", ""]
    lines.append("| Identifier | Result | Time |")
    lines.append("| --- | --- | --- |")
    for identifier in identifiers:
        entry = by_identifier.get(identifier)
        if entry is None:
            lines.append(f"| `{identifier}` | ⚠️ no report | — |")
            continue
        duration = f"{entry['duration']:.1f}s"
        if entry["error"] is None:
            lines.append(f"| `{identifier}` | ✅ | {duration} |")
        else:
            lines.append(f"| `{identifier}` | ❌ | {duration} |")
            failed_rows.append((identifier, entry["error"]))

    if failed_rows:
        lines += ["", "<details>", "<summary>Failures</summary>", ""]
        for identifier, error in failed_rows:
            lines.append(f"**`{identifier}`**")
            lines += ["```", error, "```", ""]
        lines.append("</details>")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("reports_dir", type=Path)
    parser.add_argument("identifiers_json", type=Path)
    args = parser.parse_args(argv)

    identifiers = json.loads(args.identifiers_json.read_text())
    by_identifier = load_results(args.reports_dir)
    sys.stdout.write(render(identifiers, by_identifier))
    return 0


if __name__ == "__main__":
    sys.exit(main())

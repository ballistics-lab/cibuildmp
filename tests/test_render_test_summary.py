"""bin/render_test_summary.py -- loaded by path (not part of the
installed package), same reasoning as test_plan_test_matrix.py's own
module docstring."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "render_test_summary.py"

_spec = importlib.util.spec_from_file_location("render_test_summary", SCRIPT)
render_test_summary = importlib.util.module_from_spec(_spec)
sys.modules["render_test_summary"] = render_test_summary
_spec.loader.exec_module(render_test_summary)


def _report(*results: dict) -> dict:
    return {"results": list(results)}


def test_rows_follow_identifiers_order_not_report_order():
    by_identifier = {
        "b": {"identifier": "b", "duration": 1.0, "error": None},
        "a": {"identifier": "a", "duration": 2.0, "error": None},
    }
    out = render_test_summary.render(["a", "b"], by_identifier)
    a_pos = out.index("`a`")
    b_pos = out.index("`b`")
    assert a_pos < b_pos


def test_missing_report_gets_its_own_marked_row():
    out = render_test_summary.render(
        ["a", "b"], {"a": {"identifier": "a", "duration": 1.0, "error": None}}
    )
    assert "`a` | ✅" in out
    assert "`b` | ⚠️ no report" in out


def test_failure_gets_a_details_block_with_the_real_error():
    by_identifier = {
        "a": {"identifier": "a", "duration": 3.0, "error": "make: *** Error 1"},
    }
    out = render_test_summary.render(["a"], by_identifier)
    assert "`a` | ❌" in out
    assert "<details>" in out
    assert "make: *** Error 1" in out


def test_load_results_merges_every_json_file_in_the_directory(tmp_path):
    (tmp_path / "report-1.json").write_text(
        '{"results": [{"identifier": "x", "duration": 1.0, "error": null}]}'
    )
    (tmp_path / "report-2.json").write_text(
        '{"results": [{"identifier": "y", "duration": 2.0, "error": "boom"}]}'
    )
    by_identifier = render_test_summary.load_results(tmp_path)
    assert set(by_identifier) == {"x", "y"}
    assert by_identifier["y"]["error"] == "boom"


def test_summary_counts_only_true_successes_as_passed():
    by_identifier = {
        "a": {"identifier": "a", "duration": 1.0, "error": None},
        "b": {"identifier": "b", "duration": 1.0, "error": "failed"},
    }
    out = render_test_summary.render(["a", "b", "c"], by_identifier)
    assert "1/3 passed" in out

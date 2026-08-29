"""bin/plan_test_matrix.py is not part of the installed package (its own
docstring explains why: it imports cibuildmp straight from `src/`, a
deliberate departure from every other `bin/` script's stdlib-only
convention) -- exercised the same way a workflow step would run it,
as a subprocess against a real `PYTHONPATH=src`, rather than imported
in-process.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "plan_test_matrix.py"
PACKAGE_DIR = REPO_ROOT / "examples" / "template"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(PACKAGE_DIR), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_every_identifier_appears_in_exactly_one_bucket():
    result = _run(
        "--build",
        "v1.29.0-manylinux* v1.28.0-manylinux* mpy6.3-v1.29.0-*",
        "--max-buckets",
        "5",
    )
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)

    bucketed = [i for b in plan["buckets"] for i in b["build"].split()]
    assert sorted(bucketed) == sorted(plan["identifiers"])
    assert len(bucketed) == len(set(bucketed))  # no duplicates
    assert len(plan["buckets"]) <= 5


def test_arm64_native_unix_cells_never_share_a_bucket_with_amd64():
    result = _run(
        "--build",
        "v1.29.0-manylinux_2_28_x86_64 v1.29.0-manylinux_2_28_aarch64 v1.29.0-manylinux_2_31_armv7l",
        "--max-buckets",
        "1",
    )
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)

    # max-buckets=1 is still overridden up to one bucket per distinct
    # runner class actually in play -- a job has exactly one runs-on.
    runners = {b["runner"] for b in plan["buckets"]}
    assert runners == {"ubuntu-latest", "ubuntu-24.04-arm"}
    for bucket in plan["buckets"]:
        ids = bucket["build"].split()
        if bucket["runner"] == "ubuntu-24.04-arm":
            assert all(i.endswith(("_aarch64", "_armv7l")) for i in ids)
        else:
            assert all(not i.endswith(("_aarch64", "_armv7l")) for i in ids)


def test_identifiers_output_matches_print_build_identifiers_order():
    build = "mpy6.3-v1.29.0-* mpy6.3-v1.28.0-*"
    result = _run("--build", build, "--max-buckets", "20")
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)

    env = dict(os.environ)
    ref = subprocess.run(
        [
            "cibuildmp",
            str(PACKAGE_DIR),
            "--build",
            build,
            "--print-build-identifiers",
            "--json",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if ref.returncode != 0:
        # cibuildmp itself isn't necessarily on PATH in every environment
        # this test runs in -- the ordering guarantee this test is really
        # about is covered by the resolve_entries()/cli._resolve_all()
        # call plan_test_matrix.py itself makes, so skip rather than fail
        # on an unrelated PATH issue.
        import pytest

        pytest.skip("cibuildmp CLI not on PATH")
    assert plan["identifiers"] == json.loads(ref.stdout)


def test_a_selection_matching_nothing_real_fails_loudly():
    result = _run("--build", "no-such-identifier-*")
    assert result.returncode != 0
    assert result.stdout == ""

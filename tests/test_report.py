import json
from dataclasses import dataclass
from pathlib import Path

from cibuildmp import report


@dataclass(frozen=True)
class _FakeResult:
    identifier: str
    output: Path
    duration: float

    @property
    def size(self) -> int:
        return self.output.stat().st_size


def test_entry_for_result_lists_every_file_in_the_output_directory(tmp_path):
    output_dir = tmp_path / "unix-manylinux_2_28_x86_64"
    output_dir.mkdir()
    (output_dir / "micropython-unix-manylinux_2_28_x86_64").write_bytes(b"\x00" * 10)
    (output_dir / "package.json").write_text("{}")

    result = _FakeResult(
        identifier="unix-manylinux_2_28_x86_64",
        output=output_dir / "micropython-unix-manylinux_2_28_x86_64",
        duration=1.5,
    )
    entry = report.entry_for_result(result)

    assert entry.identifier == "unix-manylinux_2_28_x86_64"
    assert entry.error is None
    assert entry.size == 10
    assert entry.output_dir == str(output_dir)
    assert entry.files == ("micropython-unix-manylinux_2_28_x86_64", "package.json")


def test_entry_for_error_carries_no_output_fields():
    entry = report.entry_for_error("mpy6.3-v1.29.0-armv6m", 3.2, RuntimeError("boom"))

    assert entry.identifier == "mpy6.3-v1.29.0-armv6m"
    assert entry.duration == 3.2
    assert entry.error == "boom"
    assert entry.output_dir is None
    assert entry.size is None
    assert entry.files == ()


def test_report_dir_defaults_under_cache_root(monkeypatch, tmp_path):
    monkeypatch.delenv("CIBMP_REPORT_PATH", raising=False)
    monkeypatch.setenv("CIBMP_CACHE_PATH", str(tmp_path / "cache"))

    assert report.report_dir() == tmp_path / "cache" / "reports"


def test_report_dir_honors_cibmp_report_path_override(monkeypatch, tmp_path):
    monkeypatch.setenv("CIBMP_REPORT_PATH", str(tmp_path / "elsewhere"))

    assert report.report_dir() == tmp_path / "elsewhere"


def test_write_report_writes_one_json_file_with_every_entry(monkeypatch, tmp_path):
    monkeypatch.setenv("CIBMP_REPORT_PATH", str(tmp_path / "reports"))

    entries = [
        report.ReportEntry(
            identifier="ok",
            duration=1.0,
            output_dir="/x/ok",
            size=42,
            files=("micropython",),
        ),
        report.entry_for_error("bad", 0.5, RuntimeError("make failed")),
    ]

    path = report.write_report(entries, total_duration=1.5)

    assert path.parent == tmp_path / "reports"
    payload = json.loads(path.read_text())
    assert payload["built"] == 1
    assert payload["failed"] == 1
    assert payload["total_duration"] == 1.5
    assert payload["results"] == [
        {
            "identifier": "ok",
            "duration": 1.0,
            "error": None,
            "output_dir": "/x/ok",
            "size": 42,
            "files": ["micropython"],
        },
        {
            "identifier": "bad",
            "duration": 0.5,
            "error": "make failed",
            "output_dir": None,
            "size": None,
            "files": [],
        },
    ]


def test_write_report_two_calls_produce_two_distinct_files(monkeypatch, tmp_path):
    # Unlike $GITHUB_STEP_SUMMARY (stepsummary.py's own open(path, "a")),
    # nothing names one report file across more than one invocation --
    # each write_report() call gets its own path.
    monkeypatch.setenv("CIBMP_REPORT_PATH", str(tmp_path / "reports"))

    first = report.write_report([], total_duration=0.0)
    second = report.write_report([], total_duration=0.0)

    assert first != second
    assert first.exists() and second.exists()

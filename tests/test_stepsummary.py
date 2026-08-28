import hashlib
from pathlib import Path

from cibuildmp.stepsummary import write_step_summary


class FakeResult:
    def __init__(self, identifier: str, output: Path, size: int, duration: float = 1.0):
        self.identifier = identifier
        self.output = output
        self._size = size
        self.duration = duration

    @property
    def size(self) -> int:
        return self._size


def test_noop_when_github_step_summary_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    result = FakeResult("mpy6.3-x64", tmp_path / "out.mpy", 229)

    # No exception, and nothing written anywhere -- there is nowhere to write.
    write_step_summary([result], 1.5)


def test_writes_an_html_table_when_set(monkeypatch, tmp_path):
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    out1 = tmp_path / "template-x64.mpy"
    out1.write_bytes(b"\x00" * 229)
    out2 = tmp_path / "template-x86.mpy"
    out2.write_bytes(b"\x00" * 260)
    results = [
        FakeResult("mpy6.3-x64", out1, 229, duration=1.2),
        FakeResult("mpy6.3-x86", out2, 260, duration=1.5),
    ]

    write_step_summary(results, 2.7)

    text = summary_path.read_text()
    assert "### cibuildmp" in text
    assert "<samp>template-x64.mpy</samp>" in text
    assert "<samp>mpy6.3-x64</samp>" in text
    assert "229 Bytes" in text
    assert hashlib.sha256(b"\x00" * 229).hexdigest() in text
    assert "2 targets built in 2.7 seconds" in text


def test_appends_rather_than_overwrites(monkeypatch, tmp_path):
    # GITHUB_STEP_SUMMARY is a real GitHub Actions convention: every step in
    # a job appends to the same file across the whole job, not just this one
    # call -- open(path, "a") must actually append, not truncate.
    summary_path = tmp_path / "summary.md"
    summary_path.write_text("### earlier step\n")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    write_step_summary([FakeResult("id", Path("/out/f.mpy"), 1)], 0.1)

    text = summary_path.read_text()
    assert text.startswith("### earlier step\n")
    assert "### cibuildmp" in text


def test_large_size_gets_kb_suffix(monkeypatch, tmp_path):
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    write_step_summary(
        [FakeResult("unix-mipsel", Path("/out/micropython-unix-mipsel"), 1784260)],
        216.4,
    )

    assert "1.8 MB" in summary_path.read_text()


def test_missing_file_renders_a_dash_instead_of_a_digest(monkeypatch, tmp_path):
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    write_step_summary(
        [FakeResult("mpy6.3-x64", Path("/does/not/exist.mpy"), 229)], 1.5
    )

    assert "&mdash;" in summary_path.read_text()


def test_empty_results_still_writes_a_header(monkeypatch, tmp_path):
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    write_step_summary([], 0.0)

    text = summary_path.read_text()
    assert "### cibuildmp" in text
    assert "0 targets built in 0.0 seconds" in text


def test_noop_when_disabled(monkeypatch, tmp_path):
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    monkeypatch.setenv("CIBMP_DISABLE_GITHUB_STEP_SUMMARY", "1")
    result = FakeResult("mpy6.3-x64", tmp_path / "out.mpy", 229)

    write_step_summary([result], 1.5)

    assert not summary_path.exists()


def test_disabled_with_0_is_still_enabled(monkeypatch, tmp_path):
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    monkeypatch.setenv("CIBMP_DISABLE_GITHUB_STEP_SUMMARY", "0")
    result = FakeResult("mpy6.3-x64", tmp_path / "out.mpy", 229)

    write_step_summary([result], 1.5)

    assert "mpy6.3-x64" in summary_path.read_text()


def test_no_options_block_when_nothing_passed(monkeypatch, tmp_path):
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    write_step_summary([FakeResult("id", Path("/out/f.mpy"), 1)], 0.1)

    assert "<details>" not in summary_path.read_text()


def test_options_block_lists_build_skip_and_matched_overrides(monkeypatch, tmp_path):
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    write_step_summary(
        [FakeResult("mpy6.3-x64", Path("/out/f.mpy"), 1)],
        0.1,
        build=["mpy6.3-*"],
        skip=["*-aarch64"],
        overrides=[
            {"select": "mpy6.3-*", "extra_make_args": ["V=1"]},
            {"select": "*-aarch64", "extra_make_args": ["V=2"]},
        ],
        override_error=ValueError,
    )

    text = summary_path.read_text()
    assert "<details>" in text
    assert "build: mpy6.3-*" in text
    assert "skip: *-aarch64" in text
    assert "'mpy6.3-*': extra_make_args" in text
    # *-aarch64 never matched this run's own identifier -- must not appear.
    assert "'*-aarch64'" not in text

from pathlib import Path

from cibuildmp.stepsummary import write_step_summary


class FakeResult:
    def __init__(self, identifier: str, output: Path, size: int):
        self.identifier = identifier
        self.output = output
        self._size = size

    @property
    def size(self) -> int:
        return self._size


def test_noop_when_github_step_summary_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    result = FakeResult("mpy6.3-x64", tmp_path / "out.mpy", 229)

    # No exception, and nothing written anywhere -- there is nowhere to write.
    write_step_summary([result], 1.5)


def test_writes_a_markdown_table_when_set(monkeypatch, tmp_path):
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    results = [
        FakeResult("mpy6.3-x64", Path("/out/template-x64.mpy"), 229),
        FakeResult("mpy6.3-x86", Path("/out/template-x86.mpy"), 260),
    ]

    write_step_summary(results, 2.7)

    text = summary_path.read_text()
    assert "2 target(s) built in 2.7s" in text
    assert "| `mpy6.3-x64` | `template-x64.mpy` | 229 bytes |" in text
    assert "| `mpy6.3-x86` | `template-x86.mpy` | 260 bytes |" in text


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


def test_large_size_gets_thousands_separator(monkeypatch, tmp_path):
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    write_step_summary(
        [FakeResult("unix-mipsel", Path("/out/micropython-unix-mipsel"), 1784260)],
        216.4,
    )

    assert "1,784,260 bytes" in summary_path.read_text()


def test_empty_results_still_writes_a_header(monkeypatch, tmp_path):
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    write_step_summary([], 0.0)

    assert "0 target(s) built in 0.0s" in summary_path.read_text()


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

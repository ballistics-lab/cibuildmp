import json
from pathlib import Path

from cibuildmp import cli
from cibuildmp.build import BuildResult
from cibuildmp.cli import main
from cibuildmp.toolchains import ResolvedToolchain


def write(tmp_path, text):
    (tmp_path / "cibuildmp.toml").write_text(text)
    return str(tmp_path)


CONFIG = """
micropython = "v1.28.0"
[natmod]
archs = ["x64", "armv6m"]
"""


def test_print_build_identifiers(tmp_path, capsys):
    assert main([write(tmp_path, CONFIG), "--print-build-identifiers"]) == 0
    assert capsys.readouterr().out.split() == [
        "mpy6.3-natmod-x64",
        "mpy6.3-natmod-armv6m",
    ]


def test_print_build_identifiers_json(tmp_path, capsys):
    assert main([write(tmp_path, CONFIG), "--print-build-identifiers", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [
        "mpy6.3-natmod-x64",
        "mpy6.3-natmod-armv6m",
    ]


def test_print_build_matrix_carries_the_runner(tmp_path, capsys):
    assert main([write(tmp_path, CONFIG), "--print-build-matrix"]) == 0
    assert json.loads(capsys.readouterr().out) == [
        {"only": "mpy6.3-natmod-x64", "os": "ubuntu-latest"},
        {"only": "mpy6.3-natmod-armv6m", "os": "ubuntu-latest"},
    ]


def test_dry_run_covers_every_target_and_succeeds(tmp_path, capsys):
    assert main([write(tmp_path, CONFIG), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "[1/2]" in out and "[2/2]" in out
    assert "ARCH=x64" in out and "ARCH=armv6m" in out


def test_dry_run_spans_multiple_micropython_tags(tmp_path, capsys):
    config = """
    micropython = ["v1.22.0", "v1.28.0"]
    [natmod]
    archs = ["x64"]
    """
    assert main([write(tmp_path, config), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "v1.22.0, v1.28.0" in out
    assert "mpy6.2-natmod-x64" in out and "mpy6.3-natmod-x64" in out


def test_only_overrides_skip(tmp_path, capsys):
    config = CONFIG + '\nskip = "*-armv6m"\n'
    argv = [write(tmp_path, config), "--only", "mpy6.3-natmod-armv6m", "--dry-run"]
    assert main(argv) == 0
    assert "ARCH=armv6m" in capsys.readouterr().out


def test_only_unknown_identifier_is_an_error(tmp_path, capsys):
    assert main([write(tmp_path, CONFIG), "--only", "mpy6.3-natmod-xtensa"]) == 2
    assert "matches no target" in capsys.readouterr().err


def test_bad_arch_is_an_error(tmp_path, capsys):
    config = '[natmod]\narchs = ["x64", "aarch64"]\n'
    assert main([write(tmp_path, config), "--print-build-identifiers"]) == 2
    assert "aarch64" in capsys.readouterr().err


def test_real_build_writes_github_step_summary_when_set(monkeypatch, tmp_path):
    # Integration check for D29's own wiring, not just stepsummary.py in
    # isolation: a real (mocked-at-the-edges) build through main() must
    # actually call write_step_summary with the same results/duration the
    # plain-text summary above it already prints -- x64 only, host gcc, to
    # keep the mocking surface minimal (no cross-toolchain resolution).
    config = '\nmicropython = "v1.28.0"\n[natmod]\narchs = ["x64"]\n'
    package_dir = Path(write(tmp_path, config))

    monkeypatch.setattr(
        cli, "resolve", lambda arch, **k: ResolvedToolchain("none", "", "", None)
    )
    monkeypatch.setattr(cli, "fetch_micropython", lambda tag, **k: tmp_path / "mpy")
    monkeypatch.setattr(cli, "build_mpy_cross", lambda mpy_dir, **k: None)
    monkeypatch.setattr(cli, "read_mpy_abi", lambda mpy_dir: "6.3")

    produced = tmp_path / "template-mpy6.3-natmod-x64.mpy"
    produced.write_bytes(b"\x00" * 42)

    def fake_build_target(build_options, chain, mpy_dir, module_root, output_dir, **k):
        return BuildResult(
            identifier=build_options.identifier, output=produced, duration=0.5
        )

    monkeypatch.setattr(cli, "build_target", fake_build_target)

    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    assert main([str(package_dir)]) == 0

    text = summary_path.read_text()
    assert "1 target(s) built in 0.5s" in text
    assert "mpy6.3-natmod-x64" in text
    assert "42 bytes" in text

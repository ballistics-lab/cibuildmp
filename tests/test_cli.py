import json

from cibuildmp.cli import main


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

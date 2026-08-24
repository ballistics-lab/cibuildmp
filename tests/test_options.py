from pathlib import Path

import pytest

from cibuildmp.options import ConfigError, Options


def write(tmp_path: Path, text: str, name: str = "cibuildmp.toml") -> Path:
    (tmp_path / name).write_text(text)
    return tmp_path


def test_defaults_with_no_config_at_all(tmp_path):
    options = Options.load(tmp_path, env={})
    assert options.config_path is None
    assert options.micropython == "v1.28.0"
    assert len(options.targets()) == 10
    build_options = options.build_options(options.targets()[0], env={})
    assert build_options.module_dir == "natmod"
    assert build_options.make_target == "dist"


def test_overrides_beat_natmod_table(tmp_path):
    write(
        tmp_path,
        """
        micropython = "v1.28.0"
        [natmod]
        archs = ["x64", "armv7emsp"]
        extra-make-args = ["COMMON=1"]
        [[overrides]]
        select = "*-armv7emsp"
        extra-make-args = ["MP_BCLIBC_PRECISION=single"]
        """,
    )
    options = Options.load(tmp_path, env={})
    resolved = {
        t.arch: options.build_options(t, env={}).extra_make_args
        for t in options.targets()
    }
    assert resolved["x64"] == ["COMMON=1"]
    assert resolved["armv7emsp"] == ["MP_BCLIBC_PRECISION=single"]


def test_override_without_select_is_an_error(tmp_path):
    write(tmp_path, '[[overrides]]\nextra-make-args = ["X=1"]\n')
    options = Options.load(tmp_path, env={})
    with pytest.raises(ConfigError, match="select"):
        options.build_options(options.targets()[0], env={})


def test_environment_beats_file(tmp_path):
    write(
        tmp_path,
        'micropython = "v1.22.0"\nskip = ""\n[natmod]\narchs = ["x64", "x86"]\n',
    )
    options = Options.load(
        tmp_path, env={"CIBMP_SKIP": "*-x86", "CIBMP_MICROPYTHON": "v1.28.0"}
    )
    assert options.abi == "6.3"  # not 6.2, which the file's tag would give
    assert [t.arch for t in options.targets()] == ["x64"]


def test_environment_beats_override(tmp_path):
    write(
        tmp_path,
        """
        [natmod]
        archs = ["armv7emsp"]
        [[overrides]]
        select = "*"
        extra-make-args = ["FROM=override"]
        """,
    )
    options = Options.load(tmp_path, env={})
    target = options.targets()[0]
    env = {"CIBMP_EXTRA_MAKE_ARGS": "FROM=env A=1"}
    assert options.build_options(target, env=env).extra_make_args == ["FROM=env", "A=1"]


def test_pyproject_fallback(tmp_path):
    write(
        tmp_path,
        '[tool.cibuildmp]\nmicropython = "v1.22.0"\n[tool.cibuildmp.natmod]\narchs = ["x64"]\n',
        name="pyproject.toml",
    )
    options = Options.load(tmp_path, env={})
    assert (
        options.config_path is not None and options.config_path.name == "pyproject.toml"
    )
    assert options.abi == "6.2"
    assert [t.arch for t in options.targets()] == ["x64"]


def test_standalone_wins_over_pyproject(tmp_path):
    write(tmp_path, 'micropython = "v1.28.0"\n')
    write(
        tmp_path, '[tool.cibuildmp]\nmicropython = "v1.21.0"\n', name="pyproject.toml"
    )
    options = Options.load(tmp_path, env={})
    assert options.config_path.name == "cibuildmp.toml"
    assert options.abi == "6.3"

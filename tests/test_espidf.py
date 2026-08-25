from pathlib import Path

import pytest

from cibuildmp.usermod import espidf
from cibuildmp.usermod.espidf import (
    EspIdfError,
    ResolvedEspIdf,
    fetch_esp_idf,
    resolve_esp_idf,
)


def test_fetch_esp_idf_clones_and_stamps(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        # Simulate git actually populating the target directory -- the
        # target path is always the command's own last argument.
        target = Path(command[-1])
        target.mkdir(parents=True)
        (target / "tools").mkdir()

    monkeypatch.setattr(espidf.subprocess, "run", fake_run)

    idf_dir = fetch_esp_idf("v5.5.1", root=tmp_path, quiet=False)

    assert idf_dir == tmp_path / "esp-idf" / "v5.5.1" / "idf"
    assert idf_dir.exists()
    assert calls[0][0] == "git"
    assert "clone" in calls[0]
    assert "--depth" in calls[0] and "--recursive" in calls[0]
    branch_idx = calls[0].index("--branch")
    assert calls[0][branch_idx + 1] == "v5.5.1"
    assert calls[0][branch_idx + 2] == espidf.IDF_GIT_URL

    # Second call is a cache hit -- no further clone.
    fetch_esp_idf("v5.5.1", root=tmp_path, quiet=False)
    assert len(calls) == 1


def test_fetch_esp_idf_quiet_inserts_quiet_flag(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        target = Path(command[-1])
        target.mkdir(parents=True)

    monkeypatch.setattr(espidf.subprocess, "run", fake_run)
    fetch_esp_idf("v5.5.1", root=tmp_path, quiet=True)

    assert "--quiet" in calls[0]


def test_fetch_esp_idf_failure_raises(tmp_path, monkeypatch):
    import subprocess as sp

    def fake_run(command, **kwargs):
        raise sp.CalledProcessError(1, command)

    monkeypatch.setattr(espidf.subprocess, "run", fake_run)

    with pytest.raises(EspIdfError, match="cloning esp-idf"):
        fetch_esp_idf("v5.5.1", root=tmp_path, quiet=True)


def test_resolve_esp_idf_tools_installs_and_caches(tmp_path, monkeypatch):
    idf_dir = tmp_path / "idf"
    (idf_dir / "tools").mkdir(parents=True)
    (idf_dir / "tools" / "idf_tools.py").write_text("")

    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)

    monkeypatch.setattr(espidf.subprocess, "run", fake_run)
    monkeypatch.setattr(espidf, "fetch_esp_idf", lambda *a, **k: idf_dir)

    idf = resolve_esp_idf("v5.5.1", "esp32", root=tmp_path, quiet=True)

    assert idf.idf_dir == idf_dir
    assert idf.tools_dir == tmp_path / "esp-idf" / "v5.5.1" / "tools" / "esp32"
    assert idf.tools_dir.exists()
    # install --targets=esp32, then install-python-env.
    assert calls[0][2:4] == ["install", "--targets=esp32"]
    assert calls[1][2] == "install-python-env"

    # Second call is a cache hit -- no further installs.
    resolve_esp_idf("v5.5.1", "esp32", root=tmp_path, quiet=True)
    assert len(calls) == 2


def test_resolve_esp_idf_tools_failure_raises(tmp_path, monkeypatch):
    import subprocess as sp

    idf_dir = tmp_path / "idf"
    (idf_dir / "tools").mkdir(parents=True)
    (idf_dir / "tools" / "idf_tools.py").write_text("")

    def fake_run(command, **kwargs):
        raise sp.CalledProcessError(1, command)

    monkeypatch.setattr(espidf.subprocess, "run", fake_run)
    monkeypatch.setattr(espidf, "fetch_esp_idf", lambda *a, **k: idf_dir)

    with pytest.raises(EspIdfError, match="esp-idf tool install failed"):
        resolve_esp_idf("v5.5.1", "esp32", root=tmp_path, quiet=True)


def test_env_asks_idf_tools_export_and_sets_idf_path(tmp_path, monkeypatch):
    export_output = (
        "OPENOCD_SCRIPTS=/tools/openocd/scripts\n"
        "IDF_PYTHON_ENV_PATH=/tools/python_env\n"
        "IDF_DEACTIVATE_FILE_PATH=/tmp/deactivate123\n"
        "PATH=/tools/xtensa-esp-elf/bin:/tools/python_env/bin:$PATH\n"
    )

    class FakeCompleted:
        stdout = export_output

    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return FakeCompleted()

    monkeypatch.setattr(espidf.subprocess, "run", fake_run)

    idf = ResolvedEspIdf(idf_dir=tmp_path / "idf", tools_dir=tmp_path / "tools")
    env = idf.env({"PATH": "/usr/bin"})

    assert env["IDF_PATH"] == str(tmp_path / "idf")
    assert env["OPENOCD_SCRIPTS"] == "/tools/openocd/scripts"
    assert env["IDF_PYTHON_ENV_PATH"] == "/tools/python_env"
    # $PATH substituted with the base env's own PATH, not left literal.
    assert env["PATH"] == "/tools/xtensa-esp-elf/bin:/tools/python_env/bin:/usr/bin"
    # Not needed for a one-shot subprocess build -- no shell to deactivate.
    assert "IDF_DEACTIVATE_FILE_PATH" not in env

    # export is called with IDF_TOOLS_PATH pointing at tools_dir.
    (_command, kwargs) = calls[0]
    assert kwargs["env"]["IDF_TOOLS_PATH"] == str(tmp_path / "tools")


def test_env_export_failure_raises(tmp_path, monkeypatch):
    import subprocess as sp

    def fake_run(command, **kwargs):
        raise sp.CalledProcessError(1, command)

    monkeypatch.setattr(espidf.subprocess, "run", fake_run)

    idf = ResolvedEspIdf(idf_dir=tmp_path / "idf", tools_dir=tmp_path / "tools")
    with pytest.raises(EspIdfError, match="esp-idf export failed"):
        idf.env()

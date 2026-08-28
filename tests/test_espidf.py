from pathlib import Path

import pytest

from cibuildmp.platforms.usermod import espidf
from cibuildmp.platforms.usermod.espidf import EspIdfError, fetch_esp_idf


def _fake_git_run(calls):
    """Simulates both `git clone` (creates the target directory) and `git
    submodule update` (target already exists, does nothing) -- the two
    real calls `fetch_esp_idf()` now makes, distinguished by which
    subcommand is in the command itself rather than by call order alone."""

    def fake_run(command, **kwargs):
        calls.append(command)
        if "clone" in command:
            target = Path(command[-1])
            target.mkdir(parents=True)
            (target / "tools").mkdir()

    return fake_run


def test_fetch_esp_idf_clones_and_stamps(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(espidf.subprocess, "run", _fake_git_run(calls))

    idf_dir = fetch_esp_idf("v5.5.1", root=tmp_path, quiet=False)

    assert idf_dir == tmp_path / "esp-idf" / "v5.5.1" / "idf"
    assert idf_dir.exists()
    assert len(calls) == 2

    clone, submodules = calls
    assert clone[0] == "git"
    assert "clone" in clone
    assert "--depth" in clone
    # No --recursive on the clone itself -- MicroPython's own
    # ci_esp32_idf_setup does the submodule fetch as a separate,
    # narrower step (see fetch_esp_idf()'s own docstring for why).
    assert "--recursive" not in clone
    branch_idx = clone.index("--branch")
    assert clone[branch_idx + 1] == "v5.5.1"
    assert clone[branch_idx + 2] == espidf.IDF_GIT_URL

    # The submodule step must target the same directory `git clone` just
    # populated -- `cached_dir()`'s own staging path, not the final
    # `idf_dir` (the rename to that happens only after `populate()`
    # returns).
    assert submodules[:4] == ["git", "-C", clone[-1], "submodule"]
    assert "--init" in submodules
    assert "--recursive" in submodules
    assert "--filter=tree:0" in submodules

    # Third+fourth calls would be a re-clone -- cache hit skips both.
    fetch_esp_idf("v5.5.1", root=tmp_path, quiet=False)
    assert len(calls) == 2


def test_fetch_esp_idf_quiet_inserts_quiet_flag(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(espidf.subprocess, "run", _fake_git_run(calls))

    fetch_esp_idf("v5.5.1", root=tmp_path, quiet=True)

    clone, submodules = calls
    assert "--quiet" in clone
    assert "--quiet" in submodules


def test_fetch_esp_idf_failure_raises(tmp_path, monkeypatch):
    import subprocess as sp

    def fake_run(command, **kwargs):
        raise sp.CalledProcessError(1, command)

    monkeypatch.setattr(espidf.subprocess, "run", fake_run)

    with pytest.raises(EspIdfError, match="cloning esp-idf"):
        fetch_esp_idf("v5.5.1", root=tmp_path, quiet=True)


def test_fetch_esp_idf_submodule_failure_raises(tmp_path, monkeypatch):
    import subprocess as sp

    def fake_run(command, **kwargs):
        if "clone" in command:
            target = Path(command[-1])
            target.mkdir(parents=True)
            return
        raise sp.CalledProcessError(1, command)

    monkeypatch.setattr(espidf.subprocess, "run", fake_run)

    with pytest.raises(EspIdfError, match="cloning esp-idf"):
        fetch_esp_idf("v5.5.1", root=tmp_path, quiet=True)


def test_idf_dir_path_shape(tmp_path):
    assert espidf.idf_dir("v5.5.1", tmp_path) == tmp_path / "esp-idf" / "v5.5.1" / "idf"


def test_tools_dir_path_shape(tmp_path):
    assert (
        espidf.tools_dir("v5.5.1", "esp32", tmp_path)
        == tmp_path / "esp-idf" / "v5.5.1" / "tools" / "esp32"
    )

import pytest


@pytest.fixture(autouse=True)
def _no_ambient_github_actions(monkeypatch):
    """This suite itself runs inside a real `usermod dev` GitHub Actions
    job, where GITHUB_ACTIONS=true is genuinely set by the runner --
    without this, any test that reaches dockerrun.ensure_image()'s
    default resolution path (no override, nothing registered) would
    silently take a different branch depending on where it happens to
    run, and in CI specifically hit
    usermod/dockerrun.py's real `docker buildx` calls rather than the
    plain `docker build` most tests assume. Force it unset by default so
    every test is hermetic; a test that wants the GITHUB_ACTIONS=true
    branch on purpose sets it back with its own monkeypatch.setenv().
    """
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

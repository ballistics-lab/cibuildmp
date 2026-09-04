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


@pytest.fixture(autouse=True)
def _scratch_root_per_test(monkeypatch, tmp_path_factory):
    """Pin `sources.scratch_root()` ([0095]) to a per-test directory.

    Two reasons, both real rather than tidiness. Without this the default
    path runs `tempfile.mkdtemp()` and registers an `atexit` cleanup, so a
    full suite run leaves one temporary tree per test that touched a build
    directory and only removes them when the interpreter exits -- and the
    module-level `_SCRATCH_ROOT` cache means every test in one process
    would otherwise share a single directory, which is exactly the
    cross-run bleed the record exists to prevent. Setting the env var also
    takes the branch that does *not* register cleanup, so nothing here
    depends on interpreter shutdown ordering.

    `tmp_path_factory`, not `tmp_path`: this is autouse, and requesting
    `tmp_path` from an autouse fixture creates one for every test in the
    suite whether or not it wanted one.
    """
    monkeypatch.setenv(
        "CIBMP_SCRATCH_PATH", str(tmp_path_factory.mktemp("cibmp-scratch"))
    )

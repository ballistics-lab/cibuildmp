import subprocess

from cibuildmp import dockerrun
from cibuildmp.platforms.usermod.build_common import (
    cmake_extra_args_env,
    probe_supported_cflags,
)


def test_cmake_extra_args_env_joins_into_one_var():
    assert cmake_extra_args_env(
        ("-DMICROPY_C_HEAP_SIZE=131072", "-DFOO=1"), var="CMAKE_ARGS"
    ) == {"CMAKE_ARGS": "-DMICROPY_C_HEAP_SIZE=131072 -DFOO=1"}


def test_cmake_extra_args_env_empty_is_no_entry_at_all():
    # Not {"CMAKE_ARGS": ""} -- Container.call() treats both the same way
    # (`env or {}`), but an absent key keeps a caller's own env= dict free
    # of a no-op entry when nobody configured anything.
    assert cmake_extra_args_env((), var="CMAKE_ARGS") == {}


def test_cmake_extra_args_env_uses_the_given_var_name():
    # rp2 and esp32 name this differently (CMAKE_ARGS vs IDFPY_FLAGS,
    # ESP-IDF's own name for the same idea) -- the helper does not
    # hardcode either.
    assert cmake_extra_args_env(("-DX=1",), var="IDFPY_FLAGS") == {
        "IDFPY_FLAGS": "-DX=1"
    }


def _container(monkeypatch, stdout: str = ""):
    """A real `dockerrun.Container`, `docker create`/`start`/`exec` all
    faked -- `probe_supported_cflags()` needs a real `container=` now
    (record 0095's own transition cleanup: every usermod port builds
    through `Container`, so the function has no bare-host fallback left to
    take a plain `image=` for). `stdout` is what every `docker exec`
    returns when the caller asked for `capture_output`."""

    def fake_run(cmd, **kwargs):
        if kwargs.get("capture_output"):
            return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
        return None

    monkeypatch.setattr(dockerrun.subprocess, "run", fake_run)
    return dockerrun.Container(image="img:local")


def test_probe_supported_cflags_empty_candidates_runs_no_container(monkeypatch):
    calls = []
    monkeypatch.setattr(
        dockerrun.subprocess, "run", lambda cmd, **k: calls.append(cmd) or None
    )

    with dockerrun.Container(image="img:local") as container:
        assert probe_supported_cflags((), container=container) == ()

    # `docker create`/`start`/`rm` from the container's own lifecycle are
    # fine -- what must never happen is an `exec` for the (empty) probe.
    assert not any(c[:2] == ["docker", "exec"] for c in calls)


def test_probe_supported_cflags_keeps_only_what_echoes_back(monkeypatch):
    # gcc rejecting an unrecognized `-Wno-error=<diagnostic>` name is a
    # hard `cc1: error`, not a warning -- the probe script only echoes a
    # candidate back on success, so whatever the container's stdout
    # doesn't name gets dropped.
    with _container(monkeypatch, stdout="-Wno-error=cpp\n") as container:
        result = probe_supported_cflags(
            ("-Wno-error=cpp", "-Wno-error=unterminated-string-initialization"),
            container=container,
        )

    assert result == ("-Wno-error=cpp",)


def test_probe_supported_cflags_preserves_candidate_order(monkeypatch):
    with _container(monkeypatch, stdout="-Wno-error=b -Wno-error=a\n") as container:
        result = probe_supported_cflags(
            ("-Wno-error=a", "-Wno-error=b"), container=container
        )

    assert result == ("-Wno-error=a", "-Wno-error=b")


def test_probe_supported_cflags_script_ends_with_true(monkeypatch):
    # `Container.call()`'s own `subprocess.run(check=True)` would turn a
    # `;`-joined shell script's non-zero exit status (whatever its *last*
    # statement leaves behind) into a `CalledProcessError` -- crashing the
    # whole build purely because the *last* candidate happened to be one
    # this gcc rejects. A trailing `; true` pins the script's own exit
    # status to 0 regardless of any individual probe's outcome.
    # Live-verified separately against a real `manylinux_2_28_i686` image
    # with `-Wno-error=unterminated-string-initialization` listed last;
    # this checks the same contract at the `Container.call()` boundary.
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if kwargs.get("capture_output"):
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return None

    monkeypatch.setattr(dockerrun.subprocess, "run", fake_run)

    with dockerrun.Container(image="img:local") as container:
        probe_supported_cflags(("-Wno-error=cpp",), container=container)

    exec_call = next(c for c in calls if c[:2] == ["docker", "exec"])
    script = exec_call[-1]
    assert script.endswith("; true")

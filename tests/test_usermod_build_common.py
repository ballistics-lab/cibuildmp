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
    # Not {"CMAKE_ARGS": ""} -- dockerrun.run() treats both the same way
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


def test_probe_supported_cflags_empty_candidates_runs_no_container(monkeypatch):
    monkeypatch.setattr(
        dockerrun.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    assert probe_supported_cflags((), image="img:local") == ()


def test_probe_supported_cflags_keeps_only_what_echoes_back(monkeypatch):
    # gcc rejecting an unrecognized `-Wno-error=<diagnostic>` name is a
    # hard `cc1: error`, not a warning -- the probe script only echoes a
    # candidate back on success, so whatever the container's stdout
    # doesn't name gets dropped.
    monkeypatch.setattr(
        dockerrun.subprocess,
        "run",
        lambda cmd, **k: dockerrun.subprocess.CompletedProcess(
            cmd, 0, stdout="-Wno-error=cpp\n"
        ),
    )

    result = probe_supported_cflags(
        ("-Wno-error=cpp", "-Wno-error=unterminated-string-initialization"),
        image="img:local",
    )

    assert result == ("-Wno-error=cpp",)


def test_probe_supported_cflags_preserves_candidate_order(monkeypatch):
    monkeypatch.setattr(
        dockerrun.subprocess,
        "run",
        lambda cmd, **k: dockerrun.subprocess.CompletedProcess(
            cmd, 0, stdout="-Wno-error=b -Wno-error=a\n"
        ),
    )

    result = probe_supported_cflags(("-Wno-error=a", "-Wno-error=b"), image="img:local")

    assert result == ("-Wno-error=a", "-Wno-error=b")


def test_probe_supported_cflags_script_ends_with_true(monkeypatch):
    # `dockerrun.run()`'s own `subprocess.run(check=True)` would turn a
    # `;`-joined shell script's non-zero exit status (whatever its *last*
    # statement leaves behind) into a `CalledProcessError` -- crashing the
    # whole build purely because the *last* candidate happened to be one
    # this gcc rejects. A trailing `; true` pins the script's own exit
    # status to 0 regardless of any individual probe's outcome.
    # Live-verified separately against a real `manylinux_2_28_i686` image
    # with `-Wno-error=unterminated-string-initialization` listed last;
    # this checks the same contract at the `dockerrun.run()` boundary.
    calls = []
    monkeypatch.setattr(dockerrun, "run", lambda cmd, **k: calls.append(cmd) or "")

    probe_supported_cflags(("-Wno-error=cpp",), image="img:local")

    script = calls[0][-1]
    assert script.endswith("; true")

import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from cibuildmp.platforms.usermod.build_common import UsermodBuildError
from cibuildmp.platforms.usermod.build_webassembly import (
    WebassemblyBuildOptions,
    _webassembly_project_mounts,
    webassembly_make_command,
)
from cibuildmp.platforms.usermod.build_webassembly import (
    build_webassembly as _build_webassembly,
)


def build_webassembly_fn(*args, staging=None, **kwargs):
    """`build_webassembly()` with a staging directory supplied -- see
    `test_usermod_build_unix.py`'s own `build_unix_fn()` for why."""
    if staging is None:
        staging = Path(tempfile.mkdtemp(prefix="cibmp-test-staging-"))
    return _build_webassembly(*args, staging=staging, **kwargs)


def _fake_docker_run(cmd, **kwargs):
    """A `dockerrun.subprocess.run` stand-in, the same shape
    `test_usermod_build_unix.py`/`test_usermod_build_rp2.py` use. Since
    record 0095 the build runs inside one long-lived container, so this
    also stands in for the copy of `micropython.mjs`/`micropython.wasm`
    into `staging` -- a `sh -c` script here (`[ -e <src> ] && cp <src>
    <dest> || true`, one line per file), not a bare `cp` argv, so this
    stand-in parses each line rather than pattern-matching `"cp" in cmd`
    the way the simpler ports' own fakes do. Parsed directly in Python
    rather than actually shelling out to `sh`: this function *is* what
    `dockerrun.subprocess.run` has been monkeypatched to, so a real
    `subprocess.run(["sh", "-c", ...])` from inside it would recurse back
    into itself.
    """
    if cmd[:2] == ["docker", "exec"] and cmd[-2] == "-c":
        for line in cmd[-1].splitlines():
            line = line.strip()
            if not line.startswith("[ -e "):
                continue
            tokens = shlex.split(line.split("||", 1)[0])
            source, dest = Path(tokens[2]), Path(tokens[-1])
            if source.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(source, dest)
    if kwargs.get("capture_output"):
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    return None


def wasm_opts(**overrides) -> WebassemblyBuildOptions:
    defaults = {
        "user_c_modules": "/gh/ws/micropython/usermod",
        "frozen_manifest": "/gh/ws/a7p_manifest.py",
        "build_dir": Path("/gh/ws/usermod/build/wasm"),
    }
    defaults.update(overrides)
    return WebassemblyBuildOptions(**defaults)


def test_webassembly_project_mounts_omits_user_c_modules_when_empty():
    assert _webassembly_project_mounts(wasm_opts(user_c_modules=""), None) == []


def test_webassembly_project_mounts_includes_user_c_modules_when_set():
    assert _webassembly_project_mounts(
        wasm_opts(user_c_modules="/gh/ws/mymod"), None
    ) == [Path("/gh/ws/mymod")]


def test_webassembly_command_matches_build_usermod_webassembly_shape():
    # build-usermod-webassembly's own "Build usermod (webassembly, pyscript
    # variant)" step -- no CROSS_COMPILE, emsdk activation is PATH/env, not
    # a make variable.
    command = webassembly_make_command(wasm_opts(), Path("/gh/ws/mpy"))

    assert command == [
        "make",
        "-C",
        "/gh/ws/mpy/ports/webassembly",
        "VARIANT=pyscript",
        "BUILD=/gh/ws/usermod/build/wasm",
        "USER_C_MODULES=/gh/ws/micropython/usermod",
        "FROZEN_MANIFEST=/gh/ws/a7p_manifest.py",
    ]


def test_webassembly_no_image_registered_is_a_clear_error(monkeypatch, tmp_path):
    # Docker-only (D30), and cibuildmp never builds an image itself any
    # more (checked against cibuildwheel's real source before deciding --
    # its own container runtime only ever pulls an already-published,
    # digest-pinned image) -- with no override and nothing pinned in
    # resources/pinned_docker_images.toml, build_webassembly() must fail
    # loudly, not fall back to building docker/webassembly.Dockerfile.
    monkeypatch.delenv("CIBMP_WEBASSEMBLY_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr("cibuildmp.dockerrun._pins", lambda: {"image_group": {}})
    build_dir = tmp_path / "build-wasm"

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    with pytest.raises(UsermodBuildError, match="no Docker image registered"):
        build_webassembly_fn(wasm_opts(build_dir=build_dir), tmp_path / "mpy")

    assert calls == []


def _mock_webassembly_image(monkeypatch, image="cibuildmp-webassembly:local"):
    monkeypatch.setenv("CIBMP_WEBASSEMBLY_DOCKER_IMAGE", image)
    # See `_mock_windows_image` for why the in-container mpy-cross build
    # is stubbed out here too (record 0044).
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_common.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )
    # `webassembly`'s image is a fixed `linux/amd64` cross host, not native
    # to whatever the test runner's own architecture is -- stubbed the same
    # way `test_usermod_build_rp2.py`'s own `_mock_rp2_image()` stubs it,
    # so `Container.__enter__` never runs a real `docker run --pull
    # missing`.
    monkeypatch.setattr("cibuildmp.dockerrun._probe_platform", lambda *a, **k: "")


def test_webassembly_no_staging_is_a_clear_error(monkeypatch, tmp_path):
    """Needs a real image resolved first but must still fail before any
    container is created -- `_build_webassembly()` directly, bypassing
    `build_webassembly_fn()`'s own default staging directory."""
    _mock_webassembly_image(monkeypatch)
    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    with pytest.raises(UsermodBuildError, match="staging directory"):
        _build_webassembly(wasm_opts(), tmp_path / "mpy")

    assert calls == []


def test_webassembly_docker_image_override_skips_own_dockerfile_build(
    monkeypatch, tmp_path
):
    _mock_webassembly_image(monkeypatch)
    build_dir = tmp_path / "build-wasm"
    build_dir.mkdir()
    (build_dir / "micropython.mjs").write_bytes(b"mjs")
    (build_dir / "micropython.wasm").write_bytes(b"wasm")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or _fake_docker_run(cmd, **k),
    )

    staging = tmp_path / "staging"
    result = build_webassembly_fn(
        wasm_opts(build_dir=build_dir), tmp_path / "mpy", staging=staging
    )

    assert result == staging / "micropython.mjs"
    assert result.read_bytes() == b"mjs"
    assert (staging / "micropython.wasm").read_bytes() == b"wasm"
    make_calls = [c for c in calls if "make" in c]
    assert len(make_calls) == 1
    exec_command = make_calls[0]
    assert exec_command[:2] == ["docker", "exec"]
    assert "make" in exec_command
    # The image itself shows up on `docker create`, not on each `exec` --
    # one long-lived container per build now, addressed by its own name.
    create = next(c for c in calls if c[:2] == ["docker", "create"])
    assert "cibuildmp-webassembly:local" in create


def test_webassembly_container_binds_the_checkout_read_only_and_the_project_rw(
    monkeypatch, tmp_path
):
    """Record 0095: the checkout is an overlay lower layer, so it is bound
    **read-only and out of the way** while the writable view goes over its
    own host path; the user's own module tree stays an ordinary read-write
    bind at its own path."""
    _mock_webassembly_image(monkeypatch)
    build_dir = tmp_path / "build-wasm"
    build_dir.mkdir()
    (build_dir / "micropython.mjs").write_bytes(b"mjs")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or _fake_docker_run(cmd, **k),
    )

    mpy_dir = tmp_path / "mpy"
    staging = tmp_path / "staging"
    build_webassembly_fn(wasm_opts(build_dir=build_dir), mpy_dir, staging=staging)

    create = next(c for c in calls if c[:2] == ["docker", "create"])
    assert f"{mpy_dir}:/cibuildmp-lower-1:ro" in create
    assert f"{mpy_dir}:{mpy_dir}" not in create
    assert f"{staging}:{staging}" in create
    assert "/gh/ws/micropython/usermod:/gh/ws/micropython/usermod" in create


def test_webassembly_missing_mjs_after_success_is_an_error(monkeypatch, tmp_path):
    _mock_webassembly_image(monkeypatch)
    build_dir = tmp_path / "build-wasm"
    build_dir.mkdir()

    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: _fake_docker_run(cmd, **k),
    )

    with pytest.raises(UsermodBuildError, match="build reported success but"):
        build_webassembly_fn(wasm_opts(build_dir=build_dir), tmp_path / "mpy")


def test_webassembly_missing_wasm_companion_is_tolerated(monkeypatch, tmp_path):
    """The `.mjs` alone is not an error at build time -- `orchestrate.py`'s
    own `webassembly_companions()` is what decides whether a missing
    `micropython.wasm` matters, host-side, after collection."""
    _mock_webassembly_image(monkeypatch)
    build_dir = tmp_path / "build-wasm"
    build_dir.mkdir()
    (build_dir / "micropython.mjs").write_bytes(b"mjs")

    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: _fake_docker_run(cmd, **k),
    )

    staging = tmp_path / "staging"
    result = build_webassembly_fn(
        wasm_opts(build_dir=build_dir), tmp_path / "mpy", staging=staging
    )

    assert result == staging / "micropython.mjs"
    assert not (staging / "micropython.wasm").exists()


def test_webassembly_build_failure_names_the_command(monkeypatch, tmp_path):
    import subprocess as sp

    _mock_webassembly_image(monkeypatch)

    def fake_run(cmd, **kwargs):
        raise sp.CalledProcessError(1, cmd)

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", fake_run)

    with pytest.raises(UsermodBuildError, match="failed with exit code"):
        build_webassembly_fn(
            wasm_opts(build_dir=tmp_path / "build-wasm"), tmp_path / "mpy"
        )


def test_webassembly_no_docker_daemon_raises_clear_error(monkeypatch, tmp_path):
    # Docker-only means "docker unavailable" is a hard, clearly-worded
    # error, not a silent bare-host fallback -- the user's own call.
    _mock_webassembly_image(monkeypatch)

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", fake_run)

    with pytest.raises(UsermodBuildError, match="docker CLI itself is not on PATH"):
        build_webassembly_fn(
            wasm_opts(build_dir=tmp_path / "build-wasm"), tmp_path / "mpy"
        )

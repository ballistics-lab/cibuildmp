import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from cibuildmp.platforms.usermod import espidf
from cibuildmp.platforms.usermod.build_common import UsermodBuildError
from cibuildmp.platforms.usermod.build_esp32 import (
    Esp32BuildOptions,
    _esp32_project_mounts,
    esp32_make_command,
)
from cibuildmp.platforms.usermod.build_esp32 import build_esp32 as _build_esp32


def build_esp32_fn(*args, staging=None, **kwargs):
    """`build_esp32()` with a staging directory supplied -- see
    `test_usermod_build_unix.py`'s own `build_unix_fn()` for why."""
    if staging is None:
        staging = Path(tempfile.mkdtemp(prefix="cibmp-test-staging-"))
    return _build_esp32(*args, staging=staging, **kwargs)


def _fake_docker_run(cmd, **kwargs):
    """A `dockerrun.subprocess.run` stand-in. Since record 0095 the build
    runs inside one long-lived container, so this also stands in for the
    copy of `micropython.bin`/`firmware.bin` into `staging` -- a `sh -c`
    script here (`[ -e <src> ] && cp <src> <dest> || true`, one line per
    file, `build_esp32()`'s own comment), not a bare `cp` argv, so this
    parses each line rather than pattern-matching `"cp" in cmd`."""
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


def esp32_opts(**overrides) -> Esp32BuildOptions:
    defaults = {
        "user_c_modules": "/gh/ws/micropython/usermod/micropython.cmake",
        "frozen_manifest": "/gh/ws/a7p_manifest.py",
    }
    defaults.update(overrides)
    return Esp32BuildOptions(**defaults)


def test_esp32_project_mounts_omits_user_c_modules_when_empty():
    # `.parent` of an empty string is still relative ("." itself), so the
    # empty case has to be checked before `.parent` is ever taken -- see
    # `_esp32_project_mounts()`'s own comment.
    assert _esp32_project_mounts(esp32_opts(user_c_modules=""), None) == []


def test_esp32_project_mounts_includes_user_c_modules_parent_when_set():
    assert _esp32_project_mounts(
        esp32_opts(user_c_modules="/gh/ws/mymod/micropython.cmake"), None
    ) == [Path("/gh/ws/mymod")]


def test_esp32_command_matches_build_usermod_esp32_shape():
    # build-usermod-esp32's own "Build usermod" step -- no BUILD=
    # override, matching its own documented reason not to pass one at all.
    command = esp32_make_command(esp32_opts(), Path("/gh/ws/mpy"))

    assert command == [
        "make",
        "-C",
        "/gh/ws/mpy/ports/esp32",
        "BOARD=ESP32_GENERIC",
        "USER_C_MODULES=/gh/ws/micropython/usermod/micropython.cmake",
        "FROZEN_MANIFEST=/gh/ws/a7p_manifest.py",
    ]
    assert not any(arg.startswith("BUILD=") for arg in command)


def test_esp32_command_carries_mpy_cross_when_given():
    command = esp32_make_command(
        esp32_opts(), Path("/gh/ws/mpy"), mpy_cross=Path("/gh/ws/mpy-cross")
    )

    assert "MICROPY_MPYCROSS=/gh/ws/mpy-cross" in command


def _mock_esp32_image(monkeypatch, image="cibuildmp-esp32:local"):
    """Docker, since 2026-08-28 -- every real build_esp32() path needs
    ensure_image() to resolve something before it will run anything at
    all, the same shape `_mock_unix_image()`/webassembly's own tests
    already use. `container_mpy_cross()` is stubbed out for the same
    reason those do (record 0044's own live finding, now true for esp32
    too): it is a second real container, and these cases are about
    build_esp32()'s own command/script shape. `_probe_platform` is
    stubbed the same way `test_usermod_build_rp2.py`'s own
    `_mock_rp2_image()` stubs it, so `Container.__enter__` never runs a
    real `docker run --pull missing` on a non-native test host."""
    monkeypatch.setenv("CIBMP_ESP32_DOCKER_IMAGE", image)
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_common.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )
    monkeypatch.setattr(
        espidf, "fetch_esp_idf", lambda version, **k: Path("/gh/ws/idf")
    )
    monkeypatch.setattr("cibuildmp.dockerrun._probe_platform", lambda *a, **k: "")


def test_esp32_docker_image_override_skips_own_dockerfile_build(monkeypatch, tmp_path):
    _mock_esp32_image(monkeypatch)
    build_dir = tmp_path / "mpy" / "ports" / "esp32" / "build-ESP32_GENERIC"
    build_dir.mkdir(parents=True)
    (build_dir / "micropython.bin").write_bytes(b"bin")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or _fake_docker_run(cmd, **k),
    )

    staging = tmp_path / "staging"
    result = build_esp32_fn(
        esp32_opts(),
        tmp_path / "mpy",
        toolchain_root=tmp_path / "cache",
        staging=staging,
    )

    assert result == staging / "micropython.bin"
    assert result.read_bytes() == b"bin"
    # Two now, not one: the cross-compiler discovery/probe step
    # ([0100]'s own rp2 correction, applied here too) runs its own
    # install+export script ahead of the real make invocation, rather
    # than folding both into the single script this used to be.
    script_calls = [c for c in calls if "bash" in c]
    assert len(script_calls) == 2
    for exec_command in script_calls:
        assert exec_command[:2] == ["docker", "exec"]
    create = next(c for c in calls if c[:2] == ["docker", "create"])
    assert "cibuildmp-esp32:local" in create


def test_esp32_no_docker_image_raises_clear_error(monkeypatch, tmp_path):
    monkeypatch.delenv("CIBMP_ESP32_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr("cibuildmp.dockerrun._pins", lambda: {"image_group": {}})

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    with pytest.raises(UsermodBuildError, match="no Docker image registered"):
        build_esp32_fn(
            esp32_opts(), tmp_path / "mpy", toolchain_root=tmp_path / "cache"
        )

    assert calls == []


def test_esp32_no_staging_is_a_clear_error(monkeypatch, tmp_path):
    """Needs a real image resolved first but must still fail before any
    container is created -- `_build_esp32()` directly, bypassing
    `build_esp32_fn()`'s own default staging directory."""
    _mock_esp32_image(monkeypatch)
    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    with pytest.raises(UsermodBuildError, match="staging directory"):
        _build_esp32(esp32_opts(), tmp_path / "mpy", toolchain_root=tmp_path / "cache")

    assert calls == []


def test_esp32_script_installs_once_then_makes(monkeypatch, tmp_path):
    """The `.installed` marker gates a real install to once per cache, but
    the install+export sequence itself now runs twice per build -- once in
    the cross-compiler discovery script, once again ahead of the real
    `make` invocation ([0100]'s own rp2 correction, applied here too: a
    probe needs the environment exported before `esp32_make_command()`'s
    own `CFLAGS_EXTRA` is built). `script_calls[-1]` is the one that
    actually runs `make`."""
    _mock_esp32_image(monkeypatch)
    build_dir = tmp_path / "mpy" / "ports" / "esp32" / "build-ESP32_GENERIC"
    build_dir.mkdir(parents=True)
    (build_dir / "micropython.bin").write_bytes(b"bin")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or _fake_docker_run(cmd, **k),
    )

    build_esp32_fn(esp32_opts(), tmp_path / "mpy", toolchain_root=tmp_path / "cache")

    script_calls = [c for c in calls if "bash" in c]
    assert len(script_calls) == 2
    script = script_calls[-1][-1]
    assert "idf_tools.py install --targets=esp32" in script
    assert "idf_tools.py install-python-env" in script
    assert "idf_tools.py export --format key-value" in script
    # Real CI (unmapped --user UID, unlike a local UID matching the
    # image's own /etc/passwd) resolves an unset HOME to "/" -- ESP-IDF's
    # own CMake ComponentManager then fails to create its cache dir
    # there, live-caught 2026-08-28. HOME must be exported before
    # anything that could touch it runs.
    assert script.index("export HOME=") < script.index("idf_tools.py install")
    assert ".installed" in script
    assert "make -C" in script
    assert "ports/esp32" in script

    # The discovery script (run first) has its own install+export copy,
    # ending in the cross-compiler glob rather than `make`.
    discover_script = script_calls[0][-1]
    assert "idf_tools.py install --targets=esp32" in discover_script
    assert "make -C" not in discover_script
    assert "*-elf-gcc" in discover_script


def test_esp32_container_binds_the_checkout_read_only_and_mounts_idf_and_tools_dirs(
    monkeypatch, tmp_path
):
    """Record 0095: the checkout is an overlay lower layer, so it is bound
    **read-only and out of the way**; the ESP-IDF checkout and its tools
    cache stay ordinary read-write binds at their own paths -- persistent
    input, not part of the ephemeral overlay."""
    _mock_esp32_image(monkeypatch)
    build_dir = tmp_path / "mpy" / "ports" / "esp32" / "build-ESP32_GENERIC"
    build_dir.mkdir(parents=True)
    (build_dir / "micropython.bin").write_bytes(b"bin")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or _fake_docker_run(cmd, **k),
    )

    mpy_dir = tmp_path / "mpy"
    build_esp32_fn(esp32_opts(), mpy_dir, toolchain_root=tmp_path / "cache")

    create = next(c for c in calls if c[:2] == ["docker", "create"])
    assert f"{mpy_dir}:/cibuildmp-lower-1:ro" in create
    assert f"{mpy_dir}:{mpy_dir}" not in create
    assert "/gh/ws/idf:/gh/ws/idf" in create
    tools_dir = tmp_path / "cache" / "esp-idf" / "v5.5.1" / "tools" / "esp32"
    assert f"{tools_dir}:{tools_dir}" in create


def test_esp32_missing_bin_after_success_is_an_error(monkeypatch, tmp_path):
    _mock_esp32_image(monkeypatch)
    (tmp_path / "mpy" / "ports" / "esp32").mkdir(parents=True)

    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: _fake_docker_run(cmd, **k),
    )

    with pytest.raises(UsermodBuildError, match="build reported success but"):
        build_esp32_fn(
            esp32_opts(), tmp_path / "mpy", toolchain_root=tmp_path / "cache"
        )


def test_esp32_collects_the_combined_firmware_when_present(monkeypatch, tmp_path):
    """`firmware.bin` -- the flashable combined image ([0079]) -- is copied
    into `staging` alongside the primary when the build produced one."""
    _mock_esp32_image(monkeypatch)
    build_dir = tmp_path / "mpy" / "ports" / "esp32" / "build-ESP32_GENERIC"
    build_dir.mkdir(parents=True)
    (build_dir / "micropython.bin").write_bytes(b"bin")
    (build_dir / "firmware.bin").write_bytes(b"combined")

    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: _fake_docker_run(cmd, **k),
    )

    staging = tmp_path / "staging"
    result = build_esp32_fn(
        esp32_opts(),
        tmp_path / "mpy",
        toolchain_root=tmp_path / "cache",
        staging=staging,
    )

    assert result == staging / "micropython.bin"
    assert (staging / "firmware.bin").read_bytes() == b"combined"


def test_esp32_build_failure_names_the_command(monkeypatch, tmp_path):
    import subprocess as sp

    _mock_esp32_image(monkeypatch)

    def fake_run(cmd, **kwargs):
        raise sp.CalledProcessError(1, cmd)

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", fake_run)

    with pytest.raises(UsermodBuildError, match="failed with exit code"):
        build_esp32_fn(
            esp32_opts(), tmp_path / "mpy", toolchain_root=tmp_path / "cache"
        )


def test_esp32_custom_board_and_target():
    command = esp32_make_command(
        esp32_opts(board="ESP32S3_GENERIC"), Path("/gh/ws/mpy")
    )

    assert "BOARD=ESP32S3_GENERIC" in command


def test_esp32_extra_cmake_args_reach_the_container_as_idfpy_flags(
    monkeypatch, tmp_path
):
    # Not a make command-line token (unlike extra_make_args): ported
    # through the container's own environment instead, since
    # ports/esp32/Makefile builds IDFPY_FLAGS with a plain `+=` that a
    # command-line assignment would replace rather than add to -- see
    # build_common.cmake_extra_args_env()'s own docstring.
    _mock_esp32_image(monkeypatch)
    build_dir = tmp_path / "mpy" / "ports" / "esp32" / "build-ESP32_GENERIC"
    build_dir.mkdir(parents=True)
    (build_dir / "micropython.bin").write_bytes(b"bin")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or _fake_docker_run(cmd, **k),
    )

    build_esp32_fn(
        esp32_opts(extra_cmake_args=("-DMICROPY_C_HEAP_SIZE=131072",)),
        tmp_path / "mpy",
        toolchain_root=tmp_path / "cache",
    )

    # The env carrying IDFPY_FLAGS is only passed to the real make
    # invocation (the last "bash" call), not the discovery script ahead
    # of it -- see build_esp32()'s own call sites.
    exec_command = [c for c in calls if "bash" in c][-1]
    assert "IDFPY_FLAGS=-DMICROPY_C_HEAP_SIZE=131072" in exec_command


def test_esp32_no_extra_cmake_args_means_no_idfpy_flags_env(monkeypatch, tmp_path):
    _mock_esp32_image(monkeypatch)
    build_dir = tmp_path / "mpy" / "ports" / "esp32" / "build-ESP32_GENERIC"
    build_dir.mkdir(parents=True)
    (build_dir / "micropython.bin").write_bytes(b"bin")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or _fake_docker_run(cmd, **k),
    )

    build_esp32_fn(esp32_opts(), tmp_path / "mpy", toolchain_root=tmp_path / "cache")

    exec_command = next(c for c in calls if "bash" in c)
    assert not any(arg.startswith("IDFPY_FLAGS=") for arg in exec_command)

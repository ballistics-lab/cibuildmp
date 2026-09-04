import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from cibuildmp import dockerrun
from cibuildmp.platforms.usermod.build_common import UsermodBuildError
from cibuildmp.platforms.usermod.build_qemu import (
    QemuBuildOptions,
    qemu_make_command,
)
from cibuildmp.platforms.usermod.build_qemu import build_qemu as _build_qemu


def build_qemu_fn(*args, staging=None, **kwargs):
    """`build_qemu()` with a staging directory supplied -- see
    `test_usermod_build_unix.py`'s own `build_unix_fn()` for why."""
    if staging is None:
        staging = Path(tempfile.mkdtemp(prefix="cibmp-test-staging-"))
    return _build_qemu(*args, staging=staging, **kwargs)


def _fake_docker_run(cmd, **kwargs):
    """A `dockerrun.subprocess.run` stand-in, the same shape
    `test_usermod_build_unix.py`/`test_usermod_build_rp2.py` use. Since
    record 0095 the build runs inside one long-lived container, so this
    also stands in for the `cp` of the finished `firmware.elf` into
    `staging`."""
    if cmd[:2] == ["docker", "exec"] and "cp" in cmd:
        source, dest = (Path(p) for p in cmd[cmd.index("cp") + 1 :][:2])
        dest.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            shutil.copy(source, dest)
    if kwargs.get("capture_output"):
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    return None


def _mock_qemu_image(monkeypatch, image="qemu:test"):
    monkeypatch.setattr(dockerrun, "ensure_image", lambda *a, **k: image)
    # `qemu`'s own image is a fixed `linux/amd64` cross host, not native to
    # whatever the test runner's own architecture is -- stubbed the same
    # way `test_usermod_build_rp2.py`'s own `_mock_rp2_image()` stubs it.
    monkeypatch.setattr(dockerrun, "_probe_platform", lambda *a, **k: "")


def qemu_opts(**overrides) -> QemuBuildOptions:
    defaults = {
        "user_c_modules": "/gh/ws/micropython/usermod",
        "frozen_manifest": "/gh/ws/a7p_manifest.py",
        "build_dir": Path("/gh/ws/usermod/build/armv7m"),
        # A real tag with a real, pinned toolchain_version for both the
        # arm and riscv toolchain families -- since [0087], build_qemu()
        # needs one to resolve which cross compiler to fetch
        # (targets.qemu_toolchain()) for every board but POWERNV9.
        "tag": "v1.29.0",
    }
    defaults.update(overrides)
    return QemuBuildOptions(**defaults)


def test_qemu_command_matches_build_usermod_armv7m_shape():
    # build-usermod-armv7m's own "Build usermod (armv7m, MPS2_AN385)" step.
    command = qemu_make_command(qemu_opts(), Path("/gh/ws/mpy"))

    assert command == [
        "make",
        "-C",
        "/gh/ws/mpy/ports/qemu",
        "BOARD=MPS2_AN385",
        "BUILD=/gh/ws/usermod/build/armv7m",
        "CROSS_COMPILE=arm-none-eabi-",
        "USER_C_MODULES=/gh/ws/micropython/usermod",
        "FROZEN_MANIFEST=/gh/ws/a7p_manifest.py",
    ]


def test_qemu_runs_in_its_own_image(monkeypatch, tmp_path):
    # Record 0032's gap, closed by 0049: qemu was the last usermod port
    # still compiling on the bare host. It survived because it *worked* --
    # `toolchains.resolve()` found an arm-none-eabi- on the runner and
    # subprocess ran it -- and deleting that resolver is what finally
    # forced the wiring D30 had required all along.
    _mock_qemu_image(monkeypatch)
    calls = []
    monkeypatch.setattr(
        dockerrun.subprocess,
        "run",
        lambda cmd, **k: calls.append(cmd) or _fake_docker_run(cmd, **k),
    )
    build_dir = tmp_path / "build-armv7m"
    build_dir.mkdir()
    (build_dir / "firmware.elf").write_bytes(b"\x7fELF")

    build_qemu_fn(
        qemu_opts(build_dir=build_dir),
        tmp_path / "mpy",
        toolchain_root=tmp_path / "toolchains",
    )

    create = next(c for c in calls if c[:2] == ["docker", "create"])
    assert "qemu:test" in create
    # An amd64 image cross-compiling to bare metal, which no Linux
    # container is native to -- so it is emulated on an arm64 host, the
    # same as windows and webassembly.
    assert "--platform=linux/amd64" in create


def test_qemu_no_staging_is_a_clear_error(monkeypatch, tmp_path):
    """Needs a real image resolved first but must still fail before any
    container is created -- `_build_qemu()` directly, bypassing
    `build_qemu_fn()`'s own default staging directory."""
    _mock_qemu_image(monkeypatch)
    calls = []
    monkeypatch.setattr(
        dockerrun.subprocess, "run", lambda cmd, **k: calls.append(cmd) or None
    )

    with pytest.raises(UsermodBuildError, match="staging directory"):
        _build_qemu(
            qemu_opts(),
            tmp_path / "mpy",
            toolchain_root=tmp_path / "toolchains",
        )

    assert calls == []


def test_qemu_builds_and_returns_firmware_path(monkeypatch, tmp_path):
    _mock_qemu_image(monkeypatch)
    build_dir = tmp_path / "build-armv7m"
    build_dir.mkdir()
    (build_dir / "firmware.elf").write_bytes(b"\x7fELF")

    monkeypatch.setattr(
        dockerrun.subprocess,
        "run",
        lambda cmd, **k: _fake_docker_run(cmd, **k),
    )

    staging = tmp_path / "staging"
    result = build_qemu_fn(
        qemu_opts(build_dir=build_dir),
        tmp_path / "mpy",
        toolchain_root=tmp_path / "toolchains",
        staging=staging,
    )

    assert result == staging / "firmware.elf"
    assert result.read_bytes() == b"\x7fELF"


def test_qemu_missing_firmware_after_success_is_an_error(monkeypatch, tmp_path):
    _mock_qemu_image(monkeypatch)
    build_dir = tmp_path / "build-armv7m"
    build_dir.mkdir()

    monkeypatch.setattr(
        dockerrun.subprocess,
        "run",
        lambda cmd, **k: _fake_docker_run(cmd, **k),
    )

    with pytest.raises(UsermodBuildError, match="build reported success but"):
        build_qemu_fn(
            qemu_opts(build_dir=build_dir),
            tmp_path / "mpy",
            toolchain_root=tmp_path / "toolchains",
        )


def test_qemu_build_failure_surfaces(monkeypatch, tmp_path):
    _mock_qemu_image(monkeypatch)

    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(dockerrun.subprocess, "run", fake_run)

    with pytest.raises(UsermodBuildError, match="failed with exit code"):
        build_qemu_fn(
            qemu_opts(build_dir=tmp_path / "build-armv7m"),
            tmp_path / "mpy",
            toolchain_root=tmp_path / "toolchains",
        )


def test_qemu_unsupported_board_rejected(tmp_path):
    with pytest.raises(UsermodBuildError, match="not supported yet"):
        build_qemu_fn(qemu_opts(board="MIMXRT1050_EVK"), tmp_path / "mpy")


def test_qemu_no_tag_raises_a_clear_error_before_touching_docker(monkeypatch, tmp_path):
    # [0087]: with embedded_base (`arm_embedded`/`riscv_embedded` before
    # record 0096) no longer baking a cross compiler, a real tag is
    # required to resolve which one to fetch -- this must fail before
    # ever calling docker.
    calls = []
    monkeypatch.setattr(
        dockerrun, "ensure_image", lambda *a, **k: calls.append(a) or "qemu:test"
    )

    with pytest.raises(UsermodBuildError, match="real MicroPython tag"):
        build_qemu_fn(
            qemu_opts(tag=""),
            tmp_path / "mpy",
            toolchain_root=tmp_path / "toolchains",
        )

    assert calls == []


def test_qemu_fetches_its_own_toolchain_and_puts_it_on_path(monkeypatch, tmp_path):
    # [0086]/[0087]: embedded_base no longer bakes a cross compiler --
    # build_qemu() must fetch it at container time and prepend it onto
    # PATH, mounting the cache directory it lands in -- a real, persistent
    # read-write host mount, not part of the checkout's own overlay
    # ([0095]).
    _mock_qemu_image(monkeypatch)
    calls = []
    monkeypatch.setattr(
        dockerrun.subprocess,
        "run",
        lambda cmd, **k: calls.append(cmd) or _fake_docker_run(cmd, **k),
    )
    build_dir = tmp_path / "build-MPS2_AN385"
    build_dir.mkdir()
    (build_dir / "firmware.elf").write_bytes(b"\x7fELF")
    toolchain_root = tmp_path / "toolchains"

    build_qemu_fn(
        qemu_opts(build_dir=build_dir), tmp_path / "mpy", toolchain_root=toolchain_root
    )

    create = next(c for c in calls if c[:2] == ["docker", "create"])
    expected_dir = (
        toolchain_root / "toolchains" / "arm-none-eabi-" / "cross" / "15.2.1-1.1"
    )
    assert expected_dir.parent.is_dir()  # created host-side
    mount = f"{expected_dir.parent.as_posix()}:{expected_dir.parent.as_posix()}"
    assert mount in create

    script_call = next(
        c for c in calls if "BOARD=MPS2_AN385" in " ".join(str(p) for p in c)
    )
    script = script_call[-1]
    assert f'export PATH="{(expected_dir / "bin").as_posix()}:$PATH"' in script


def test_qemu_container_binds_the_checkout_read_only_and_the_project_rw(
    monkeypatch, tmp_path
):
    """Record 0095: the checkout is an overlay lower layer, so it is bound
    **read-only and out of the way** while the writable view goes over its
    own host path; the user's own module tree stays an ordinary read-write
    bind at its own path."""
    _mock_qemu_image(monkeypatch)
    build_dir = tmp_path / "build-armv7m"
    build_dir.mkdir()
    (build_dir / "firmware.elf").write_bytes(b"\x7fELF")

    calls = []
    monkeypatch.setattr(
        dockerrun.subprocess,
        "run",
        lambda cmd, **k: calls.append(cmd) or _fake_docker_run(cmd, **k),
    )

    mpy_dir = tmp_path / "mpy"
    staging = tmp_path / "staging"
    build_qemu_fn(
        qemu_opts(build_dir=build_dir),
        mpy_dir,
        toolchain_root=tmp_path / "toolchains",
        staging=staging,
    )

    create = next(c for c in calls if c[:2] == ["docker", "create"])
    assert f"{mpy_dir}:/cibuildmp-lower-1:ro" in create
    assert f"{mpy_dir}:{mpy_dir}" not in create
    assert f"{staging}:{staging}" in create
    assert "/gh/ws/micropython/usermod:/gh/ws/micropython/usermod" in create


@pytest.mark.parametrize(
    ("board", "expected_cross"),
    [
        ("MICROBIT", "arm-none-eabi-"),
        ("MPS2_AN385", "arm-none-eabi-"),
        ("MPS2_AN500", "arm-none-eabi-"),
        ("MPS3_AN547", "arm-none-eabi-"),
        ("NETDUINO2", "arm-none-eabi-"),
        ("SABRELITE", "arm-none-eabi-"),
        ("VIRT_RV32", "riscv64-unknown-elf-"),
        ("VIRT_RV64", "riscv64-unknown-elf-"),
        ("POWERNV9", "powerpc64le-linux-gnu-"),
    ],
)
def test_qemu_uses_its_boards_own_cross_prefix(
    board, expected_cross, monkeypatch, tmp_path
):
    """Each board gets its own prefix, not always armv7m's --
    VIRT_RV32/VIRT_RV64 are RISC-V. The prefixes used to come from
    `toolchains.resolve()` answering "which one works on this machine";
    record 0049 deleted that question, so the map states them and the
    image supplies exactly those names."""
    _mock_qemu_image(monkeypatch)
    commands = []
    monkeypatch.setattr(
        dockerrun.subprocess,
        "run",
        lambda cmd, **k: commands.append(cmd) or _fake_docker_run(cmd, **k),
    )
    build_dir = tmp_path / f"build-{board}"
    build_dir.mkdir()
    (build_dir / "firmware.elf").write_bytes(b"\x7fELF")

    build_qemu_fn(
        qemu_opts(board=board, build_dir=build_dir),
        tmp_path / "mpy",
        toolchain_root=tmp_path / "toolchains",
    )

    # POWERNV9 needs no fetch (its own ppc64le_linux image still bakes
    # its toolchain, record 0025) -- plain `make` argv on the exec.
    # Every other board's own exec runs a `bash -c` script: fetch, PATH
    # export, then the real make invocation.
    exec_command = next(c for c in commands if "make" in " ".join(str(p) for p in c))
    haystack = (
        exec_command[-1] if exec_command[-3:-1] == ["bash", "-c"] else exec_command
    )
    assert f"CROSS_COMPILE={expected_cross}" in haystack


def test_qemu_riscv_command_carries_the_riscv_prefix(tmp_path):
    command = qemu_make_command(
        qemu_opts(board="VIRT_RV64"), Path("/gh/ws/mpy"), "riscv64-unknown-elf-"
    )

    assert command == [
        "make",
        "-C",
        "/gh/ws/mpy/ports/qemu",
        "BOARD=VIRT_RV64",
        "BUILD=/gh/ws/usermod/build/armv7m",
        "CROSS_COMPILE=riscv64-unknown-elf-",
        "USER_C_MODULES=/gh/ws/micropython/usermod",
        "FROZEN_MANIFEST=/gh/ws/a7p_manifest.py",
    ]

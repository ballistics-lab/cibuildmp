from pathlib import Path

import pytest

from cibuildmp import dockerrun
from cibuildmp.platforms.usermod.build_common import UsermodBuildError
from cibuildmp.platforms.usermod.build_qemu import (
    QemuBuildOptions,
    build_qemu,
    qemu_make_command,
)


def qemu_opts(**overrides) -> QemuBuildOptions:
    defaults = {
        "user_c_modules": "/gh/ws/micropython/usermod",
        "frozen_manifest": "/gh/ws/a7p_manifest.py",
        "build_dir": Path("/gh/ws/usermod/build/armv7m"),
        # A real tag with a real, pinned toolchain_version for both
        # arm_embedded and riscv_embedded -- since [0087], build_qemu()
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
    calls = []
    monkeypatch.setattr(dockerrun, "ensure_image", lambda *a, **k: "qemu:test")
    monkeypatch.setattr(dockerrun, "run", lambda command, **kw: calls.append(kw))
    build_dir = tmp_path / "build-armv7m"
    build_dir.mkdir()
    (build_dir / "firmware.elf").write_bytes(b"\x7fELF")

    build_qemu(
        qemu_opts(build_dir=build_dir),
        tmp_path / "mpy",
        toolchain_root=tmp_path / "toolchains",
    )

    assert calls[0]["image"] == "qemu:test"
    # An amd64 image cross-compiling to bare metal, which no Linux
    # container is native to -- so it is emulated on an arm64 host, the
    # same as windows and webassembly.
    assert calls[0]["oci_platform"] == "linux/amd64"


def test_qemu_builds_and_returns_firmware_path(monkeypatch, tmp_path):
    build_dir = tmp_path / "build-armv7m"
    build_dir.mkdir()
    (build_dir / "firmware.elf").write_bytes(b"\x7fELF")

    monkeypatch.setattr(dockerrun, "ensure_image", lambda *a, **k: "qemu:test")
    monkeypatch.setattr(dockerrun, "run", lambda *a, **k: None)

    result = build_qemu(
        qemu_opts(build_dir=build_dir),
        tmp_path / "mpy",
        toolchain_root=tmp_path / "toolchains",
    )

    assert result == build_dir / "firmware.elf"


def test_qemu_missing_firmware_after_success_is_an_error(monkeypatch, tmp_path):
    build_dir = tmp_path / "build-armv7m"
    build_dir.mkdir()

    monkeypatch.setattr(dockerrun, "ensure_image", lambda *a, **k: "qemu:test")
    monkeypatch.setattr(dockerrun, "run", lambda *a, **k: None)

    with pytest.raises(UsermodBuildError, match="build reported success but"):
        build_qemu(
            qemu_opts(build_dir=build_dir),
            tmp_path / "mpy",
            toolchain_root=tmp_path / "toolchains",
        )


def test_qemu_build_failure_surfaces(monkeypatch, tmp_path):
    monkeypatch.setattr(dockerrun, "ensure_image", lambda *a, **k: "qemu:test")
    monkeypatch.setattr(
        dockerrun,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(
            UsermodBuildError("failed with exit code 1")
        ),
    )

    with pytest.raises(UsermodBuildError, match="failed with exit code"):
        build_qemu(
            qemu_opts(build_dir=tmp_path / "build-armv7m"),
            tmp_path / "mpy",
            toolchain_root=tmp_path / "toolchains",
        )


def test_qemu_unsupported_board_rejected(tmp_path):
    with pytest.raises(UsermodBuildError, match="not supported yet"):
        build_qemu(qemu_opts(board="MIMXRT1050_EVK"), tmp_path / "mpy")


def test_qemu_no_tag_raises_a_clear_error_before_touching_docker(monkeypatch, tmp_path):
    # [0087]: with arm_embedded/riscv_embedded no longer baking a cross
    # compiler, a real tag is required to resolve which one to fetch --
    # this must fail before ever calling docker.
    calls = []
    monkeypatch.setattr(
        dockerrun, "ensure_image", lambda *a, **k: calls.append(a) or "qemu:test"
    )

    with pytest.raises(UsermodBuildError, match="real MicroPython tag"):
        build_qemu(
            qemu_opts(tag=""),
            tmp_path / "mpy",
            toolchain_root=tmp_path / "toolchains",
        )

    assert calls == []


def test_qemu_fetches_its_own_toolchain_and_puts_it_on_path(monkeypatch, tmp_path):
    # [0086]/[0087]: arm_embedded no longer bakes a cross compiler --
    # build_qemu() must fetch it at container time and prepend it onto
    # PATH, mounting the cache directory it lands in.
    monkeypatch.setattr(dockerrun, "ensure_image", lambda *a, **k: "qemu:test")
    calls = []
    monkeypatch.setattr(
        dockerrun, "run", lambda command, **kw: calls.append((command, kw))
    )
    build_dir = tmp_path / "build-MPS2_AN385"
    build_dir.mkdir()
    (build_dir / "firmware.elf").write_bytes(b"\x7fELF")
    toolchain_root = tmp_path / "toolchains"

    build_qemu(
        qemu_opts(build_dir=build_dir), tmp_path / "mpy", toolchain_root=toolchain_root
    )

    command, kwargs = calls[0]
    assert command[:2] == ["bash", "-c"]
    script = command[2]
    expected_dir = (
        toolchain_root / "toolchains" / "arm-none-eabi-" / "cross" / "15.2.1-1.1"
    )
    assert expected_dir.parent.is_dir()  # created host-side
    assert expected_dir.parent in kwargs["mounts"]
    assert f'export PATH="{(expected_dir / "bin").as_posix()}:$PATH"' in script


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
    commands = []
    monkeypatch.setattr(dockerrun, "ensure_image", lambda *a, **k: "qemu:test")
    monkeypatch.setattr(
        dockerrun, "run", lambda command, **kw: commands.append(command)
    )
    build_dir = tmp_path / f"build-{board}"
    build_dir.mkdir()
    (build_dir / "firmware.elf").write_bytes(b"\x7fELF")

    build_qemu(
        qemu_opts(board=board, build_dir=build_dir),
        tmp_path / "mpy",
        toolchain_root=tmp_path / "toolchains",
    )

    # POWERNV9 needs no fetch (its own ppc64le_linux image still bakes
    # its toolchain, record 0025) -- plain command, unwrapped. Every
    # other board's command is now a bash -c script: fetch, PATH export,
    # then the real make invocation.
    command = commands[0]
    haystack = command[-1] if command[:2] == ["bash", "-c"] else command
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

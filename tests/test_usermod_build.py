from pathlib import Path

import pytest

from cibuildmp import dockerrun
from cibuildmp.usermod import build
from cibuildmp.usermod.build import (
    UNIX_ARCH_SETTINGS,
    WINDOWS_ARCH_SETTINGS,
    Esp32BuildOptions,
    QemuBuildOptions,
    UnixBuildOptions,
    UsermodBuildError,
    WebassemblyBuildOptions,
    WindowsBuildOptions,
    build_esp32,
    build_qemu,
    build_unix,
    build_webassembly,
    build_windows,
    esp32_make_command,
    qemu_make_command,
    run_unix_deplibs,
    unix_make_command,
    webassembly_make_command,
    windows_make_command,
)
from cibuildmp.usermod.espidf import ResolvedEspIdf


def _pe(machine: int, *, pe_offset: int = 0x80) -> bytes:
    """The smallest byte string `verify_windows_output()` will accept.

    A two-byte `b"MZ"` used to be enough for the windows build tests,
    because `build_windows()` checked only that the file existed. It
    checks the COFF `Machine` now, so a stub has to carry a real DOS
    stub, a real `e_lfanew`, a real `PE\0\0` and a real machine value --
    which is the point: the stub that used to pass is exactly the shape
    of output the check exists to reject.
    """
    data = bytearray(pe_offset + 6)
    data[:2] = b"MZ"
    data[0x3C:0x40] = pe_offset.to_bytes(4, "little")
    data[pe_offset : pe_offset + 4] = b"PE\0\0"
    data[pe_offset + 4 : pe_offset + 6] = machine.to_bytes(2, "little")
    return bytes(data)


def fake_elf(target: str = "manylinux_2_28_x86_64") -> bytes:
    """A 20-byte ELF header claiming `target`'s own architecture.

    `verify_unix_output()` (record 0043) reads `e_machine`, `EI_CLASS` and
    `EI_DATA` off the finished binary, so a stub build's output has to be
    a header rather than the four magic bytes these tests used to write.
    That is the check earning its keep: under the native-image model a
    wrong-platform image produces a *working* binary of the wrong
    architecture, which nothing else here would notice.
    """
    machine, elf_class, elf_data = UNIX_ARCH_SETTINGS[
        dockerrun.split_tag(target)[1]
    ].elf
    byteorder = "big" if elf_data == 2 else "little"
    return (
        b"\x7fELF"
        + bytes([elf_class, elf_data, 1, 0])
        + bytes(8)
        + (2).to_bytes(2, byteorder)
        + machine.to_bytes(2, byteorder)
    )


def opts(target: str = "manylinux_2_28_x86_64", **overrides) -> UnixBuildOptions:
    defaults = {
        "target": target,
        "user_c_modules": "/gh/ws/micropython/usermod",
        "frozen_manifest": "/gh/ws/a7p_manifest.py",
        "build_dir": Path("/gh/ws/usermod/build/x86_64"),
    }
    defaults.update(overrides)
    return UnixBuildOptions(**defaults)


def test_native_command_passes_an_empty_cross_compile():
    # Record 0043: the compiler inside a `manylinux_2_28_x86_64` image
    # already targets x86_64, so `CROSS_COMPILE=` is empty on purpose --
    # not missing. It is passed explicitly rather than omitted so the
    # Makefile's own default can never quietly supply a prefix.
    command = unix_make_command(opts(), Path("/gh/ws/mpy"))

    assert command == [
        "make",
        "-C",
        "/gh/ws/mpy/ports/unix",
        "VARIANT=standard",
        "BUILD=/gh/ws/usermod/build/x86_64",
        "CROSS_COMPILE=",
        "USER_C_MODULES=/gh/ws/micropython/usermod",
        "FROZEN_MANIFEST=/gh/ws/a7p_manifest.py",
    ]


def test_every_native_target_shares_that_shape():
    # The point of the native-image model: aarch64, armv7l and i686 stop
    # being special cases. `MICROPY_FORCE_32BIT` (the old x86 row) and
    # `MICROPY_STANDALONE` (the old armhf row) are both gone -- their
    # images provide a native compiler and a resolvable libffi.
    for target in (
        "manylinux_2_28_aarch64",
        "manylinux_2_31_armv7l",
        "manylinux_2_28_i686",
        "musllinux_1_2_riscv64",
    ):
        command = unix_make_command(opts(target), Path("/gh/ws/mpy"))

        assert "CROSS_COMPILE=" in command
        assert "MICROPY_FORCE_32BIT=1" not in command
        assert "MICROPY_STANDALONE=1" not in command


def test_mipsel_is_the_one_target_that_still_cross_compiles():
    # 0043's documented exception -- no pypa image, no PEP 600 tag, no
    # Docker official image for 32-bit mipsel, so nothing to be native to.
    command = unix_make_command(opts("manylinux_2_39_mipsel"), Path("/gh/ws/mpy"))

    assert "CROSS_COMPILE=mipsel-linux-gnu-" in command
    assert "MICROPY_STANDALONE=1" in command
    assert "LDFLAGS_EXTRA=-static" in command


_FAKE_UNIX_IMAGE = "manylinux_2_28_x86_64:local"


def _mock_unix_image(monkeypatch, image=_FAKE_UNIX_IMAGE):
    """Docker-only (D30): every real build_unix() path needs
    ensure_image() to resolve something before it will run anything at
    all. Tests that only care about the make/deplibs command shape (not
    about image resolution itself) fake a resolved image this way and
    mock dockerrun's own subprocess.run -- not build.subprocess, which
    build_unix() no longer calls under any circumstance now that there
    is no bare-host path left."""
    monkeypatch.setattr("cibuildmp.dockerrun.ensure_image", lambda *a, **k: image)
    # Neutralise the emulation/linux32 probe too (record 0043). It starts
    # a real throwaway container for any non-native platform, which every
    # target but one is on an x86_64 host -- and it has its own dedicated
    # coverage in test_usermod_dockerrun.py. These cases are about the
    # make/deplibs command shape, not about how the image is reached.
    monkeypatch.setattr("cibuildmp.dockerrun._probe_platform", lambda *a, **k: "")
    # ...and the in-container mpy-cross build (record 0043's own live
    # finding: the host's binary cannot run inside these images). It is a
    # second real container, and these cases are about the port build's
    # own command shape.
    monkeypatch.setattr(
        "cibuildmp.usermod.build.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )


def test_deplibs_command_shape(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd),
    )
    run_unix_deplibs(
        opts("manylinux_2_39_mipsel"), Path("/gh/ws/mpy"), docker_image=_FAKE_UNIX_IMAGE
    )

    assert calls[0][-1] == "deplibs"
    assert "MICROPY_STANDALONE=1" in calls[0]


def test_every_upstream_arch_plus_mipsel_has_settings():
    # cibuildwheel's own seven, under its own names (0043 step 4), plus
    # cibuildmp's own mipsel. `x64`/`x86`/`armhf` are gone as spellings.
    assert set(UNIX_ARCH_SETTINGS) == {
        "x86_64",
        "i686",
        "aarch64",
        "armv7l",
        "ppc64le",
        "s390x",
        "riscv64",
        "mipsel",
    }


def test_unknown_target_rejected():
    with pytest.raises(UsermodBuildError, match="unknown unix target"):
        build_unix(opts("manylinux_2_28_sparc64"), Path("/gh/ws/mpy"))


def test_a_real_arch_under_an_undeclared_floor_is_rejected():
    # `manylinux_2_34` is a real upstream floor this project does not
    # curate for any arch, so it names no cell of the matrix -- and must
    # fail as an unknown *target*, not slip through on its arch alone.
    with pytest.raises(UsermodBuildError, match="unknown unix target"):
        build_unix(opts("manylinux_2_34_x86_64"), Path("/gh/ws/mpy"))


@pytest.mark.parametrize(
    "arch",
    [
        "manylinux_2_28_x86_64",
        "manylinux_2_28_i686",
        "manylinux_2_28_aarch64",
        "manylinux_2_31_armv7l",
        "manylinux_2_39_mipsel",
    ],
)
def test_unix_no_image_registered_is_a_clear_error(monkeypatch, tmp_path, arch):
    # Docker-only (D30): no bare-host fallback for any unix target any
    # more -- with no override and nothing pinned in
    # resources/pinned_docker_images.toml, build_unix() must fail loudly,
    # the same shape build_webassembly() already has. That is the state
    # every `unix` cell is actually in on this branch (record 0044), not
    # a hypothetical.
    monkeypatch.setattr("cibuildmp.dockerrun.ensure_image", lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd),
    )

    with pytest.raises(UsermodBuildError, match="no Docker image registered"):
        build_unix(opts(arch, build_dir=tmp_path / f"build-{arch}"), tmp_path / "mpy")

    assert calls == []


@pytest.mark.parametrize("arch", ["manylinux_2_39_mipsel"])
def test_mipsel_runs_deplibs_before_build(monkeypatch, tmp_path, arch):
    _mock_unix_image(monkeypatch)
    run_calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: run_calls.append(cmd),
    )
    build_dir = tmp_path / f"build-{arch}"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(fake_elf(arch))

    build_unix(opts(arch, build_dir=build_dir), tmp_path / "mpy")

    assert run_calls[0][-1] == "deplibs"
    assert any("USER_C_MODULES" in arg for arg in run_calls[1])


@pytest.mark.parametrize("arch", ["manylinux_2_39_mipsel"])
def test_mipsel_builds_and_returns_binary_path(monkeypatch, tmp_path, arch):
    _mock_unix_image(monkeypatch)
    build_dir = tmp_path / f"build-{arch}"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(fake_elf(arch))
    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", lambda *a, **k: None)

    result = build_unix(opts(arch, build_dir=build_dir), tmp_path / "mpy")

    assert result == build_dir / "micropython"


def test_x86_64_builds_and_returns_binary_path(tmp_path, monkeypatch):
    _mock_unix_image(monkeypatch)
    build_dir = tmp_path / "build-x86_64"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(fake_elf())

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", lambda *a, **k: None)
    result = build_unix(opts(build_dir=build_dir), tmp_path / "mpy")

    assert result == build_dir / "micropython"


def test_missing_binary_after_success_is_an_error(tmp_path, monkeypatch):
    _mock_unix_image(monkeypatch)
    build_dir = tmp_path / "build-x86_64"
    build_dir.mkdir()

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", lambda *a, **k: None)
    with pytest.raises(UsermodBuildError, match="build reported success but"):
        build_unix(opts(build_dir=build_dir), tmp_path / "mpy")


def test_build_failure_names_the_command(tmp_path, monkeypatch):
    import subprocess as sp

    _mock_unix_image(monkeypatch)

    def fake_run(cmd, **kwargs):
        raise sp.CalledProcessError(1, cmd)

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", fake_run)
    with pytest.raises(UsermodBuildError, match="failed with exit code"):
        build_unix(opts(build_dir=tmp_path / "build-x86_64"), tmp_path / "mpy")


def test_aarch64_no_longer_cross_compiles():
    # It did until record 0043 (`CROSS_COMPILE=aarch64-linux-gnu-`, an apt
    # cross toolchain in an amd64 image, plus a ports.ubuntu.com mirror
    # rewrite). That whole setup encoded "the host is x86_64" as a
    # constant, which is false on an arm64 runner -- so the image is
    # native now and the prefix is empty.
    command = unix_make_command(opts("manylinux_2_28_aarch64"), Path("/gh/ws/mpy"))

    assert "CROSS_COMPILE=" in command
    assert "CROSS_COMPILE=aarch64-linux-gnu-" not in command
    assert "MICROPY_STANDALONE=1" not in command


def test_aarch64_builds_and_returns_binary_path(monkeypatch, tmp_path):
    _mock_unix_image(monkeypatch)
    build_dir = tmp_path / "build-manylinux_2_28_aarch64"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(fake_elf("manylinux_2_28_aarch64"))

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", lambda *a, **k: None)

    result = build_unix(
        opts("manylinux_2_28_aarch64", build_dir=build_dir), tmp_path / "mpy"
    )

    assert result == build_dir / "micropython"


# ── qemu ───────────────────────────────────────────────────────────────────


def qemu_opts(**overrides) -> QemuBuildOptions:
    defaults = {
        "user_c_modules": "/gh/ws/micropython/usermod",
        "frozen_manifest": "/gh/ws/a7p_manifest.py",
        "build_dir": Path("/gh/ws/usermod/build/armv7m"),
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

    build_qemu(qemu_opts(build_dir=build_dir), tmp_path / "mpy")

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

    result = build_qemu(qemu_opts(build_dir=build_dir), tmp_path / "mpy")

    assert result == build_dir / "firmware.elf"


def test_qemu_missing_firmware_after_success_is_an_error(monkeypatch, tmp_path):
    build_dir = tmp_path / "build-armv7m"
    build_dir.mkdir()

    monkeypatch.setattr(dockerrun, "ensure_image", lambda *a, **k: "qemu:test")
    monkeypatch.setattr(dockerrun, "run", lambda *a, **k: None)

    with pytest.raises(UsermodBuildError, match="build reported success but"):
        build_qemu(qemu_opts(build_dir=build_dir), tmp_path / "mpy")


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
        build_qemu(qemu_opts(build_dir=tmp_path / "build-armv7m"), tmp_path / "mpy")


def test_qemu_unsupported_board_rejected(tmp_path):
    with pytest.raises(UsermodBuildError, match="not supported yet"):
        build_qemu(qemu_opts(board="MIMXRT1050_EVK"), tmp_path / "mpy")


@pytest.mark.parametrize(
    ("board", "expected_cross"),
    [
        ("MPS2_AN385", "arm-none-eabi-"),
        ("VIRT_RV32", "riscv64-unknown-elf-"),
        ("VIRT_RV64", "riscv64-unknown-elf-"),
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

    build_qemu(qemu_opts(board=board, build_dir=build_dir), tmp_path / "mpy")

    assert f"CROSS_COMPILE={expected_cross}" in commands[0]


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


# ── webassembly ──────────────────────────────────────────────────────────


def wasm_opts(**overrides) -> WebassemblyBuildOptions:
    defaults = {
        "user_c_modules": "/gh/ws/micropython/usermod",
        "frozen_manifest": "/gh/ws/a7p_manifest.py",
        "build_dir": Path("/gh/ws/usermod/build/wasm"),
    }
    defaults.update(overrides)
    return WebassemblyBuildOptions(**defaults)


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
    monkeypatch.setattr("cibuildmp.dockerrun._pins", lambda: {"image": {}, "port": {}})
    build_dir = tmp_path / "build-wasm"

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    with pytest.raises(UsermodBuildError, match="no Docker image registered"):
        build_webassembly(wasm_opts(build_dir=build_dir), tmp_path / "mpy")

    assert calls == []


def test_webassembly_docker_image_override_skips_own_dockerfile_build(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CIBMP_WEBASSEMBLY_DOCKER_IMAGE", "cibuildmp-webassembly:local")
    # See `_mock_windows_image` for why the in-container mpy-cross build
    # is stubbed out here too (record 0044).
    monkeypatch.setattr(
        "cibuildmp.usermod.build.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )
    build_dir = tmp_path / "build-wasm"
    build_dir.mkdir()
    (build_dir / "micropython.mjs").write_bytes(b"")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    build_webassembly(wasm_opts(build_dir=build_dir), tmp_path / "mpy")

    assert len(calls) == 1
    docker_command = calls[0]
    assert docker_command[:3] == ["docker", "run", "--rm"]
    assert "cibuildmp-webassembly:local" in docker_command
    assert "make" in docker_command


def test_webassembly_docker_image_mounts_mpy_dir_and_user_c_modules(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CIBMP_WEBASSEMBLY_DOCKER_IMAGE", "cibuildmp-webassembly:local")
    # See `_mock_windows_image` for why the in-container mpy-cross build
    # is stubbed out here too (record 0044).
    monkeypatch.setattr(
        "cibuildmp.usermod.build.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )
    build_dir = tmp_path / "build-wasm"
    build_dir.mkdir()
    (build_dir / "micropython.mjs").write_bytes(b"")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    mpy_dir = tmp_path / "mpy"
    build_webassembly(wasm_opts(build_dir=build_dir), mpy_dir)

    docker_command = calls[0]
    assert f"{mpy_dir}:{mpy_dir}" in docker_command
    assert "/gh/ws/micropython/usermod:/gh/ws/micropython/usermod" in docker_command


def test_webassembly_missing_mjs_after_success_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setenv("CIBMP_WEBASSEMBLY_DOCKER_IMAGE", "cibuildmp-webassembly:local")
    # See `_mock_windows_image` for why the in-container mpy-cross build
    # is stubbed out here too (record 0044).
    monkeypatch.setattr(
        "cibuildmp.usermod.build.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )
    build_dir = tmp_path / "build-wasm"
    build_dir.mkdir()

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", lambda *a, **k: None)

    with pytest.raises(UsermodBuildError, match="build reported success but"):
        build_webassembly(wasm_opts(build_dir=build_dir), tmp_path / "mpy")


def test_webassembly_build_failure_names_the_command(monkeypatch, tmp_path):
    import subprocess as sp

    monkeypatch.setenv("CIBMP_WEBASSEMBLY_DOCKER_IMAGE", "cibuildmp-webassembly:local")
    # See `_mock_windows_image` for why the in-container mpy-cross build
    # is stubbed out here too (record 0044).
    monkeypatch.setattr(
        "cibuildmp.usermod.build.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )

    def fake_run(cmd, **kwargs):
        raise sp.CalledProcessError(1, cmd)

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", fake_run)

    with pytest.raises(UsermodBuildError, match="failed with exit code"):
        build_webassembly(
            wasm_opts(build_dir=tmp_path / "build-wasm"), tmp_path / "mpy"
        )


def test_webassembly_no_docker_daemon_raises_clear_error(monkeypatch, tmp_path):
    # Docker-only means "docker unavailable" is a hard, clearly-worded
    # error, not a silent bare-host fallback -- the user's own call.
    monkeypatch.setenv("CIBMP_WEBASSEMBLY_DOCKER_IMAGE", "cibuildmp-webassembly:local")
    # See `_mock_windows_image` for why the in-container mpy-cross build
    # is stubbed out here too (record 0044).
    monkeypatch.setattr(
        "cibuildmp.usermod.build.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", fake_run)

    with pytest.raises(UsermodBuildError, match="docker CLI itself is not on PATH"):
        build_webassembly(
            wasm_opts(build_dir=tmp_path / "build-wasm"), tmp_path / "mpy"
        )


# ── esp32 ────────────────────────────────────────────────────────────────


def esp32_opts(**overrides) -> Esp32BuildOptions:
    defaults = {
        "user_c_modules": "/gh/ws/micropython/usermod/micropython.cmake",
        "frozen_manifest": "/gh/ws/a7p_manifest.py",
    }
    defaults.update(overrides)
    return Esp32BuildOptions(**defaults)


def fake_idf(tmp_path) -> ResolvedEspIdf:
    return ResolvedEspIdf(idf_dir=tmp_path / "idf", tools_dir=tmp_path / "tools")


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


def test_esp32_resolves_esp_idf_before_building(monkeypatch, tmp_path):
    calls = []

    def fake_resolve(version, idf_target, **kwargs):
        calls.append((version, idf_target))
        return fake_idf(tmp_path)

    monkeypatch.setattr(build.espidf, "resolve_esp_idf", fake_resolve)
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(ResolvedEspIdf, "env", lambda self, base=None: {})

    build_dir = tmp_path / "mpy" / "ports" / "esp32" / "build-ESP32_GENERIC"
    build_dir.mkdir(parents=True)
    (build_dir / "micropython.bin").write_bytes(b"")

    build_esp32(esp32_opts(), tmp_path / "mpy")

    assert calls == [("v5.5.1", "esp32")]


def test_esp32_builds_and_returns_bin_path(monkeypatch, tmp_path):
    build_dir = tmp_path / "mpy" / "ports" / "esp32" / "build-ESP32_GENERIC"
    build_dir.mkdir(parents=True)
    (build_dir / "micropython.bin").write_bytes(b"")

    monkeypatch.setattr(
        build.espidf, "resolve_esp_idf", lambda *a, **k: fake_idf(tmp_path)
    )
    monkeypatch.setattr(ResolvedEspIdf, "env", lambda self, base=None: {})
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: None)

    result = build_esp32(esp32_opts(), tmp_path / "mpy")

    assert result == build_dir / "micropython.bin"


def test_esp32_missing_bin_after_success_is_an_error(monkeypatch, tmp_path):
    (tmp_path / "mpy" / "ports" / "esp32").mkdir(parents=True)

    monkeypatch.setattr(
        build.espidf, "resolve_esp_idf", lambda *a, **k: fake_idf(tmp_path)
    )
    monkeypatch.setattr(ResolvedEspIdf, "env", lambda self, base=None: {})
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: None)

    with pytest.raises(UsermodBuildError, match="build reported success but"):
        build_esp32(esp32_opts(), tmp_path / "mpy")


def test_esp32_build_failure_names_the_command(monkeypatch, tmp_path):
    import subprocess as sp

    def fake_run(cmd, **kwargs):
        raise sp.CalledProcessError(1, cmd)

    monkeypatch.setattr(
        build.espidf, "resolve_esp_idf", lambda *a, **k: fake_idf(tmp_path)
    )
    monkeypatch.setattr(ResolvedEspIdf, "env", lambda self, base=None: {})
    monkeypatch.setattr(build.subprocess, "run", fake_run)

    with pytest.raises(UsermodBuildError, match="failed with exit code"):
        build_esp32(esp32_opts(), tmp_path / "mpy")


def test_esp32_custom_board_and_target():
    command = esp32_make_command(
        esp32_opts(board="ESP32S3_GENERIC"), Path("/gh/ws/mpy")
    )

    assert "BOARD=ESP32S3_GENERIC" in command


# ── windows ──────────────────────────────────────────────────────────────


def windows_opts(**overrides) -> WindowsBuildOptions:
    defaults = {
        "arch": "x64",
        "user_c_modules": "/gh/ws/micropython/usermod",
        "frozen_manifest": "/gh/ws/a7p_manifest.py",
        "build_dir": Path("/gh/ws/usermod/build/windows-x64"),
    }
    defaults.update(overrides)
    return WindowsBuildOptions(**defaults)


def test_windows_x64_command_matches_upstream_cross_build_shape():
    # tools/ci.sh's own ci_windows_build: CROSS_COMPILE=x86_64-w64-mingw32-,
    # no MSYS2-specific overrides (STRIP/SIZE/COMPILER_TARGET) -- a plain
    # GNU mingw-w64 cross-gcc needs none of them.
    command = windows_make_command(windows_opts(arch="x64"), Path("/gh/ws/mpy"))

    assert command == [
        "make",
        "-C",
        "/gh/ws/mpy/ports/windows",
        "VARIANT=standard",
        "BUILD=/gh/ws/usermod/build/windows-x64",
        "CROSS_COMPILE=x86_64-w64-mingw32-",
        "USER_C_MODULES=/gh/ws/micropython/usermod",
        "FROZEN_MANIFEST=/gh/ws/a7p_manifest.py",
    ]


def test_windows_x86_command_uses_i686_prefix():
    command = windows_make_command(windows_opts(arch="x86"), Path("/gh/ws/mpy"))

    assert "CROSS_COMPILE=i686-w64-mingw32-" in command


def test_windows_unknown_arch_rejected(tmp_path):
    with pytest.raises(UsermodBuildError, match="unknown windows arch"):
        build_windows(windows_opts(arch="riscv64"), tmp_path / "mpy")


# ── windows/arm64 (llvm-mingw) ───────────────────────────────────────────


def test_windows_arm64_command_matches_verified_shape():
    # Verified live: COMPILER_TARGET=/STRIP=/SIZE= and the three
    # CFLAGS_EXTRA suppressions are load-bearing (see
    # WINDOWS_ARCH_SETTINGS' own comments for exactly why), not
    # cosmetic.
    command = windows_make_command(
        windows_opts(
            arch="arm64", build_dir=Path("/gh/ws/usermod/build/windows-arm64")
        ),
        Path("/gh/ws/mpy"),
    )

    assert command == [
        "make",
        "-C",
        "/gh/ws/mpy/ports/windows",
        "VARIANT=standard",
        "BUILD=/gh/ws/usermod/build/windows-arm64",
        "CROSS_COMPILE=aarch64-w64-mingw32-",
        "COMPILER_TARGET=mingw-forced",
        "STRIP=",
        "SIZE=true",
        (
            "CFLAGS_EXTRA=-Wno-double-promotion -Wno-uninitialized "
            "-Wno-default-const-init-var-unsafe"
        ),
        "USER_C_MODULES=/gh/ws/micropython/usermod",
        "FROZEN_MANIFEST=/gh/ws/a7p_manifest.py",
    ]


_FAKE_WINDOWS_IMAGE = "cibuildmp-windows:local"


def _mock_windows_image(monkeypatch, image=_FAKE_WINDOWS_IMAGE):
    """Docker-only (D30/D32), same helper shape `_mock_unix_image` has
    and for the same reason: build_windows() has no bare-host path left
    at all, so every real build path needs ensure_image() to resolve
    something first. Tests that only care about the make command shape
    fake a resolved image here and mock dockerrun's own subprocess.run
    -- build.subprocess is no longer called by this port under any
    circumstance.

    Also stubs the in-container mpy-cross build (record 0044): this
    port's image is amd64, so on an arm64 host a host-built mpy-cross
    could not run inside it, and `py/mkrules.mk` runs mpy-cross in the
    container to compile FROZEN_MANIFEST. It is a second real container
    and has its own live coverage; these cases are about the make
    command's own shape."""
    monkeypatch.setattr("cibuildmp.dockerrun.ensure_image", lambda *a, **k: image)
    monkeypatch.setattr(
        "cibuildmp.usermod.build.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )


@pytest.mark.parametrize("arch", ["x64", "x86", "arm64"])
def test_windows_no_image_registered_is_a_clear_error(monkeypatch, tmp_path, arch):
    # D32's own closing gap: `windows` used to have pinned entries
    # nothing ever read. All three arches now resolve through
    # ensure_image(), so with no override and nothing registered they
    # must fail loudly rather than quietly cross-compiling on the host.
    monkeypatch.setattr("cibuildmp.dockerrun.ensure_image", lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd),
    )

    with pytest.raises(UsermodBuildError, match="no Docker image registered"):
        build_windows(
            windows_opts(arch=arch, build_dir=tmp_path / f"build-{arch}"),
            tmp_path / "mpy",
        )

    assert calls == []


@pytest.mark.parametrize("arch", ["x64", "x86", "arm64"])
def test_windows_runs_make_inside_the_container(monkeypatch, tmp_path, arch):
    # Every arch, arm64 included: the llvm-mingw toolchain arm64 needs is
    # baked into docker/windows.Dockerfile now, so there is no host-side
    # resolve step and nothing to inject into the environment -- the
    # image's own ENV PATH covers it.
    _mock_windows_image(monkeypatch)
    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd),
    )

    build_dir = tmp_path / f"build-{arch}"
    build_dir.mkdir()
    # This arch's own machine value, not a fixed one: build_windows()
    # verifies the COFF header now, so a stub that is right for x64 and
    # wrong for the other two would fail two thirds of this parametrize.
    (build_dir / "micropython.exe").write_bytes(
        _pe(WINDOWS_ARCH_SETTINGS[arch].machine)
    )

    result = build_windows(
        windows_opts(arch=arch, build_dir=build_dir), tmp_path / "mpy"
    )

    assert result == build_dir / "micropython.exe"
    assert len(calls) == 1
    docker_command = calls[0]
    assert docker_command[0] == "docker"
    assert _FAKE_WINDOWS_IMAGE in docker_command
    # The make command is passed through unchanged, at the same absolute
    # paths -- dockerrun mounts them identically inside (D26).
    assert "make" in docker_command
    assert f"CROSS_COMPILE={WINDOWS_ARCH_SETTINGS[arch].cross_compile}" in (
        docker_command
    )


def test_windows_mounts_mpy_dir_and_user_c_modules(monkeypatch, tmp_path):
    _mock_windows_image(monkeypatch)
    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd),
    )

    build_dir = tmp_path / "build-x86_64"
    build_dir.mkdir()
    (build_dir / "micropython.exe").write_bytes(_pe(0x8664))

    opts_ = windows_opts(arch="x64", build_dir=build_dir)
    build_windows(opts_, tmp_path / "mpy")

    mounts = [calls[0][i + 1] for i, part in enumerate(calls[0]) if part == "-v"]
    mpy = (tmp_path / "mpy").as_posix()
    assert f"{mpy}:{mpy}" in mounts
    assert any(opts_.user_c_modules in m for m in mounts)


def test_windows_missing_exe_after_success_is_an_error(monkeypatch, tmp_path):
    _mock_windows_image(monkeypatch)
    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", lambda *a, **k: None)
    build_dir = tmp_path / "build-arm64"
    build_dir.mkdir()

    with pytest.raises(UsermodBuildError, match="build reported success but"):
        build_windows(windows_opts(arch="arm64", build_dir=build_dir), tmp_path / "mpy")


def test_windows_build_failure_names_the_command(monkeypatch, tmp_path):
    import subprocess as sp

    _mock_windows_image(monkeypatch)

    def fake_run(cmd, **kwargs):
        raise sp.CalledProcessError(1, cmd)

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", fake_run)

    with pytest.raises(UsermodBuildError, match="failed with exit code"):
        build_windows(
            windows_opts(arch="arm64", build_dir=tmp_path / "build-arm64"),
            tmp_path / "mpy",
        )


# ── unix / docker strategy (D26 proof-of-concept) ───────────────────────────


def test_unix_docker_image_skips_host_toolchain_probe(monkeypatch, tmp_path):
    # CIBMP_UNIX_MANYLINUX_2_28_AARCH64_DOCKER_IMAGE set: the toolchain lives
    # inside the image, not on this host's PATH, so build_unix() must not
    # call shutil.which() at all -- a bare-host probe would reject a
    # perfectly good docker build.
    monkeypatch.setenv(
        "CIBMP_UNIX_MANYLINUX_2_28_AARCH64_DOCKER_IMAGE",
        "manylinux_2_28_aarch64:local",
    )
    # `build` no longer imports shutil at all -- with no bare-host path
    # left for any port there is nothing to probe PATH with, which is a
    # stronger guarantee than mocking shutil.which to fail was.
    assert not hasattr(build, "shutil")
    # This case resolves its image through the real env-var path rather
    # than `_mock_unix_image`, so it has to silence the emulation probe
    # itself -- aarch64 is non-native on an x86_64 host, and the probe
    # would otherwise start a real container.
    monkeypatch.setattr("cibuildmp.dockerrun._probe_platform", lambda *a, **k: "")
    monkeypatch.setattr(
        "cibuildmp.usermod.build.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )
    build_dir = tmp_path / "build-manylinux_2_28_aarch64"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(fake_elf("manylinux_2_28_aarch64"))

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    result = build_unix(
        opts("manylinux_2_28_aarch64", build_dir=build_dir), tmp_path / "mpy"
    )

    assert result == build_dir / "micropython"
    assert len(calls) == 1
    docker_command = calls[0]
    assert docker_command[:3] == ["docker", "run", "--rm"]
    assert "manylinux_2_28_aarch64:local" in docker_command
    assert "make" in docker_command


def test_unix_docker_image_mounts_mpy_dir_and_user_c_modules(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "CIBMP_UNIX_MANYLINUX_2_28_X86_64_DOCKER_IMAGE", "manylinux_2_28_x86_64:local"
    )
    monkeypatch.setattr(
        "cibuildmp.usermod.build.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )
    build_dir = tmp_path / "build-x86_64"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(fake_elf())

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    mpy_dir = tmp_path / "mpy"
    build_unix(opts(build_dir=build_dir), mpy_dir)

    docker_command = calls[0]
    assert f"{mpy_dir}:{mpy_dir}" in docker_command
    assert "/gh/ws/micropython/usermod:/gh/ws/micropython/usermod" in docker_command


# test_unix_no_image_registered_is_a_clear_error (above) already covers
# "no CIBMP_UNIX_<TARGET>_DOCKER_IMAGE, no pinned digest" for every
# target -- unix has no bare-host fallback left to fall back to (D30).


# ── unix_extra_cflags() -- three axes, and which one each rule is on ────


def test_the_musl_rule_covers_the_whole_musllinux_column():
    # `-Wno-error=cpp` is a property of the libc: musl's own
    # `sys/cdefs.h` is a bare `#warning`, reached through berkeley-db's
    # `db.h` from extmod/modbtree.c. glibc has no such header warning, so
    # no manylinux cell may carry it.
    for target in dockerrun.unix_targets():
        floor, _arch = dockerrun.split_tag(target)
        flags = build.unix_extra_cflags(target)
        assert ("-Wno-error=cpp" in flags) == floor.startswith("musllinux"), target


def test_the_array_bounds_rule_is_per_architecture_not_per_cell():
    # Both aarch64 cells trip gcc 14's `-Werror=array-bounds=` false
    # positive in mbedtls's own `mbedtls_xor`, from two different bases
    # and two different libcs -- AlmaLinux 8/glibc and Alpine/musl. It
    # started as a per-tag entry for `manylinux_2_28_aarch64` alone, on
    # the reasoning that bounds analysis differs by target; the second
    # aarch64 cell ever built (run 32960761641) showed the axis was the
    # architecture. Every non-aarch64 cell built so far is clean.
    for target in dockerrun.unix_targets():
        _floor, arch = dockerrun.split_tag(target)
        flags = build.unix_extra_cflags(target)
        assert ("-Wno-error=array-bounds" in flags) == (arch == "aarch64"), target


def test_musl_aarch64_carries_both_rules_at_once():
    # The cell that proved the two axes are independent: it needs the
    # libc rule *and* the architecture rule, and neither table knows
    # about the other.
    assert build.unix_extra_cflags("musllinux_1_2_aarch64") == (
        "-Wno-error=cpp",
        "-Wno-error=array-bounds",
    )


def test_a_cell_needing_nothing_gets_nothing():
    assert build.unix_extra_cflags("manylinux_2_28_x86_64") == ()


# ── verify_windows_output() -- the check windows did not have ───────────


@pytest.mark.parametrize(
    ("arch", "machine"), [("x64", 0x8664), ("x86", 0x014C), ("arm64", 0xAA64)]
)
def test_each_windows_arch_accepts_its_own_machine(arch, machine, tmp_path):
    binary = tmp_path / "micropython.exe"
    binary.write_bytes(_pe(machine))

    build.verify_windows_output(arch, binary)


def test_another_arch_machine_is_rejected(tmp_path):
    # The whole point: `make` and `ld` both succeed when CROSS_COMPILE
    # names another architecture's toolchain, so the failure this catches
    # does not look like a failure anywhere else.
    binary = tmp_path / "micropython.exe"
    binary.write_bytes(_pe(0x8664))

    with pytest.raises(UsermodBuildError, match="0x8664, expected 0xaa64"):
        build.verify_windows_output("arm64", binary)


def test_an_elf_named_exe_is_rejected(tmp_path):
    # A `CROSS_COMPILE=` that resolved to the host's own gcc produces
    # exactly this, and `binary.exists()` -- the only check windows had
    # before -- passes it.
    binary = tmp_path / "micropython.exe"
    binary.write_bytes(b"\x7fELF" + bytes(0x100))

    with pytest.raises(UsermodBuildError, match="not a PE executable at all"):
        build.verify_windows_output("x64", binary)


def test_a_dos_header_pointing_nowhere_is_rejected(tmp_path):
    binary = tmp_path / "micropython.exe"
    data = bytearray(_pe(0x8664))
    data[0x3C:0x40] = (0x7000).to_bytes(4, "little")
    binary.write_bytes(bytes(data))

    with pytest.raises(UsermodBuildError, match="no PE signature"):
        build.verify_windows_output("x64", binary)


def test_every_windows_arch_declares_a_machine():
    # A settings entry added without one would default to 0 and reject
    # every real binary, which is a worse failure than no check at all.
    for arch, settings in WINDOWS_ARCH_SETTINGS.items():
        assert settings.machine, arch

from pathlib import Path

import pytest

from cibuildmp.toolchains import ResolvedToolchain
from cibuildmp.usermod import build
from cibuildmp.usermod.build import (
    UNIX_ARCH_SETTINGS,
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
from cibuildmp.usermod.llvmmingw import ResolvedLlvmMingw


def opts(arch: str = "x64", **overrides) -> UnixBuildOptions:
    defaults = {
        "arch": arch,
        "user_c_modules": "/gh/ws/micropython/usermod",
        "frozen_manifest": "/gh/ws/a7p_manifest.py",
        "build_dir": Path("/gh/ws/usermod/build/x64"),
    }
    defaults.update(overrides)
    return UnixBuildOptions(**defaults)


def test_x64_command_matches_a7p_workflow_shape():
    # build-usermod-unix's own "Build usermod (x64)" step, x64 has no
    # CROSS_COMPILE and no link_opts.
    command = unix_make_command(opts("x64"), Path("/gh/ws/mpy"))

    assert command == [
        "make",
        "-C",
        "/gh/ws/mpy/ports/unix",
        "VARIANT=standard",
        "BUILD=/gh/ws/usermod/build/x64",
        "CROSS_COMPILE=",
        "USER_C_MODULES=/gh/ws/micropython/usermod",
        "FROZEN_MANIFEST=/gh/ws/a7p_manifest.py",
    ]


def test_x86_command_adds_force_32bit():
    command = unix_make_command(opts("x86"), Path("/gh/ws/mpy"))

    assert "MICROPY_FORCE_32BIT=1" in command


def test_armhf_command_adds_standalone_and_static_link():
    command = unix_make_command(opts("armhf"), Path("/gh/ws/mpy"))

    assert "CROSS_COMPILE=arm-linux-gnueabihf-" in command
    assert "MICROPY_STANDALONE=1" in command
    assert "LDFLAGS_EXTRA=-static" in command


_FAKE_UNIX_IMAGE = "cibuildmp-unix-manylinux:local"


def _mock_unix_image(monkeypatch, image=_FAKE_UNIX_IMAGE):
    """Docker-only (D30): every real build_unix() path needs
    ensure_image() to resolve something before it will run anything at
    all. Tests that only care about the make/deplibs command shape (not
    about image resolution itself) fake a resolved image this way and
    mock dockerrun's own subprocess.run -- not build.subprocess, which
    build_unix() no longer calls under any circumstance now that there
    is no bare-host path left."""
    monkeypatch.setattr(
        "cibuildmp.usermod.dockerrun.ensure_image", lambda *a, **k: image
    )


def test_deplibs_command_shape(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "cibuildmp.usermod.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd),
    )
    run_unix_deplibs(opts("armhf"), Path("/gh/ws/mpy"), docker_image=_FAKE_UNIX_IMAGE)

    assert calls[0][-1] == "deplibs"
    assert "MICROPY_STANDALONE=1" in calls[0]


def test_all_five_archs_have_settings():
    assert set(UNIX_ARCH_SETTINGS) == {"x64", "x86", "aarch64", "armhf", "mipsel"}


def test_unknown_arch_rejected():
    with pytest.raises(UsermodBuildError, match="unknown unix arch"):
        build_unix(opts("riscv64"), Path("/gh/ws/mpy"))


@pytest.mark.parametrize("arch", ["x64", "x86", "aarch64", "armhf", "mipsel"])
def test_unix_no_image_registered_is_a_clear_error(monkeypatch, tmp_path, arch):
    # Docker-only (D30): no bare-host fallback for any unix arch any
    # more -- with no override and nothing in PORT_IMAGES, build_unix()
    # must fail loudly, the same shape build_webassembly() already has.
    monkeypatch.setattr(
        "cibuildmp.usermod.dockerrun.ensure_image", lambda *a, **k: None
    )
    calls = []
    monkeypatch.setattr(
        "cibuildmp.usermod.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd),
    )

    with pytest.raises(UsermodBuildError, match="no Docker image registered"):
        build_unix(opts(arch, build_dir=tmp_path / f"build-{arch}"), tmp_path / "mpy")

    assert calls == []


@pytest.mark.parametrize("arch", ["armhf", "mipsel"])
def test_armhf_mipsel_runs_deplibs_before_build(monkeypatch, tmp_path, arch):
    _mock_unix_image(monkeypatch)
    run_calls = []
    monkeypatch.setattr(
        "cibuildmp.usermod.dockerrun.subprocess.run",
        lambda cmd, **k: run_calls.append(cmd),
    )
    build_dir = tmp_path / f"build-{arch}"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(b"\x7fELF")

    build_unix(opts(arch, build_dir=build_dir), tmp_path / "mpy")

    assert run_calls[0][-1] == "deplibs"
    assert any("USER_C_MODULES" in arg for arg in run_calls[1])


@pytest.mark.parametrize("arch", ["armhf", "mipsel"])
def test_armhf_mipsel_builds_and_returns_binary_path(monkeypatch, tmp_path, arch):
    _mock_unix_image(monkeypatch)
    build_dir = tmp_path / f"build-{arch}"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(b"\x7fELF")
    monkeypatch.setattr(
        "cibuildmp.usermod.dockerrun.subprocess.run", lambda *a, **k: None
    )

    result = build_unix(opts(arch, build_dir=build_dir), tmp_path / "mpy")

    assert result == build_dir / "micropython"


def test_x64_builds_and_returns_binary_path(tmp_path, monkeypatch):
    _mock_unix_image(monkeypatch)
    build_dir = tmp_path / "build-x64"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(b"\x7fELF")

    monkeypatch.setattr(
        "cibuildmp.usermod.dockerrun.subprocess.run", lambda *a, **k: None
    )
    result = build_unix(opts("x64", build_dir=build_dir), tmp_path / "mpy")

    assert result == build_dir / "micropython"


def test_missing_binary_after_success_is_an_error(tmp_path, monkeypatch):
    _mock_unix_image(monkeypatch)
    build_dir = tmp_path / "build-x64"
    build_dir.mkdir()

    monkeypatch.setattr(
        "cibuildmp.usermod.dockerrun.subprocess.run", lambda *a, **k: None
    )
    with pytest.raises(UsermodBuildError, match="build reported success but"):
        build_unix(opts("x64", build_dir=build_dir), tmp_path / "mpy")


def test_build_failure_names_the_command(tmp_path, monkeypatch):
    import subprocess as sp

    _mock_unix_image(monkeypatch)

    def fake_run(cmd, **kwargs):
        raise sp.CalledProcessError(1, cmd)

    monkeypatch.setattr("cibuildmp.usermod.dockerrun.subprocess.run", fake_run)
    with pytest.raises(UsermodBuildError, match="failed with exit code"):
        build_unix(opts("x64", build_dir=tmp_path / "build-x64"), tmp_path / "mpy")


def test_aarch64_command_cross_compiles_not_host_gcc():
    # Verified live on a real ubuntu-latest runner: aarch64-linux-gnu-gcc
    # (apt) cross-compiles from x86_64 straight to a linked ARM aarch64
    # ELF -- no MICROPY_STANDALONE/deplibs step needed the way armhf/mipsel
    # require.
    command = unix_make_command(opts("aarch64"), Path("/gh/ws/mpy"))

    assert "CROSS_COMPILE=aarch64-linux-gnu-" in command
    assert "MICROPY_STANDALONE=1" not in command


def test_aarch64_builds_and_returns_binary_path(monkeypatch, tmp_path):
    _mock_unix_image(monkeypatch)
    build_dir = tmp_path / "build-aarch64"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(b"\x7fELF")

    monkeypatch.setattr(
        "cibuildmp.usermod.dockerrun.subprocess.run", lambda *a, **k: None
    )

    result = build_unix(opts("aarch64", build_dir=build_dir), tmp_path / "mpy")

    assert result == build_dir / "micropython"


# ── qemu ───────────────────────────────────────────────────────────────────

HOST_CHAIN = ResolvedToolchain("host", "arm-none-eabi-", "arm-none-eabi-", None)


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
    command = qemu_make_command(qemu_opts(), Path("/gh/ws/mpy"), HOST_CHAIN)

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


def test_qemu_probes_armv7m_toolchain_not_a_new_one(monkeypatch, tmp_path):
    """qemu must reuse toolchains.resolve("armv7m") -- natmod's own
    arm-none-eabi- pin -- not a second toolchain resolution path."""
    calls = []
    monkeypatch.setattr(
        build.toolchains,
        "resolve",
        lambda arch, **k: calls.append(arch) or HOST_CHAIN,
    )
    build_dir = tmp_path / "build-armv7m"
    build_dir.mkdir()
    (build_dir / "firmware.elf").write_bytes(b"\x7fELF")
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: None)

    build_qemu(qemu_opts(build_dir=build_dir), tmp_path / "mpy")

    assert calls == ["armv7m"]


def test_qemu_builds_and_returns_firmware_path(monkeypatch, tmp_path):
    build_dir = tmp_path / "build-armv7m"
    build_dir.mkdir()
    (build_dir / "firmware.elf").write_bytes(b"\x7fELF")

    monkeypatch.setattr(build.toolchains, "resolve", lambda arch, **k: HOST_CHAIN)
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: None)

    result = build_qemu(qemu_opts(build_dir=build_dir), tmp_path / "mpy")

    assert result == build_dir / "firmware.elf"


def test_qemu_missing_firmware_after_success_is_an_error(monkeypatch, tmp_path):
    build_dir = tmp_path / "build-armv7m"
    build_dir.mkdir()

    monkeypatch.setattr(build.toolchains, "resolve", lambda arch, **k: HOST_CHAIN)
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: None)

    with pytest.raises(UsermodBuildError, match="build reported success but"):
        build_qemu(qemu_opts(build_dir=build_dir), tmp_path / "mpy")


def test_qemu_build_failure_names_the_command(monkeypatch, tmp_path):
    import subprocess as sp

    def fake_run(cmd, **kwargs):
        raise sp.CalledProcessError(1, cmd)

    monkeypatch.setattr(build.toolchains, "resolve", lambda arch, **k: HOST_CHAIN)
    monkeypatch.setattr(build.subprocess, "run", fake_run)

    with pytest.raises(UsermodBuildError, match="failed with exit code"):
        build_qemu(qemu_opts(build_dir=tmp_path / "build-armv7m"), tmp_path / "mpy")


def test_qemu_unsupported_board_rejected(tmp_path):
    with pytest.raises(UsermodBuildError, match="not supported yet"):
        build_qemu(qemu_opts(board="MIMXRT1050_EVK"), tmp_path / "mpy")


@pytest.mark.parametrize(
    ("board", "expected_arch"),
    [("MPS2_AN385", "armv7m"), ("VIRT_RV32", "rv32imc"), ("VIRT_RV64", "rv64imc")],
)
def test_qemu_resolves_board_specific_toolchain(
    board, expected_arch, monkeypatch, tmp_path
):
    """Each board must probe its own arch's toolchain, not always
    armv7m's -- VIRT_RV32/VIRT_RV64 need rv32imc/rv64imc's
    riscv-none-elf, not arm-none-eabi-."""
    calls = []
    monkeypatch.setattr(
        build.toolchains,
        "resolve",
        lambda arch, **k: calls.append(arch) or HOST_CHAIN,
    )
    build_dir = tmp_path / f"build-{board}"
    build_dir.mkdir()
    (build_dir / "firmware.elf").write_bytes(b"\x7fELF")
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: None)

    build_qemu(qemu_opts(board=board, build_dir=build_dir), tmp_path / "mpy")

    assert calls == [expected_arch]


def test_qemu_riscv_command_uses_the_resolved_prefix(tmp_path):
    riscv_chain = ResolvedToolchain(
        "host", "riscv64-unknown-elf-", "riscv64-unknown-elf-", None
    )
    command = qemu_make_command(
        qemu_opts(board="VIRT_RV64"), Path("/gh/ws/mpy"), riscv_chain
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
    # digest-pinned image) -- with no override and nothing in
    # PORT_IMAGES, build_webassembly() must fail loudly, not fall back to
    # building docker/webassembly.Dockerfile on its own.
    monkeypatch.delenv("CIBMP_WEBASSEMBLY_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr("cibuildmp.usermod.dockerrun.PORT_IMAGES", {})
    build_dir = tmp_path / "build-wasm"

    calls = []
    monkeypatch.setattr(
        "cibuildmp.usermod.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    with pytest.raises(UsermodBuildError, match="no Docker image registered"):
        build_webassembly(wasm_opts(build_dir=build_dir), tmp_path / "mpy")

    assert calls == []


def test_webassembly_docker_image_override_skips_own_dockerfile_build(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CIBMP_WEBASSEMBLY_DOCKER_IMAGE", "cibuildmp-webassembly:local")
    build_dir = tmp_path / "build-wasm"
    build_dir.mkdir()
    (build_dir / "micropython.mjs").write_bytes(b"")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.usermod.dockerrun.subprocess.run",
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
    build_dir = tmp_path / "build-wasm"
    build_dir.mkdir()
    (build_dir / "micropython.mjs").write_bytes(b"")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.usermod.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    mpy_dir = tmp_path / "mpy"
    build_webassembly(wasm_opts(build_dir=build_dir), mpy_dir)

    docker_command = calls[0]
    assert f"{mpy_dir}:{mpy_dir}" in docker_command
    assert "/gh/ws/micropython/usermod:/gh/ws/micropython/usermod" in docker_command


def test_webassembly_missing_mjs_after_success_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setenv("CIBMP_WEBASSEMBLY_DOCKER_IMAGE", "cibuildmp-webassembly:local")
    build_dir = tmp_path / "build-wasm"
    build_dir.mkdir()

    monkeypatch.setattr(
        "cibuildmp.usermod.dockerrun.subprocess.run", lambda *a, **k: None
    )

    with pytest.raises(UsermodBuildError, match="build reported success but"):
        build_webassembly(wasm_opts(build_dir=build_dir), tmp_path / "mpy")


def test_webassembly_build_failure_names_the_command(monkeypatch, tmp_path):
    import subprocess as sp

    monkeypatch.setenv("CIBMP_WEBASSEMBLY_DOCKER_IMAGE", "cibuildmp-webassembly:local")

    def fake_run(cmd, **kwargs):
        raise sp.CalledProcessError(1, cmd)

    monkeypatch.setattr("cibuildmp.usermod.dockerrun.subprocess.run", fake_run)

    with pytest.raises(UsermodBuildError, match="failed with exit code"):
        build_webassembly(
            wasm_opts(build_dir=tmp_path / "build-wasm"), tmp_path / "mpy"
        )


def test_webassembly_no_docker_daemon_raises_clear_error(monkeypatch, tmp_path):
    # Docker-only means "docker unavailable" is a hard, clearly-worded
    # error, not a silent bare-host fallback -- the user's own call.
    monkeypatch.setenv("CIBMP_WEBASSEMBLY_DOCKER_IMAGE", "cibuildmp-webassembly:local")

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr("cibuildmp.usermod.dockerrun.subprocess.run", fake_run)

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


def test_windows_missing_toolchain_names_apt_package(monkeypatch, tmp_path):
    monkeypatch.setattr(build.shutil, "which", lambda name: None)

    with pytest.raises(UsermodBuildError, match="apt install gcc-mingw-w64-x86-64"):
        build_windows(windows_opts(), tmp_path / "mpy")


def test_windows_probes_toolchain_before_building(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        build.shutil, "which", lambda name: calls.append(name) or f"/usr/bin/{name}"
    )
    build_dir = tmp_path / "build-x64"
    build_dir.mkdir()
    (build_dir / "micropython.exe").write_bytes(b"MZ")
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: None)

    build_windows(windows_opts(build_dir=build_dir), tmp_path / "mpy")

    assert calls == ["x86_64-w64-mingw32-gcc"]


def test_windows_builds_and_returns_exe_path(monkeypatch, tmp_path):
    build_dir = tmp_path / "build-x64"
    build_dir.mkdir()
    (build_dir / "micropython.exe").write_bytes(b"MZ")

    monkeypatch.setattr(build.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: None)

    result = build_windows(windows_opts(build_dir=build_dir), tmp_path / "mpy")

    assert result == build_dir / "micropython.exe"


def test_windows_missing_exe_after_success_is_an_error(monkeypatch, tmp_path):
    build_dir = tmp_path / "build-x64"
    build_dir.mkdir()

    monkeypatch.setattr(build.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: None)

    with pytest.raises(UsermodBuildError, match="build reported success but"):
        build_windows(windows_opts(build_dir=build_dir), tmp_path / "mpy")


def test_windows_build_failure_names_the_command(monkeypatch, tmp_path):
    import subprocess as sp

    def fake_run(cmd, **kwargs):
        raise sp.CalledProcessError(1, cmd)

    monkeypatch.setattr(build.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(build.subprocess, "run", fake_run)

    with pytest.raises(UsermodBuildError, match="failed with exit code"):
        build_windows(windows_opts(build_dir=tmp_path / "build-x64"), tmp_path / "mpy")


# ── windows/arm64 (llvm-mingw) ───────────────────────────────────────────


def test_windows_arm64_command_matches_verified_shape():
    # Verified live: COMPILER_TARGET=/STRIP=/SIZE= and the three
    # CFLAGS_EXTRA suppressions are load-bearing (see
    # resources/usermod.toml's own [llvm-mingw] table for exactly why),
    # not cosmetic. No apt_package -- this arch has none.
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


def test_windows_arm64_resolves_llvm_mingw_not_apt(monkeypatch, tmp_path):
    resolve_calls = []

    def fake_resolve(**kwargs):
        resolve_calls.append(kwargs)
        return ResolvedLlvmMingw(install_dir=tmp_path / "llvm-mingw")

    monkeypatch.setattr(build.llvmmingw, "resolve_llvm_mingw", fake_resolve)
    monkeypatch.setattr(
        build.shutil,
        "which",
        lambda name: (_ for _ in ()).throw(
            AssertionError("arm64 must not probe PATH for a gcc")
        ),
    )

    run_calls = []
    monkeypatch.setattr(build.subprocess, "run", lambda cmd, **k: run_calls.append(k))

    build_dir = tmp_path / "build-arm64"
    build_dir.mkdir()
    (build_dir / "micropython.exe").write_bytes(b"MZ")

    build_windows(windows_opts(arch="arm64", build_dir=build_dir), tmp_path / "mpy")

    assert len(resolve_calls) == 1
    # The resolved toolchain's own PATH is what subprocess.run() gets --
    # not a bare host lookup.
    assert "PATH" in run_calls[0]["env"]


def test_windows_arm64_builds_and_returns_exe_path(monkeypatch, tmp_path):
    build_dir = tmp_path / "build-arm64"
    build_dir.mkdir()
    (build_dir / "micropython.exe").write_bytes(b"MZ")

    monkeypatch.setattr(
        build.llvmmingw,
        "resolve_llvm_mingw",
        lambda **k: ResolvedLlvmMingw(install_dir=tmp_path / "llvm-mingw"),
    )
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: None)

    result = build_windows(
        windows_opts(arch="arm64", build_dir=build_dir), tmp_path / "mpy"
    )

    assert result == build_dir / "micropython.exe"


def test_windows_arm64_missing_exe_after_success_is_an_error(monkeypatch, tmp_path):
    build_dir = tmp_path / "build-arm64"
    build_dir.mkdir()

    monkeypatch.setattr(
        build.llvmmingw,
        "resolve_llvm_mingw",
        lambda **k: ResolvedLlvmMingw(install_dir=tmp_path / "llvm-mingw"),
    )
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: None)

    with pytest.raises(UsermodBuildError, match="build reported success but"):
        build_windows(windows_opts(arch="arm64", build_dir=build_dir), tmp_path / "mpy")


def test_windows_arm64_build_failure_names_the_command(monkeypatch, tmp_path):
    import subprocess as sp

    def fake_run(cmd, **kwargs):
        raise sp.CalledProcessError(1, cmd)

    monkeypatch.setattr(
        build.llvmmingw,
        "resolve_llvm_mingw",
        lambda **k: ResolvedLlvmMingw(install_dir=tmp_path / "llvm-mingw"),
    )
    monkeypatch.setattr(build.subprocess, "run", fake_run)

    with pytest.raises(UsermodBuildError, match="failed with exit code"):
        build_windows(
            windows_opts(arch="arm64", build_dir=tmp_path / "build-arm64"),
            tmp_path / "mpy",
        )


# ── unix / docker strategy (D26 proof-of-concept) ───────────────────────────


def test_unix_docker_image_skips_host_toolchain_probe(monkeypatch, tmp_path):
    # CIBMP_UNIX_AARCH64_MANYLINUX_DOCKER_IMAGE set: the toolchain lives
    # inside the image, not on this host's PATH, so build_unix() must not
    # call shutil.which() at all -- a bare-host probe would reject a
    # perfectly good docker build.
    monkeypatch.setenv(
        "CIBMP_UNIX_AARCH64_MANYLINUX_DOCKER_IMAGE",
        "cibuildmp-unix-manylinux-aarch64:local",
    )
    monkeypatch.setattr(
        build.shutil,
        "which",
        lambda name: pytest.fail(f"unexpected host toolchain probe: {name}"),
    )
    build_dir = tmp_path / "build-aarch64"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(b"\x7fELF")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.usermod.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    result = build_unix(opts("aarch64", build_dir=build_dir), tmp_path / "mpy")

    assert result == build_dir / "micropython"
    assert len(calls) == 1
    docker_command = calls[0]
    assert docker_command[:3] == ["docker", "run", "--rm"]
    assert "cibuildmp-unix-manylinux-aarch64:local" in docker_command
    assert "make" in docker_command


def test_unix_docker_image_mounts_mpy_dir_and_user_c_modules(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "CIBMP_UNIX_X64_MANYLINUX_DOCKER_IMAGE", "cibuildmp-unix-manylinux-x64:local"
    )
    build_dir = tmp_path / "build-x64"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(b"\x7fELF")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.usermod.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    mpy_dir = tmp_path / "mpy"
    build_unix(opts("x64", build_dir=build_dir), mpy_dir)

    docker_command = calls[0]
    assert f"{mpy_dir}:{mpy_dir}" in docker_command
    assert "/gh/ws/micropython/usermod:/gh/ws/micropython/usermod" in docker_command


# test_unix_no_image_registered_is_a_clear_error (above) already covers
# "no CIBMP_UNIX_X64_MANYLINUX_DOCKER_IMAGE / PORT_IMAGES entry" for
# every arch, x64 included -- unix has no bare-host fallback left to
# fall back to (D30).

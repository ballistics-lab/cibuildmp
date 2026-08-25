from pathlib import Path

from cibuildmp.usermod import build as build_module
from cibuildmp.usermod.options import UsermodOptions
from cibuildmp.usermod.orchestrate import build, build_one
from cibuildmp.usermod.targets import UsermodTarget


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "cibuildmp.toml"
    path.write_text(text)
    return path


def make_module_dir(package_dir: Path, name: str = "usermod") -> None:
    mod = package_dir / name / "mymod"
    mod.mkdir(parents=True)
    (mod / "mymod.c").write_text("// stub\n")
    (mod / "micropython.mk").write_text("SRC_USERMOD += mymod.c\n")


def test_build_one_unix_writes_into_output_dir_identifier(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    make_module_dir(package_dir)
    write_config(package_dir, '[usermod]\nports = ["unix"]\n')
    options = UsermodOptions.load(package_dir)
    options.output_dir = tmp_path / "mpyhouse"

    mpy_dir = tmp_path / "mpy"
    target = UsermodTarget(port="unix", arch="x64")

    def fake_run(cmd, **kwargs):
        build_dir = mpy_dir / "ports" / "unix" / "build-unix-x64"
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "micropython").write_bytes(b"\x7fELF")

    monkeypatch.setattr(build_module.subprocess, "run", fake_run)
    (mpy_dir / "ports" / "unix").mkdir(parents=True)

    result = build_one(options, target, mpy_dir)

    assert result.identifier == "unix-x64"
    assert result.output == options.output_dir / "unix-x64" / "micropython-unix-x64"
    assert result.output.read_bytes() == b"\x7fELF"


def test_build_one_qemu_uses_default_board_not_empty_string(tmp_path, monkeypatch):
    # Regression check for the bug caught while writing this: qemu has no
    # configurable axis, so target.arch is always "" -- passing that
    # through as board= would silently override QemuBuildOptions' own
    # "MPS2_AN385" default with an empty string.
    package_dir = tmp_path / "pkg"
    make_module_dir(package_dir)
    write_config(package_dir, '[usermod]\nports = ["qemu"]\n')
    options = UsermodOptions.load(package_dir)
    options.output_dir = tmp_path / "mpyhouse"

    mpy_dir = tmp_path / "mpy"
    target = UsermodTarget(port="qemu", arch="")

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        build_dir = mpy_dir / "ports" / "qemu" / "build-qemu"
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "firmware.elf").write_bytes(b"\x7fELF")

    monkeypatch.setattr(build_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        build_module.toolchains,
        "resolve",
        lambda arch, **k: build_module.ResolvedToolchain(
            "host", "arm-none-eabi-", "arm-none-eabi-", None
        ),
    )
    (mpy_dir / "ports" / "qemu").mkdir(parents=True)

    result = build_one(options, target, mpy_dir)

    assert "BOARD=MPS2_AN385" in captured["cmd"]
    assert result.identifier == "qemu"


def test_build_one_writes_combined_manifest_when_present(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    make_module_dir(package_dir)
    (package_dir / "extra_manifest.py").write_text('freeze("extra")\n')
    write_config(
        package_dir,
        """
        [usermod]
        ports = ["unix"]
        manifest = "extra_manifest.py"
        """,
    )
    options = UsermodOptions.load(package_dir)
    options.output_dir = tmp_path / "mpyhouse"

    mpy_dir = tmp_path / "mpy"
    target = UsermodTarget(port="unix", arch="x64")
    written_manifest = {}

    def fake_run(cmd, **kwargs):
        for arg in cmd:
            if arg.startswith("FROZEN_MANIFEST="):
                path = Path(arg.removeprefix("FROZEN_MANIFEST="))
                written_manifest["path"] = path
                written_manifest["text"] = path.read_text()
        build_dir = mpy_dir / "ports" / "unix" / "build-unix-x64"
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "micropython").write_bytes(b"\x7fELF")

    monkeypatch.setattr(build_module.subprocess, "run", fake_run)
    (mpy_dir / "ports" / "unix").mkdir(parents=True)

    build_one(options, target, mpy_dir)

    assert (
        'include("$(PORT_DIR)/variants/standard/manifest.py")'
        in written_manifest["text"]
    )
    assert str(package_dir / "extra_manifest.py") in written_manifest["text"]


def test_build_one_esp32_passes_board_through(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    make_module_dir(package_dir)
    write_config(
        package_dir,
        """
        [usermod]
        ports = ["esp32"]

        [usermod.esp32]
        boards = ["ESP32_GENERIC_S3"]
        """,
    )
    options = UsermodOptions.load(package_dir)
    options.output_dir = tmp_path / "mpyhouse"

    mpy_dir = tmp_path / "mpy"
    target = UsermodTarget(port="esp32", arch="ESP32_GENERIC_S3")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        build_dir = mpy_dir / "ports" / "esp32" / "build-ESP32_GENERIC_S3"
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "micropython.bin").write_bytes(b"\x7fELF")

    class _FakeIdf:
        def env(self):
            return {}

    monkeypatch.setattr(build_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        build_module.espidf, "resolve_esp_idf", lambda *a, **k: _FakeIdf()
    )
    (mpy_dir / "ports" / "esp32").mkdir(parents=True)

    result = build_one(options, target, mpy_dir)

    assert "BOARD=ESP32_GENERIC_S3" in captured["cmd"]
    assert result.identifier == "esp32-ESP32_GENERIC_S3"


def test_build_fetches_micropython_and_builds_mpy_cross_once(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    make_module_dir(package_dir)
    write_config(package_dir, '[usermod]\nports = ["unix"]\n')
    options = UsermodOptions.load(package_dir)
    options.output_dir = tmp_path / "mpyhouse"

    mpy_dir = tmp_path / "mpy"
    (mpy_dir / "ports" / "unix").mkdir(parents=True)
    calls = []

    import cibuildmp.usermod.orchestrate as orchestrate_module

    monkeypatch.setattr(
        orchestrate_module.sources,
        "fetch_micropython",
        lambda tag, **k: calls.append(("fetch", tag)) or mpy_dir,
    )
    monkeypatch.setattr(
        orchestrate_module.sources,
        "build_mpy_cross",
        lambda d, **k: calls.append(("mpy-cross", d)),
    )

    def fake_run(cmd, **kwargs):
        build_dir = mpy_dir / "ports" / "unix" / "build-unix-x64"
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "micropython").write_bytes(b"\x7fELF")

    monkeypatch.setattr(build_module.subprocess, "run", fake_run)

    results = build(options, [UsermodTarget(port="unix", arch="x64")])

    assert calls == [("fetch", "v1.28.0"), ("mpy-cross", mpy_dir)]
    assert len(results) == 1
    assert results[0].identifier == "unix-x64"

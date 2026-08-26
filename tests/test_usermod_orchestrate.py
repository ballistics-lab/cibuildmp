from pathlib import Path

import pytest

from cibuildmp import dockerrun
from cibuildmp.platforms.natmod.options import DEFAULT_MICROPYTHON
from cibuildmp.platforms.usermod import build as build_module
from cibuildmp.platforms.usermod.options import UsermodOptions
from cibuildmp.platforms.usermod.orchestrate import build, build_one
from cibuildmp.platforms.usermod.targets import UsermodTarget


# Every `unix` cell in resources/pinned_docker_images.toml is empty until
# publish-docker-images.yml has run under record 0043's new names, so
# these cases resolve an image the same way a local build does today --
# through the documented override -- rather than depending on the pin
# table's current contents. `_probe_platform` is stubbed for the same
# reason test_usermod_build.py stubs it: it starts a real throwaway
# container, and it has its own coverage in test_usermod_dockerrun.py.
@pytest.fixture(autouse=True)
def _resolved_image(monkeypatch):
    monkeypatch.setattr(dockerrun, "ensure_image", lambda *a, **k: "stub-image:local")
    monkeypatch.setattr(dockerrun, "_probe_platform", lambda *a, **k: "")
    monkeypatch.setattr(
        build_module,
        "container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )


# A 20-byte x86_64 ELF header: `verify_unix_output()` (record 0043) reads
# `e_machine`/`EI_CLASS`/`EI_DATA` off whatever the build produced, so a
# stub binary has to be a header rather than the four magic bytes.
FAKE_X86_64_ELF = (
    b"\x7fELF"
    + bytes([2, 1, 1, 0])
    + bytes(8)
    + (2).to_bytes(2, "little")
    + (62).to_bytes(2, "little")
)


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
    write_config(package_dir, "[unix]\n")
    options = UsermodOptions.load(package_dir)
    options.output_dir = tmp_path / "mpyhouse"

    mpy_dir = tmp_path / "mpy"
    target = UsermodTarget(port="unix", arch="manylinux_2_28_x86_64")

    def fake_run(cmd, **kwargs):
        build_dir = mpy_dir / "ports" / "unix" / "build-unix-manylinux_2_28_x86_64"
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "micropython").write_bytes(FAKE_X86_64_ELF)

    monkeypatch.setattr(build_module.subprocess, "run", fake_run)
    (mpy_dir / "ports" / "unix").mkdir(parents=True)

    result = build_one(options, target, mpy_dir)

    assert result.identifier == "unix-manylinux_2_28_x86_64"
    assert (
        result.output
        == options.output_dir
        / "unix-manylinux_2_28_x86_64"
        / "micropython-unix-manylinux_2_28_x86_64"
    )
    assert result.output.read_bytes() == FAKE_X86_64_ELF


def test_build_one_qemu_uses_default_board_not_empty_string(tmp_path, monkeypatch):
    # Regression check for the bug caught while writing this: qemu has no
    # configurable axis, so target.arch is always "" -- passing that
    # through as board= would silently override QemuBuildOptions' own
    # "MPS2_AN385" default with an empty string.
    package_dir = tmp_path / "pkg"
    make_module_dir(package_dir)
    write_config(package_dir, "[qemu]\n")
    options = UsermodOptions.load(package_dir)
    options.output_dir = tmp_path / "mpyhouse"

    mpy_dir = tmp_path / "mpy"
    target = UsermodTarget(port="qemu", arch="")

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        build_dir = mpy_dir / "ports" / "qemu" / "build-qemu"
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "firmware.elf").write_bytes(FAKE_X86_64_ELF)

    monkeypatch.setattr(dockerrun, "ensure_image", lambda *a, **k: "qemu:test")
    monkeypatch.setattr(dockerrun, "run", lambda cmd, **k: fake_run(cmd, **k))
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
        [unix]
        manifest = "extra_manifest.py"
        """,
    )
    options = UsermodOptions.load(package_dir)
    options.output_dir = tmp_path / "mpyhouse"

    mpy_dir = tmp_path / "mpy"
    target = UsermodTarget(port="unix", arch="manylinux_2_28_x86_64")
    written_manifest = {}

    def fake_run(cmd, **kwargs):
        for arg in cmd:
            if arg.startswith("FROZEN_MANIFEST="):
                path = Path(arg.removeprefix("FROZEN_MANIFEST="))
                written_manifest["path"] = path
                written_manifest["text"] = path.read_text()
        build_dir = mpy_dir / "ports" / "unix" / "build-unix-manylinux_2_28_x86_64"
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "micropython").write_bytes(FAKE_X86_64_ELF)

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
        [esp32]
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
        (build_dir / "micropython.bin").write_bytes(FAKE_X86_64_ELF)

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


def test_build_fetches_micropython_and_skips_the_host_mpy_cross(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    make_module_dir(package_dir)
    write_config(package_dir, "[unix]\n")
    options = UsermodOptions.load(package_dir)
    options.output_dir = tmp_path / "mpyhouse"

    mpy_dir = tmp_path / "mpy"
    (mpy_dir / "ports" / "unix").mkdir(parents=True)
    calls = []

    import cibuildmp.platforms.usermod.orchestrate as orchestrate_module

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
        build_dir = (
            mpy_dir
            / "ports"
            / "unix"
            / f"build-{DEFAULT_MICROPYTHON}-unix-manylinux_2_28_x86_64"
        )
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "micropython").write_bytes(FAKE_X86_64_ELF)

    monkeypatch.setattr(build_module.subprocess, "run", fake_run)

    results = build(
        options,
        [
            UsermodTarget(
                port="unix", arch="manylinux_2_28_x86_64", tag=DEFAULT_MICROPYTHON
            )
        ],
    )

    # No host mpy-cross for a `unix` target: record 0044 gave it
    # `container_mpy_cross()`, because a host-built one cannot run inside
    # an image of another architecture or another libc. Only `qemu`
    # still reaches the host copy.
    assert calls == [("fetch", DEFAULT_MICROPYTHON)]
    assert len(results) == 1
    assert results[0].identifier == f"{DEFAULT_MICROPYTHON}-unix-manylinux_2_28_x86_64"


def test_build_groups_by_tag_and_fetches_once_per_group(tmp_path, monkeypatch):
    # The regression 0051's usermod half exists to fix: two tags of the
    # same port/arch must produce two distinct output directories in one
    # run, not one overwriting the other -- and each tag is fetched once,
    # not once per target in it (mirrors natmod's own cli.build()).
    package_dir = tmp_path / "pkg"
    make_module_dir(package_dir)
    write_config(package_dir, "[unix]\n")
    options = UsermodOptions.load(package_dir)
    options.output_dir = tmp_path / "mpyhouse"

    calls = []

    import cibuildmp.platforms.usermod.orchestrate as orchestrate_module

    def fake_fetch(tag, **k):
        calls.append(("fetch", tag))
        mpy_dir = tmp_path / f"mpy-{tag}"
        (mpy_dir / "ports" / "unix").mkdir(parents=True, exist_ok=True)
        return mpy_dir

    monkeypatch.setattr(orchestrate_module.sources, "fetch_micropython", fake_fetch)
    monkeypatch.setattr(
        orchestrate_module.sources,
        "build_mpy_cross",
        lambda d, **k: calls.append(("mpy-cross", d)),
    )

    def fake_run(cmd, **kwargs):
        # unix_make_command() always carries its own `BUILD=<build_dir>`
        # entry -- read it back rather than hardcoding one, since this
        # test runs the same command shape against two different
        # mpy_dirs (one per tag).
        build_arg = next(a for a in cmd if a.startswith("BUILD="))
        build_dir = Path(build_arg.removeprefix("BUILD="))
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "micropython").write_bytes(FAKE_X86_64_ELF)

    monkeypatch.setattr(build_module.subprocess, "run", fake_run)

    targets = [
        UsermodTarget(port="unix", arch="manylinux_2_28_x86_64", tag="v1.28.0"),
        UsermodTarget(port="unix", arch="manylinux_2_28_x86_64", tag="v1.29.0"),
    ]
    results = build(options, targets)

    assert calls == [("fetch", "v1.28.0"), ("fetch", "v1.29.0")]
    identifiers = {r.identifier for r in results}
    assert identifiers == {
        "v1.28.0-unix-manylinux_2_28_x86_64",
        "v1.29.0-unix-manylinux_2_28_x86_64",
    }
    output_dirs = {r.output.parent for r in results}
    assert (
        len(output_dirs) == 2
    )  # two distinct directories, not one overwriting the other


def test_build_one_resolves_relative_output_dir_against_package_dir(
    tmp_path, monkeypatch
):
    # Regression check: a real Docker-action run caught this -- process
    # cwd there is always the repo root, not package_dir, so a relative
    # output_dir (the real default, "mpyhouse") must resolve against
    # package_dir, not the bare cwd. This session's own default-output_dir
    # tests all set an absolute output_dir directly, which never exercised
    # the bug (Path("x") / "/abs" == "/abs" regardless of the left side).
    package_dir = tmp_path / "pkg"
    make_module_dir(package_dir)
    write_config(package_dir, "[unix]\n")
    options = UsermodOptions.load(package_dir)
    options.output_dir = Path("mpyhouse")  # relative, the real default

    mpy_dir = tmp_path / "mpy"
    target = UsermodTarget(port="unix", arch="manylinux_2_28_x86_64")

    def fake_run(cmd, **kwargs):
        build_dir = mpy_dir / "ports" / "unix" / "build-unix-manylinux_2_28_x86_64"
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "micropython").write_bytes(FAKE_X86_64_ELF)

    monkeypatch.setattr(build_module.subprocess, "run", fake_run)
    (mpy_dir / "ports" / "unix").mkdir(parents=True)

    result = build_one(options, target, mpy_dir)

    assert result.output == package_dir / "mpyhouse" / "unix-manylinux_2_28_x86_64" / (
        "micropython-unix-manylinux_2_28_x86_64"
    )
    assert not (tmp_path / "mpyhouse").exists()  # not resolved against cwd/tmp_path


def test_build_one_preserves_executable_bit(tmp_path, monkeypatch):
    # Regression check: shutil.copyfile() copies content only, not mode --
    # a real collected unix-manylinux_2_28_x86_64 binary came out `-rw-r--r--`, unrunnable,
    # caught only by actually trying to execute it after a real CLI build.
    # Unlike natmod's own .mpy (never executed directly, D23), a usermod
    # build's output IS meant to be run.
    package_dir = tmp_path / "pkg"
    make_module_dir(package_dir)
    write_config(package_dir, "[unix]\n")
    options = UsermodOptions.load(package_dir)
    options.output_dir = tmp_path / "mpyhouse"

    mpy_dir = tmp_path / "mpy"
    target = UsermodTarget(port="unix", arch="manylinux_2_28_x86_64")

    def fake_run(cmd, **kwargs):
        build_dir = mpy_dir / "ports" / "unix" / "build-unix-manylinux_2_28_x86_64"
        build_dir.mkdir(parents=True, exist_ok=True)
        produced = build_dir / "micropython"
        produced.write_bytes(FAKE_X86_64_ELF)
        produced.chmod(0o755)

    monkeypatch.setattr(build_module.subprocess, "run", fake_run)
    (mpy_dir / "ports" / "unix").mkdir(parents=True)

    result = build_one(options, target, mpy_dir)

    assert result.output.stat().st_mode & 0o111 != 0

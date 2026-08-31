import json
from pathlib import Path

import pytest

from cibuildmp import dockerrun
from cibuildmp.platforms.usermod import build_common, espidf
from cibuildmp.platforms.usermod.options import UsermodOptions
from cibuildmp.platforms.usermod.orchestrate import _dest_name, build, build_one
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
        build_common,
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
    write_config(package_dir, "")
    options = UsermodOptions.load(package_dir)
    options.output_dir = tmp_path / "mpyhouse"

    mpy_dir = tmp_path / "mpy"
    target = UsermodTarget(port="unix", arch="manylinux_2_28_x86_64")

    def fake_run(cmd, **kwargs):
        build_dir = mpy_dir / "ports" / "unix" / "build-unix-manylinux_2_28_x86_64"
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "micropython").write_bytes(FAKE_X86_64_ELF)

    monkeypatch.setattr(dockerrun.subprocess, "run", fake_run)
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


def test_build_one_substitutes_micropython_placeholder_in_user_c_modules(
    tmp_path, monkeypatch
):
    # `{micropython}` (docs/records/0069's own addendum) lets `user-c-modules`
    # name a path *inside the pinned checkout* without a caller resolving it
    # first -- `mpy_dir` is already real and resolved by the time `build_one()`
    # runs, for every port uniformly. No module directory needs to actually
    # exist under `package_dir` here: the substituted value is already
    # absolute, so `package_dir / user_c_modules` discards `package_dir`
    # entirely (the same `Path("x") / "/abs" == "/abs"` behaviour the
    # relative-output_dir test above already relies on).
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    write_config(package_dir, 'user-c-modules = "{micropython}/vendor/mymod"\n')
    options = UsermodOptions.load(package_dir)
    options.output_dir = tmp_path / "mpyhouse"

    mpy_dir = tmp_path / "mpy"
    target = UsermodTarget(port="unix", arch="manylinux_2_28_x86_64")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        build_dir = mpy_dir / "ports" / "unix" / "build-unix-manylinux_2_28_x86_64"
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "micropython").write_bytes(FAKE_X86_64_ELF)

    monkeypatch.setattr(dockerrun.subprocess, "run", fake_run)
    (mpy_dir / "ports" / "unix").mkdir(parents=True)

    build_one(options, target, mpy_dir)

    expected = f"USER_C_MODULES={(mpy_dir / 'vendor' / 'mymod').as_posix()}"
    assert expected in " ".join(captured["cmd"])


def test_dest_name_unset_keeps_todays_filename():
    # record 0052, A3: gated on `name` alone -- a project that has not set
    # it yet keeps exactly today's filename, "micropython" stem included.
    assert (
        _dest_name(Path("micropython"), "unix-manylinux_2_28_x86_64")
        == "micropython-unix-manylinux_2_28_x86_64"
    )


def test_dest_name_with_name_and_version_drops_the_micropython_stem():
    assert (
        _dest_name(
            Path("micropython.exe"),
            "windows-arm64",
            name="mylib",
            version="1.2.0",
        )
        == "mylib-1.2.0-windows-arm64.exe"
    )


def test_dest_name_with_name_only_omits_the_version_segment():
    assert (
        _dest_name(Path("micropython.bin"), "esp32-ESP32_GENERIC", name="mylib")
        == "mylib-esp32-ESP32_GENERIC.bin"
    )


def test_build_one_threads_name_and_version_into_the_output_filename(
    tmp_path, monkeypatch
):
    package_dir = tmp_path / "pkg"
    make_module_dir(package_dir)
    write_config(package_dir, 'name = "mylib"\nversion = "1.2.0"\n')
    options = UsermodOptions.load(package_dir)
    options.output_dir = tmp_path / "mpyhouse"

    mpy_dir = tmp_path / "mpy"
    target = UsermodTarget(port="unix", arch="manylinux_2_28_x86_64")

    def fake_run(cmd, **kwargs):
        build_dir = mpy_dir / "ports" / "unix" / "build-unix-manylinux_2_28_x86_64"
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "micropython").write_bytes(FAKE_X86_64_ELF)

    monkeypatch.setattr(dockerrun.subprocess, "run", fake_run)
    (mpy_dir / "ports" / "unix").mkdir(parents=True)

    result = build_one(options, target, mpy_dir)

    assert (
        result.output
        == options.output_dir
        / "unix-manylinux_2_28_x86_64"
        / "mylib-1.2.0-unix-manylinux_2_28_x86_64"
    )


def test_build_one_qemu_uses_default_board_not_empty_string(tmp_path, monkeypatch):
    # Regression check for the bug caught while writing this: qemu has no
    # configurable axis, so target.arch is always "" -- passing that
    # through as board= would silently override QemuBuildOptions' own
    # "MPS2_AN385" default with an empty string.
    package_dir = tmp_path / "pkg"
    make_module_dir(package_dir)
    write_config(package_dir, "")
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
        manifest = "extra_manifest.py"
        [unix]
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

    monkeypatch.setattr(dockerrun.subprocess, "run", fake_run)
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

    monkeypatch.setenv("CIBMP_ESP32_DOCKER_IMAGE", "cibuildmp-esp32:local")
    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", fake_run)
    monkeypatch.setattr(
        build_common,
        "container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )
    monkeypatch.setattr(espidf, "fetch_esp_idf", lambda version, **k: tmp_path / "idf")
    (mpy_dir / "ports" / "esp32").mkdir(parents=True)

    result = build_one(options, target, mpy_dir)

    assert "BOARD=ESP32_GENERIC_S3" in " ".join(captured["cmd"])
    assert result.identifier == "esp32-ESP32_GENERIC_S3"


def test_build_one_esp32_threads_real_idf_version_and_target(tmp_path, monkeypatch):
    # ESP32_GENERIC_C3 at v1.29.0 is a real row (resources/build-platforms.toml):
    # idf_version = "v5.5.2", mcu = "esp32c3" -- neither matches
    # Esp32BuildOptions' own defaults ("v5.5.1"/"esp32"), so this only
    # passes if _port_build_options() actually resolved the real row
    # rather than falling back to them.
    package_dir = tmp_path / "pkg"
    make_module_dir(package_dir)
    write_config(package_dir, "")
    options = UsermodOptions.load(package_dir)
    options.output_dir = tmp_path / "mpyhouse"

    mpy_dir = tmp_path / "mpy"
    target = UsermodTarget(port="esp32", arch="ESP32_GENERIC_C3", tag="v1.29.0")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        build_dir = mpy_dir / "ports" / "esp32" / "build-ESP32_GENERIC_C3"
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "micropython.bin").write_bytes(FAKE_X86_64_ELF)

    fetch_calls = []
    monkeypatch.setenv("CIBMP_ESP32_DOCKER_IMAGE", "cibuildmp-esp32:local")
    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", fake_run)
    monkeypatch.setattr(
        build_common,
        "container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )
    monkeypatch.setattr(
        espidf,
        "fetch_esp_idf",
        lambda version, **k: fetch_calls.append(version) or tmp_path / "idf" / version,
    )
    (mpy_dir / "ports" / "esp32").mkdir(parents=True)

    build_one(options, target, mpy_dir)

    assert fetch_calls == ["v5.5.2"]
    script = " ".join(captured["cmd"])
    assert "--targets=esp32c3" in script
    assert "esp-idf/v5.5.2/tools/esp32c3" in script


def test_build_fetches_micropython_and_skips_the_host_mpy_cross(tmp_path, monkeypatch):
    package_dir = tmp_path / "pkg"
    make_module_dir(package_dir)
    write_config(package_dir, "")
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
        build_dir = mpy_dir / "ports" / "unix" / "build-v1.29.0-manylinux_2_28_x86_64"
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "micropython").write_bytes(FAKE_X86_64_ELF)

    monkeypatch.setattr(dockerrun.subprocess, "run", fake_run)

    results = build(
        options,
        [UsermodTarget(port="unix", arch="manylinux_2_28_x86_64", tag="v1.29.0")],
    )

    # No host mpy-cross for a `unix` target: record 0044 gave it
    # `container_mpy_cross()`, because a host-built one cannot run inside
    # an image of another architecture or another libc. Only `qemu`
    # still reaches the host copy.
    assert calls == [("fetch", "v1.29.0")]
    assert len(results) == 1
    assert results[0].identifier == "v1.29.0-manylinux_2_28_x86_64"


def test_build_groups_by_tag_and_fetches_once_per_group(tmp_path, monkeypatch):
    # The regression 0051's usermod half exists to fix: two tags of the
    # same port/arch must produce two distinct output directories in one
    # run, not one overwriting the other -- and each tag is fetched once,
    # not once per target in it (mirrors natmod's own cli.build()).
    package_dir = tmp_path / "pkg"
    make_module_dir(package_dir)
    write_config(package_dir, "")
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

    monkeypatch.setattr(dockerrun.subprocess, "run", fake_run)

    targets = [
        UsermodTarget(port="unix", arch="manylinux_2_28_x86_64", tag="v1.28.0"),
        UsermodTarget(port="unix", arch="manylinux_2_28_x86_64", tag="v1.29.0"),
    ]
    results = build(options, targets)

    assert calls == [("fetch", "v1.28.0"), ("fetch", "v1.29.0")]
    identifiers = {r.identifier for r in results}
    assert identifiers == {
        "v1.28.0-manylinux_2_28_x86_64",
        "v1.29.0-manylinux_2_28_x86_64",
    }
    output_dirs = {r.output.parent for r in results}
    assert (
        len(output_dirs) == 2
    )  # two distinct directories, not one overwriting the other


def test_build_keep_going_continues_past_a_failed_target(tmp_path, monkeypatch):
    # qemu fails, unix still gets attempted and its result is still
    # returned -- the default (fail-fast) would have stopped at whichever
    # of the two `build_one()` calls ran first.
    package_dir = tmp_path / "pkg"
    make_module_dir(package_dir)
    write_config(package_dir, "")
    options = UsermodOptions.load(package_dir)
    options.output_dir = tmp_path / "mpyhouse"

    import cibuildmp.platforms.usermod.orchestrate as orchestrate_module

    monkeypatch.setattr(
        orchestrate_module.sources,
        "fetch_micropython",
        lambda tag, **k: tmp_path / "mpy",
    )
    monkeypatch.setattr(
        orchestrate_module.sources, "build_mpy_cross", lambda d, **k: None
    )

    def fake_build_one(options, target, mpy_dir, **k):
        if target.port == "qemu":
            raise build_common.UsermodBuildError("simulated qemu failure")
        identifier_dir = options.output_dir / target.identifier
        identifier_dir.mkdir(parents=True, exist_ok=True)
        produced = identifier_dir / "micropython"
        produced.write_bytes(FAKE_X86_64_ELF)
        return orchestrate_module.UsermodBuildResult(
            identifier=target.identifier, output=produced, duration=0.1
        )

    monkeypatch.setattr(orchestrate_module, "build_one", fake_build_one)
    monkeypatch.setenv("CIBMP_REPORT_PATH", str(tmp_path / "reports"))

    targets = [
        UsermodTarget(port="unix", arch="manylinux_2_28_x86_64", tag="v1.29.0"),
        # No tag -- a hand-built UsermodTarget with a real tag must match a
        # real (port, tag, arch) row (see .identifier's own docstring);
        # "" is the plain, pre-0052 {port}-{arch} shape every build-
        # mechanics test other than the real-row ones already uses.
        UsermodTarget(port="qemu", arch=""),
    ]

    results = orchestrate_module.build(options, targets, keep_going=True)

    assert [r.identifier for r in results] == ["v1.29.0-manylinux_2_28_x86_64"]

    report_files = list((tmp_path / "reports").glob("*.json"))
    assert len(report_files) == 1
    payload = json.loads(report_files[0].read_text())
    assert payload["built"] == 1
    assert payload["failed"] == 1
    failed = next(r for r in payload["results"] if r["error"])
    assert "simulated qemu failure" in failed["error"]


def test_build_without_keep_going_raises_but_still_writes_a_report(
    tmp_path, monkeypatch
):
    package_dir = tmp_path / "pkg"
    make_module_dir(package_dir)
    write_config(package_dir, "")
    options = UsermodOptions.load(package_dir)
    options.output_dir = tmp_path / "mpyhouse"

    import cibuildmp.platforms.usermod.orchestrate as orchestrate_module

    monkeypatch.setattr(
        orchestrate_module.sources,
        "fetch_micropython",
        lambda tag, **k: tmp_path / "mpy",
    )

    def fake_build_one(options, target, mpy_dir, **k):
        raise build_common.UsermodBuildError("simulated failure")

    monkeypatch.setattr(orchestrate_module, "build_one", fake_build_one)
    monkeypatch.setenv("CIBMP_REPORT_PATH", str(tmp_path / "reports"))

    targets = [UsermodTarget(port="unix", arch="manylinux_2_28_x86_64", tag="v1.29.0")]

    with pytest.raises(build_common.UsermodBuildError):
        orchestrate_module.build(options, targets)

    # write_report() runs from the `finally` regardless of keep_going, so
    # the one failure this raised on is still on record.
    report_files = list((tmp_path / "reports").glob("*.json"))
    assert len(report_files) == 1
    payload = json.loads(report_files[0].read_text())
    assert payload["failed"] == 1
    assert payload["built"] == 0


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
    write_config(package_dir, "")
    options = UsermodOptions.load(package_dir)
    options.output_dir = Path("mpyhouse")  # relative, the real default

    mpy_dir = tmp_path / "mpy"
    target = UsermodTarget(port="unix", arch="manylinux_2_28_x86_64")

    def fake_run(cmd, **kwargs):
        build_dir = mpy_dir / "ports" / "unix" / "build-unix-manylinux_2_28_x86_64"
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "micropython").write_bytes(FAKE_X86_64_ELF)

    monkeypatch.setattr(dockerrun.subprocess, "run", fake_run)
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
    write_config(package_dir, "")
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

    monkeypatch.setattr(dockerrun.subprocess, "run", fake_run)
    (mpy_dir / "ports" / "unix").mkdir(parents=True)

    result = build_one(options, target, mpy_dir)

    assert result.output.stat().st_mode & 0o111 != 0


def test_build_one_copies_repaired_unix_lib_sidecar_alongside_the_binary(
    tmp_path, monkeypatch
):
    # Regression check, record 0069/0070: `repair_unix_binary()` vendors
    # libffi.so.6 into a `lib/` dir beside the built binary and points it
    # there with `patchelf --set-rpath '$ORIGIN/lib'` -- a real collected
    # artifact silently shipped without that sidecar, "$ORIGIN" resolving
    # to wherever the binary actually runs from, not its original build
    # directory, and failed "error while loading shared libraries:
    # libffi.so.6: cannot open shared object file" the first time anything
    # in this project actually executed a collected unix binary
    # (examples/usercmodule/smoke_test.py, not just `ls`ed its output).
    package_dir = tmp_path / "pkg"
    make_module_dir(package_dir)
    write_config(package_dir, "")
    options = UsermodOptions.load(package_dir)
    options.output_dir = tmp_path / "mpyhouse"

    mpy_dir = tmp_path / "mpy"
    target = UsermodTarget(port="unix", arch="manylinux_2_28_x86_64")

    def fake_run(cmd, **kwargs):
        build_dir = mpy_dir / "ports" / "unix" / "build-unix-manylinux_2_28_x86_64"
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "micropython").write_bytes(FAKE_X86_64_ELF)
        # What a real repair_unix_binary() run leaves behind -- this test
        # stubs dockerrun.subprocess.run entirely, so the real ldd/patchelf
        # invocation never runs; simulating its own output directly is what
        # lets this test exercise build_one()'s own collection step without
        # a real container.
        lib_dir = build_dir / "lib"
        lib_dir.mkdir()
        (lib_dir / "libffi.so.6").write_bytes(b"\x7fELF-stub-shared-object")

    monkeypatch.setattr(dockerrun.subprocess, "run", fake_run)
    (mpy_dir / "ports" / "unix").mkdir(parents=True)

    result = build_one(options, target, mpy_dir)

    sidecar = result.output.parent / "lib" / "libffi.so.6"
    assert sidecar.is_file()
    assert sidecar.read_bytes() == b"\x7fELF-stub-shared-object"


def test_build_one_skips_lib_copy_when_no_sidecar_exists(tmp_path, monkeypatch):
    # The common case (a statically-linked or already-in-floor target) --
    # repair_unix_binary() creates no `lib/` dir at all, and this must stay
    # a plain no-op rather than raising on a directory that never existed.
    package_dir = tmp_path / "pkg"
    make_module_dir(package_dir)
    write_config(package_dir, "")
    options = UsermodOptions.load(package_dir)
    options.output_dir = tmp_path / "mpyhouse"

    mpy_dir = tmp_path / "mpy"
    target = UsermodTarget(port="unix", arch="manylinux_2_28_x86_64")

    def fake_run(cmd, **kwargs):
        build_dir = mpy_dir / "ports" / "unix" / "build-unix-manylinux_2_28_x86_64"
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "micropython").write_bytes(FAKE_X86_64_ELF)

    monkeypatch.setattr(dockerrun.subprocess, "run", fake_run)
    (mpy_dir / "ports" / "unix").mkdir(parents=True)

    result = build_one(options, target, mpy_dir)

    assert not (result.output.parent / "lib").exists()


def test_build_one_collects_the_wasm_blob_beside_the_mjs(tmp_path, monkeypatch):
    # Record 0079: `ports/webassembly` builds `micropython.mjs` AND
    # `micropython.wasm` (its own README says so, and nothing passes
    # emscripten `-sSINGLE_FILE`). The driver returns the `.mjs`, which
    # loads the blob by that literal name from its own directory -- so
    # collecting the `.mjs` alone shipped 217,344 of the 680,703 bytes a
    # real build produced, and running it aborted with "failed to
    # asynchronously prepare wasm: ENOENT ... micropython.wasm".
    package_dir = tmp_path / "pkg"
    make_module_dir(package_dir)
    write_config(package_dir, "")
    options = UsermodOptions.load(package_dir)
    options.output_dir = tmp_path / "mpyhouse"

    mpy_dir = tmp_path / "mpy"
    target = UsermodTarget(port="webassembly", arch="wasm32")

    def fake_run(cmd, **kwargs):
        build_dir = mpy_dir / "ports" / "webassembly" / "build-webassembly-wasm32"
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "micropython.mjs").write_text(
            "var wasmBinaryFile='micropython.wasm'"
        )
        (build_dir / "micropython.wasm").write_bytes(b"\x00asm\x01\x00\x00\x00")

    monkeypatch.setattr(dockerrun, "run", fake_run)
    (mpy_dir / "ports" / "webassembly").mkdir(parents=True)

    result = build_one(options, target, mpy_dir)

    blob = result.output.parent / "micropython.wasm"
    assert blob.is_file()
    assert blob.read_bytes() == b"\x00asm\x01\x00\x00\x00"
    # Under its own name, not `_dest_name()`-qualified: the `.mjs` looks
    # for exactly this string.
    assert not list(result.output.parent.glob("*-wasm32.wasm"))


def test_build_one_collects_the_esp32_combined_firmware(tmp_path, monkeypatch):
    # Record 0079: the driver returns `micropython.bin`, the application
    # image; `firmware.bin` is the combined bootloader + partition table
    # + application one that actually flashes (ports/esp32/README.md).
    # Both real consumers that ship an esp32 artifact upload both files.
    package_dir = tmp_path / "pkg"
    make_module_dir(package_dir)
    write_config(package_dir, "")
    options = UsermodOptions.load(package_dir)
    options.output_dir = tmp_path / "mpyhouse"

    mpy_dir = tmp_path / "mpy"
    target = UsermodTarget(port="esp32", arch="ESP32_GENERIC")

    def fake_run(cmd, **kwargs):
        build_dir = mpy_dir / "ports" / "esp32" / "build-ESP32_GENERIC"
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "micropython.bin").write_bytes(FAKE_X86_64_ELF)
        (build_dir / "firmware.bin").write_bytes(b"combined-image")

    monkeypatch.setenv("CIBMP_ESP32_DOCKER_IMAGE", "cibuildmp-esp32:local")
    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", fake_run)
    monkeypatch.setattr(espidf, "fetch_esp_idf", lambda version, **k: tmp_path / "idf")
    (mpy_dir / "ports" / "esp32").mkdir(parents=True)

    result = build_one(options, target, mpy_dir)

    combined = result.output.parent / "firmware.bin"
    assert combined.is_file()
    assert combined.read_bytes() == b"combined-image"


def test_build_one_does_not_copy_a_non_unix_lib_directory(tmp_path, monkeypatch):
    # Record 0079's other half: record 0070's fix copied any `lib/` next
    # to the produced binary, for every port. `ports/qemu` has one --
    # `libm/`'s own object files -- so a real collected
    # `mpyhouse/v1.28.0-qemu-MPS2_AN385/lib/` carried 54 `.o`/`.P`
    # intermediates (240K of build scratch) out to a release. Only the
    # port knows which siblings are part of its artifact, and `qemu`
    # declares none.
    package_dir = tmp_path / "pkg"
    make_module_dir(package_dir)
    write_config(package_dir, "")
    options = UsermodOptions.load(package_dir)
    options.output_dir = tmp_path / "mpyhouse"

    mpy_dir = tmp_path / "mpy"
    target = UsermodTarget(port="qemu", arch="")

    def fake_run(cmd, **kwargs):
        build_dir = mpy_dir / "ports" / "qemu" / "build-qemu"
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "firmware.elf").write_bytes(FAKE_X86_64_ELF)
        libm = build_dir / "lib" / "libm"
        libm.mkdir(parents=True)
        (libm / "math.o").write_bytes(b"object-file")

    monkeypatch.setattr(dockerrun, "ensure_image", lambda *a, **k: "qemu:test")
    monkeypatch.setattr(dockerrun, "run", lambda cmd, **k: fake_run(cmd, **k))
    (mpy_dir / "ports" / "qemu").mkdir(parents=True)

    result = build_one(options, target, mpy_dir)

    assert not (result.output.parent / "lib").exists()


def test_build_one_collects_vendored_libs_without_the_port_object_tree(
    tmp_path, monkeypatch
):
    # Record 0079, caught on a downloaded CI artifact: `ports/unix/
    # build-<identifier>/lib/` is the port's OWN object directory
    # (`mbedtls/`, `berkeley-db-1.xx/`, `littlefs/`, `oofatfs/`), and
    # `repair_unix_binary()` drops its vendored shared object straight
    # into it. Record 0070's fix copied the whole directory, so a real
    # `manylinux_2_28_x86_64` artifact shipped 2.0M of `lib/` for 40K of
    # actual dependency -- 94 `.o` plus 94 `.P` files along for the ride.
    # What repair vendors is always a plain file directly in `lib/`.
    package_dir = tmp_path / "pkg"
    make_module_dir(package_dir)
    write_config(package_dir, "")
    options = UsermodOptions.load(package_dir)
    options.output_dir = tmp_path / "mpyhouse"

    mpy_dir = tmp_path / "mpy"
    target = UsermodTarget(port="unix", arch="manylinux_2_28_x86_64")

    def fake_run(cmd, **kwargs):
        build_dir = mpy_dir / "ports" / "unix" / "build-unix-manylinux_2_28_x86_64"
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "micropython").write_bytes(FAKE_X86_64_ELF)
        lib_dir = build_dir / "lib"
        (lib_dir / "mbedtls").mkdir(parents=True)
        (lib_dir / "mbedtls" / "aes.o").write_bytes(b"object-file")
        (lib_dir / "mbedtls" / "aes.P").write_bytes(b"depfile")
        (lib_dir / "libffi.so.6").write_bytes(b"\x7fELF-stub-shared-object")

    monkeypatch.setattr(dockerrun.subprocess, "run", fake_run)
    (mpy_dir / "ports" / "unix").mkdir(parents=True)

    result = build_one(options, target, mpy_dir)

    collected_lib = result.output.parent / "lib"
    # The vendored .so lands where `$ORIGIN/lib` will look for it...
    assert (collected_lib / "libffi.so.6").is_file()
    # ...and the port's own intermediates do not come with it.
    assert not (collected_lib / "mbedtls").exists()
    assert [p.name for p in collected_lib.iterdir()] == ["libffi.so.6"]

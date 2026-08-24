import subprocess
import sys
from pathlib import Path

import pytest

from cibuildmp import build
from cibuildmp.build import (
    BuildError,
    BuildResult,
    build_target,
    collect_output,
    make_command,
    output_name,
    read_native_arch,
    run_make,
    run_pre_build_command,
    verify_output,
)
from cibuildmp.options import BuildOptions
from cibuildmp.targets import Target
from cibuildmp.toolchains import ResolvedToolchain

HOST_CHAIN = ResolvedToolchain("none", "", "", None)


def build_options(arch: str = "armv7emsp", **overrides) -> BuildOptions:
    defaults = {
        "target": Target(abi="6.3", mode="natmod", arch=arch),
        "micropython": "v1.28.0",
        "output_dir": Path("mpyhouse"),
        "module_dir": "natmod",
        "make_target": "dist",
    }
    defaults.update(overrides)
    return BuildOptions(**defaults)


def write_mpy(
    path: Path, *, native_code: int, version: int = 6, sub_version: int = 3
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header_flags = (native_code << 2) | sub_version
    path.write_bytes(bytes([ord("M"), version, header_flags, 31]) + b"\x00" * 8)


# -- make_command -----------------------------------------------------------


def test_make_command_carries_python_and_arch(tmp_path):
    opts = build_options(extra_make_args=["MP_BCLIBC_PRECISION=single"])
    command = make_command(opts, tmp_path / "mpy", tmp_path / "natmod")
    assert command == [
        "make",
        "-C",
        str(tmp_path / "natmod"),
        "ARCH=armv7emsp",
        f"MPY_DIR={tmp_path / 'mpy'}",
        f"PYTHON={sys.executable}",
        "MP_BCLIBC_PRECISION=single",
        "dist",
    ]


# -- run_pre_build_command / run_make ----------------------------------------


def test_pre_build_command_noop_when_empty(tmp_path):
    run_pre_build_command(tmp_path, "", {})  # must not raise / must not shell out


def test_pre_build_command_runs_in_module_root(tmp_path):
    run_pre_build_command(tmp_path, "touch marker", {})
    assert (tmp_path / "marker").exists()


def test_pre_build_command_failure_is_a_build_error(tmp_path):
    with pytest.raises(BuildError, match="pre-build-command failed"):
        run_pre_build_command(tmp_path, "exit 1", {})


def test_run_make_failure_names_the_command(tmp_path, monkeypatch):
    def fake_run(command, **kwargs):
        raise subprocess.CalledProcessError(2, command)

    monkeypatch.setattr(build.subprocess, "run", fake_run)
    with pytest.raises(BuildError, match="exit code 2"):
        run_make(build_options(), tmp_path / "mpy", tmp_path, {})


def test_run_make_does_not_also_pass_cwd(tmp_path, monkeypatch):
    # `-C module_root` in the command already makes make chdir there; also
    # passing cwd=module_root double-applies it, breaking whenever
    # module_root is relative (options.package_dir defaults to ".") --
    # make then looks for module_root nested inside itself.
    calls = []

    def fake_run(command, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(build.subprocess, "run", fake_run)
    relative_module_root = Path("natmod")
    run_make(build_options(), tmp_path / "mpy", relative_module_root, {})
    assert "cwd" not in calls[0]


# -- collect_output -----------------------------------------------------------


def test_collect_output_finds_the_single_mpy(tmp_path):
    write_mpy(tmp_path / "build" / "armv7emsp-eabi" / "mymodule.mpy", native_code=7)
    found = collect_output(build_options(), tmp_path)
    assert found == tmp_path / "build" / "armv7emsp-eabi" / "mymodule.mpy"


def test_collect_output_missing_is_a_build_error(tmp_path):
    with pytest.raises(BuildError, match="produced no .mpy"):
        collect_output(build_options(), tmp_path)


def test_collect_output_ambiguous_is_a_build_error(tmp_path):
    write_mpy(tmp_path / "build" / "armv7emsp-a" / "one.mpy", native_code=7)
    write_mpy(tmp_path / "build" / "armv7emsp-b" / "two.mpy", native_code=7)
    with pytest.raises(BuildError, match="ambiguous output"):
        collect_output(build_options(), tmp_path)


# -- header parsing / verification -------------------------------------------


def test_read_native_arch(tmp_path):
    mpy = tmp_path / "m.mpy"
    write_mpy(mpy, native_code=10)  # xtensawin
    assert read_native_arch(mpy) == 10


def test_read_native_arch_rejects_bad_magic(tmp_path):
    mpy = tmp_path / "m.mpy"
    mpy.write_bytes(b"\x00\x06\x2b\x1f")
    with pytest.raises(BuildError, match="bad header"):
        read_native_arch(mpy)


def test_verify_output_accepts_matching_arch(tmp_path):
    mpy = tmp_path / "m.mpy"
    write_mpy(mpy, native_code=7)  # armv7emsp
    verify_output(build_options("armv7emsp"), mpy)  # must not raise


def test_verify_output_rejects_mismatched_arch(tmp_path):
    mpy = tmp_path / "m.mpy"
    write_mpy(mpy, native_code=2)  # x64, not armv7emsp
    with pytest.raises(BuildError, match="expected 7"):
        verify_output(build_options("armv7emsp"), mpy)


# -- output_name / build_target -----------------------------------------------


def test_output_name_is_unambiguous():
    mpy = Path("build/armv7emsp-eabi/mymodule.mpy")
    assert output_name(build_options(), mpy) == "mymodule-mpy6.3-natmod-armv7emsp.mpy"


def test_build_target_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: None)

    def fake_make(*a, **k):
        write_mpy(
            tmp_path / "natmod" / "build" / "armv7emsp-eabi" / "mymodule.mpy",
            native_code=7,
        )

    monkeypatch.setattr(build, "run_make", fake_make)

    opts = build_options()
    result = build_target(
        opts,
        HOST_CHAIN,
        tmp_path / "mpy",
        tmp_path / "natmod",
        tmp_path / "out",
        set(),
    )
    assert isinstance(result, BuildResult)
    assert result.output == tmp_path / "out" / "mymodule-mpy6.3-natmod-armv7emsp.mpy"
    assert result.output.exists()
    assert result.size > 0


def test_build_target_rejects_duplicate_output_name(tmp_path, monkeypatch):
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: None)

    def fake_make(*a, **k):
        write_mpy(
            tmp_path / "natmod" / "build" / "armv7emsp-eabi" / "mymodule.mpy",
            native_code=7,
        )

    monkeypatch.setattr(build, "run_make", fake_make)

    seen = {"mymodule-mpy6.3-natmod-armv7emsp.mpy"}
    with pytest.raises(BuildError, match="two targets"):
        build_target(
            build_options(),
            HOST_CHAIN,
            tmp_path / "mpy",
            tmp_path / "natmod",
            tmp_path / "out",
            seen,
        )

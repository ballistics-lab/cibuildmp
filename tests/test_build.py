import json
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
    read_mpy_header,
    read_native_arch,
    run_make,
    run_pre_build_command,
    verify_output,
)
from cibuildmp.options import BuildOptions
from cibuildmp.targets import Target
from cibuildmp.toolchains import ResolvedToolchain

HOST_CHAIN = ResolvedToolchain("none", "", "", None)


def build_options(
    arch: str = "armv7emsp", arch_flags: int = 0, **overrides
) -> BuildOptions:
    defaults = {
        "target": Target(abi="6.3", mode="natmod", arch=arch, arch_flags=arch_flags),
        "micropython": "v1.28.0",
        "output_dir": Path("mpyhouse"),
        "module_dir": "natmod",
        "make_target": "dist",
    }
    defaults.update(overrides)
    return BuildOptions(**defaults)


def _encode_varint(value: int) -> bytes:
    """Inverse of build._read_varint -- big-endian 7-bit groups, MSB=more."""
    if value == 0:
        return bytes([0])
    chunks = []
    v = value
    while v:
        chunks.append(v & 0x7F)
        v >>= 7
    chunks.reverse()
    return bytes(c | 0x80 for c in chunks[:-1]) + bytes([chunks[-1]])


def write_mpy(
    path: Path,
    *,
    native_code: int,
    version: int = 6,
    sub_version: int = 3,
    arch_flags: int = 0,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header_flags = (native_code << 2) | sub_version
    data = bytearray([ord("M"), version, header_flags, 31])
    if arch_flags:
        data[2] |= 0x40  # MPY_ARCH_FLAGS_BIT
        data += _encode_varint(arch_flags)
    data += b"\x00" * 8
    path.write_bytes(bytes(data))


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
    # "echo hi > marker", not "touch marker": both /bin/sh -c and
    # cmd.exe /c understand echo + redirection, so this actually tests
    # cwd handling on every host shell=True picks, not just Unix ones --
    # touch has no cmd.exe equivalent (found by a real windows-latest CI
    # run of this same test, docs/BACKLOG.md's own "Windows/macOS hosts").
    run_pre_build_command(tmp_path, "echo hi > marker", {})
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


def test_read_native_arch_masks_out_the_arch_flags_marker_bit(tmp_path):
    # Regression: MPY_FEATURE_DECODE_ARCH is ((feat >> 2) & 0x2F), not a
    # bare shift. Without the mask, rv32imc (11) with the arch-flags marker
    # bit set decodes as 27 instead of 11.
    mpy = tmp_path / "m.mpy"
    write_mpy(mpy, native_code=11, arch_flags=3)
    assert read_native_arch(mpy) == 11


def test_read_mpy_header_round_trips_arch_flags(tmp_path):
    mpy = tmp_path / "m.mpy"
    write_mpy(mpy, native_code=11, arch_flags=3)
    version, arch, arch_flags = read_mpy_header(mpy)
    assert (version, arch, arch_flags) == (6, 11, 3)


def test_read_mpy_header_no_arch_flags_bit_reads_zero(tmp_path):
    mpy = tmp_path / "m.mpy"
    write_mpy(mpy, native_code=7)
    assert read_mpy_header(mpy) == (6, 7, 0)


def test_verify_output_accepts_matching_arch(tmp_path):
    mpy = tmp_path / "m.mpy"
    write_mpy(mpy, native_code=7)  # armv7emsp
    verify_output(build_options("armv7emsp"), mpy)  # must not raise


def test_verify_output_rejects_mismatched_arch(tmp_path):
    mpy = tmp_path / "m.mpy"
    write_mpy(mpy, native_code=2)  # x64, not armv7emsp
    with pytest.raises(BuildError, match="expected 7"):
        verify_output(build_options("armv7emsp"), mpy)


def test_verify_output_accepts_matching_arch_flags(tmp_path):
    mpy = tmp_path / "m.mpy"
    write_mpy(mpy, native_code=11, arch_flags=3)
    verify_output(build_options("rv32imc", arch_flags=3), mpy)  # must not raise


def test_verify_output_rejects_mismatched_arch_flags(tmp_path):
    mpy = tmp_path / "m.mpy"
    write_mpy(mpy, native_code=11, arch_flags=1)
    with pytest.raises(BuildError, match="arch_flags"):
        verify_output(build_options("rv32imc", arch_flags=3), mpy)


# -- output_name / build_target -----------------------------------------------


def test_output_name_is_unambiguous():
    mpy = Path("build/armv7emsp-eabi/mymodule.mpy")
    assert output_name(build_options(), mpy) == "mymodule-mpy6.3-natmod-armv7emsp.mpy"


def _stub_make(tmp_path, native_code=7, arch_flags=0):
    def fake_make(*a, **k):
        write_mpy(
            tmp_path / "natmod" / "build" / "armv7emsp-eabi" / "mymodule.mpy",
            native_code=native_code,
            arch_flags=arch_flags,
        )

    return fake_make


def test_build_target_writes_into_its_own_identifier_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(build, "run_make", _stub_make(tmp_path))

    opts = build_options()
    result = build_target(
        opts, HOST_CHAIN, tmp_path / "mpy", tmp_path / "natmod", tmp_path / "out"
    )
    assert isinstance(result, BuildResult)
    expected = (
        tmp_path
        / "out"
        / "mpy6.3-natmod-armv7emsp"
        / "mymodule-mpy6.3-natmod-armv7emsp.mpy"
    )
    assert result.output == expected
    assert result.output.exists()
    assert result.size > 0


def test_build_target_skips_package_json_without_a_version(tmp_path, monkeypatch):
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(build, "run_make", _stub_make(tmp_path))

    result = build_target(
        build_options(),
        HOST_CHAIN,
        tmp_path / "mpy",
        tmp_path / "natmod",
        tmp_path / "out",
    )
    assert not (result.output.parent / "package.json").exists()


def test_build_target_writes_package_json_with_a_version(tmp_path, monkeypatch):
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(build, "run_make", _stub_make(tmp_path))

    result = build_target(
        build_options(),
        HOST_CHAIN,
        tmp_path / "mpy",
        tmp_path / "natmod",
        tmp_path / "out",
        version="0.3.0",
    )
    manifest_path = result.output.parent / "package.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["version"] == "0.3.0"
    # target_path ("mymodule.mpy", what `import mymodule` needs on-device)
    # is deliberately not the same as url (the qualified, collision-safe
    # filename this package.json sits next to).
    assert manifest["urls"] == [["mymodule.mpy", result.output.name]]


def test_build_target_copies_extra_files_and_lists_them(tmp_path, monkeypatch):
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(build, "run_make", _stub_make(tmp_path))

    facade = tmp_path / "src" / "facade.py"
    facade.parent.mkdir(parents=True, exist_ok=True)
    facade.write_text("# facade\n")

    result = build_target(
        build_options(),
        HOST_CHAIN,
        tmp_path / "mpy",
        tmp_path / "natmod",
        tmp_path / "out",
        extra_files=[facade],
        version="0.3.0",
    )
    assert (result.output.parent / "facade.py").read_text() == "# facade\n"
    manifest = json.loads((result.output.parent / "package.json").read_text())
    assert ["facade.py", "facade.py"] in manifest["urls"]


def test_build_target_missing_extra_file_is_a_build_error(tmp_path, monkeypatch):
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(build, "run_make", _stub_make(tmp_path))

    with pytest.raises(BuildError, match="extra-files entry not found"):
        build_target(
            build_options(),
            HOST_CHAIN,
            tmp_path / "mpy",
            tmp_path / "natmod",
            tmp_path / "out",
            extra_files=[tmp_path / "nope.py"],
            version="0.3.0",
        )

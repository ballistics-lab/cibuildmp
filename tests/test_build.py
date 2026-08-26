import json
from pathlib import Path

import pytest

from cibuildmp import dockerrun
from cibuildmp.platforms.natmod import build
from cibuildmp.platforms.natmod.build import (
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
from cibuildmp.platforms.natmod.options import BuildOptions
from cibuildmp.platforms.natmod.targets import Target


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
        (tmp_path / "natmod").as_posix(),
        "ARCH=armv7emsp",
        f"MPY_DIR={(tmp_path / 'mpy').as_posix()}",
        # `python3`, not sys.executable: D12's mechanism for reaching
        # pyelftools named a path inside cibuildmp's own virtualenv, and
        # that path does not exist inside the image the build now runs in
        # (record 0049). The image carries pyelftools instead.
        "PYTHON=python3",
        "MP_BCLIBC_PRECISION=single",
        "dist",
    ]


# -- run_pre_build_command / run_make ----------------------------------------
#
# Both go through a container now (record 0049), so these patch
# `dockerrun.run` rather than `subprocess` -- the same shape the usermod
# build tests already had.


def _capture_docker(monkeypatch):
    calls = []
    monkeypatch.setattr(build, "_natmod_image", lambda: "natmod:test")
    monkeypatch.setattr(
        dockerrun, "run", lambda command, **kw: calls.append((command, kw))
    )
    return calls


def test_pre_build_command_noop_when_empty(tmp_path, monkeypatch):
    calls = _capture_docker(monkeypatch)
    run_pre_build_command(tmp_path, "", tmp_path / "mpy", tmp_path)
    assert calls == []  # no container started at all


def test_pre_build_command_runs_in_the_same_image_as_the_build(tmp_path, monkeypatch):
    # It moved into the container with the compile it precedes: a7p's own
    # `make fetch-nanopb` is a build step, and running it against a
    # different set of tools than the compile that follows is the kind of
    # difference that surfaces as a link error several steps later.
    calls = _capture_docker(monkeypatch)
    run_pre_build_command(tmp_path, "make fetch-nanopb", tmp_path / "mpy", tmp_path)

    command, kwargs = calls[0]
    assert command == ["bash", "-c", "make fetch-nanopb"]
    assert kwargs["workdir"] == tmp_path.resolve()
    assert kwargs["image"] == "natmod:test"


def test_pre_build_command_failure_is_a_build_error(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "_natmod_image", lambda: "natmod:test")
    monkeypatch.setattr(
        dockerrun, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    with pytest.raises(BuildError, match="pre-build-command"):
        run_pre_build_command(tmp_path, "exit 1", tmp_path / "mpy", tmp_path)


def test_run_make_failure_names_the_target(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "_natmod_image", lambda: "natmod:test")
    monkeypatch.setattr(
        dockerrun,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("exit code 2")),
    )
    with pytest.raises(BuildError, match="exit code 2"):
        run_make(build_options(), tmp_path / "mpy", tmp_path, tmp_path)


def test_run_make_mounts_the_package_root_not_the_module_dir(tmp_path, monkeypatch):
    # A project's Makefile is entitled to reach outside `natmod/` -- the
    # documented layout has `natmod/`, `usermod/` and `src/` as siblings,
    # and the template compiles `../src/template_core.c`. Mounting only
    # the module directory made that file not exist, reported three
    # layers down as "No rule to make target '../src/template_core.c'".
    calls = _capture_docker(monkeypatch)
    package_dir = tmp_path / "project"
    module_root = package_dir / "natmod"
    module_root.mkdir(parents=True)
    run_make(build_options(), tmp_path / "mpy", module_root, package_dir)

    _command, kwargs = calls[0]
    assert package_dir.resolve() in kwargs["mounts"]
    assert kwargs["workdir"] == module_root.resolve()


def test_run_make_resolves_relative_paths(tmp_path, monkeypatch):
    # Docker refuses a relative `-w` and cannot bind-mount a relative
    # source, and `module_root` is routinely relative on the host: it is
    # `package_dir / module_dir` and `package_dir` defaults to ".". The
    # bare-host `subprocess.run` this replaced never cared.
    calls = _capture_docker(monkeypatch)
    run_make(build_options(), Path("mpy"), Path("natmod"), Path("."))

    _command, kwargs = calls[0]
    assert all(m.is_absolute() for m in kwargs["mounts"])
    assert kwargs["workdir"].is_absolute()


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
    monkeypatch.setattr(build, "run_make", _stub_make(tmp_path))

    opts = build_options()
    result = build_target(
        opts,
        tmp_path / "mpy",
        tmp_path / "natmod",
        tmp_path / "out",
        package_dir=tmp_path,
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
    monkeypatch.setattr(build, "run_make", _stub_make(tmp_path))

    result = build_target(
        build_options(),
        tmp_path / "mpy",
        tmp_path / "natmod",
        tmp_path / "out",
        package_dir=tmp_path,
    )
    assert not (result.output.parent / "package.json").exists()


def test_build_target_writes_package_json_with_a_version(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "run_make", _stub_make(tmp_path))

    result = build_target(
        build_options(),
        tmp_path / "mpy",
        tmp_path / "natmod",
        tmp_path / "out",
        package_dir=tmp_path,
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
    monkeypatch.setattr(build, "run_make", _stub_make(tmp_path))

    facade = tmp_path / "src" / "facade.py"
    facade.parent.mkdir(parents=True, exist_ok=True)
    facade.write_text("# facade\n")

    result = build_target(
        build_options(),
        tmp_path / "mpy",
        tmp_path / "natmod",
        tmp_path / "out",
        package_dir=tmp_path,
        extra_files=[facade],
        version="0.3.0",
    )
    assert (result.output.parent / "facade.py").read_text() == "# facade\n"
    manifest = json.loads((result.output.parent / "package.json").read_text())
    assert ["facade.py", "facade.py"] in manifest["urls"]


def test_build_target_missing_extra_file_is_a_build_error(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "run_make", _stub_make(tmp_path))

    with pytest.raises(BuildError, match="extra-files entry not found"):
        build_target(
            build_options(),
            tmp_path / "mpy",
            tmp_path / "natmod",
            tmp_path / "out",
            package_dir=tmp_path,
            extra_files=[tmp_path / "nope.py"],
            version="0.3.0",
        )

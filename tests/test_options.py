from pathlib import Path

import pytest

from cibuildmp.platforms.natmod.options import ConfigError, Options
from cibuildmp.platforms.natmod.targets import newest_known_abi

# There is no `archs` config key any more (record 0052's own live-caught
# correction: it duplicated exactly what a `build`/`skip` glob over the
# identifier already expresses). Every fixture below that used to narrow
# to a specific arch or set of arches via `archs = [...]` now does it via
# `build`, prefixed with the current default ABI so a config that doesn't
# care about spanning more than one ABI still resolves deterministically.
ABI = newest_known_abi()


def build_for(*archs: str) -> str:
    # rv32imc may carry a +0x{flags} suffix (D15) -- a plain literal
    # suffix match would miss it, so it alone gets a trailing wildcard;
    # safe against every other arch name (none is its own prefix).
    parts = [f"{a}*" if a == "rv32imc" else a for a in archs]
    if len(parts) == 1:
        return f'build = "mpy{ABI}-*-{parts[0]}"\n'
    return f'build = "mpy{ABI}-*-{{{",".join(parts)}}}"\n'


def write(tmp_path: Path, text: str, name: str = "cibuildmp.toml") -> Path:
    (tmp_path / name).write_text(text)
    return tmp_path


def test_defaults_with_no_config_at_all(tmp_path):
    options = Options.load(tmp_path, env={})
    assert options.config_path is None
    # No micropython/mpy-abi config key any more (record 0052, A2): the
    # version axis is a static domain, and an unconfigured build selector
    # narrows it to the newest known ABI by itself -- derived, not
    # restated, so a test about *defaulting* does not fail every time
    # upstream ships a release. All ten arches are real for that ABI's
    # own newest tag (verified live, not assumed), so a bare config still
    # produces exactly ten targets, same as before A2.
    assert options.build == [f"mpy{newest_known_abi()}-*"]
    assert len(options.targets()) == 10
    assert {t.abi for t in options.targets()} == {newest_known_abi()}
    build_options = options.build_options(options.targets()[0], env={})
    assert build_options.module_dir == "natmod"
    assert build_options.make_target == "dist"


def test_overrides_beat_natmod_table(tmp_path):
    write(
        tmp_path,
        build_for("x64", "armv7emsp")
        + """
        extra-make-args = ["COMMON=1"]

        [override."*-armv7emsp"]
        extra-make-args = ["MP_BCLIBC_PRECISION=single"]
        """,
    )
    options = Options.load(tmp_path, env={})
    resolved = {
        t.arch: options.build_options(t, env={}).extra_make_args
        for t in options.targets()
    }
    assert resolved["x64"] == ["COMMON=1"]
    assert resolved["armv7emsp"] == ["MP_BCLIBC_PRECISION=single"]


def test_a_select_key_inside_an_override_body_is_an_error(tmp_path):
    # The glob is the table's own name now (`[override."glob"]`) -- a
    # `select` key inside the body would only duplicate it, so it is
    # rejected at load time rather than silently shadowing the name.
    write(tmp_path, '[override."*"]\nselect = "*"\nextra-make-args = ["X=1"]\n')
    with pytest.raises(ConfigError, match="select"):
        Options.load(tmp_path, env={})


def test_environment_beats_file(tmp_path):
    # record 0052, A2: micropython/mpy-abi are gone as config keys, so
    # this now exercises skip -- CIBMP_SKIP still beats the file's own
    # skip = "" the same way CIBMP_MICROPYTHON used to beat a file tag.
    write(tmp_path, 'skip = ""\n' + build_for("x64", "x86"))
    options = Options.load(tmp_path, env={"CIBMP_SKIP": "*-x86"})
    assert [t.arch for t in options.targets()] == ["x64"]


def test_environment_beats_override(tmp_path):
    write(
        tmp_path,
        build_for("armv7emsp")
        + """
        [override."*"]
        extra-make-args = ["FROM=override"]
        """,
    )
    options = Options.load(tmp_path, env={})
    target = options.targets()[0]
    env = {"CIBMP_EXTRA_MAKE_ARGS": "FROM=env A=1"}
    assert options.build_options(target, env=env).extra_make_args == ["FROM=env", "A=1"]


def test_pyproject_fallback(tmp_path):
    write(
        tmp_path,
        "[tool.cibuildmp]\n" + build_for("x64"),
        name="pyproject.toml",
    )
    options = Options.load(tmp_path, env={})
    assert (
        options.config_path is not None and options.config_path.name == "pyproject.toml"
    )
    assert [t.arch for t in options.targets()] == ["x64"]


def test_standalone_wins_over_pyproject(tmp_path):
    write(tmp_path, build_for("x64"))
    write(
        tmp_path,
        "[tool.cibuildmp]\n" + build_for("armv6m"),
        name="pyproject.toml",
    )
    options = Options.load(tmp_path, env={})
    assert options.config_path.name == "cibuildmp.toml"
    assert [t.arch for t in options.targets()] == ["x64"]


def test_arch_flags_land_on_rv32imc_identifier_and_make_args(tmp_path):
    write(
        tmp_path,
        build_for("rv32imc", "rv64imc")
        + """
        arch-flags = "zba,zcmp"
        """,
    )
    options = Options.load(tmp_path, env={})
    targets = {t.arch: t for t in options.targets()}
    assert targets["rv32imc"].identifier == "mpy6.3-v1.30.0-preview-rv32imc+0x3"
    assert (
        targets["rv64imc"].identifier == "mpy6.3-v1.30.0-preview-rv64imc"
    )  # unaffected

    rv32_args = options.build_options(targets["rv32imc"], env={}).extra_make_args
    assert "ARCH_FLAGS=0x3" in rv32_args
    rv64_args = options.build_options(targets["rv64imc"], env={}).extra_make_args
    assert not any(a.startswith("ARCH_FLAGS=") for a in rv64_args)


def test_arch_flags_list_builds_one_rv32imc_target_per_variant(tmp_path):
    write(
        tmp_path,
        build_for("rv32imc")
        + """
        arch-flags = ["", "zba", "zba,zcmp"]
        """,
    )
    options = Options.load(tmp_path, env={})
    identifiers = [t.identifier for t in options.targets()]
    assert identifiers == [
        "mpy6.3-v1.30.0-preview-rv32imc",
        "mpy6.3-v1.30.0-preview-rv32imc+0x1",
        "mpy6.3-v1.30.0-preview-rv32imc+0x3",
    ]
    make_args_by_id = {
        t.identifier: options.build_options(t, env={}).extra_make_args
        for t in options.targets()
    }
    assert not any(
        a.startswith("ARCH_FLAGS=")
        for a in make_args_by_id["mpy6.3-v1.30.0-preview-rv32imc"]
    )
    assert "ARCH_FLAGS=0x1" in make_args_by_id["mpy6.3-v1.30.0-preview-rv32imc+0x1"]
    assert "ARCH_FLAGS=0x3" in make_args_by_id["mpy6.3-v1.30.0-preview-rv32imc+0x3"]


def test_arch_flags_list_dedupes_two_spellings_of_the_same_value(tmp_path):
    # "0x3" and "zba,zcmp" both resolve to 3 -- before the dedup fix this
    # silently produced two targets sharing one identifier (the second
    # build's output overwriting the first's), the same collision class
    # D13 exists to prevent for tags.
    write(
        tmp_path,
        build_for("rv32imc")
        + """
        arch-flags = ["0x3", "zba,zcmp"]
        """,
    )
    options = Options.load(tmp_path, env={})
    identifiers = [t.identifier for t in options.targets()]
    assert identifiers == ["mpy6.3-v1.30.0-preview-rv32imc+0x3"]


def test_version_defaults_empty_and_is_settable(tmp_path):
    write(tmp_path, "")
    assert Options.load(tmp_path, env={}).version == ""
    versioned = Options.load(tmp_path, env={"CIBMP_VERSION": "0.3.0"})
    assert versioned.version == "0.3.0"


def test_name_defaults_empty_and_is_settable(tmp_path):
    # record 0052, A3: `name`, alongside `version`, feeds output_name()'s
    # {name}-{version}- filename prefix.
    write(tmp_path, "")
    assert Options.load(tmp_path, env={}).name == ""
    named = Options.load(tmp_path, env={"CIBMP_NAME": "mylib"})
    assert named.name == "mylib"


def test_extra_files_from_publish_table(tmp_path):
    write(
        tmp_path,
        """
        [publish]
        extra-files = ["src/facade.py", "src/ffi.py"]
        """,
    )
    options = Options.load(tmp_path, env={})
    assert options.extra_files() == ["src/facade.py", "src/ffi.py"]


def test_a_top_level_key_inside_the_natmod_table_names_where_it_goes(tmp_path):
    # `version` is truly top-level-only, same as every other generic key
    # -- "unknown key" would be a lie here, the tool knows precisely what
    # `version` means, just not in this table.
    write(tmp_path, 'version = "0.1.0"\n[natmod]\nname = "x"\nversion = "0.2.0"\n')

    with pytest.raises(ConfigError, match="read from the top level"):
        Options.load(tmp_path)


def test_build_skip_inside_the_natmod_table_is_an_error(tmp_path):
    # record 0052's own live-caught correction, retracting the earlier
    # "per-platform build/skip" addendum this test used to cover:
    # [natmod] build/skip was always exactly a sufficiently-scoped
    # top-level pattern restated, so it is a loud, specific "move it to
    # the top level" error now, the same as any other generic key.
    write(tmp_path, 'skip = "*-armv6m"\n[natmod]\nskip = ""\n')

    with pytest.raises(ConfigError, match="read from the top level"):
        Options.load(tmp_path, env={})


def test_an_unknown_key_in_the_natmod_table_is_an_error(tmp_path):
    write(tmp_path, '[natmod]\nmodule-dr = "natmod"\n')

    with pytest.raises(ConfigError, match="unknown key `module-dr`"):
        Options.load(tmp_path)


def test_archs_is_gone_as_a_config_key(tmp_path):
    # record 0052's own live-caught correction: archs filtered candidate
    # rows by .arch alone, before build/skip ever ran -- exactly what a
    # build/skip glob over the identifier already expresses directly
    # (e.g. build = "*-x64"), so it is removed rather than kept dual-read.
    write(tmp_path, '[natmod]\narchs = ["x64"]\n')

    with pytest.raises(ConfigError, match="unknown key `archs`"):
        Options.load(tmp_path)


def test_arch_flags_in_an_overrides_table_is_an_error(tmp_path):
    # `arch-flags` is resolved by the global opt() against the top level
    # and `[natmod]`, never per target, so an override carrying one was
    # ignored outright -- the same shape as the `skip` trap.
    write(
        tmp_path,
        """
        [override."*"]
        arch-flags = "rv32imc"
        """,
    )

    with pytest.raises(ConfigError, match=r'\[override\."\*"\]: unknown key'):
        Options.load(tmp_path)


def test_reachability_audit_rejects_an_override_select_that_can_never_match(tmp_path):
    # record 0052, A5: "*-aarch64" can never match any identifier at all
    # (dynruntime.mk has no such arch, in any ABI) -- caught before a real
    # build ever starts, the same way a misplaced key already is (0048),
    # one level down at the selector-string level.
    write(
        tmp_path,
        """
        [override."*-aarch64"]
        extra-make-args = ["X=1"]
        """,
    )
    with pytest.raises(
        ConfigError, match=r'\[override\."\*-aarch64"\]: \'\*-aarch64\''
    ):
        Options.load(tmp_path).targets()


def test_reachability_audit_allows_a_deliberate_skip_everything(tmp_path):
    # The distinction this audit exists to preserve: skip = "*" narrows a
    # real, reachable domain down to zero *selected* targets, which stays
    # entirely legitimate -- only a pattern that can never match anything
    # in the first place is an error.
    write(tmp_path, 'skip = "*"\n')
    assert Options.load(tmp_path).targets() == []

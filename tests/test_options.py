from pathlib import Path

import pytest

from cibuildmp.platforms.natmod.options import DEFAULT_MICROPYTHON, ConfigError, Options


def write(tmp_path: Path, text: str, name: str = "cibuildmp.toml") -> Path:
    (tmp_path / name).write_text(text)
    return tmp_path


def test_defaults_with_no_config_at_all(tmp_path):
    options = Options.load(tmp_path, env={})
    assert options.config_path is None
    # Derived, not restated: which release is newest changes on
    # upstream's schedule, and a test about *defaulting* should not fail
    # every time it does. `test_targets.py` owns the pin itself.
    assert options.micropython == [DEFAULT_MICROPYTHON]
    assert len(options.targets()) == 10
    build_options = options.build_options(options.targets()[0], env={})
    assert build_options.module_dir == "natmod"
    assert build_options.make_target == "dist"


def test_overrides_beat_natmod_table(tmp_path):
    write(
        tmp_path,
        """
        micropython = "v1.28.0"
        [natmod]
        archs = ["x64", "armv7emsp"]
        extra-make-args = ["COMMON=1"]
        [[overrides]]
        select = "*-armv7emsp"
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


def test_override_without_select_is_an_error(tmp_path):
    write(tmp_path, '[[overrides]]\nextra-make-args = ["X=1"]\n')
    options = Options.load(tmp_path, env={})
    with pytest.raises(ConfigError, match="select"):
        options.build_options(options.targets()[0], env={})


def test_environment_beats_file(tmp_path):
    write(
        tmp_path,
        'micropython = "v1.22.0"\nskip = ""\n[natmod]\narchs = ["x64", "x86"]\n',
    )
    options = Options.load(
        tmp_path, env={"CIBMP_SKIP": "*-x86", "CIBMP_MICROPYTHON": "v1.28.0"}
    )
    # not 6.2, which the file's tag would give
    assert options.tag_groups() == [("v1.28.0", "6.3")]
    assert [t.arch for t in options.targets()] == ["x64"]


def test_environment_beats_override(tmp_path):
    write(
        tmp_path,
        """
        [natmod]
        archs = ["armv7emsp"]
        [[overrides]]
        select = "*"
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
        '[tool.cibuildmp]\nmicropython = "v1.22.0"\n[tool.cibuildmp.natmod]\narchs = ["x64"]\n',
        name="pyproject.toml",
    )
    options = Options.load(tmp_path, env={})
    assert (
        options.config_path is not None and options.config_path.name == "pyproject.toml"
    )
    assert options.tag_groups() == [("v1.22.0", "6.2")]
    assert [t.arch for t in options.targets()] == ["x64"]


def test_standalone_wins_over_pyproject(tmp_path):
    write(tmp_path, 'micropython = "v1.28.0"\n')
    write(
        tmp_path, '[tool.cibuildmp]\nmicropython = "v1.21.0"\n', name="pyproject.toml"
    )
    options = Options.load(tmp_path, env={})
    assert options.config_path.name == "cibuildmp.toml"
    assert options.tag_groups() == [("v1.28.0", "6.3")]


def test_micropython_list_spans_two_abi_groups(tmp_path):
    write(
        tmp_path,
        """
        micropython = ["v1.22.0", "v1.28.0"]
        [natmod]
        archs = ["x64"]
        """,
    )
    options = Options.load(tmp_path, env={})
    assert options.tag_groups() == [("v1.22.0", "6.2"), ("v1.28.0", "6.3")]
    targets = options.targets()
    assert [(t.tag, t.abi, t.identifier) for t in targets] == [
        ("v1.22.0", "6.2", "mpy6.2-natmod-x64"),
        ("v1.28.0", "6.3", "mpy6.3-natmod-x64"),
    ]


def test_micropython_list_dedups_redundant_abi(tmp_path):
    write(
        tmp_path,
        """
        micropython = ["v1.23.0", "v1.28.0"]
        [natmod]
        archs = ["x64"]
        """,
    )
    options = Options.load(tmp_path, env={})
    # Both are ABI 6.3 -- one build, not two, and it is built against
    # whichever tag was listed first.
    assert options.tag_groups() == [("v1.23.0", "6.3")]
    assert [t.tag for t in options.targets()] == ["v1.23.0"]


def test_micropython_env_accepts_space_separated_list(tmp_path):
    write(tmp_path, '[natmod]\narchs = ["x64"]\n')
    options = Options.load(tmp_path, env={"CIBMP_MICROPYTHON": "v1.22.0 v1.28.0"})
    assert options.micropython == ["v1.22.0", "v1.28.0"]
    assert options.tag_groups() == [("v1.22.0", "6.2"), ("v1.28.0", "6.3")]


def test_mpy_abi_string_is_still_an_override(tmp_path):
    # Unchanged from before 0051: a bare string forces every listed tag
    # to resolve to that one ABI, regardless of what MPY_ABI says.
    write(
        tmp_path,
        """
        micropython = ["v1.22.0", "v1.28.0"]
        mpy-abi = "7.0"
        [natmod]
        archs = ["x64"]
        """,
    )
    options = Options.load(tmp_path, env={})
    assert options.mpy_abi == "7.0"
    assert options.tag_groups() == [("v1.22.0", "7.0")]


def test_mpy_abi_list_states_the_axis_directly(tmp_path):
    # The new path (0051): mpy-abi as a list is the axis itself, resolved
    # backwards to each ABI's own newest known tag -- micropython is not
    # consulted at all.
    write(
        tmp_path,
        """
        micropython = "v1.21.0"
        mpy-abi = ["6.3", "6.2"]
        [natmod]
        archs = ["x64"]
        """,
    )
    options = Options.load(tmp_path, env={})
    assert options.mpy_abi == ["6.3", "6.2"]
    assert options.tag_groups() == [("v1.29.0", "6.3"), ("v1.23.0-preview", "6.2")]
    identifiers = [t.identifier for t in options.targets()]
    assert identifiers == ["mpy6.3-natmod-x64", "mpy6.2-natmod-x64"]


def test_mpy_abi_env_multi_token_is_axis_single_token_is_override(tmp_path):
    write(tmp_path, '[natmod]\narchs = ["x64"]\n')
    axis = Options.load(tmp_path, env={"CIBMP_MPY_ABI": "6.3 6.2"})
    assert axis.mpy_abi == ["6.3", "6.2"]
    override = Options.load(
        tmp_path, env={"CIBMP_MICROPYTHON": "v1.22.0", "CIBMP_MPY_ABI": "7.0"}
    )
    assert override.mpy_abi == "7.0"
    assert override.tag_groups() == [("v1.22.0", "7.0")]


def test_arch_flags_land_on_rv32imc_identifier_and_make_args(tmp_path):
    write(
        tmp_path,
        """
        [natmod]
        archs = ["rv32imc", "rv64imc"]
        arch-flags = "zba,zcmp"
        """,
    )
    options = Options.load(tmp_path, env={})
    targets = {t.arch: t for t in options.targets()}
    assert targets["rv32imc"].identifier == "mpy6.3-natmod-rv32imc+0x3"
    assert targets["rv64imc"].identifier == "mpy6.3-natmod-rv64imc"  # unaffected

    rv32_args = options.build_options(targets["rv32imc"], env={}).extra_make_args
    assert "ARCH_FLAGS=0x3" in rv32_args
    rv64_args = options.build_options(targets["rv64imc"], env={}).extra_make_args
    assert not any(a.startswith("ARCH_FLAGS=") for a in rv64_args)


def test_arch_flags_list_builds_one_rv32imc_target_per_variant(tmp_path):
    write(
        tmp_path,
        """
        [natmod]
        archs = ["rv32imc"]
        arch-flags = ["", "zba", "zba,zcmp"]
        """,
    )
    options = Options.load(tmp_path, env={})
    identifiers = [t.identifier for t in options.targets()]
    assert identifiers == [
        "mpy6.3-natmod-rv32imc",
        "mpy6.3-natmod-rv32imc+0x1",
        "mpy6.3-natmod-rv32imc+0x3",
    ]
    make_args_by_id = {
        t.identifier: options.build_options(t, env={}).extra_make_args
        for t in options.targets()
    }
    assert not any(
        a.startswith("ARCH_FLAGS=") for a in make_args_by_id["mpy6.3-natmod-rv32imc"]
    )
    assert "ARCH_FLAGS=0x1" in make_args_by_id["mpy6.3-natmod-rv32imc+0x1"]
    assert "ARCH_FLAGS=0x3" in make_args_by_id["mpy6.3-natmod-rv32imc+0x3"]


def test_arch_flags_list_dedupes_two_spellings_of_the_same_value(tmp_path):
    # "0x3" and "zba,zcmp" both resolve to 3 -- before the dedup fix this
    # silently produced two targets sharing one identifier (the second
    # build's output overwriting the first's), the same collision class
    # D13 exists to prevent for tags.
    write(
        tmp_path,
        """
        [natmod]
        archs = ["rv32imc"]
        arch-flags = ["0x3", "zba,zcmp"]
        """,
    )
    options = Options.load(tmp_path, env={})
    identifiers = [t.identifier for t in options.targets()]
    assert identifiers == ["mpy6.3-natmod-rv32imc+0x3"]


def test_version_defaults_empty_and_is_settable(tmp_path):
    write(tmp_path, '[natmod]\narchs = ["x64"]\n')
    assert Options.load(tmp_path, env={}).version == ""
    versioned = Options.load(tmp_path, env={"CIBMP_VERSION": "0.3.0"})
    assert versioned.version == "0.3.0"


def test_extra_files_from_publish_table(tmp_path):
    write(
        tmp_path,
        """
        [natmod]
        archs = ["x64"]
        [publish]
        extra-files = ["src/facade.py", "src/ffi.py"]
        """,
    )
    options = Options.load(tmp_path, env={})
    assert options.extra_files() == ["src/facade.py", "src/ffi.py"]


def test_a_top_level_key_inside_the_natmod_table_names_where_it_goes(tmp_path):
    # The exact trap that cost `test_only_overrides_skip` its meaning:
    # `skip` under `[natmod]` was read by nothing, and `archs` right next
    # to it is dual-read and works, so there was every reason to expect
    # this to work too. "unknown key" would be a lie here -- the tool
    # knows precisely what `skip` means, just not in this table.
    write(tmp_path, 'micropython = "v1.28.0"\n[natmod]\nskip = "*-armv6m"\n')

    with pytest.raises(ConfigError, match="read from the top level"):
        Options.load(tmp_path)


def test_an_unknown_key_in_the_natmod_table_is_an_error(tmp_path):
    write(tmp_path, '[natmod]\nmodule-dr = "natmod"\n')

    with pytest.raises(ConfigError, match="unknown key `module-dr`"):
        Options.load(tmp_path)


def test_archs_stays_dual_read_and_is_not_flagged(tmp_path):
    # Predates 0048 and is not the trap: both placements work, so neither
    # is silent. Asserted so the new check does not quietly take it away.
    write(tmp_path, '[natmod]\narchs = ["x64"]\n')

    assert Options.load(tmp_path).archs == ["x64"]


def test_arch_flags_in_an_overrides_table_is_an_error(tmp_path):
    # `arch-flags` is resolved by the global opt() against the top level
    # and `[natmod]`, never per target, so an override carrying one was
    # ignored outright -- the same shape as the `skip` trap.
    write(
        tmp_path,
        """
        micropython = "v1.28.0"
        [natmod]
        archs = ["x64"]
        [[overrides]]
        select = "*"
        arch-flags = "rv32imc"
        """,
    )

    with pytest.raises(ConfigError, match=r"\[\[overrides\]\]: unknown key"):
        Options.load(tmp_path)

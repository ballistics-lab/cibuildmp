from pathlib import Path

import pytest

from cibuildmp.platforms.usermod.options import UsermodConfigError, UsermodOptions
from cibuildmp.platforms.usermod.targets import KNOWN_PORTS

BUILD_UNIX_V129 = 'build = "v1.29.0-*manylinux* v1.29.0-*musllinux*"'


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "cibuildmp.toml"
    path.write_text(text)
    return path


def test_every_known_port_is_always_in_scope(tmp_path):
    # There is no more [unix]/[esp32]/etc. table, and no more `ports =
    # [...]` list -- every port is always in scope; build/skip is the
    # only thing that narrows which of it actually gets selected.
    write_config(tmp_path, "")
    options = UsermodOptions.load(tmp_path)

    assert options.ports == list(KNOWN_PORTS)


def test_zero_config_selects_nothing(tmp_path):
    write_config(tmp_path, "")
    assert UsermodOptions.load(tmp_path).targets() == []


def test_build_glob_selects_the_real_unix_v1_29_0_cells(tmp_path):
    write_config(tmp_path, BUILD_UNIX_V129)
    options = UsermodOptions.load(tmp_path)

    identifiers = [t.identifier for t in options.targets()]
    assert identifiers == [
        "v1.29.0-manylinux_2_28_x86_64",
        "v1.29.0-musllinux_1_2_x86_64",
        "v1.29.0-manylinux_2_28_i686",
        "v1.29.0-musllinux_1_2_i686",
        "v1.29.0-manylinux_2_28_aarch64",
        "v1.29.0-musllinux_1_2_aarch64",
        "v1.29.0-manylinux_2_28_ppc64le",
        "v1.29.0-musllinux_1_2_ppc64le",
        "v1.29.0-manylinux_2_28_s390x",
        "v1.29.0-musllinux_1_2_s390x",
        "v1.29.0-manylinux_2_31_armv7l",
        "v1.29.0-musllinux_1_2_armv7l",
        "v1.29.0-manylinux_2_39_riscv64",
        "v1.29.0-musllinux_1_2_riscv64",
        "v1.29.0-manylinux_2_41_mipsel",
    ]


def test_build_glob_selects_a_single_cell(tmp_path):
    write_config(tmp_path, 'build = "v1.29.0-manylinux_2_28_aarch64"\n')
    options = UsermodOptions.load(tmp_path)

    assert [t.identifier for t in options.targets()] == [
        "v1.29.0-manylinux_2_28_aarch64"
    ]


def test_build_glob_selects_multiple_esp32_boards(tmp_path):
    write_config(
        tmp_path,
        'build = "v1.29.0-esp32-ESP32_GENERIC v1.29.0-esp32-ESP32_GENERIC_S3"\n',
    )
    options = UsermodOptions.load(tmp_path)

    assert [t.identifier for t in options.targets()] == [
        "v1.29.0-esp32-ESP32_GENERIC",
        "v1.29.0-esp32-ESP32_GENERIC_S3",
    ]


def test_build_glob_selects_qemu_riscv_boards(tmp_path):
    write_config(tmp_path, 'build = "v1.29.0-qemu-VIRT_RV32 v1.29.0-qemu-VIRT_RV64"\n')
    options = UsermodOptions.load(tmp_path)

    assert [t.identifier for t in options.targets()] == [
        "v1.29.0-qemu-VIRT_RV32",
        "v1.29.0-qemu-VIRT_RV64",
    ]


def test_unrecognised_board_is_simply_unreachable(tmp_path):
    # There is no separate board-validation step any more -- a typo'd
    # board name is just a glob that matches nothing real, caught by the
    # ordinary reachability audit (record 0052, A5), the same as any
    # other bad selector.
    write_config(tmp_path, 'build = "v1.29.0-esp32-NOT_A_REAL_BOARD"\n')
    with pytest.raises(UsermodConfigError, match="matches no known identifier"):
        UsermodOptions.load(tmp_path).targets()


def test_unix_and_windows_identifiers_carry_no_port_name(tmp_path):
    # The real, live-caught finding: resources/build-platforms.toml's own
    # identifier_format for unix/windows/webassembly carries no port name
    # at all ("{tag}-{arch}"), unlike qemu/esp32 ("{tag}-{port}-{board}").
    write_config(tmp_path, 'build = "v1.29.0-win32"\n')
    assert [t.identifier for t in UsermodOptions.load(tmp_path).targets()] == [
        "v1.29.0-win32"
    ]


def test_user_c_modules_and_manifest_default(tmp_path):
    # "." (the project root), not "usermod" -- record 0051's ninth
    # addendum.
    write_config(tmp_path, 'build = "v1.29.0-manylinux_2_28_x86_64"\n')
    options = UsermodOptions.load(tmp_path)
    build_options = options.build_options(options.targets()[0])

    assert build_options.user_c_modules == "."
    assert build_options.manifest == ""


def test_user_c_modules_and_manifest_overridable_globally(tmp_path):
    write_config(
        tmp_path,
        """
        user-c-modules = "mymod"
        manifest = "extra_manifest.py"
        build = "v1.29.0-manylinux_2_28_x86_64"
        """,
    )
    options = UsermodOptions.load(tmp_path)
    build_options = options.build_options(options.targets()[0])

    assert build_options.user_c_modules == "mymod"
    assert build_options.manifest == "extra_manifest.py"


def test_build_skip_selectors(tmp_path):
    write_config(
        tmp_path,
        """
        build = "v1.29.0-manylinux_2_28_x86_64 v1.29.0-manylinux_2_28_i686"
        skip = "v1.29.0-manylinux_2_28_i686"
        """,
    )
    options = UsermodOptions.load(tmp_path)

    assert [t.identifier for t in options.targets()] == [
        "v1.29.0-manylinux_2_28_x86_64"
    ]


def test_build_options_carries_user_c_modules_and_manifest(tmp_path):
    write_config(
        tmp_path,
        """
        user-c-modules = "mymod"
        manifest = "extra.py"
        build = "v1.29.0-manylinux_2_28_x86_64"
        """,
    )
    options = UsermodOptions.load(tmp_path)
    target = options.targets()[0]
    build_options = options.build_options(target)

    assert build_options.identifier == "v1.29.0-manylinux_2_28_x86_64"
    assert build_options.port == "unix"
    assert build_options.user_c_modules == "mymod"
    assert build_options.manifest == "extra.py"


def test_no_user_c_modules_defaults_to_false(tmp_path):
    write_config(tmp_path, 'build = "v1.29.0-manylinux_2_28_x86_64"\n')
    options = UsermodOptions.load(tmp_path)
    build_options = options.build_options(options.targets()[0])

    assert build_options.no_user_c_modules is False
    assert build_options.user_c_modules == "."


def test_no_user_c_modules_resolves_user_c_modules_to_empty(tmp_path):
    # Record 0056's Option A: the flag, not the empty string, is the
    # signal -- `user_c_modules` is folded to "" rather than left at
    # DEFAULT_USER_C_MODULES ("."), which is what lets every
    # `USER_C_MODULES=` command line stay unconditional and still no-op.
    write_config(
        tmp_path,
        """
        no-user-c-modules = true
        build = "v1.29.0-manylinux_2_28_x86_64"
        """,
    )
    options = UsermodOptions.load(tmp_path)
    build_options = options.build_options(options.targets()[0])

    assert build_options.no_user_c_modules is True
    assert build_options.user_c_modules == ""


def test_no_user_c_modules_and_user_c_modules_together_is_an_error(tmp_path):
    write_config(
        tmp_path,
        """
        no-user-c-modules = true
        user-c-modules = "mymod"
        build = "v1.29.0-manylinux_2_28_x86_64"
        """,
    )
    options = UsermodOptions.load(tmp_path)
    with pytest.raises(UsermodConfigError, match="mutually exclusive"):
        options.build_options(options.targets()[0])


def test_no_user_c_modules_true_alone_is_not_an_error(tmp_path):
    # The trap the record itself flags: `user-c-modules` always has a
    # *value* (it defaults to "."), so the mutual-exclusion check has to
    # test "explicitly set", not "is truthy" -- a naive version would
    # fire on every single use of the flag.
    write_config(
        tmp_path,
        """
        no-user-c-modules = true
        build = "v1.29.0-manylinux_2_28_x86_64"
        """,
    )
    options = UsermodOptions.load(tmp_path)
    options.build_options(options.targets()[0])  # must not raise


def test_no_user_c_modules_via_env_conflicts_with_file_user_c_modules(tmp_path):
    write_config(
        tmp_path,
        """
        user-c-modules = "mymod"
        build = "v1.29.0-manylinux_2_28_x86_64"
        """,
    )
    options = UsermodOptions.load(tmp_path)
    target = options.targets()[0]
    with pytest.raises(UsermodConfigError, match="mutually exclusive"):
        options.build_options(target, env={"CIBMP_NO_USER_C_MODULES": "true"})


def test_no_user_c_modules_via_env_var(tmp_path):
    write_config(tmp_path, 'build = "v1.29.0-manylinux_2_28_x86_64"\n')
    options = UsermodOptions.load(tmp_path)
    target = options.targets()[0]
    build_options = options.build_options(target, env={"CIBMP_NO_USER_C_MODULES": "1"})

    assert build_options.no_user_c_modules is True
    assert build_options.user_c_modules == ""


def test_no_user_c_modules_rejects_a_non_boolean_value(tmp_path):
    write_config(
        tmp_path,
        """
        no-user-c-modules = "sure"
        build = "v1.29.0-manylinux_2_28_x86_64"
        """,
    )
    options = UsermodOptions.load(tmp_path)
    with pytest.raises(UsermodConfigError, match="no-user-c-modules"):
        options.build_options(options.targets()[0])


def test_extra_make_args_shared_across_targets(tmp_path):
    write_config(
        tmp_path,
        """
        extra-make-args = ["DEBUG=1"]
        build = "v1.29.0-manylinux_2_28_x86_64"
        """,
    )
    options = UsermodOptions.load(tmp_path)
    build_options = options.build_options(options.targets()[0])

    assert build_options.extra_make_args == ["DEBUG=1"]


def test_extra_cmake_args_defaults_to_empty(tmp_path):
    write_config(tmp_path, 'build = "v1.29.0-manylinux_2_28_x86_64"\n')
    options = UsermodOptions.load(tmp_path)
    build_options = options.build_options(options.targets()[0])

    assert build_options.extra_cmake_args == []


def test_extra_cmake_args_shared_across_targets(tmp_path):
    # Meaningless to unix (a Make port with no CMake in the loop at all),
    # but resolves the same way extra-make-args does regardless of which
    # port ends up reading it -- only rp2/esp32's own build_<port>()
    # functions actually consume it.
    write_config(
        tmp_path,
        """
        extra-cmake-args = ["-DMICROPY_C_HEAP_SIZE=131072"]
        build = "v1.29.0-rp2-RPI_PICO"
        """,
    )
    options = UsermodOptions.load(tmp_path)
    build_options = options.build_options(options.targets()[0])

    assert build_options.extra_cmake_args == ["-DMICROPY_C_HEAP_SIZE=131072"]


def test_extra_cmake_args_via_override(tmp_path):
    write_config(
        tmp_path,
        """
        build = "v1.29.0-rp2-RPI_PICO v1.29.0-esp32-ESP32_GENERIC"

        [override."*-rp2-*"]
        extra-cmake-args = ["-DMICROPY_C_HEAP_SIZE=131072"]
        """,
    )
    options = UsermodOptions.load(tmp_path)
    by_identifier = {
        t.identifier: options.build_options(t).extra_cmake_args
        for t in options.targets()
    }

    assert by_identifier["v1.29.0-rp2-RPI_PICO"] == ["-DMICROPY_C_HEAP_SIZE=131072"]
    assert by_identifier["v1.29.0-esp32-ESP32_GENERIC"] == []


def test_per_port_build_skip_env_override(tmp_path, monkeypatch):
    # CIBMP_SKIP_UNIX -- the per-platform env var every dual-read key
    # already gets for free from the cascade, a real capability distinct
    # from any TOML placement.
    write_config(tmp_path, 'build = "v1.29.0-manylinux_2_28_x86_64 v1.29.0-wasm32"\n')
    monkeypatch.setenv("CIBMP_SKIP_UNIX", "*")

    identifiers = [t.identifier for t in UsermodOptions.load(tmp_path).targets()]

    assert identifiers == ["v1.29.0-wasm32"]


def test_reachability_audit_rejects_an_unreachable_build(tmp_path):
    write_config(tmp_path, 'build = "*-not-a-real-unix-cell"\n')

    with pytest.raises(UsermodConfigError, match=r"build: '\*-not-a-real"):
        UsermodOptions.load(tmp_path).targets()


def test_shared_top_level_keys_honour_the_environment(tmp_path, monkeypatch):
    write_config(tmp_path, "")
    monkeypatch.setenv("CIBMP_OUTPUT_DIR", "elsewhere")
    options = UsermodOptions.load(tmp_path)

    assert options.output_dir == Path("elsewhere")


def test_name_and_version_default_empty_and_are_settable(tmp_path):
    # record 0052, A3: usermod reads `name`/`version` too -- both feed
    # orchestrate.py's own _dest_name() filename prefix.
    write_config(tmp_path, "")
    unset = UsermodOptions.load(tmp_path)
    assert unset.name == ""
    assert unset.version == ""

    write_config(tmp_path, 'name = "mylib"\nversion = "1.2.0"\n')
    options = UsermodOptions.load(tmp_path)
    assert options.name == "mylib"
    assert options.version == "1.2.0"


# ── record 0051 point 7 / Phase G: [override] ────────────────────────────


def test_usermod_overrides_beat_the_file(tmp_path):
    write_config(
        tmp_path,
        f"""
        extra-make-args = ["COMMON=1"]
        {BUILD_UNIX_V129}

        [override."*-manylinux_2_28_x86_64"]
        extra-make-args = ["FROM=override"]
        """,
    )
    options = UsermodOptions.load(tmp_path)
    resolved = {
        t.identifier: options.build_options(t).extra_make_args
        for t in options.targets()
    }
    assert resolved["v1.29.0-manylinux_2_28_x86_64"] == ["FROM=override"]
    assert resolved["v1.29.0-manylinux_2_28_i686"] == ["COMMON=1"]


def test_usermod_a_select_key_inside_an_override_body_is_an_error(tmp_path):
    write_config(tmp_path, '[override."*"]\nselect = "*"\nmanifest = "x.py"\n')
    with pytest.raises(UsermodConfigError, match="select"):
        UsermodOptions.load(tmp_path)


def test_usermod_environment_beats_override(tmp_path):
    write_config(
        tmp_path,
        """
        build = "v1.29.0-manylinux_2_28_x86_64"

        [override."*"]
        extra-make-args = ["FROM=override"]
        """,
    )
    options = UsermodOptions.load(tmp_path)
    target = options.targets()[0]
    env = {"CIBMP_EXTRA_MAKE_ARGS": "FROM=env A=1"}
    assert options.build_options(target, env=env).extra_make_args == [
        "FROM=env",
        "A=1",
    ]


def test_usermod_override_beats_the_file_for_manifest(tmp_path):
    write_config(
        tmp_path,
        """
        manifest = "default.py"
        build = "v1.29.0-manylinux_2_28_x86_64"

        [override."*"]
        manifest = "special.py"
        """,
    )
    options = UsermodOptions.load(tmp_path)
    assert options.build_options(options.targets()[0]).manifest == "special.py"


def test_an_unknown_key_in_usermod_overrides_is_an_error(tmp_path):
    write_config(
        tmp_path,
        """
        build = "v1.29.0-manylinux_2_28_x86_64"

        [override."*"]
        arch-flags = "zba"
        """,
    )
    with pytest.raises(UsermodConfigError, match=r'\[override\."\*"\]: unknown key'):
        UsermodOptions.load(tmp_path)


def test_reachability_audit_rejects_an_override_select_that_can_never_match(tmp_path):
    write_config(
        tmp_path,
        """
        build = "v1.29.0-manylinux_2_28_x86_64"

        [override."*-notaport"]
        extra-make-args = ["X=1"]
        """,
    )
    with pytest.raises(
        UsermodConfigError, match=r'\[override\."\*-notaport"\]: \'\*-notaport\''
    ):
        UsermodOptions.load(tmp_path).targets()


def test_reachability_audit_allows_an_override_meant_only_for_natmod(tmp_path):
    # task #66: an override entirely valid for natmod alone must not be
    # flagged just because this direct, usermod-only caller never loads
    # natmod's own config (`_foreign_override_identifiers()`'s own job).
    write_config(
        tmp_path,
        """
        build = "v1.29.0-manylinux_2_28_x86_64"

        [override."*-armv7emsp"]
        extra-make-args = ["MP_BCLIBC_PRECISION=single"]
        """,
    )
    UsermodOptions.load(tmp_path).targets()  # must not raise


def test_reachability_audit_allows_a_deliberate_skip_everything(tmp_path):
    write_config(tmp_path, 'build = "v1.29.0-*"\nskip = "*"\n')
    assert UsermodOptions.load(tmp_path).targets() == []

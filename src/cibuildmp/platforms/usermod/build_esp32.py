"""usermod build driver: `esp32` (**D19**).

Its toolchain (ESP-IDF) is a whole environment, not one `<prefix>gcc` --
`usermod/espidf.py` is its own resolver. Not part of **M8**'s original
port list (`unix`/`webassembly`/`qemu`/`windows`) -- added alongside
**M9**'s own ESP-IDF provisioning work, since a resolver with nothing
driving a build through it proves less than one that does.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

from . import build_common, espidf
from .build_common import UsermodBuildError, usermod_mounts


@dataclass(frozen=True)
class Esp32BuildOptions:
    user_c_modules: str
    frozen_manifest: str
    board: str = "ESP32_GENERIC"
    idf_target: str = "esp32"
    idf_version: str = "v5.5.1"
    extra_make_args: tuple[str, ...] = ()
    extra_cmake_args: tuple[str, ...] = ()


def esp32_make_command(
    opts: Esp32BuildOptions, mpy_dir: Path, *, mpy_cross: Path | None = None
) -> list[str]:
    # No BUILD= override, even resolving to the exact value the port
    # already defaults to: build-usermod-esp32's own comment documents a
    # real CI failure this causes -- passing BUILD= at all (not what it's
    # set to) makes the port's own internal CMake-driven mpy-cross
    # sub-build pick up FROZEN_MANIFEST through MAKEFLAGS and fail with
    # "undefined reference to mp_qstr_frozen_const_pool", a separate copy
    # of the same symptom build_mpy_cross() being called explicitly,
    # first, already prevents for the main mpy-cross build.
    return [
        "make",
        "-C",
        (mpy_dir / "ports" / "esp32").as_posix(),
        f"BOARD={opts.board}",
        f"USER_C_MODULES={opts.user_c_modules}",
        f"FROZEN_MANIFEST={opts.frozen_manifest}",
        # py/mkenv.mk's own `MICROPY_MPYCROSS` override -- the container's
        # own copy (container_mpy_cross()), never the host's. See that
        # function's own docstring for why a host-built mpy-cross cannot
        # run inside this port's container either, now that it does.
        *([f"MICROPY_MPYCROSS={mpy_cross.as_posix()}"] if mpy_cross else []),
        *opts.extra_make_args,
    ]


def _esp32_container_script(
    opts: Esp32BuildOptions,
    mpy_dir: Path,
    idf_dir: Path,
    tools_dir: Path,
    mpy_cross: Path,
) -> str:
    """The one shell invocation `build_esp32()` runs inside the container:
    install ESP-IDF's own tools (only once -- `.installed` marks a cache
    hit, the same "cached by existence" rule `container_mpy_cross()` and
    `sources.build_mpy_cross()` both already use), export the environment
    `idf_tools.py export` computes, then `make`. One invocation, not
    several `dockerrun.run()` calls, because `dockerrun.run()` has no
    stdout-capturing mode to hand `export`'s own key=value lines back to a
    second call -- letting bash itself `eval` them, in the same shell that
    then runs `make`, needs no such plumbing at all, and gets `$PATH`-style
    substitutions in exported values (`ResolvedEspIdf.env()`'s own old
    special case) for free from the shell instead of a bespoke replace.

    Every path here is `.as_posix()` and already bind-mounted at its own
    identical host path (`build_esp32()`'s own `mounts=`), the same
    convention every other port's `*_make_command()` already relies on --
    this script needs no rewriting to run the same inside the container as
    the paths already resolve to on the host.

    `HOME` set explicitly, to `tools_dir` -- `dockerrun.run()`'s own
    `--user <uid>:<gid>` (not root, and not any name `/etc/passwd` inside
    `esp_idf_base` knows) leaves it unset otherwise. Every other port's
    script is plain `make`, needing no per-user state; ESP-IDF's own
    CMake ComponentManager is not, and resolves an unset `HOME` to `/` --
    live-caught on real CI, not locally: "Failed to create cache
    directory: /.cache/Espressif/ComponentManager", a directory no
    non-root container user can create. `tools_dir` is already mounted
    and already writable by this same user (created host-side, before
    the container starts), so it costs nothing new to point `HOME` at.
    """
    tools_py = shlex.quote((idf_dir / "tools" / "idf_tools.py").as_posix())
    marker = shlex.quote((tools_dir / ".installed").as_posix())
    idf_tools_path = shlex.quote(tools_dir.as_posix())
    idf_path = shlex.quote(idf_dir.as_posix())
    make_command = shlex.join(esp32_make_command(opts, mpy_dir, mpy_cross=mpy_cross))
    return f"""set -eux
export HOME={idf_tools_path}
export IDF_TOOLS_PATH={idf_tools_path}
if [ ! -e {marker} ]; then
    python3 {tools_py} install --targets={shlex.quote(opts.idf_target)}
    python3 {tools_py} install-python-env
    touch {marker}
fi
eval "$(python3 {tools_py} export --format key-value | sed 's/^/export /')"
export IDF_PATH={idf_path}
{make_command}
"""


def build_esp32(
    opts: Esp32BuildOptions,
    mpy_dir: Path,
    *,
    toolchain_root: Path | None = None,
    quiet: bool = False,
    package_dir: Path | None = None,
) -> Path:
    """Build ports/esp32 for `opts.board`, returning the produced
    `micropython.bin`.

    Docker, since 2026-08-28 -- `usermod/espidf.py`'s own module docstring
    has the full reasoning (the bare-host `idf_tools.py install-python-env`
    step refused to run from inside cibuildmp's own `uv tool install`
    venv). Only the `git clone` (`espidf.fetch_esp_idf()`, source, portable)
    stays on the host; installing ESP-IDF's own tools, and `make` itself,
    both run inside `esp_idf_base` ([0058]) via `_esp32_container_script()`
    above, in one `dockerrun.run()` call.

    mpy-cross is built inside the same container too now
    (`container_mpy_cross()`, matching `unix`/`windows`/`webassembly`) --
    `esp32` moved out of `orchestrate.py`'s own `_HOST_MPY_CROSS_PORTS` in
    the same change, since a host-built mpy-cross is exactly the "wrong
    glibc" binary that function's own docstring warns about, once `make`
    itself is no longer running on the host either.

    The output path is `mpy_dir / "ports" / "esp32" / "build-<BOARD>" /
    "micropython.bin"` -- the port's own unmodified default build
    directory, since nothing here overrides `BUILD=`.
    """
    from ... import dockerrun

    docker_image = dockerrun.ensure_image("esp32")
    if docker_image is None:
        raise UsermodBuildError(
            "esp32: no Docker image registered -- see "
            "`resources/pinned_docker_images.toml`, or point "
            "CIBMP_ESP32_DOCKER_IMAGE at a local tag"
        )
    oci_platform = dockerrun.platform_for("esp32")
    timeout = dockerrun.timeout_for("esp32")

    idf_dir = espidf.fetch_esp_idf(opts.idf_version, root=toolchain_root, quiet=quiet)
    tools_dir = espidf.tools_dir(opts.idf_version, opts.idf_target, root=toolchain_root)
    tools_dir.mkdir(parents=True, exist_ok=True)

    mpy_cross = build_common.container_mpy_cross(
        mpy_dir,
        slug="esp32",
        image=docker_image,
        oci_platform=oci_platform,
        timeout=timeout,
    )

    script = _esp32_container_script(opts, mpy_dir, idf_dir, tools_dir, mpy_cross)
    dockerrun.run(
        ["bash", "-c", script],
        # The *directory* `opts.user_c_modules` resolves inside
        # (`portinfo.resolve_user_c_modules()`'s own cmake branch appends
        # `/micropython.cmake` to it), not the file itself -- a Make
        # port's own `USER_C_MODULES=` is already that directory
        # (`resolve_user_c_modules()`'s make branch returns it unchanged),
        # so mounting `Path(opts.user_c_modules)` there already covers
        # any sibling file the config's own `manifest = "..."` combined
        # into `opts.frozen_manifest` might `include()` -- live-caught
        # 2026-08-28, esp32's own bare `.cmake` file mount left exactly
        # that sibling (`usermod/manifest.py`) unreachable: `CMake Error
        # ... [Errno 2] No such file or directory`. `.parent` brings this
        # port's own mount up to the same directory-level coverage every
        # Make port already has, not a new guarantee beyond that.
        # `package_dir`, when given, is appended on top -- see
        # `build_common.usermod_mounts()`.
        mounts=[
            *usermod_mounts(
                mpy_dir, Path(opts.user_c_modules).parent, package_dir=package_dir
            ),
            idf_dir,
            tools_dir,
        ],
        workdir=mpy_dir / "ports" / "esp32",
        image=docker_image,
        timeout=timeout,
        oci_platform=oci_platform,
        # ESP-IDF's own name for the same idea `rp2` calls CMAKE_ARGS --
        # ports/esp32/Makefile: `IDFPY_FLAGS += -D MICROPY_BOARD=... $(CMAKE_ARGS)`,
        # never reset first, so this reaches idf.py's own cmake invocation
        # the same append-not-replace way. See
        # `build_common.cmake_extra_args_env()`'s own docstring for why an
        # environment variable, not a make command-line token.
        env=build_common.cmake_extra_args_env(opts.extra_cmake_args, var="IDFPY_FLAGS"),
    )

    firmware = mpy_dir / "ports" / "esp32" / f"build-{opts.board}" / "micropython.bin"
    if not firmware.exists():
        raise UsermodBuildError(
            f"esp32/{opts.board}: build reported success but {firmware} is missing"
        )
    return firmware

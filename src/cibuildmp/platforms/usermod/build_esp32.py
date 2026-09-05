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
from .build_common import UsermodBuildError


@dataclass(frozen=True)
class Esp32BuildOptions:
    user_c_modules: str
    frozen_manifest: str
    board: str = "ESP32_GENERIC"
    idf_target: str = "esp32"
    idf_version: str = "v5.5.1"
    tag: str = ""
    extra_make_args: tuple[str, ...] = ()
    extra_cmake_args: tuple[str, ...] = ()


def esp32_make_command(
    opts: Esp32BuildOptions,
    mpy_dir: Path,
    *,
    mpy_cross: Path | None = None,
    extra_cflags: tuple[str, ...] | None = None,
) -> list[str]:
    # No BUILD= override, even resolving to the exact value the port
    # already defaults to: build-usermod-esp32's own comment documents a
    # real CI failure this causes -- passing BUILD= at all (not what it's
    # set to) makes the port's own internal CMake-driven mpy-cross
    # sub-build pick up FROZEN_MANIFEST through MAKEFLAGS and fail with
    # "undefined reference to mp_qstr_frozen_const_pool", a separate copy
    # of the same symptom build_mpy_cross() being called explicitly,
    # first, already prevents for the main mpy-cross build.
    # `CFLAGS_EXTRA` here, not just on the `container_mpy_cross()` call
    # below: `ports/esp32`'s own build recompiles `py/` too, into the
    # firmware itself, so a diagnostic a MicroPython release needs
    # suppressed for `mpy-cross` hits this build the same way ([0091],
    # mirroring `build_unix.py`'s own two-call-site pattern).
    #
    # `extra_cflags`, when given, overrides `tag_cflags()`'s own raw
    # candidate list -- the same override `rp2_make_command()` gained
    # ([0060]'s own correction addendum) after `resources/tag_cflags.toml`'s
    # `-Wno-error=unterminated-string-initialization` (a real gcc-15
    # diagnostic name) turned out to be a hard `cc1: error` on any
    # pre-`v1.26.0`-era cross compiler that does not recognize it at all.
    # `build_esp32()` discovers the real cross compiler ESP-IDF's own
    # `idf_tools.py export` put on `PATH` and probes against it with
    # `build_common.probe_supported_cflags()` before calling this -- see
    # that function's own comment for why esp32 cannot just reuse
    # `rp2`'s/`samd`'s plain `<prefix>gcc` full-path probe.
    cflags = extra_cflags if extra_cflags is not None else build_common.tag_cflags(opts.tag)
    return [
        "make",
        "-C",
        (mpy_dir / "ports" / "esp32").as_posix(),
        f"BOARD={opts.board}",
        f"USER_C_MODULES={opts.user_c_modules}",
        f"FROZEN_MANIFEST={opts.frozen_manifest}",
        *([f"CFLAGS_EXTRA={' '.join(cflags)}"] if cflags else []),
        # py/mkenv.mk's own `MICROPY_MPYCROSS` override -- the container's
        # own copy (container_mpy_cross()), never the host's. See that
        # function's own docstring for why a host-built mpy-cross cannot
        # run inside this port's container either, now that it does.
        *([f"MICROPY_MPYCROSS={mpy_cross.as_posix()}"] if mpy_cross else []),
        *opts.extra_make_args,
    ]


def _esp32_env_script(opts: Esp32BuildOptions, idf_dir: Path, tools_dir: Path) -> str:
    """Install ESP-IDF's own tools (only once -- `.installed` marks a cache
    hit, the same "cached by existence" rule `container_mpy_cross()` and
    `sources.build_mpy_cross()` both already use) and export the
    environment `idf_tools.py export` computes -- the half of the old
    single `_esp32_container_script()` that both `make` and a cross-compiler
    probe need identically. Split out ([0100]'s own rp2 correction, applied
    here too): a probe needs this environment exported to find the real
    compiler on `PATH` *before* `esp32_make_command()`'s own `CFLAGS_EXTRA`
    is built, and there is no cheaper way to get there than running this
    same, idempotent sequence twice (once to discover, once to build) --
    `idf_tools.py export` itself does no network I/O once `.installed`
    exists, so the repeat costs nothing but a fast local read.

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
"""


def _esp32_discover_cross_gcc_script(
    opts: Esp32BuildOptions, idf_dir: Path, tools_dir: Path
) -> str:
    """`_esp32_env_script()`'s own environment, plus one line that finds
    the real cross compiler `idf_tools.py export` just put on `PATH` and
    prints its full path -- nothing else on stdout, so
    `build_esp32()` can use the container's own `capture_output=True`
    return value directly.

    No static `idf_target -> cross prefix` table (`xtensa-esp32-elf-`,
    `riscv32-esp-elf-`, `xtensa-esp32s3-elf-`, ...) to keep in sync: this
    module's own docstring already explains why `espidf.py` is not shaped
    like `toolchain_fetch.py`'s `TOOLCHAIN_CROSS_PREFIX` -- "there is no
    single `<prefix>gcc` to find on `PATH` here" applies just as much to a
    guessed name as to a hand-maintained resolver, and ESP-IDF's own
    `idf_tools.py export` already exports exactly the one toolchain
    `--targets=` installed onto `PATH`, so asking the shell to find the
    one `*-elf-gcc` binary there is the same "let the tool that actually
    knows answer" principle `probe_supported_cflags()`'s own docstring
    already applies to gcc itself. Empty output means none was found (an
    ESP-IDF layout this glob does not anticipate) -- `build_esp32()`
    falls back to unprobed `tag_cflags()` rather than failing the whole
    build over a probe that could not run.
    """
    env_script = _esp32_env_script(opts, idf_dir, tools_dir)
    return f"""{env_script}
CROSS_GCC=""
for _dir in $(echo "$PATH" | tr ':' '\\n'); do
    for _candidate in "$_dir"/*-elf-gcc; do
        if [ -x "$_candidate" ]; then
            CROSS_GCC="$_candidate"
            break 2
        fi
    done
done
echo "$CROSS_GCC"
"""


def _esp32_project_mounts(
    opts: Esp32BuildOptions, package_dir: Path | None
) -> list[Path]:
    """The *directory* `opts.user_c_modules` resolves inside
    (`portinfo.resolve_user_c_modules()`'s own cmake branch appends
    `/micropython.cmake` to it), not the file itself -- a Make port's own
    `USER_C_MODULES=` is already that directory
    (`resolve_user_c_modules()`'s make branch returns it unchanged), so
    mounting `Path(opts.user_c_modules)` there already covers any sibling
    file the config's own `manifest = "..."` combined into
    `opts.frozen_manifest` might `include()` -- live-caught 2026-08-28,
    esp32's own bare `.cmake` file mount left exactly that sibling
    (`usermod/manifest.py`) unreachable: `CMake Error ... [Errno 2] No
    such file or directory`. `.parent` brings this port's own mount up to
    the same directory-level coverage every Make port already has, not a
    new guarantee beyond that. `package_dir`, when given, is appended on
    top -- `build_unix.py`'s own `_project_mounts()`.

    No entry at all when `opts.user_c_modules` is empty (record 0056's
    no-module build): `Path("").parent` is still `Path(".")`, the same
    relative-mount problem `_project_mounts()`'s own comment names, and
    there is no `micropython.cmake` sibling to reach once
    `USER_C_MODULES=` goes out empty.
    """
    mounts = [Path(opts.user_c_modules).parent] if opts.user_c_modules else []
    if package_dir is not None:
        mounts.append(package_dir.resolve())
    return mounts


def build_esp32(
    opts: Esp32BuildOptions,
    mpy_dir: Path,
    *,
    toolchain_root: Path | None = None,
    quiet: bool = False,
    package_dir: Path | None = None,
    staging: Path | None = None,
) -> Path:
    """Build ports/esp32 for `opts.board`, returning the produced
    `micropython.bin`.

    Docker, since 2026-08-28 -- `usermod/espidf.py`'s own module docstring
    has the full reasoning (the bare-host `idf_tools.py install-python-env`
    step refused to run from inside cibuildmp's own `uv tool install`
    venv). Only the `git clone` (`espidf.fetch_esp_idf()`, source, portable)
    stays on the host; installing ESP-IDF's own tools, and `make` itself,
    both run inside `esp_idf_base` ([0058]), via `_esp32_env_script()`'s
    shared install+export sequence -- run twice now, not once, since the
    cross-compiler probe below (a live-caught correction, mirroring
    [0060]'s own addendum for `rp2`) needs that same environment exported
    a second time before `make` itself runs. Both runs are cheap once
    ESP-IDF's own tools are installed: `idf_tools.py export` does no
    network I/O by itself.

    mpy-cross is built inside the same container too now
    (`container_mpy_cross()`, matching `unix`/`windows`/`webassembly`) --
    `esp32` moved out of `orchestrate.py`'s own `_HOST_MPY_CROSS_PORTS` in
    the same change, since a host-built mpy-cross is exactly the "wrong
    glibc" binary that function's own docstring warns about, once `make`
    itself is no longer running on the host either.

    **`Container`/overlay, not `dockerrun.run()`** ([0095]). The checkout
    arrives read-only, `container.overlay(mpy_dir)` gives the build a
    writable view of it that dies with the container -- needed here for
    the same reason `rp2` needs it, not just `container_mpy_cross()`'s
    own in-`mpy_dir` write: `ports/esp32` is CMake-driven like `rp2`, and
    passing `BUILD=` at all (not merely what it resolves to) makes the
    port's own internal mpy-cross sub-build pick up `FROZEN_MANIFEST`
    through `MAKEFLAGS` and fail (`esp32_make_command()`'s own comment),
    so the build tree stays at the port's unmodified default,
    `mpy_dir/ports/esp32/build-<BOARD>/`, which only exists on a writable
    checkout. `idf_dir`/`tools_dir` are fetched, persistent input
    ([0095]'s own category A -- the ESP-IDF checkout and its own tools
    cache), so both stay plain, real read-write host mounts *outside* the
    overlay, the same reasoning `build_rp2()`'s own toolchain cache mount
    already documents.

    **Two files copied to `staging`, both tolerant of a missing source**
    -- `micropython.bin` (the primary) and `firmware.bin` (the combined
    bootloader + partition table + application image `esp32_companions()`
    collects, [0079]), the same "let `produced.exists()` raise the
    informative error, not an opaque `cp` failure" reasoning
    `build_webassembly()`'s own comment gives for its own two-file output.

    The output path is `staging / "micropython.bin"`.
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

    if staging is None:
        msg = (
            "esp32 builds need a staging directory to hand the artifact "
            "back through ([0095]); orchestrate.build_one() provides one"
        )
        raise UsermodBuildError(msg)

    idf_dir = espidf.fetch_esp_idf(opts.idf_version, root=toolchain_root, quiet=quiet)
    tools_dir = espidf.tools_dir(opts.idf_version, opts.idf_target, root=toolchain_root)
    tools_dir.mkdir(parents=True, exist_ok=True)

    with dockerrun.overlay_container(
        mpy_dir,
        image=docker_image,
        oci_platform=oci_platform,
        mounts=[
            staging,
            idf_dir,
            tools_dir,
            *_esp32_project_mounts(opts, package_dir),
        ],
    ) as container:
        container.overlay(mpy_dir)

        mpy_cross = build_common.container_mpy_cross(
            mpy_dir,
            timeout=timeout,
            extra_cflags=build_common.tag_cflags(opts.tag),
            container=container,
        )

        # Discover the real cross compiler `idf_tools.py export` puts on
        # `PATH` and probe against it, the same live-caught fix [0060]'s
        # own correction addendum gave `rp2` -- `tag_cflags()`'s own
        # `-Wno-error=unterminated-string-initialization` is a hard `cc1:
        # error` on any pre-`v1.26.0`-era cross compiler that does not
        # recognize it. See `_esp32_discover_cross_gcc_script()`'s own
        # docstring for why this discovers the binary rather than naming
        # it from a static `idf_target -> prefix` table.
        discover_script = _esp32_discover_cross_gcc_script(opts, idf_dir, tools_dir)
        cross_gcc = container.call(
            ["bash", "-c", discover_script],
            workdir=mpy_dir / "ports" / "esp32",
            timeout=timeout,
            capture_output=True,
        )
        cross_gcc = (cross_gcc or "").strip()
        probed_cflags = (
            build_common.probe_supported_cflags(
                build_common.tag_cflags(opts.tag),
                compiler=cross_gcc,
                timeout=timeout,
                container=container,
            )
            if cross_gcc
            # No compiler found by the glob -- fall back to the raw,
            # unprobed list rather than failing the whole build over a
            # probe that could not run at all (see the discover script's
            # own docstring).
            else build_common.tag_cflags(opts.tag)
        )

        make_command = esp32_make_command(
            opts, mpy_dir, mpy_cross=mpy_cross, extra_cflags=probed_cflags
        )
        env_script = _esp32_env_script(opts, idf_dir, tools_dir)
        script = f"{env_script}{shlex.join(make_command)}\n"
        container.call(
            ["bash", "-c", script],
            workdir=mpy_dir / "ports" / "esp32",
            timeout=timeout,
            # ESP-IDF's own name for the same idea `rp2` calls CMAKE_ARGS --
            # ports/esp32/Makefile: `IDFPY_FLAGS += -D MICROPY_BOARD=... $(CMAKE_ARGS)`,
            # never reset first, so this reaches idf.py's own cmake
            # invocation the same append-not-replace way. See
            # `build_common.cmake_extra_args_env()`'s own docstring for why
            # an environment variable, not a make command-line token.
            env=build_common.cmake_extra_args_env(
                opts.extra_cmake_args, var="IDFPY_FLAGS"
            ),
        )

        build_dir = mpy_dir / "ports" / "esp32" / f"build-{opts.board}"
        primary_src = (build_dir / "micropython.bin").as_posix()
        combined_src = (build_dir / "firmware.bin").as_posix()
        primary_dest = (staging / "micropython.bin").as_posix()
        combined_dest = (staging / "firmware.bin").as_posix()
        copy_script = (
            f"[ -e {shlex.quote(primary_src)} ] && "
            f"cp {shlex.quote(primary_src)} {shlex.quote(primary_dest)} || true\n"
            f"[ -e {shlex.quote(combined_src)} ] && "
            f"cp {shlex.quote(combined_src)} {shlex.quote(combined_dest)} || true\n"
        )
        container.call(["sh", "-c", copy_script], workdir=build_dir, timeout=timeout)

    firmware = staging / "micropython.bin"
    if not firmware.exists():
        raise UsermodBuildError(
            f"esp32/{opts.board}: build reported success but {firmware} is missing"
        )
    return firmware


def esp32_companions(produced: Path) -> list[Path]:
    """`firmware.bin` -- the combined image, the one that is flashable.

    `produced` is `micropython.bin`, the application image alone.
    `ports/esp32/README.md`: the build "will produce a combined
    `firmware.bin` image", combined meaning bootloader + partition table
    + `micropython.bin`. A real local build has both, and they differ --
    1,777,392 against 1,715,952 bytes.

    `micropython.bin` stays the primary rather than the two swapping
    places: the collected name is `<name>-<identifier>.bin`, and moving
    which file that points at would silently change what an existing
    consumer already flashes.
    """
    combined = produced.parent / "firmware.bin"
    return [combined] if combined.is_file() else []

"""What every `build_<port>()` driver shares: the one exception type they
all raise, and the one container-mpy-cross helper they all call.

Split out of a single `build.py` (2026-08-29) once that file reached seven
ports and 1600+ lines -- the same one-file-per-platform shape cibuildwheel
itself uses (`linux.py`/`macos.py`/`windows.py`/`pyodide.py` plus a shared
`util.py`), read directly before choosing this layout, not recalled (see
this repo's own CLAUDE.md on that discipline). See
docs/records/0061-usermod-build-drivers-split-per-port.md for the record.

Every `Path` embedded into a `make` command line, across every port module
below, goes through `.as_posix()`, never a bare `str()`: a real
`usermod-dev.yml` run on `windows-latest`, back when that port still ran
under MSYS2, caught this -- `str(WindowsPath(...))` produces backslashes,
and GNU Make wants forward slashes regardless of host OS. Kept as the rule
for every port, not just the one that surfaced it.
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path

# `natmod` needed this same per-tag `CFLAGS_EXTRA` fact for its own
# `mpy-cross` build ([0091]) and cannot import `usermod` (the established
# one-way dependency), so it lives in the shared module both families
# already import `fetch_micropython()`/`read_mpy_abi()` from. Re-exported
# here, unchanged, so `build_common.tag_cflags(...)`/`build_common.TAG_CFLAGS`
# keep resolving for every existing caller in this package.
from ...sources import TAG_CFLAGS, scratch_root, tag_cflags  # noqa: F401


class UsermodBuildError(Exception):
    pass


def usermod_mounts(
    mpy_dir: Path, user_c_modules_mount: Path, *, package_dir: Path | None
) -> list[Path]:
    """The bind mounts every `build_<port>()` gives its own `dockerrun.run()`
    call: `mpy_dir`, `user_c_modules_mount`, and -- when the caller has one
    to give -- the whole `package_dir` too.

    `user_c_modules_mount` is a `Path`, not a bare `USER_C_MODULES` string,
    because what actually needs mounting differs by build system: Make
    ports mount `USER_C_MODULES` itself (`opts.user_c_modules`, a real
    directory `py/py.mk`'s own glob reads); CMake ports (`esp32`/`rp2`)
    resolve `USER_C_MODULES` to a *file* (`portinfo.resolve_user_c_modules()`
    appends `/micropython.cmake`), so their own callers pass that file's
    `.parent` instead -- both already did before `package_dir` existed
    here, unchanged by this helper.

    `dockerrun.run()` bind-mounts each of these at its own identical host
    path (its own docstring), so a module whose sources reach *outside*
    `USER_C_MODULES` via a relative path (`../src`, `../../natmod/nanopb`,
    a sibling directory two levels up, whatever the consumer's own layout
    actually is) previously saw nothing there at all -- confirmed live
    against a real consumer (`o-murphy/a7p`'s own `usermod/a7p/
    micropython.mk`, `../../src`/`../../natmod/nanopb` both invisible
    in-container, "No such file or directory" on a path that existed on the
    host the whole time), and independently already known: `examples/
    template`'s own `usermod/micropython.mk` carries the identical warning
    for the identical reason, worked around there by setting
    `user-c-modules = "."` so `USER_C_MODULES` itself resolves to
    `package_dir` -- a real fix, but one that requires restructuring the
    consumer's own module to sit exactly one level under its own project
    root, which cibuildwheel does not ask of a `setup.py`/`pyproject.toml`
    and this project should not ask of a module either.

    `package_dir` is mounted instead, unconditionally, the same way
    `natmod/build.py` already mounts it for every natmod target
    (`mounts=[mpy_dir, package_dir.resolve()]` there, unchanged) --
    consistent with cibuildwheel's own principle that nothing about the
    project being built should be invisible to the container it builds in,
    even though the mechanism here (an extra bind mount at the project's
    own identical host path) is simpler than cibuildwheel's own `docker cp`/
    tar-pipe copy-in (`OCIContainer.copy_into()`) -- this project already
    bind-mounts everything else at identical host paths, and one more
    mount at the same convention costs nothing where a wholesale change of
    mechanism would.

    `USER_C_MODULES` itself stays in the list even though `package_dir`
    (when given) already contains it -- a strict subdirectory of an
    already-mounted tree bind-mounts for free either way, and dropping it
    would make this helper's own list depend on `package_dir` always being
    given, which it is not (see the `None` default: called directly, in a
    handful of tests, with no `package_dir` in scope at all).

    `package_dir=None` (its own tests, or a direct API caller with no
    project directory in scope) keeps today's narrower behaviour exactly,
    rather than raising or guessing one -- there is no sane default to
    invent for "no project directory was given."

    `scratch_root()` is in the list unconditionally, for every port,
    since [0095] moved compiled build state out of `mpy_dir`: a Make port
    writes its `BUILD=` tree there, and `container_mpy_cross()` writes its
    binary there, so a build whose only mount was `mpy_dir` would now have
    nowhere to put its output. It is mounted rather than each individual
    `build-<identifier>/` for a specific reason -- `docker run -v` creates
    a **root-owned** directory when the bind source does not exist on the
    host, and `build_one()` deletes and recreates that directory per
    build, so mounting it directly would hand the `--user` container a
    path it cannot write to. `scratch_root()` itself always exists (that
    function creates it) and is never deleted mid-run. Ports with no
    `build_dir` of their own (`esp32`, `rp2` -- both CMake-driven, see
    `rp2_make_command()`'s own comment on why neither overrides `BUILD=`)
    still get the mount, because `container_mpy_cross()` is common to
    every port.
    """
    mounts = [mpy_dir, user_c_modules_mount, scratch_root()]
    if package_dir is not None:
        mounts.append(package_dir.resolve())
    return mounts


def cmake_extra_args_env(
    extra_cmake_args: tuple[str, ...], *, var: str
) -> dict[str, str]:
    """`extra-cmake-args` -> the one `dockerrun.run()` `env={...}` entry
    that actually reaches a CMake-driven port's own build, for the two
    usermod ports whose own Makefile wraps `cmake`/`idf.py` rather than
    calling either directly: `rp2` (`var="CMAKE_ARGS"`) and `esp32`
    (`var="IDFPY_FLAGS"`, ESP-IDF's own name for the same idea).

    Not a plain `extra_make_args`-style command-line token, on purpose.
    Both ports' own Makefiles build that variable with a plain `+=`
    (`ports/rp2/Makefile`: `CMAKE_ARGS += -DMICROPY_BOARD=...`;
    `ports/esp32/Makefile`: `IDFPY_FLAGS += -D MICROPY_BOARD=... $(CMAKE_ARGS)`),
    never resetting it first -- and GNU Make's own precedence
    (command-line > makefile assignment > environment) means a
    command-line `make CMAKE_ARGS=-Dfoo=1` is not an *append*, whatever
    operator the makefile itself later uses on it: verified live, twice
    (`make CMAKE_ARGS=...` and even `make CMAKE_ARGS+=...` both replace
    the makefile's own `-DMICROPY_BOARD=...`/`-DUSER_C_MODULES=...`
    entirely, leaving only the command-line value). An **environment**
    variable of the same name sits one precedence tier below a makefile's
    own assignment, so the makefile's `+=` treats it as the *starting*
    value and appends its own required flags on top -- confirmed the same
    way, `CMAKE_ARGS=-Dfoo=1 make` keeps every flag the makefile itself
    still adds. `dockerrun.run()`'s own `env=` becomes `-e KEY=VALUE` on
    the `docker run` invocation, landing in the container's process
    environment before the script or `make` call inside it ever runs --
    exactly this tier.

    `{}` (no entry at all) when `extra_cmake_args` is empty, rather than
    an explicit `{var: ""}`: harmless either way (an empty environment
    value behaves like unset for a `+=`-only variable), but an absent key
    keeps a caller's own `dockerrun.run(..., env=...)` call sites free of
    a no-op entry when nobody configured anything.
    """
    if not extra_cmake_args:
        return {}
    return {var: " ".join(extra_cmake_args)}


def probe_supported_cflags(
    candidates: tuple[str, ...],
    *,
    image: str,
    compiler: str = "gcc",
    oci_platform: str | None = None,
    linux32: bool = False,
    timeout: float | None = None,
) -> tuple[str, ...]:
    """Every `-Wno-error=<diagnostic>` in `candidates` this image's own
    `compiler` actually recognizes, in the same order -- live-checked
    inside `image` itself, not assumed from what a *different* image's
    gcc happens to accept.

    Found live, against a real `manylinux_2_28_i686` build once `unix`
    stopped resolving to a cibuildmp-published image and started hitting
    pypa's own per-arch gcc directly: `TAG_CFLAGS`'s own
    `-Wno-error=unterminated-string-initialization` (a real gcc-15
    diagnostic, [0082]) is not a harmless no-op on a gcc-14 image the way
    its own comment assumed ("a suppressed warning that never fires on a
    cell that does not hit it") -- gcc 14 does not recognize
    `-Wunterminated-string-initialization` as a diagnostic name *at all*,
    so `-Wno-error=` naming it is a hard `cc1: error: ... no option
    '-Wunterminated-string-initialization'`, on every single translation
    unit, not a warning quietly doing nothing. `manylinux_2_28`'s own
    gcc ladder (11 -> 12 -> 14, record 0084's own addendum) never reaches
    15 at all, so this was always going to happen the first time a
    pre-`v1.26.0` tag actually built against that family's own real
    compiler.

    `compiler` defaults to the bare `gcc` every native pypa image runs
    the real build with, but that default is wrong for `mipsel` -- its
    image is a Bootlin cross-toolchain, so the compiler the real build
    actually invokes is `mipsel-linux-gnu-gcc`
    (`UnixArchSettings.cross_compile + "gcc"`), a *different, older*
    binary than whatever bare `gcc` resolves to inside that same image
    (its own build tooling, native to the image's host arch). Found
    live: the first version of this function always probed bare `gcc`,
    which on the `manylinux_2_41_mipsel` image happily accepted
    `-Wno-error=unterminated-string-initialization` -- disproving this
    docstring's own prior claim that every Bootlin/xpack toolchain here
    was already known to be gcc >=15 -- while the real
    `mipsel-linux-gnu-gcc` (gcc 14.3.0) rejected it exactly as any other
    gcc-14 compiler would, and the build failed regardless of the
    (wrongly-probed) filtered result.

    No per-arch gcc-version table to keep in sync as a result: the
    compiler itself is asked, once per (image, compiler, candidate
    list), the same "let the tool that actually knows answer" principle
    CLAUDE.md's own top rule already applies to reading cibuildwheel
    instead of guessing at it. Empty `candidates` short-circuits with no
    container run at all -- true for every `v1.26.0`-and-later, non-musl
    build, the common case.
    """
    if not candidates:
        return ()
    from ... import dockerrun

    # `dockerrun.run()` runs this with `check=True` -- a `;`-joined shell
    # script's own exit status is whatever its *last* statement leaves
    # behind, so without the trailing `; true` a probe would raise
    # `CalledProcessError` (crashing the whole build, not just reporting
    # one unsupported flag) purely because the *last* candidate in the
    # list happened to be the one this gcc rejects, regardless of how
    # every earlier candidate actually probed.
    quoted_compiler = shlex.quote(compiler)
    probe = (
        "; ".join(
            f'printf "" | {quoted_compiler} {shlex.quote(flag)} -x c -c -o /dev/null - '
            f">/dev/null 2>&1 && echo {shlex.quote(flag)}"
            for flag in candidates
        )
        + "; true"
    )
    output = dockerrun.run(
        ["sh", "-c", probe],
        mounts=[],
        workdir=Path("/"),
        image=image,
        timeout=timeout,
        oci_platform=oci_platform,
        linux32=linux32,
        capture_output=True,
    )
    supported = set((output or "").split())
    return tuple(flag for flag in candidates if flag in supported)


def container_mpy_cross(
    mpy_dir: Path,
    *,
    slug: str,
    image: str,
    oci_platform: str | None = None,
    linux32: bool = False,
    timeout: float | None = None,
    extra_cflags: tuple[str, ...] = (),
) -> Path:
    """Build `mpy-cross` **inside `image`** and return the binary, for the
    port build to pass as `MICROPY_MPYCROSS=`.

    Found the hard way, on the first real build under record 0043's native
    images -- not anticipated by that record, and the reason it needed a
    live run rather than a review:

        mpy-cross: /lib64/libc.so.6: version `GLIBC_2.34' not found
        make: *** [py/mkrules.mk:231: .../frozen_content.c] Error 1

    `sources.build_mpy_cross()` builds mpy-cross on the **host**, and
    `py/mkrules.mk` then executes it *inside the container* to compile the
    frozen manifest. That worked only for as long as every image was
    `ubuntu:24.04` -- the same glibc as a typical host, by coincidence
    rather than by design. It breaks two different ways now, and both are
    structural rather than incidental:

    * **A real libc floor is a floor.** `manylinux_2_28` is AlmaLinux 8,
      glibc 2.28; a host-built binary needing 2.34 cannot run there. The
      lower and more useful the floor, the more certainly this fails --
      so the failure gets *worse* as the manylinux claim gets *better*.
      For musllinux there is no version to argue about: a glibc binary
      does not run under musl at all.
    * **Native images have a native architecture.** An x86_64 host's
      mpy-cross cannot execute inside a `linux/arm64` container under any
      libc. This alone makes the in-container build mandatory, not merely
      safer, for every non-native target -- which under 0043 is most of
      the matrix.

    The same reasoning reaches the cross-compiling ports (`windows`,
    `webassembly`, `qemu`) from the other direction: their images are
    amd64, so on an **arm64 host** the host-built mpy-cross is an arm64
    binary that cannot run inside them. That is exactly the "one config,
    either host architecture" property 0043 exists to provide, so they
    use this too.

    `slug` scopes the build directory (`mpy-cross/build-<slug>/` under
    `scratch_root()`) so each image gets its own binary and none of them
    collide -- including with `natmod`'s own container-built binary, which
    has to stay at `mpy_dir/mpy-cross/build/` because `py/dynruntime.mk`
    hardcodes `MPY_CROSS = $(MPY_DIR)/mpy-cross/...` with no override
    (see `natmod/build.py`'s own `build_mpy_cross()`).

    Under `scratch_root()`, not `mpy_dir`, since [0095]: `mpy_dir` is
    fetched input that a CI cache step may restore from a previous run,
    and this binary is keyed on an image -- so a restored one is a
    silently wrong compiler, not a saved minute. Within one invocation
    every identifier sharing a `slug` still builds it exactly once, which
    is the reuse this function was written for; across invocations the
    default `scratch_root()` is a fresh directory, so the existence check
    below no longer answers "was one ever built" but "was one built by
    this run".

    Cached by existence, like `sources.build_mpy_cross()`: a rebuilt
    container binary is only needed when the image itself changes, and the
    image is digest-pinned.
    """
    from ... import dockerrun

    build_dir = scratch_root() / "mpy-cross" / f"build-{slug}"
    binary = build_dir / "mpy-cross"
    if binary.exists():
        return binary

    dockerrun.run(
        [
            "make",
            "-C",
            (mpy_dir / "mpy-cross").as_posix(),
            f"BUILD={build_dir.as_posix()}",
            # `mpy-cross` compiles `py/` too, so a diagnostic that stops a
            # port build stops this one first -- live-caught in CI
            # (33636118022): `v1.20.0`'s `-Werror=dangling-pointer=` in
            # `py/stackctrl.c` failed here, before the port's own make ever
            # ran, while the row's `cflags_extra` was reaching only the
            # port. Anything the caller needs relaxed for its own sources
            # has to be relaxed for this build as well.
            *([f"CFLAGS_EXTRA={' '.join(extra_cflags)}"] if extra_cflags else []),
            f"-j{os.cpu_count() or 1}",
        ],
        # `scratch_root()` alongside `mpy_dir`: `make -C <mpy_dir>/mpy-cross`
        # reads its sources from the checkout and writes every object into
        # `BUILD=`, which is no longer inside it ([0095]).
        mounts=[mpy_dir, scratch_root()],
        workdir=mpy_dir / "mpy-cross",
        image=image,
        timeout=timeout,
        oci_platform=oci_platform,
        linux32=linux32,
    )
    if not binary.exists():
        raise UsermodBuildError(
            f"mpy-cross build inside {image} reported success but {binary} is missing"
        )
    return binary

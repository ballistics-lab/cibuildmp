"""Running a usermod build end to end: resolve a target's port-specific
`*BuildOptions`, write its combined manifest, call the matching
`build_<port>()`, collect the result.

Mirrors `build.build_target()`'s own shape (mpy-cross built once, shared
across targets; `output_dir/<identifier>/` per target) but simpler: no
`verify_output()` (there is no `.mpy` header to check a full port binary
against) and no `package_target()`/`package.json` at all -- a usermod
build's output is a full port binary meant to be flashed or run
directly, not `mip.install()`-ed into a running MicroPython, so D14's
packaging step does not apply (confirmed with the user directly, not
assumed).

Not yet supported, deliberately, same as `usermod/options.py`'s own
docstring already flags:
- No `extra-files` equivalent (natmod's own `[publish] extra-files`) --
  a real, cheap follow-up, just not attempted in this first slice.
- No per-target `pre-build-command`.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import sources
from . import manifests, portinfo
from .build import (
    Esp32BuildOptions,
    QemuBuildOptions,
    UnixBuildOptions,
    UsermodBuildError,
    WebassemblyBuildOptions,
    WindowsBuildOptions,
    build_esp32,
    build_qemu,
    build_unix,
    build_webassembly,
    build_windows,
)
from .options import UsermodBuildOptions, UsermodOptions
from .targets import UsermodTarget

# port -> the build_<port>() function, uniform signature across all five:
# build_x(opts, mpy_dir, *, toolchain_root=None, quiet=False) -> Path.
_BUILD_FN: dict[str, Callable[..., Path]] = {
    "unix": build_unix,
    "windows": build_windows,
    "qemu": build_qemu,
    "webassembly": build_webassembly,
    "esp32": build_esp32,
}


@dataclass(frozen=True)
class UsermodBuildResult:
    identifier: str
    output: Path
    duration: float

    @property
    def size(self) -> int:
        return self.output.stat().st_size


def _resolved_build_dir(mpy_dir: Path, port: str, identifier: str) -> Path:
    # One build directory per identifier, not the port's own bare default
    # -- so building unix-x64 and unix-aarch64 against the same checkout
    # in one invocation never has one overwrite the other mid-build.
    return mpy_dir / "ports" / port / f"build-{identifier}"


def _manifest_path(mpy_dir: Path, port: str, identifier: str) -> Path:
    return mpy_dir / "ports" / port / f"cibuildmp-manifest-{identifier}.py"


def _port_build_options(
    build_options: UsermodBuildOptions,
    mpy_dir: Path,
    package_dir: Path,
) -> Any:
    """The port-specific `*BuildOptions` `usermod/build.py` wants, built
    from `build_options`' own generic ingredients: `user_c_modules`
    resolved (D16), a combined manifest written to a real file (D17,
    empty -- and no file at all -- when neither the port nor the config
    has one to include), a per-identifier `build_dir`."""
    target = build_options.target
    port = target.port
    identifier = target.identifier

    module_root = (package_dir / build_options.module_dir).resolve()
    user_c_modules = portinfo.resolve_user_c_modules(port, module_root.as_posix())

    module_manifest = (
        (package_dir / build_options.manifest).resolve().as_posix()
        if build_options.manifest
        else ""
    )
    manifest_text = manifests.combined_manifest(port, module_manifest)
    frozen_manifest = ""
    if manifest_text:
        manifest_path = _manifest_path(mpy_dir, port, identifier)
        manifest_path.write_text(manifest_text)
        frozen_manifest = manifest_path.as_posix()

    extra_make_args = tuple(build_options.extra_make_args)

    if port == "unix":
        return UnixBuildOptions(
            arch=target.arch,
            user_c_modules=user_c_modules,
            frozen_manifest=frozen_manifest,
            build_dir=_resolved_build_dir(mpy_dir, port, identifier),
            extra_make_args=extra_make_args,
        )
    if port == "windows":
        return WindowsBuildOptions(
            arch=target.arch,
            user_c_modules=user_c_modules,
            frozen_manifest=frozen_manifest,
            build_dir=_resolved_build_dir(mpy_dir, port, identifier),
            extra_make_args=extra_make_args,
        )
    if port == "qemu":
        # No board= here: qemu has no configurable axis yet
        # (usermod/targets.py's own _PORT_AXES), so target.arch is
        # always "" -- passing that through would override
        # QemuBuildOptions' own "MPS2_AN385" default with an empty
        # string instead of leaving it alone.
        return QemuBuildOptions(
            user_c_modules=user_c_modules,
            frozen_manifest=frozen_manifest,
            build_dir=_resolved_build_dir(mpy_dir, port, identifier),
            extra_make_args=extra_make_args,
        )
    if port == "webassembly":
        return WebassemblyBuildOptions(
            user_c_modules=user_c_modules,
            frozen_manifest=frozen_manifest,
            build_dir=_resolved_build_dir(mpy_dir, port, identifier),
            extra_make_args=extra_make_args,
        )
    if port == "esp32":
        return Esp32BuildOptions(
            user_c_modules=user_c_modules,
            frozen_manifest=frozen_manifest,
            board=target.arch,
            extra_make_args=extra_make_args,
        )
    raise UsermodBuildError(f"no build_options builder wired for port {port!r}")


def _dest_name(produced: Path, identifier: str) -> str:
    # Identifier-qualified even though the file already lives in its own
    # identifier/ directory -- same reasoning natmod's own output_name()
    # gives: stays unambiguous if a caller later flattens several
    # identifiers' directories into one namespace (a GitHub Release's own
    # flat asset list, which cannot nest directories).
    return f"{produced.stem}-{identifier}{produced.suffix}"


def build_one(
    options: UsermodOptions,
    target: UsermodTarget,
    mpy_dir: Path,
    *,
    toolchain_root: Path | None = None,
    quiet: bool = False,
) -> UsermodBuildResult:
    start = time.time()
    build_options = options.build_options(target)
    port_opts = _port_build_options(build_options, mpy_dir, options.package_dir)

    build_fn = _BUILD_FN[target.port]
    produced = build_fn(port_opts, mpy_dir, toolchain_root=toolchain_root, quiet=quiet)

    identifier_dir = options.output_dir / target.identifier
    identifier_dir.mkdir(parents=True, exist_ok=True)
    dest = identifier_dir / _dest_name(produced, target.identifier)
    shutil.copyfile(produced, dest)

    return UsermodBuildResult(
        identifier=target.identifier, output=dest, duration=time.time() - start
    )


def build(
    options: UsermodOptions,
    targets: list[UsermodTarget],
    *,
    toolchain_root: Path | None = None,
    quiet: bool = False,
) -> list[UsermodBuildResult]:
    """Build every selected target in one invocation.

    MicroPython is fetched and mpy-cross built once, shared across every
    target -- the same D9 reasoning `cli.build()` already applies for
    natmod, and for the same reason: nothing here needs a different
    checkout or a different mpy-cross per target, since none of the five
    ports' own axes (arch/board) change which MicroPython release is
    being built, only how it is cross-compiled.
    """
    mpy_dir = sources.fetch_micropython(options.micropython)
    sources.build_mpy_cross(mpy_dir, quiet=quiet)

    results = []
    for target in targets:
        results.append(
            build_one(
                options, target, mpy_dir, toolchain_root=toolchain_root, quiet=quiet
            )
        )
    return results

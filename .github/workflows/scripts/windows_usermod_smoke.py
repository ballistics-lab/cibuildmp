"""One-off live proof for build_windows() (D18) -- not run on every push,
only via usermod-dev.yml's own workflow_dispatch trigger: a real MSYS2
package install (mingw-w64-x86_64-gcc) plus a full MicroPython compile is
too slow for the on-push job that already runs the hermetic suite.

Mirrors the same "run it for real against a real checkout" proof unix,
qemu, webassembly and esp32 already got in this project's own dev
sandbox -- windows cannot be proven there at all, so this is its only
real channel. Deliberately a throwaway script, not part of the package:
there is no CLI/action.yml wiring for usermod yet (that gap is real and
separate, see docs/BACKLOG.md), so this stands in for it until one
exists.
"""

from __future__ import annotations

from cibuildmp.sources import fetch_micropython
from cibuildmp.usermod.build import WindowsBuildOptions, build_windows
from cibuildmp.usermod.msys2 import ResolvedMsys2, resolve_msys2

TAG = "v1.28.0"


def main() -> None:
    mpy_dir = fetch_micropython(TAG, quiet=False)

    user_c_modules = mpy_dir / "usermod-smoke-empty"
    user_c_modules.mkdir(exist_ok=True)

    # USER_C_MODULES must be a path MSYS2 bash/make can use, same reason
    # build_windows() itself converts mpy_dir -- .as_posix() alone is not
    # enough (see msys2.py's ResolvedMsys2.to_posix_path docstring).
    root = resolve_msys2(quiet=False)
    session = ResolvedMsys2(root=root, msystem="MINGW64")
    user_c_modules_posix = session.to_posix_path(str(user_c_modules))

    opts = WindowsBuildOptions(
        user_c_modules=user_c_modules_posix,
        frozen_manifest="variants/manifest.py",
    )
    binary = build_windows(opts, mpy_dir, quiet=False)
    print(f"OK: {binary} ({binary.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

"""Per-port build-system shape and default-manifest path.

Neither field comes from `mpbuild`'s board_database.py (D7 vendors that
separately, in usermod/boards.py) -- USER_C_MODULES shape and manifest
layout are cibuildmp's own concern, not something mpbuild ever resolves.
The pinned table itself, and how each value was verified, lives in
resources/usermod.toml (D10's own "pinned data lives in resources/, not in
Python" pattern) -- see docs/0000-TRACKER.md D16 and D17.
"""

from __future__ import annotations

from pathlib import Path

from ...resources import usermod_data

_PORTS: dict[str, dict[str, str]] = usermod_data()["port"]


class UnknownPortError(ValueError):
    pass


def _port(name: str) -> dict[str, str]:
    try:
        return _PORTS[name]
    except KeyError:
        raise UnknownPortError(
            f"no usermod port data for {name!r}. Known: {', '.join(known_ports())}"
        ) from None


def build_system(port: str) -> str:
    """ "make" or "cmake" -- which USER_C_MODULES shape this port's build
    expects (D16). See resources/usermod.toml for what each shape means.
    """
    return _port(port)["build-system"]


def default_manifest(port: str) -> str | None:
    """The manifest.py this port resolves to under exactly how a7p's own
    mp-usermod.yml builds it today, relative to $(PORT_DIR); None if it
    ships none (D17) -- confirmed for `qemu`, not assumed.

    NOT a general per-variant/per-board resolver: unix and webassembly
    both build a specific, non-default variant there (their own
    mpconfigvariant.mk overrides the port-level Makefile default), so
    their values here are that override, not the port-level default the
    other four ports resolve to unmodified. See resources/usermod.toml
    for exactly which is which and why.
    """
    value = _port(port)["default-manifest"]
    return value or None


def known_ports() -> tuple[str, ...]:
    """Ports resources/usermod.toml has data for -- deliberately just the
    six D16-D21 already has a working reference implementation for, not
    every port MicroPython ships.
    """
    return tuple(sorted(_PORTS))


def resolve_user_c_modules(port: str, module_dir: str) -> str:
    """The USER_C_MODULES value to pass for `port`'s build, given the
    directory holding a consumer's own module (D16).

    "cmake" ports take the module's own `micropython.cmake` file
    directly: py/usermod.cmake would also accept a bare directory there
    (it appends `/micropython.cmake` itself), but every real cmake-port
    consumer (a7p's own mp-usermod.yml, for both esp32 and rp2) always
    passes the file, so this mirrors that rather than relying on the
    directory form nothing here has actually exercised.

    "make" ports are the asymmetric half, and a real, live-caught trap
    (o-murphy/micropython-wasm3's own migration, 2026-08-29): py/py.mk
    globs `<module_dir>/*/micropython.mk` -- one directory level *above*
    the module itself, not `module_dir` directly. A consumer whose module
    sits flat (`usermod/micropython.mk`, `module_dir="usermod"` -- the
    exact shape a single-module project reaches for first) gets a glob
    that matches nothing, and nothing here or in upstream py.mk raises
    for that: the port just builds and links with zero user modules,
    silently. cibuildmp's own examples/template avoids this by
    structuring around it (`usermod/micropython.mk` one level down,
    `micropython.cmake` one level *up* at the project root, both reached
    correctly from a single `user-c-modules = "."`) -- correct, but only
    because whoever wrote it already knew this asymmetry existed; nothing
    enforces or explains it to a new consumer, wasm3's own first attempt
    included.

    So: when `module_dir` itself already contains a `micropython.mk`
    (points straight at the module, the flat/single-module shape), resolve
    to its parent instead -- the glob then finds it at
    `<parent>/<module_dir's own name>/micropython.mk`, exactly like the
    multi-module shape (`module_dir` genuinely holding several `*/
    micropython.mk` subdirectories, a7p's own `usermod/a7p/micropython.mk`
    included) already works today. That existing shape is unaffected: a
    `module_dir` with no `micropython.mk` directly inside it (a7p's own
    `usermod/`, examples/template's own `.`) falls through unchanged, the
    same value this function has always returned for it.
    """
    if build_system(port) == "cmake":
        return f"{module_dir}/micropython.cmake"
    if (Path(module_dir) / "micropython.mk").is_file():
        return str(Path(module_dir).parent)
    return module_dir

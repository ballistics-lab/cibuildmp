"""Per-port build-system shape and default-manifest path.

Neither field comes from `mpbuild`'s board_database.py (D7 vendors that
separately, in usermod/boards.py) -- USER_C_MODULES shape and manifest
layout are cibuildmp's own concern, not something mpbuild ever resolves.
The pinned table itself, and how each value was verified, lives in
resources/usermod.toml (D10's own "pinned data lives in resources/, not in
Python" pattern) -- see docs/BACKLOG.md D16 and D17.
"""

from __future__ import annotations

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

    "make" ports take `module_dir` as-is -- py/py.mk globs
    `<module_dir>/*/micropython.mk`. "cmake" ports take the module's own
    `micropython.cmake` file directly: py/usermod.cmake would also accept
    a bare directory there (it appends `/micropython.cmake` itself), but
    every real cmake-port consumer (a7p's own mp-usermod.yml, for both
    esp32 and rp2) always passes the file, so this mirrors that rather
    than relying on the directory form nothing here has actually
    exercised.
    """
    if build_system(port) == "cmake":
        return f"{module_dir}/micropython.cmake"
    return module_dir

"""Usermod config loading: the `[usermod]` table (and its per-port
`[usermod.<port>]` sub-tables), read the same way `options.py` reads
`[natmod]` -- D5's own "config is scoped by build mode, the way
cibuildwheel scopes by platform" -- but genuinely a separate tree, not a
second copy-paste of `Options`: usermod's own axes (which ports, which
per-port arch/board) don't fit natmod's single flat `archs` list at all.

Deliberately narrower than `Options` for now, not an oversight:
- No `[[overrides]]` glob mechanism yet -- natmod's own took real design
  around a single flat identifier namespace; usermod's per-port option
  shapes (UnixBuildOptions/WindowsBuildOptions/QemuBuildOptions/
  WebassemblyBuildOptions/Esp32BuildOptions, usermod/build.py) are not
  uniform enough to reuse it unmodified, and extending it properly is
  its own slice of work, not attempted here.
- No `CIBMP_*` environment overrides for `[usermod]`'s own keys (`ports`,
  `module-dir`, `manifest`, `build`, `skip`, `extra-make-args`) -- only
  `micropython`/`output-dir`, genuinely shared with natmod, are read the
  same env-aware way `options.py`'s own `opt()` does.

No `version`/`package.json` here at all: usermod output is a full port
binary meant to be flashed or run directly, not a `.mpy` `mip.install()`
target -- D14's packaging step does not apply (confirmed with the user
directly before building this, not assumed either way).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..natmod.options import (
    DEFAULT_MICROPYTHON,
    DEFAULT_OUTPUT_DIR,
    check_table_keys,
    read_config,
)
from ..natmod.targets import parse_selector
from .targets import KNOWN_PORTS, UsermodTarget, axis_key, select, usermod_targets

DEFAULT_MODULE_DIR = "usermod"

# Keys `[usermod]` itself may carry. `build`/`skip` are **not** here: as
# of record 0048 they are top-level in both modes, and their presence in
# this table is diagnosed on its own (see `load()`), not as an unknown
# key -- the tool knows exactly what they mean, just not here.
USERMOD_TABLE_KEYS: frozenset[str] = frozenset(
    {
        "ports",
        "module-dir",
        "manifest",
        "extra-make-args",
    }
)

# Accepted in `[usermod]` but reported: the placement record 0048 is
# retiring. Kept working rather than removed outright because it was the
# documented one for every usermod config written so far, even though a
# sweep of the configs in reach found none actually using it.
DEPRECATED_USERMOD_TABLE_KEYS: frozenset[str] = frozenset({"build", "skip"})

__all__ = [
    "UsermodBuildOptions",
    "UsermodOptions",
]


class UsermodConfigError(Exception):
    pass


def _selector(
    raw: Mapping[str, Any], usermod: Mapping[str, Any], key: str, default: str
) -> Any:
    """`build`/`skip`, from the top level, with the old `[usermod]`
    placement still honoured and reported.

    Record 0048: this key used to be read *only* from `[usermod]` here
    and *only* from the top level in natmod mode, so the same key meant
    the same thing and was read from opposite places, and putting it in
    the other one produced no diagnostic at all. Top level is canonical
    now, in both modes.

    The old placement keeps working rather than breaking, but it says so:
    every usermod config written so far was told to use it. When both are
    present the top level wins, because that is the one this tool will
    still read next year.
    """
    env_value = os.environ.get("CIBMP_" + key.upper())
    if env_value is not None:
        return env_value
    if key in usermod:
        # stderr, not stdout: `--print-build-identifiers` and
        # `--print-build-matrix` write machine-readable output there, and
        # cibuildmp-matrix's own action does `json.loads()` on it. A
        # warning on stdout would not merely be noise, it would corrupt a
        # matrix -- caught by a test asserting the exact stdout of a
        # --print-build-identifiers run.
        print(
            f"cibuildmp: warning: `{key}` in [usermod] is deprecated -- it is "
            f"read from the top level of the config now, the same place "
            f"natmod already read it from (record 0048). Move it above the "
            f"[usermod] line."
            + ("  The top-level value is the one being used." if key in raw else ""),
            file=sys.stderr,
        )
        if key not in raw:
            return usermod[key]
    return raw.get(key, default)


def _as_list(value: Any, key: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    raise UsermodConfigError(f"{key}: expected a list, got {type(value).__name__}")


@dataclass
class UsermodBuildOptions:
    """Ingredients for one target's build, not yet the port-specific
    `*BuildOptions` `usermod/build.py` wants -- `usermod/orchestrate.py`
    resolves `manifest`/`module_dir` into real filesystem paths (writing
    the combined manifest text, picking a build directory) and builds
    the actual `UnixBuildOptions`/etc. from these, the same split
    `options.BuildOptions` -> `build.build_target()` already has for
    natmod (nothing here touches the filesystem)."""

    target: UsermodTarget
    micropython: str
    module_dir: str
    manifest: str
    extra_make_args: list[str] = field(default_factory=list)

    @property
    def identifier(self) -> str:
        return self.target.identifier

    @property
    def port(self) -> str:
        return self.target.port


@dataclass
class UsermodOptions:
    """The whole `[usermod]` config, before it is narrowed to a single
    target."""

    package_dir: Path
    config_path: Path | None
    micropython: str
    output_dir: Path
    ports: list[str]
    module_dir: str
    manifest: str
    build: list[str]
    skip: list[str]
    extra_make_args: list[str]
    axis_overrides: dict[str, list[str]]

    @classmethod
    def load(
        cls,
        package_dir: Path,
        config_file: Path | None = None,
        preread: tuple[Path | None, dict[str, Any]] | None = None,
    ) -> UsermodOptions:
        """`preread`, when given, is `(config_path, raw)` the caller
        already got from `read_config()` -- `cli.py`'s own mode-detection
        peek has to read the file once to decide natmod vs usermod, so
        this avoids reading and parsing the same TOML file a second
        time."""
        if preread is None:
            config_path, raw = read_config(package_dir, config_file)
        else:
            config_path, raw = preread

        usermod = dict(raw.get("usermod") or {})

        check_table_keys(
            usermod,
            where="[usermod]",
            known=USERMOD_TABLE_KEYS,
            error=UsermodConfigError,
            # Per-port sub-tables are validated below, once `ports` is
            # known; `build`/`skip` are diagnosed as a placement further
            # down. Neither is an unknown key.
            allowed_extra=frozenset(KNOWN_PORTS) | DEPRECATED_USERMOD_TABLE_KEYS,
        )

        # Environment beats the file for the two genuinely shared
        # top-level keys, the same way `options.py`'s own `opt()` does.
        # This module's docstring has claimed as much since it was
        # written; the code read `raw` directly and consulted no
        # environment at all, so `CIBMP_MICROPYTHON` and
        # `CIBMP_OUTPUT_DIR` silently did nothing in usermod mode while
        # working in natmod mode. Found by the record 0048 audit, which
        # went looking for exactly this shape -- a key that looks
        # honoured and is not -- and is the same defect as the one that
        # record is named for, one layer up.
        def opt(key: str, default: Any = None) -> Any:
            env_value = os.environ.get("CIBMP_" + key.replace("-", "_").upper())
            if env_value is not None:
                return env_value
            return raw.get(key, default)

        # micropython is a genuinely shared top-level key (D13: natmod's
        # own tag_groups() lets it be a list, for spanning an ABI
        # boundary -- a concept usermod has no equivalent of). Take the
        # first entry when it is one, same "whichever came first" rule
        # tag_groups() itself already uses, rather than str()-ing a
        # Python list into nonsense.
        micropython_value = opt("micropython", DEFAULT_MICROPYTHON)
        if isinstance(micropython_value, list):
            micropython_value = (
                micropython_value[0] if micropython_value else DEFAULT_MICROPYTHON
            )

        ports_value = usermod.get("ports")
        ports = (
            _as_list(ports_value, "ports")
            if ports_value is not None
            else list(KNOWN_PORTS)
        )

        axis_overrides: dict[str, list[str]] = {}
        for port in ports:
            port_table = usermod.get(port)
            if not isinstance(port_table, dict):
                continue
            key = axis_key(port)
            if key is None:
                if port_table:
                    raise UsermodConfigError(
                        f"[usermod.{port}]: this port has no configurable axis "
                        f"yet, but the table is not empty"
                    )
                continue
            check_table_keys(
                port_table,
                where=f"[usermod.{port}]",
                known=frozenset({key}),
                error=UsermodConfigError,
            )
            if key in port_table:
                axis_overrides[port] = _as_list(
                    port_table[key], f"usermod.{port}.{key}"
                )

        return cls(
            package_dir=package_dir,
            config_path=config_path,
            micropython=str(micropython_value),
            output_dir=Path(str(opt("output-dir", DEFAULT_OUTPUT_DIR))),
            ports=ports,
            module_dir=str(usermod.get("module-dir", DEFAULT_MODULE_DIR)),
            manifest=str(usermod.get("manifest", "")),
            build=parse_selector(_selector(raw, usermod, "build", "*")),
            skip=parse_selector(_selector(raw, usermod, "skip", "")),
            extra_make_args=_as_list(
                usermod.get("extra-make-args"), "usermod.extra-make-args"
            ),
            axis_overrides=axis_overrides,
        )

    def targets(self) -> list[UsermodTarget]:
        all_targets = usermod_targets(self.ports, self.axis_overrides)
        return select(all_targets, self.build, self.skip)

    def build_options(self, target: UsermodTarget) -> UsermodBuildOptions:
        return UsermodBuildOptions(
            target=target,
            micropython=self.micropython,
            module_dir=self.module_dir,
            manifest=self.manifest,
            extra_make_args=list(self.extra_make_args),
        )

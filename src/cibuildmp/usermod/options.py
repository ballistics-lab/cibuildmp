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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..natmod.options import DEFAULT_MICROPYTHON, DEFAULT_OUTPUT_DIR, read_config
from ..natmod.targets import parse_selector
from .targets import KNOWN_PORTS, UsermodTarget, axis_key, select, usermod_targets

DEFAULT_MODULE_DIR = "usermod"

__all__ = [
    "UsermodBuildOptions",
    "UsermodOptions",
]


class UsermodConfigError(Exception):
    pass


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

        # micropython is a genuinely shared top-level key (D13: natmod's
        # own tag_groups() lets it be a list, for spanning an ABI
        # boundary -- a concept usermod has no equivalent of). Take the
        # first entry when it is one, same "whichever came first" rule
        # tag_groups() itself already uses, rather than str()-ing a
        # Python list into nonsense.
        micropython_value = raw.get("micropython", DEFAULT_MICROPYTHON)
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
            if key in port_table:
                axis_overrides[port] = _as_list(
                    port_table[key], f"usermod.{port}.{key}"
                )

        return cls(
            package_dir=package_dir,
            config_path=config_path,
            micropython=str(micropython_value),
            output_dir=Path(str(raw.get("output-dir", DEFAULT_OUTPUT_DIR))),
            ports=ports,
            module_dir=str(usermod.get("module-dir", DEFAULT_MODULE_DIR)),
            manifest=str(usermod.get("manifest", "")),
            build=parse_selector(usermod.get("build", "*")),
            skip=parse_selector(usermod.get("skip", "")),
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

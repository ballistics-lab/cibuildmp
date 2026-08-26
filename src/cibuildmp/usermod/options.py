"""Usermod config loading: the `[usermod]` table (and its per-port
`[usermod.<port>]` sub-tables), read the same way `options.py` reads
`[natmod]` -- D5's own "config is scoped by build mode, the way
cibuildwheel scopes by platform" -- but genuinely a separate tree, not a
second copy-paste of `Options`: usermod's own axes (which ports, which
per-port arch/board) don't fit natmod's single flat `archs` list at all.

Deliberately narrower than `Options` for now, not an oversight:
- `[[usermod.overrides]]` (**0051** point 7) is its own, nested array --
  not a share of natmod's top-level `[[overrides]]`, since the two modes'
  override tables accept different keys and a config with both `[natmod]`
  and `[usermod]` tables would otherwise need one shared list whose keys
  mean different things depending which mode reads it. Narrower than
  natmod's own: no `variant` (a real field on three of five ports'
  `*BuildOptions`, still config-surface-less) yet.
- `CIBMP_*` environment overrides exist for `module-dir`/`manifest`/
  `extra-make-args` at `build_options()`'s own per-target resolution
  (mirroring natmod's `file -> override -> environment` cascade), and for
  `micropython`/`output-dir`/`enable`, genuinely shared with natmod, at
  `load()`'s own top-level `opt()`. `ports`/`build`/`skip` still have
  none at `load()` -- `ports` because axis selection has no per-target
  meaning to layer an env override onto, `build`/`skip` because they are
  already top-level-shared keys read through `options.py`'s own `opt()`
  (record 0048).

No `version`/`package.json` here at all: usermod output is a full port
binary meant to be flashed or run directly, not a `.mpy` `mip.install()`
target -- D14's packaging step does not apply (confirmed with the user
directly before building this, not assumed either way).
"""

from __future__ import annotations

import os
import shlex
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
from ..selector import matches, parse_selector, select
from .targets import (
    DEFAULT_PORTS,
    GROUPS,
    KNOWN_PORTS,
    UsermodTarget,
    axis_key,
    usermod_targets,
)

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
        "overrides",
    }
)

# Accepted in `[usermod]` but reported: the placement record 0048 is
# retiring. Kept working rather than removed outright because it was the
# documented one for every usermod config written so far, even though a
# sweep of the configs in reach found none actually using it.
DEPRECATED_USERMOD_TABLE_KEYS: frozenset[str] = frozenset({"build", "skip"})

# `[[usermod.overrides]]` (**0051** point 7) -- usermod's own, nested
# under `[usermod]` rather than sharing natmod's top-level
# `[[overrides]]`, because the two modes' override tables accept
# different keys and a config with both `[natmod]` and `[usermod]`
# tables (a real shape -- see examples/template/cibuildmp.toml) would
# otherwise need one shared list whose keys mean different things
# depending which mode reads it. `variant` (a real field on
# UnixBuildOptions/WebassemblyBuildOptions/WindowsBuildOptions, fixed
# today, no config surface at all) is deliberately not here yet --
# wiring it needs orchestrate._port_build_options() to pass it through
# per port, its own smaller follow-up.
USERMOD_OVERRIDE_TABLE_KEYS: frozenset[str] = frozenset(
    {"select", "module-dir", "manifest", "extra-make-args"}
)

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
        # `--print-build-identifiers --json` write machine-readable
        # output there, and callers parse it. A
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


def _as_list_or_str(value: Any, key: str) -> list[str]:
    """Like `_as_list()`, but a string is shell-split rather than
    rejected -- for `build_options()`'s own per-target resolution, where
    a value can come from the environment (always a string) as well as
    the file, the same shape natmod's own `_as_list` already has. Every
    other `_as_list()` call site here stays strict: `ports`/axis values
    coming from the file as a bare string is a real config mistake worth
    catching, not something the environment layer needs to produce."""
    if isinstance(value, str):
        return shlex.split(value)
    return _as_list(value, key)


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
    micropython: list[str]
    output_dir: Path
    ports: list[str]
    module_dir: str
    manifest: str
    build: list[str]
    skip: list[str]
    extra_make_args: list[str]
    axis_overrides: dict[str, list[str]]
    # [[usermod.overrides]] tables (0051 point 7) -- not axis_overrides
    # above (which port/arch a config selects), per-target *option*
    # overrides layered over module-dir/manifest/extra-make-args, the
    # same "file -> matching [[overrides]] -> environment" shape
    # natmod's own Options.build_options() already has.
    overrides: list[dict[str, Any]] = field(default_factory=list)
    # Names in GROUPS (0051 point 8) that build = "*" should reach anyway
    # -- e.g. enable = ["unix-emulated-everywhere"]. Validated against
    # GROUPS.keys() in targets(), not at load() time, since CLI --enable
    # (usermod/cli.py) still needs to union into this after load().
    enable: frozenset[str] = frozenset()

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

        # micropython is a genuinely shared top-level key, and a real list
        # now (**0051**): usermod's identifier gained a leading tag slot
        # specifically so more than one release can be selected in one
        # invocation without one overwriting another's output. Before
        # this record it was silently truncated to its first entry --
        # the only thing standing between a two-tag config and a
        # collision, since nothing distinguished the two releases'
        # outputs. Accepts the same shapes natmod's own list-valued
        # options do: a TOML list, or a string (file or environment)
        # split on whitespace.
        micropython_value = opt("micropython", DEFAULT_MICROPYTHON)
        if isinstance(micropython_value, list):
            micropython = [str(v) for v in micropython_value] or [DEFAULT_MICROPYTHON]
        else:
            micropython = str(micropython_value).split() or [DEFAULT_MICROPYTHON]

        ports_value = usermod.get("ports")
        ports = (
            _as_list(ports_value, "ports")
            if ports_value is not None
            else list(DEFAULT_PORTS)
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

        overrides = list(usermod.get("overrides") or [])
        if not isinstance(overrides, list):
            raise UsermodConfigError("[usermod] overrides must be an array of tables")
        for override in overrides:
            if isinstance(override, dict):
                check_table_keys(
                    override,
                    where="[[usermod.overrides]]",
                    known=USERMOD_OVERRIDE_TABLE_KEYS,
                    error=UsermodConfigError,
                )

        return cls(
            package_dir=package_dir,
            config_path=config_path,
            micropython=micropython,
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
            overrides=overrides,
            enable=frozenset(parse_selector(opt("enable"))),
        )

    def targets(self) -> list[UsermodTarget]:
        unknown = self.enable - GROUPS.keys()
        if unknown:
            raise UsermodConfigError(
                f"enable: unknown group(s) {', '.join(sorted(unknown))}. Known: "
                f"{', '.join(sorted(GROUPS))}"
            )
        all_targets = usermod_targets(self.micropython, self.ports, self.axis_overrides)
        return select(all_targets, self.build, self.skip, enable=self.enable, groups=GROUPS)

    def build_options(
        self, target: UsermodTarget, env: Mapping[str, str] | None = None
    ) -> UsermodBuildOptions:
        """Resolve per-target options: file -> matching
        [[usermod.overrides]] -> environment -- the same shape natmod's
        own Options.build_options() already has (0051 point 7)."""
        environ: Mapping[str, str] = os.environ if env is None else env

        layers: list[dict[str, Any]] = [
            {
                "module-dir": self.module_dir,
                "manifest": self.manifest,
                "extra-make-args": list(self.extra_make_args),
            }
        ]
        for override in self.overrides:
            selector = override.get("select")
            if selector is None:
                raise UsermodConfigError(
                    "every [[usermod.overrides]] table needs a `select` key"
                )
            if matches(target.identifier, parse_selector(selector)):
                layers.append(override)

        def opt(key: str, default: Any = None) -> Any:
            env_value = environ.get("CIBMP_" + key.replace("-", "_").upper())
            if env_value is not None:
                return env_value
            # Later layers win: a matching override beats the file.
            for layer in reversed(layers):
                if key in layer:
                    return layer[key]
            return default

        return UsermodBuildOptions(
            target=target,
            micropython=target.tag,
            module_dir=str(opt("module-dir", DEFAULT_MODULE_DIR)),
            manifest=str(opt("manifest", "")),
            extra_make_args=_as_list_or_str(opt("extra-make-args"), "extra-make-args"),
        )

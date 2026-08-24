"""Config loading and option resolution.

Precedence, lowest to highest:
    defaults -> config file -> matching [[overrides]] -> environment -> CLI

Config lives in cibuildmp.toml at the package root, with the same tree
accepted under [tool.cibuildmp] in pyproject.toml for the rare MicroPython
C-module repo that has one. cibuildmp.toml wins when both exist.
"""

from __future__ import annotations

import os
import shlex
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .targets import (
    NATMOD_ARCHS,
    Target,
    matches,
    natmod_targets,
    parse_selector,
    resolve_micropython_tags,
    select,
)

CONFIG_FILENAME = "cibuildmp.toml"

DEFAULT_MICROPYTHON = "v1.28.0"
DEFAULT_OUTPUT_DIR = "mpyhouse"
DEFAULT_MODULE_DIR = "natmod"
DEFAULT_MAKE_TARGET = "dist"


class ConfigError(Exception):
    pass


def _as_list(value: Any, key: str) -> list[str]:
    """Accept a list, or a shell-ish string, for list-valued options.

    The string form exists for the environment layer -- CIBMP_EXTRA_MAKE_ARGS
    can only ever be a string -- and is accepted in the file too so the two
    layers do not disagree about what a valid value looks like.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return shlex.split(value)
    if isinstance(value, list):
        return [str(v) for v in value]
    raise ConfigError(f"{key}: expected a list or a string, got {type(value).__name__}")


@dataclass
class BuildOptions:
    """Fully resolved options for a single target."""

    target: Target
    micropython: str
    output_dir: Path
    module_dir: str
    make_target: str
    runs_on: str = ""
    extra_make_args: list[str] = field(default_factory=list)
    pre_build_command: str = ""

    @property
    def identifier(self) -> str:
        return self.target.identifier


@dataclass
class Options:
    """The whole config, before it is narrowed to a single target."""

    package_dir: Path
    config_path: Path | None
    micropython: list[str]
    output_dir: Path
    build: list[str]
    skip: list[str]
    archs: list[str]
    micropython_submodules: list[str]
    mpy_abi: str | None
    natmod: dict[str, Any]
    overrides: list[dict[str, Any]]

    # ── Loading ───────────────────────────────────────────────────────────

    @classmethod
    def load(
        cls,
        package_dir: Path,
        config_file: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Options:
        environ: Mapping[str, str] = os.environ if env is None else env
        config_path, raw = _read_config(package_dir, config_file)

        natmod = dict(raw.get("natmod") or {})
        overrides = list(raw.get("overrides") or [])
        if not isinstance(overrides, list):
            raise ConfigError("[[overrides]] must be an array of tables")

        def opt(key: str, default: Any = None) -> Any:
            # Environment beats the file for every global option. Keys are
            # kebab-case in TOML (matching cibuildwheel) and
            # CIBMP_SCREAMING_SNAKE in the environment.
            env_value = environ.get("CIBMP_" + key.replace("-", "_").upper())
            if env_value is not None:
                return env_value
            return raw.get(key, default)

        archs_value = opt("archs") or natmod.get("archs") or list(NATMOD_ARCHS)

        return cls(
            package_dir=package_dir,
            config_path=config_path,
            micropython=_as_list(
                opt("micropython", DEFAULT_MICROPYTHON), "micropython"
            ),
            output_dir=Path(str(opt("output-dir", DEFAULT_OUTPUT_DIR))),
            build=parse_selector(opt("build", "*")),
            skip=parse_selector(opt("skip", "")),
            archs=_as_list(archs_value, "archs"),
            micropython_submodules=_as_list(
                opt("micropython-submodules"), "micropython-submodules"
            ),
            mpy_abi=(str(opt("mpy-abi")) if opt("mpy-abi") is not None else None),
            natmod=natmod,
            overrides=overrides,
        )

    # ── Resolution ────────────────────────────────────────────────────────

    def tag_groups(self) -> list[tuple[str, str]]:
        """One (tag, abi) pair per distinct ABI `micropython` resolves to.

        See resolve_micropython_tags(): almost always a single pair, since
        that is the common case (**D13**), but never fewer than the number
        of distinct ABIs actually requested.
        """
        return resolve_micropython_tags(self.micropython, self.mpy_abi)

    def targets(self) -> list[Target]:
        """Every target this config selects.

        One ABI group per `tag_groups()` entry, archs in NATMOD_ARCHS order
        within each group.
        """
        all_targets = [
            target
            for tag, abi in self.tag_groups()
            for target in natmod_targets(self.archs, abi, tag)
        ]
        return select(all_targets, self.build, self.skip)

    def build_options(
        self, target: Target, env: Mapping[str, str] | None = None
    ) -> BuildOptions:
        """Resolve per-target options: file -> overrides -> environment."""
        environ: Mapping[str, str] = os.environ if env is None else env

        layers: list[dict[str, Any]] = [self.natmod]
        for override in self.overrides:
            selector = override.get("select")
            if selector is None:
                raise ConfigError("every [[overrides]] table needs a `select` key")
            if matches(target.identifier, parse_selector(selector)):
                layers.append(override)

        def opt(key: str, default: Any = None) -> Any:
            env_value = environ.get("CIBMP_" + key.replace("-", "_").upper())
            if env_value is not None:
                return env_value
            # Later layers win: a matching override beats [natmod].
            for layer in reversed(layers):
                if key in layer:
                    return layer[key]
            return default

        return BuildOptions(
            target=target,
            micropython=target.tag,
            output_dir=self.output_dir,
            module_dir=str(opt("module-dir", DEFAULT_MODULE_DIR)),
            make_target=str(opt("make-target", DEFAULT_MAKE_TARGET)),
            runs_on=str(opt("runs-on", target.default_runner)),
            extra_make_args=_as_list(opt("extra-make-args"), "extra-make-args"),
            pre_build_command=str(opt("pre-build-command", "")),
        )


def _read_config(
    package_dir: Path, config_file: Path | None
) -> tuple[Path | None, dict[str, Any]]:
    if config_file is not None:
        if not config_file.is_file():
            raise ConfigError(f"config file not found: {config_file}")
        return config_file, _load_toml_tree(config_file)

    standalone = package_dir / CONFIG_FILENAME
    if standalone.is_file():
        return standalone, _load_toml_tree(standalone)

    pyproject = package_dir / "pyproject.toml"
    if pyproject.is_file():
        with pyproject.open("rb") as f:
            data = tomllib.load(f)
        tool = (data.get("tool") or {}).get("cibuildmp")
        if tool is not None:
            return pyproject, dict(tool)

    # No config at all is legitimate: every option has a default, so a repo
    # following the conventional natmod/ layout builds with none.
    return None, {}


def _load_toml_tree(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        data = tomllib.load(f)
    if path.name == "pyproject.toml":
        return dict((data.get("tool") or {}).get("cibuildmp") or {})
    return data

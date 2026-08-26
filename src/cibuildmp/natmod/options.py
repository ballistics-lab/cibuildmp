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
    parse_arch_flags,
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
    arch_flags: list[str]
    version: str
    natmod: dict[str, Any]
    overrides: list[dict[str, Any]]
    publish: dict[str, Any]

    # ── Loading ───────────────────────────────────────────────────────────

    @classmethod
    def load(
        cls,
        package_dir: Path,
        config_file: Path | None = None,
        env: Mapping[str, str] | None = None,
        preread: tuple[Path | None, dict[str, Any]] | None = None,
    ) -> Options:
        """`preread`, when given, is `(config_path, raw)` the caller
        already got from `read_config()` -- `cli.py`'s own mode-detection
        peek has to read the file once to decide natmod vs usermod
        (usermod/options.py's `UsermodOptions.load()` takes the same
        parameter, for the same reason), so this avoids reading and
        parsing the same TOML file a second time on the natmod path.
        """
        environ: Mapping[str, str] = os.environ if env is None else env
        config_path, raw = (
            preread if preread is not None else read_config(package_dir, config_file)
        )

        natmod = dict(raw.get("natmod") or {})
        overrides = list(raw.get("overrides") or [])
        if not isinstance(overrides, list):
            raise ConfigError("[[overrides]] must be an array of tables")
        publish = dict(raw.get("publish") or {})

        def opt(key: str, default: Any = None) -> Any:
            # Environment beats the file for every global option. Keys are
            # kebab-case in TOML (matching cibuildwheel) and
            # CIBMP_SCREAMING_SNAKE in the environment.
            env_value = environ.get("CIBMP_" + key.replace("-", "_").upper())
            if env_value is not None:
                return env_value
            return raw.get(key, default)

        archs_value = opt("archs") or natmod.get("archs") or list(NATMOD_ARCHS)
        arch_flags_value = opt("arch-flags") or natmod.get("arch-flags") or []

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
            arch_flags=_as_list(arch_flags_value, "arch-flags"),
            version=str(opt("version", "")),
            natmod=natmod,
            overrides=overrides,
            publish=publish,
        )

    # ── Resolution ────────────────────────────────────────────────────────

    def tag_groups(self) -> list[tuple[str, str]]:
        """One (tag, abi) pair per distinct ABI `micropython` resolves to.

        See resolve_micropython_tags(): almost always a single pair, since
        that is the common case (**D13**), but never fewer than the number
        of distinct ABIs actually requested.
        """
        return resolve_micropython_tags(self.micropython, self.mpy_abi)

    def extra_files(self) -> list[str]:
        """`[publish] extra-files` -- files copied into every identifier's
        own output directory alongside its `.mpy`, for a facade or anything
        else meant to install regardless of target arch (**D14**)."""
        return _as_list(self.publish.get("extra-files"), "extra-files")

    def targets(self) -> list[Target]:
        """Every target this config selects.

        One ABI group per `tag_groups()` entry, archs in NATMOD_ARCHS order
        within each group. `arch_flags` (rv32imc only) is resolved here,
        before selection, since it is part of the identifier that
        `build`/`skip`/`[[overrides]]` glob against. A list produces one
        rv32imc target *per entry* -- "build every arch-flags variant" is
        its own request, distinct from "build every arch", so
        `arch-flags = ["", "zba,zcmp"]` is two rv32imc identifiers, not one.
        """
        arch_flags = (
            [parse_arch_flags("rv32imc", value) for value in self.arch_flags]
            if self.arch_flags
            else [0]
        )
        all_targets = [
            target
            for tag, abi in self.tag_groups()
            for target in natmod_targets(self.archs, abi, tag, arch_flags)
        ]
        return select(all_targets, self.build, self.skip)

    def all_targets(self) -> list[Target]:
        """Every identifier this config can name, ignoring `archs`,
        `build` and `skip` -- what `--only` resolves against (**0045**).

        Upstream's `--only` takes its `choices` from `read_all_configs()`,
        i.e. from what exists rather than from what is selected. The
        natmod analogue is not quite that, and the difference is real
        rather than a shortcut: an identifier's ABI slot (`mpy6.3-`) comes
        from the `MPY_VERSION`/`MPY_SUB_VERSION` of an actual MicroPython
        checkout, so the set of nameable identifiers genuinely depends on
        this config's own `micropython` key and cannot be enumerated
        without it. `tag_groups()` therefore stays; `archs`, `build` and
        `skip` -- which are selection, not existence -- do not.

        `arch_flags` stays for the same reason as `tag_groups()`: **D15**
        made a `+0x..` suffix part of the identifier, and which variants
        exist is a config statement ("build every arch-flags variant" is
        its own request), not a filter over a fixed set.
        """
        arch_flags = (
            [parse_arch_flags("rv32imc", value) for value in self.arch_flags]
            if self.arch_flags
            else [0]
        )
        return [
            target
            for tag, abi in self.tag_groups()
            for target in natmod_targets(list(NATMOD_ARCHS), abi, tag, arch_flags)
        ]

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

        extra_make_args = _as_list(opt("extra-make-args"), "extra-make-args")
        if target.arch_flags:
            # The packed int as hex, not the config's own raw string: with
            # arch-flags now a list (one rv32imc Target per entry), the
            # Target itself is the only place that still knows which entry
            # produced it. mpy_ld.py's validate_arch_flags() accepts a
            # numeric string exactly as well as a named-flag list, so this
            # round-trips to the same value either way.
            extra_make_args = [
                f"ARCH_FLAGS=0x{target.arch_flags:x}",
                *extra_make_args,
            ]

        return BuildOptions(
            target=target,
            micropython=target.tag,
            output_dir=self.output_dir,
            module_dir=str(opt("module-dir", DEFAULT_MODULE_DIR)),
            make_target=str(opt("make-target", DEFAULT_MAKE_TARGET)),
            runs_on=str(opt("runs-on", target.default_runner)),
            extra_make_args=extra_make_args,
            pre_build_command=str(opt("pre-build-command", "")),
        )


def read_config(
    package_dir: Path, config_file: Path | None
) -> tuple[Path | None, dict[str, Any]]:
    """The raw parsed `cibuildmp.toml`/`[tool.cibuildmp]` tree, before any
    mode-specific interpretation. Public (not `Options.load()`-internal)
    so `cli.py` can peek at which top-level tables (`natmod`/`usermod`)
    are present to auto-detect build mode, and so `usermod/options.py`
    can read the same file without a second, differently-shaped parser.
    """
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

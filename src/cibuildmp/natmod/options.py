"""Config loading and option resolution.

Precedence, lowest to highest:
    defaults -> global config -> platform config -> matching [[overrides]]
    -> environment -> CLI

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

from ..options import Options as OptionCascade
from ..options import suggest
from ..selector import matches, parse_selector, select
from .targets import (
    NATMOD_ARCHS,
    Target,
    natmod_targets,
    parse_arch_flags,
    resolve_abi_selector,
    resolve_micropython_tags,
)

CONFIG_FILENAME = "cibuildmp.toml"

DEFAULT_MICROPYTHON = "v1.29.0"
DEFAULT_OUTPUT_DIR = "mpyhouse"
DEFAULT_MODULE_DIR = "natmod"
DEFAULT_MAKE_TARGET = "dist"


class ConfigError(Exception):
    pass


# ── option schemas (Phase F, record 0051 points 4/6) ───────────────────
#
# Record 0048 fixed "a key placed in the wrong table is silently ignored"
# by giving every key exactly one correct location and erroring on every
# other (`TOP_LEVEL_ONLY_KEYS`, `NATMOD_TABLE_KEYS`, `check_table_keys()`).
# That does not generalise to six platforms sharing option keys, so this
# phase replaces the partition with a cascade
# (`default -> global -> platform -> env`, `cibuildmp/options.py`): every
# platform-schema key is valid at the global level (that platform's own
# default) *and* inside that platform's own table (its override) -- there
# is no more "wrong table" for a key that belongs to some schema. What
# stays an error is a key that belongs to *no* schema at all (a typo), and
# a key that belongs to a *different* platform's schema, written inside a
# table that is not that platform's -- `check_keys()` below, replacing
# `check_table_keys()`.
#
# `enable` stays generic (top-level/global only, no per-platform meaning
# -- an invocation-wide identifier filter) even though only usermod
# defines any groups today, for the same reason it was in
# `TOP_LEVEL_ONLY_KEYS` before: a config surface with nothing to gate
# would be speculative, but listing the key means a misplaced `enable`
# inside `[natmod]` still gets a clear error instead of silently doing
# nothing.
GENERIC_KEYS: frozenset[str] = frozenset(
    {
        "micropython",
        "output-dir",
        "build",
        "skip",
        "version",
        "mpy-abi",
        "micropython-submodules",
        "enable",
    }
)

# Keys `[natmod]` itself, or the top level as natmod's own default, may
# carry: the two dual-read axis keys plus the four per-target ones
# `build_options()`'s own `opt()` layers over.
NATMOD_SCHEMA: frozenset[str] = frozenset(
    {
        "archs",
        "arch-flags",
        "module-dir",
        "make-target",
        "extra-make-args",
        "pre-build-command",
    }
)

# `[[overrides]]` layers over natmod's own per-target `opt()`, so it takes
# the same four keys plus its own `select`. Notably *not* `arch-flags`:
# that one is resolved once for the whole config, never per target, so an
# `arch-flags` in an override table would be silently ignored -- exactly
# the shape 0048 is about.
OVERRIDE_TABLE_KEYS: frozenset[str] = frozenset(
    {
        "select",
        "module-dir",
        "make-target",
        "extra-make-args",
        "pre-build-command",
    }
)


def check_keys(
    table: Mapping[str, Any],
    known: frozenset[str],
    *,
    where: str,
    error: type[Exception] = ConfigError,
) -> None:
    """Reject a key this table does not read -- the cascade-era
    replacement for record 0048's own `check_table_keys()`. Shared with
    `usermod/options.py`, which passes its own per-port schema and
    `UsermodConfigError`.

    A key that belongs to `GENERIC_KEYS` (read from the top level, for
    every platform, always) gets its own message naming where it should
    go, because "unknown key 'skip'" would be actively misleading about a
    key the tool very much knows. Anything else unknown to `known` is a
    genuine typo, with a `difflib`-suggested close match when one exists
    (the same library upstream's own `_validate_global_option()` uses).
    """
    for key in table:
        if key in known:
            continue
        if key in GENERIC_KEYS:
            raise error(
                f"{where}: `{key}` is read from the top level of the config, "
                f"not from {where} -- move it above the {where} line. It "
                f"applies to the whole invocation rather than to one "
                f"platform, so there is only one place it can mean anything."
            )
        msg = f"{where}: unknown key `{key}`. Known keys here: {', '.join(sorted(known))}."
        hint = suggest(key, known)
        if hint:
            msg += f" Perhaps you meant `{hint}`?"
        raise error(msg)


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


def _parse_mpy_abi(value: Any) -> str | list[str] | None:
    """`mpy-abi` is dual-shape (0051). A single value is the pre-0051
    override: force this one ABI onto every `micropython` tag, via
    `abi_for_tag()`'s own `override` parameter. More than one value --
    a TOML list, or (from the environment, which can only ever be a
    string) more than one whitespace-separated token -- states the axis
    directly: these are the ABIs to build, each resolved to its own
    newest known tag by `resolve_abi_selector()` instead of derived from
    `micropython`. A single-token string, whichever layer it came from,
    keeps meaning what it always has -- this is additive, not a breaking
    change to the override.
    """
    if value is None:
        return None
    if isinstance(value, list):
        return [str(v) for v in value]
    tokens = str(value).split()
    return tokens if len(tokens) > 1 else str(value)


@dataclass
class BuildOptions:
    """Fully resolved options for a single target."""

    target: Target
    micropython: str
    output_dir: Path
    module_dir: str
    make_target: str
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
    mpy_abi: str | list[str] | None
    arch_flags: list[str]
    version: str
    overrides: list[dict[str, Any]]
    publish: dict[str, Any]
    # The cascade instance backing build_options()'s own per-target
    # resolution of module-dir/make-target/extra-make-args/
    # pre-build-command -- env excluded here (build_options() checks the
    # environment itself, after overrides, matching the precedence it has
    # always had), platform_tables={"natmod": <the [natmod] table>}.
    _cascade_file: OptionCascade = field(repr=False, compare=False)

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
        already got from `read_config()` -- `cli.py`'s own platform-
        detection peek has to read the file once to decide which
        platforms are active (usermod/options.py's `UsermodOptions.load()`
        takes the same parameter, for the same reason), so this avoids
        reading and parsing the same TOML file a second time on the
        natmod path.
        """
        environ: Mapping[str, str] = os.environ if env is None else env
        config_path, raw = (
            preread if preread is not None else read_config(package_dir, config_file)
        )

        natmod_table = dict(raw.get("natmod") or {})
        overrides = list(raw.get("overrides") or [])
        if not isinstance(overrides, list):
            raise ConfigError("[[overrides]] must be an array of tables")
        publish = dict(raw.get("publish") or {})

        check_keys(natmod_table, NATMOD_SCHEMA, where="[natmod]")
        for override in overrides:
            if isinstance(override, dict):
                check_keys(override, OVERRIDE_TABLE_KEYS, where="[[overrides]]")

        platform_tables = {"natmod": natmod_table}
        cascade_env = OptionCascade(
            global_table=raw, platform_tables=platform_tables, env=environ
        )
        cascade_file = OptionCascade(
            global_table=raw, platform_tables=platform_tables, env={}
        )

        def opt(key: str, default: Any = None) -> Any:
            # Environment beats the file for every global option. Keys are
            # kebab-case in TOML (matching cibuildwheel) and
            # CIBMP_SCREAMING_SNAKE in the environment.
            env_value = environ.get("CIBMP_" + key.replace("-", "_").upper())
            if env_value is not None:
                return env_value
            return raw.get(key, default)

        # `archs`/`arch-flags` go through the real cascade now rather than
        # the old `opt(key) or natmod.get(key) or default` chain -- same
        # dual-read guarantee (both placements work), but platform now
        # beats global (matching upstream's own more-specific-wins rule,
        # and every other cascade-resolved key in this file) rather than
        # the old, incidental "top level beats [natmod]" order. Also
        # gains a `CIBMP_ARCHS_NATMOD`-style per-platform env override for
        # free.
        archs_value = cascade_env.get(
            "archs", platform="natmod", default=list(NATMOD_ARCHS)
        )
        arch_flags_value = cascade_env.get("arch-flags", platform="natmod", default=[])

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
            mpy_abi=_parse_mpy_abi(opt("mpy-abi")),
            arch_flags=_as_list(arch_flags_value, "arch-flags"),
            version=str(opt("version", "")),
            overrides=overrides,
            publish=publish,
            _cascade_file=cascade_file,
        )

    # ── Resolution ────────────────────────────────────────────────────────

    def tag_groups(self) -> list[tuple[str, str]]:
        """One (tag, abi) pair per distinct ABI this config selects.

        Two ways to state the axis (**0051**). If `mpy-abi` is a list, it
        names the ABIs directly -- `resolve_abi_selector()` resolves each
        to its own newest known tag, the direction `MPY_ABI` cannot run
        forwards. Otherwise `micropython`'s own tags are resolved to the
        ABI they produce (`resolve_micropython_tags()`, almost always a
        single pair since that is the common case -- **D13**), with
        `mpy-abi` as a bare string still available as a per-invocation
        override forcing one ABI onto every tag, unchanged from before
        this record.
        """
        if isinstance(self.mpy_abi, list):
            return resolve_abi_selector(self.mpy_abi)
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
        """Resolve per-target options: file (global -> [natmod]) ->
        overrides -> environment."""
        environ: Mapping[str, str] = os.environ if env is None else env

        base = {
            "module-dir": self._cascade_file.get(
                "module-dir", platform="natmod", default=DEFAULT_MODULE_DIR
            ),
            "make-target": self._cascade_file.get(
                "make-target", platform="natmod", default=DEFAULT_MAKE_TARGET
            ),
            "extra-make-args": self._cascade_file.get(
                "extra-make-args", platform="natmod", default=[]
            ),
            "pre-build-command": self._cascade_file.get(
                "pre-build-command", platform="natmod", default=""
            ),
        }
        layers: list[dict[str, Any]] = [base]
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
            # Later layers win: a matching override beats the file.
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
            extra_make_args=extra_make_args,
            pre_build_command=str(opt("pre-build-command", "")),
        )


def read_config(
    package_dir: Path, config_file: Path | None
) -> tuple[Path | None, dict[str, Any]]:
    """The raw parsed `cibuildmp.toml`/`[tool.cibuildmp]` tree, before any
    platform-specific interpretation. Public (not `Options.load()`-internal)
    so `cli.py` can peek at which top-level platform tables (`natmod`,
    `unix`, ...) are present to determine which platforms are active, and
    so `usermod/options.py` can read the same file without a second,
    differently-shaped parser.
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

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

from ...options import InheritRule, matching_overrides, override_extra_layers, suggest
from ...options import Options as OptionCascade
from ...selector import parse_selector, select
from .targets import (
    NATMOD_ARCHS,
    Target,
    all_tag_groups,
    archs_available_for,
    natmod_targets,
    newest_known_abi,
    resolve_arch_flags,
    validate_archs_recognized,
)

CONFIG_FILENAME = "cibuildmp.toml"

# Still natmod's own constant (usermod/options.py imports it too, for its
# own unrelated `micropython` key -- A2 is natmod-only) but no longer read
# by natmod's own load() below: the version axis has no config key any
# more, and `newest_known_abi()` -- derived from resources/build-
# platforms.toml, not a literal string needing a manual bump on every
# MicroPython release -- is what an unconfigured natmod `build` selector
# narrows to instead (record 0052, A2).
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

# ── merged [[overrides]] (Phase G) ──────────────────────────────────────
#
# Natmod's own top-level [[overrides]] and usermod's own
# [[usermod-overrides]] (Phase F) merge into one shared top-level
# [[overrides]] list here -- record 0051's own "Phase G". Two validation
# tiers: *loose*, at parse time (load_overrides() below, called by both
# this module's own Options.load() and usermod/options.py's
# UsermodOptions.load()) -- is this key valid for *any* platform's
# override surface at all, a typo check; and *strict*, at build_options()
# resolution time, once the matched identifier's own platform
# (target.port) is known -- is this key valid for *that* specific
# platform. The strict tier is what actually needs Target.port to exist
# for natmod too (natmod/targets.py).
NATMOD_OVERRIDE_OPTION_KEYS: frozenset[str] = frozenset(
    {"module-dir", "make-target", "extra-make-args", "pre-build-command"}
)

# A mirror of usermod/options.py's own USERMOD_PORT_BASE, restated here
# rather than imported: this module must not import usermod/options.py
# (usermod already imports from here -- check_keys, read_config, two
# constants -- and that direction stays one-way, natmod as the shared
# base every platform module imports from, never the reverse). Kept in
# sync by tests/test_overrides.py's own drift-guard test
# (OVERRIDE_UNION_KEYS >= USERMOD_PORT_BASE, importing both real
# constants), not by construction -- the same tradeoff natmod/targets.py
# already makes between NATMOD_ARCH_NATIVE_CODE and NATIVE_ARCH_CODE, two
# separately-named constants built from the same data for two call sites.
_USERMOD_OVERRIDE_OPTION_KEYS_MIRROR: frozenset[str] = frozenset(
    {"user-c-modules", "manifest", "extra-make-args"}
)

_OVERRIDE_META_KEYS: frozenset[str] = frozenset({"select", "inherit"})

# The tier-1 schema: every key valid on *some* platform's own override
# surface. Deliberately excludes `arch-flags` (resolved once for the
# whole config, never per target, so an override carrying it would be
# silently ignored -- exactly the shape 0048 is about) and every axis key
# (`archs`/`boards` -- resolved before any override can match).
OVERRIDE_UNION_KEYS: frozenset[str] = (
    NATMOD_OVERRIDE_OPTION_KEYS
    | _USERMOD_OVERRIDE_OPTION_KEYS_MIRROR
    | _OVERRIDE_META_KEYS
)

# The only option genuinely list-shaped across every platform's own
# override surface -- the one key `inherit` can name.
INHERITABLE_OVERRIDE_KEYS: frozenset[str] = frozenset({"extra-make-args"})


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


def _check_inherit(
    override: Mapping[str, Any], *, where: str, error: type[Exception]
) -> None:
    """`inherit = {extra-make-args = "append"}` -- validated at parse
    time, not deferred to `resolve_cascade()`'s own generic error: a bad
    `inherit` key can never become valid depending on which target later
    matches, so failing immediately is both cheaper to pin down and
    better UX (names the override, not just the eventual cascade call)."""
    inherit = override.get("inherit")
    if inherit is None:
        return
    if not isinstance(inherit, dict):
        raise error(
            f'{where}: inherit must be a table, e.g. {{"extra-make-args" = "append"}}'
        )
    for key, rule in inherit.items():
        if key not in INHERITABLE_OVERRIDE_KEYS:
            raise error(
                f"{where}: inherit={{{key} = ...}} -- inherit only applies to "
                f"list-valued options. Known: "
                f"{', '.join(sorted(INHERITABLE_OVERRIDE_KEYS))}."
            )
        if rule not in InheritRule.ALL:
            raise error(
                f"{where}: unknown inherit rule {rule!r} for {key!r}. Known: "
                f"{', '.join(sorted(InheritRule.ALL))}."
            )


def load_overrides(
    raw: Mapping[str, Any], *, error: type[Exception] = ConfigError
) -> list[dict[str, Any]]:
    """Parse and loosely (tier-1) validate the merged, top-level
    `[[overrides]]` list -- shared by every platform (Phase G). Called
    once by each of this module's own `Options.load()` and
    `usermod/options.py`'s `UsermodOptions.load()`, against the same
    already-parsed `raw` dict -- re-validating twice is cheap (dict-
    membership checks over an already-parsed, typically-short list, no
    I/O), not the "parsing the same file twice" this is written to
    avoid (`read_config()`/`preread` already solve that).
    """
    overrides = list(raw.get("overrides") or [])
    if not isinstance(overrides, list):
        raise error("[[overrides]] must be an array of tables")
    for override in overrides:
        if isinstance(override, dict):
            check_keys(
                override, OVERRIDE_UNION_KEYS, where="[[overrides]]", error=error
            )
            _check_inherit(override, where="[[overrides]]", error=error)
    return overrides


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
    output_dir: Path
    build: list[str]
    skip: list[str]
    archs: list[str]
    micropython_submodules: list[str]
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
        overrides = load_overrides(raw)
        publish = dict(raw.get("publish") or {})

        check_keys(natmod_table, NATMOD_SCHEMA, where="[natmod]")

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

        # No `micropython`/`mpy-abi` config key any more (record 0052, A2):
        # the version axis is a statically known domain (`all_tag_groups()`,
        # `targets.py`), narrowed by `build`/`skip` matching identifiers,
        # exactly like `archs` already narrows `NATMOD_ARCHS`. An
        # unconfigured `build` selector still keeps today's narrow default
        # -- only the newest known ABI -- by defaulting to
        # `f"mpy{newest_known_abi()}-*"` instead of `"*"`; an explicit
        # `build = "*"` (or `"mpy6.2-*"`, etc.) opens it up wider.
        default_build = f"mpy{newest_known_abi()}-*"

        return cls(
            package_dir=package_dir,
            config_path=config_path,
            output_dir=Path(str(opt("output-dir", DEFAULT_OUTPUT_DIR))),
            build=parse_selector(opt("build", default_build)),
            skip=parse_selector(opt("skip", "")),
            archs=_as_list(archs_value, "archs"),
            micropython_submodules=_as_list(
                opt("micropython-submodules"), "micropython-submodules"
            ),
            arch_flags=_as_list(arch_flags_value, "arch-flags"),
            version=str(opt("version", "")),
            overrides=overrides,
            publish=publish,
            _cascade_file=cascade_file,
        )

    # ── Resolution ────────────────────────────────────────────────────────

    def tag_groups(self) -> list[tuple[str, str]]:
        """One (tag, abi) pair per known ABI -- the full natmod version
        axis domain (record 0052, A2), each resolved to its own newest
        known tag. No `micropython`/`mpy-abi` config key states this any
        more; `build`/`skip` narrow it downstream by matching identifiers,
        the same way `archs` already narrows `NATMOD_ARCHS`.
        """
        return all_tag_groups()

    def extra_files(self) -> list[str]:
        """`[publish] extra-files` -- files copied into every identifier's
        own output directory alongside its `.mpy`, for a facade or anything
        else meant to install regardless of target arch (**D14**)."""
        return _as_list(self.publish.get("extra-files"), "extra-files")

    def targets(self) -> list[Target]:
        """Every target this config selects.

        One ABI group per `tag_groups()` entry -- every known ABI by
        default (record 0052, A2), each swept against `self.archs`
        (`NATMOD_ARCHS` by default) *intersected with* whatever that
        specific ABI's own tag actually has available
        (`archs_available_for()`). The intersection matters here and did
        not before A2: most ABIs predate at least one arch
        (`rv32imc`/`rv64imc`/`xtensawin` were all added over time), so
        sweeping every known ABI by default must not crash on the ones
        that cannot build everything -- it must simply contribute fewer
        targets for them, exactly as `select()` below then narrows the
        combined result to what `build`/`skip` actually asked for.
        `arch_flags` (rv32imc only) is resolved here, before selection,
        since it is part of the identifier that `build`/`skip`/
        `[[overrides]]` glob against. A list produces one rv32imc target
        *per entry* -- "build every arch-flags variant" is its own
        request, distinct from "build every arch", so
        `arch-flags = ["", "zba,zcmp"]` is two rv32imc identifiers, not
        one.
        """
        validate_archs_recognized(self.archs)
        arch_flags = resolve_arch_flags("rv32imc", self.arch_flags)
        all_targets = [
            target
            for tag, abi in self.tag_groups()
            for target in natmod_targets(
                [a for a in self.archs if a in archs_available_for(tag)],
                abi,
                tag,
                arch_flags,
            )
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
        which tags `resources/build-platforms.toml` has actually walked.
        `tag_groups()` therefore stays; `archs`, `build` and `skip` --
        which are selection, not existence -- do not, though the same
        per-tag intersection `targets()` needs still applies: an arch
        `NATMOD_ARCHS` lists but a given ABI's own tag does not have is
        not a *nameable* identifier for that ABI, so it is excluded here
        too rather than only filtered downstream.

        `arch_flags` stays for the same reason as `tag_groups()`: **D15**
        made a `+0x..` suffix part of the identifier, and which variants
        exist is a config statement ("build every arch-flags variant" is
        its own request), not a filter over a fixed set.
        """
        arch_flags = resolve_arch_flags("rv32imc", self.arch_flags)
        return [
            target
            for tag, abi in self.tag_groups()
            for target in natmod_targets(
                [a for a in NATMOD_ARCHS if a in archs_available_for(tag)],
                abi,
                tag,
                arch_flags,
            )
        ]

    def build_options(
        self, target: Target, env: Mapping[str, str] | None = None
    ) -> BuildOptions:
        """Resolve per-target options: file (global -> [natmod]) ->
        matching [[overrides]] (each layered per its own `inherit` rule)
        -> environment."""
        environ: Mapping[str, str] = os.environ if env is None else env

        matching = matching_overrides(
            self.overrides, target.identifier, error=ConfigError
        )
        for override in matching:
            option_keys = {
                k: v for k, v in override.items() if k not in {"select", "inherit"}
            }
            check_keys(
                option_keys,
                NATMOD_OVERRIDE_OPTION_KEYS,
                where=f"[[overrides]] matching {target.identifier!r} (platform 'natmod')",
            )

        def opt(key: str, default: Any = None) -> Any:
            env_value = environ.get("CIBMP_" + key.replace("-", "_").upper())
            if env_value is not None:
                return env_value
            return self._cascade_file.get(
                key,
                platform=target.port,
                default=default,
                extra_layers=override_extra_layers(matching, key),
            )

        extra_make_args = _as_list(opt("extra-make-args", []), "extra-make-args")
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

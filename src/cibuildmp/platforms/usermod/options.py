"""Usermod config loading: every port's own top-level table (`[unix]`,
`[windows]`, `[qemu]`, `[webassembly]`, `[esp32]`), sibling to `[natmod]`,
read the same cascade way `natmod/options.py` reads `[natmod]` (Phase F,
record 0051 points 4/6) -- but genuinely a separate tree, not a second
copy-paste of `Options`: usermod's own axes (which ports, which per-port
arch/board) don't fit natmod's single flat `archs` list at all.

`[usermod]` itself no longer exists as a concept -- every port table
used to nest under it (`[usermod.<port>]`) and carry a `ports = [...]`
list; now table presence alone selects a port, exactly the rule
`[natmod]`'s own presence has always followed. `cli.py`'s
`_reject_legacy_usermod_table()` is what turns a lingering `[usermod]`
into a loud, specific error before this module ever sees the config.

`[[overrides]]` is shared with natmod now (Phase G, record 0051's third
addendum) -- `natmod/options.py`'s own `load_overrides()` parses and
loosely validates the merged, top-level list once; each of natmod's and
this module's own `build_options()` does its own *strict*,
per-matched-platform validation at resolution time (`target.port` is what
makes that possible for natmod too). `inherit = {extra-make-args =
"append"|"prepend"|"none"}` lives per override table there too.

Deliberately narrower than `natmod/options.py`'s own `Options` still: no
`variant` (a real field on three of five ports' `*BuildOptions`, still
config-surface-less) yet.

`user-c-modules`/`manifest`/`extra-make-args` are genuinely global-with-
per-platform-override now (Phase F): resolved per target through the
same `cibuildmp.options.Options` cascade `natmod/options.py` uses, not
eagerly-resolved scalar fields shared by every selected port
unconditionally the way they were before this phase.

No `version`/`package.json` here at all: usermod output is a full port
binary meant to be flashed or run directly, not a `.mpy` `mip.install()`
target -- D14's packaging step does not apply (confirmed with the user
directly before building this, not assumed either way).
"""

from __future__ import annotations

import os
import shlex
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...options import Options as OptionCascade
from ...options import matching_overrides, override_extra_layers
from ...selector import parse_selector, select
from ..natmod.options import (
    DEFAULT_MICROPYTHON,
    DEFAULT_OUTPUT_DIR,
    check_keys,
    load_overrides,
    read_config,
)
from .targets import (
    GROUPS,
    KNOWN_PORTS,
    UsermodTarget,
    all_usermod_targets,
    axis_key,
    usermod_targets,
)

# "." (the project root), not a literal "usermod" subdirectory --
# record 0051's own sixth/ninth addenda. Broader, not narrower: py.mk's
# own `$(USER_C_MODULES)/*/micropython.mk` glob finds a module one level
# below whatever this points at, so "." still finds a real `usermod/`
# subdirectory exactly the way the old "usermod" default did, but also
# finds any other top-level directory holding a module, whatever it is
# named -- the same shape every real consumer this repo has seen
# (`examples/template`, micropython-bclibc, a7p) already configures by
# hand, because their own module dir sits beside sibling source (a
# `src/` this repo's own `examples/template` shares between natmod and
# usermod) that the narrower default's own bind-mount could not reach.
DEFAULT_USER_C_MODULES = "."

# Keys shared across every usermod port's own table -- the platform-
# specific axis key (`archs`/`boards`, from `axis_key(port)`) is added
# per port in `_port_schema()` below. `user-c-modules`, not `module-dir`
# -- natmod's own `module-dir` names the directory `make -C` runs in
# directly (it must contain that project's own Makefile); this key's
# value is instead forwarded as `USER_C_MODULES=` into the *MicroPython
# port's own* Makefile/CMake, a directory that never needs a Makefile of
# its own. Same underlying purpose ("point at your module's root"),
# different downstream consumer -- sharing one name with natmod's own
# key meant `examples/template/cibuildmp.toml` could not promote one
# shared default without silently overriding natmod's own "natmod"
# default at the same time (record 0051's sixth addendum). Named for the
# literal Makefile variable it feeds, the same principle `extra-make-args`
# already follows.
USERMOD_PORT_BASE: frozenset[str] = frozenset(
    {"user-c-modules", "manifest", "extra-make-args"}
)


def _port_schema(port: str) -> frozenset[str]:
    key = axis_key(port)
    return USERMOD_PORT_BASE | ({key} if key else frozenset())


# port name -> that port's own option-key schema, for `check_keys()`'s
# per-platform-table validation. A key valid for a *different* port's
# table (e.g. `make-target`, natmod-only) is still a loud, specific error
# -- validating against `SCHEMAS[port]` alone, never the union, is what
# keeps record 0048's original guarantee (misplaced key is never silent)
# under the cascade.
SCHEMAS: dict[str, frozenset[str]] = {port: _port_schema(port) for port in KNOWN_PORTS}

__all__ = [
    "UsermodBuildOptions",
    "UsermodOptions",
    "check_usermod_family_table",
]


class UsermodConfigError(Exception):
    pass


def check_usermod_family_table(
    raw: Mapping[str, Any], *, error: type[Exception] = UsermodConfigError
) -> dict[str, Any]:
    """Parse and validate `[usermod]` -- shared defaults for all five
    usermod ports at once (record 0051's ninth addendum), sibling to
    `[natmod]`, not a container over `[unix]`/`[esp32]`/etc. and not a
    selector: which ports are active is still table presence alone
    (Phase F), unchanged by this table's own presence or absence.

    Two failure shapes get distinct treatment. The pre-Phase-F shape --
    `ports = [...]`, or a nested `[usermod.<port>]` sub-table TOML parses
    as a dict value here -- means this config has not migrated at all,
    and gets a dedicated, specific message pointing at the real shape,
    the same courtesy `cli.py`'s own (now-removed) blanket `[usermod]`
    rejection used to give. Anything else unknown to `USERMOD_PORT_BASE`
    (a typo, a per-port axis key like `archs` written here instead of in
    its own port table) falls through to the ordinary `check_keys()`
    error.

    Exported (not `_`-private) because `cli.py`'s own `active_platforms()`
    calls this unconditionally, before it is known whether any usermod
    port is even active -- a config whose *only* usermod content is a
    stale `[usermod] ports = [...]` selects zero usermod ports under the
    new presence rule, so nothing would otherwise ever call into this
    module far enough to catch it, and the config would silently just
    build natmod alone (record 0048's own bug class). `UsermodOptions.load()`
    below calls this again for direct callers that bypass `cli.py`
    entirely (most tests) -- cheap, no I/O, not the "parsing the file
    twice" `read_config()`'s own `preread` already avoids.
    """
    table = dict(raw.get("usermod") or {})
    if "ports" in table:
        raise error(
            "[usermod] ports = [...] no longer exists. Which usermod ports "
            "are active is table presence now -- write [unix], [windows], "
            "[qemu], [webassembly], [esp32] directly, sibling to [usermod] "
            "and [natmod]. [usermod] itself only holds shared defaults for "
            "every active port now (user-c-modules/manifest/"
            "extra-make-args), not a port list."
        )
    nested = sorted(k for k, v in table.items() if isinstance(v, dict))
    if nested:
        raise error(
            f"[usermod.{nested[0]}] no longer exists -- there is no more "
            f"nesting under [usermod]. Write [{nested[0]}] as its own "
            "top-level table, sibling to [usermod] and [natmod]."
        )
    check_keys(table, USERMOD_PORT_BASE, where="[usermod]", error=error)
    return table


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
    resolves `manifest`/`user_c_modules` into real filesystem paths
    (writing the combined manifest text, picking a build directory) and
    builds the actual `UnixBuildOptions`/etc. from these, the same split
    `options.BuildOptions` -> `build.build_target()` already has for
    natmod (nothing here touches the filesystem)."""

    target: UsermodTarget
    micropython: str
    user_c_modules: str
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
    """Every active usermod port's config, before it is narrowed to a
    single target."""

    package_dir: Path
    config_path: Path | None
    micropython: list[str]
    output_dir: Path
    ports: list[str]
    build: list[str]
    skip: list[str]
    axis_overrides: dict[str, list[str]]
    # The shared, top-level [[overrides]] list (0051 point 7, merged with
    # natmod's own in Phase G) -- not axis_overrides above (which
    # port/arch a config selects), per-target *option* overrides layered
    # over user-c-modules/manifest/extra-make-args, the same "file -> matching
    # override (each with its own inherit rule) -> environment" shape
    # natmod's own Options.build_options() already has.
    overrides: list[dict[str, Any]] = field(default_factory=list)
    # Names in GROUPS (0051 point 8) that build = "*" should reach anyway
    # -- e.g. enable = ["unix-emulated-everywhere"]. Validated against
    # GROUPS.keys() in targets(), not at load() time, since CLI --enable
    # (usermod/cli.py) still needs to union into this after load().
    enable: frozenset[str] = frozenset()
    # The cascade instance backing build_options()'s own per-target
    # resolution of user-c-modules/manifest/extra-make-args -- env excluded
    # here (build_options() checks the environment itself, after
    # overrides, matching the precedence it has always had),
    # platform_tables keyed by port name.
    _cascade: OptionCascade = field(default=None, repr=False, compare=False)  # type: ignore[assignment]

    @classmethod
    def load(
        cls,
        package_dir: Path,
        config_file: Path | None = None,
        preread: tuple[Path | None, dict[str, Any]] | None = None,
        ports: list[str] | None = None,
    ) -> UsermodOptions:
        """`preread`, when given, is `(config_path, raw)` the caller
        already got from `read_config()` -- `cli.py`'s own platform-
        detection peek has to read the file once to decide which
        platforms are active, so this avoids reading and parsing the
        same TOML file a second time.

        `ports`, when given, is the list of usermod ports `cli.py`'s own
        `active_platforms()` already resolved for this invocation (every
        `[<port>]` table present, or an explicit `--platform` filter).
        When `None` -- a direct caller bypassing `cli.py`, as most tests
        do -- it is derived the same way, straight from table presence.
        """
        if preread is None:
            config_path, raw = read_config(package_dir, config_file)
        else:
            config_path, raw = preread

        if ports is None:
            ports = [p for p in KNOWN_PORTS if p in raw]

        # Environment beats the file for the two genuinely shared
        # top-level keys, the same way `natmod/options.py`'s own `opt()`
        # does.
        def opt(key: str, default: Any = None) -> Any:
            env_value = os.environ.get("CIBMP_" + key.replace("-", "_").upper())
            if env_value is not None:
                return env_value
            return raw.get(key, default)

        # micropython is a genuinely shared top-level key, and a real list
        # (**0051**): usermod's identifier gained a leading tag slot
        # specifically so more than one release can be selected in one
        # invocation without one overwriting another's output. Accepts
        # the same shapes natmod's own list-valued options do: a TOML
        # list, or a string (file or environment) split on whitespace.
        micropython_value = opt("micropython", DEFAULT_MICROPYTHON)
        if isinstance(micropython_value, list):
            micropython = [str(v) for v in micropython_value] or [DEFAULT_MICROPYTHON]
        else:
            micropython = str(micropython_value).split() or [DEFAULT_MICROPYTHON]

        family_table = check_usermod_family_table(raw, error=UsermodConfigError)

        platform_tables: dict[str, dict[str, Any]] = {}
        axis_overrides: dict[str, list[str]] = {}
        for port in ports:
            port_table = dict(raw.get(port) or {})
            check_keys(
                port_table, SCHEMAS[port], where=f"[{port}]", error=UsermodConfigError
            )
            platform_tables[port] = port_table
            key = axis_key(port)
            if key is not None and key in port_table:
                axis_overrides[port] = _as_list(port_table[key], f"{port}.{key}")

        cascade = OptionCascade(
            global_table=raw,
            family_table=family_table,
            platform_tables=platform_tables,
            env={},
        )

        overrides = load_overrides(raw, error=UsermodConfigError)

        return cls(
            package_dir=package_dir,
            config_path=config_path,
            micropython=micropython,
            output_dir=Path(str(opt("output-dir", DEFAULT_OUTPUT_DIR))),
            ports=ports,
            build=parse_selector(opt("build", "*")),
            skip=parse_selector(opt("skip", "")),
            axis_overrides=axis_overrides,
            overrides=overrides,
            enable=frozenset(parse_selector(opt("enable"))),
            _cascade=cascade,
        )

    def targets(self) -> list[UsermodTarget]:
        unknown = self.enable - GROUPS.keys()
        if unknown:
            raise UsermodConfigError(
                f"enable: unknown group(s) {', '.join(sorted(unknown))}. Known: "
                f"{', '.join(sorted(GROUPS))}"
            )
        all_targets = usermod_targets(self.micropython, self.ports, self.axis_overrides)
        return select(
            all_targets, self.build, self.skip, enable=self.enable, groups=GROUPS
        )

    def all_targets(self) -> list[UsermodTarget]:
        """Every identifier this config can name, across every known port
        -- what `--only` resolves against (**0045**), independent of
        `ports`/axis-overrides/`build`/`skip`. A thin wrapper around the
        free function of the same job (`all_usermod_targets()`) added so
        `cli.py`'s own dispatch can call `resolve_options(...).all_targets()`
        the same way for every family (Phase H) -- mirrors natmod's own
        `Options.all_targets()` method, which had no free-function
        equivalent to begin with.
        """
        return all_usermod_targets(self.micropython)

    def build_options(
        self, target: UsermodTarget, env: Mapping[str, str] | None = None
    ) -> UsermodBuildOptions:
        """Resolve per-target options: file (global -> that target's own
        port table) -> matching [[overrides]] (each layered per its own
        `inherit` rule) -> environment -- the same shape natmod's own
        Options.build_options() already has (0051 point 7, merged in
        Phase G)."""
        environ: Mapping[str, str] = os.environ if env is None else env

        matching = matching_overrides(
            self.overrides, target.identifier, error=UsermodConfigError
        )
        for override in matching:
            option_keys = {
                k: v for k, v in override.items() if k not in {"select", "inherit"}
            }
            check_keys(
                option_keys,
                USERMOD_PORT_BASE,
                where=f"[[overrides]] matching {target.identifier!r} (platform {target.port!r})",
                error=UsermodConfigError,
            )

        def opt(key: str, default: Any = None) -> Any:
            env_value = environ.get("CIBMP_" + key.replace("-", "_").upper())
            if env_value is not None:
                return env_value
            return self._cascade.get(
                key,
                platform=target.port,
                default=default,
                extra_layers=override_extra_layers(matching, key),
            )

        return UsermodBuildOptions(
            target=target,
            micropython=target.tag,
            user_c_modules=str(opt("user-c-modules", DEFAULT_USER_C_MODULES)),
            manifest=str(opt("manifest", "")),
            extra_make_args=_as_list_or_str(opt("extra-make-args"), "extra-make-args"),
        )

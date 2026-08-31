"""Usermod config loading. `[unix]`/`[windows]`/`[qemu]`/`[webassembly]`/
`[esp32]` do not exist as config tables at all any more -- every one of
them used to carry a per-port axis (`archs =`/`boards =`) and, before
that, to gate whether the port was active in the first place (table
presence as activation). Both concepts are retracted, live, in the same
session that removed natmod's own `archs` and the `platform_tables`
cascade tier: every port is always in scope, and `all_usermod_targets()`
(`targets.py`) already enumerates every real `(port, tag, arch/board)`
row `resources/build-platforms.toml` has -- there is nothing left for a
per-port table to select or configure. `cli.py`'s own
`_reject_platform_tables()` turns a config still writing one of these six
names into a loud, specific error before this module ever sees it.

`[usermod]` (a seventh, different kind of table -- not a selector, a
value-holding tier of shared defaults for every port at once) is gone too
now (record 0074). Unlike the six tables above, it was never a real,
load-bearing config surface any real consumer of this project actually
wrote -- it survived every earlier round of retraction "at the user's own
explicit insistence" (record 0051's ninth addendum) on principle alone,
with no real config ever using it: every one either sets these keys at
the bare top level or narrows one port at a time through
`[override."<glob>"]`. Removed outright rather than added to
`cli.py`'s own retired-table list with its own migration message --
there is no real config to migrate, so a stray `[usermod]` table now
falls through to the same plain "unknown table" error any other
unrecognised top-level table gets.

`[override]` is shared with natmod (Phase G, record 0051's third
addendum) -- `natmod/options.py`'s own `load_overrides()` parses and
loosely validates the merged, top-level list once; each of natmod's and
this module's own `build_options()` does its own *strict*,
per-matched-platform validation at resolution time (`target.port` is what
makes that possible for natmod too). `inherit = {extra-make-args =
"append"|"prepend"|"none"}` lives per override table there too.

Deliberately narrower than `natmod/options.py`'s own `Options` still: no
`variant` (a real field on three of five ports' `*BuildOptions`, still
config-surface-less) yet.

`user-c-modules`/`manifest`/`extra-make-args` resolve per target through
the same `cibuildmp.options.Options` cascade `natmod/options.py` uses, not
eagerly-resolved scalar fields.

No `package.json` here at all: usermod output is a full port binary meant
to be flashed or run directly, not a `.mpy` `mip.install()` target -- D14's
packaging step does not apply (confirmed with the user directly before
building this, not assumed either way). `name`/`version` do reach usermod
now (record 0052, A3) -- not for a package.json that will never exist, but
because `orchestrate.py`'s own `_dest_name()` had no project identity at
all before this: every produced binary's own stem was always literally
`"micropython"`/`"micropython.exe"`, regardless of which project's config
built it.
"""

from __future__ import annotations

import os
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...options import Options as OptionCascade
from ...options import (
    check_selector_reachable,
    matching_overrides,
    override_extra_layers,
)
from ...selector import parse_selector, select
from ..natmod.options import (
    DEFAULT_OUTPUT_DIR,
    check_keys,
    load_overrides,
    read_config,
)
from ..natmod.options import ConfigError as NatmodConfigError
from ..natmod.options import Options as NatmodOptions
from .targets import KNOWN_PORTS, UsermodTarget, all_usermod_targets

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

# The three per-target option keys usermod's own `[override]` entries
# read. `user-c-modules`, not `module-dir`
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
    {"user-c-modules", "manifest", "extra-make-args", "extra-cmake-args"}
)

# `USERMOD_ONLY_GENERIC_KEYS`'s own counterpart to `user-c-modules`/
# `manifest` -- generic (global-only, or per-target via `[override]`) but
# meaningless to natmod's own `check_keys()` caller under these names (it
# has no `user-c-modules`/`manifest` key at all, only its own differently-
# named `module-dir`, record 0051's sixth addendum), so kept out of the
# truly-shared `GENERIC_KEYS` in `natmod/options.py` the same way that
# module's own `NATMOD_ONLY_GENERIC_KEYS` is. `extra-make-args`/`build`/
# `skip` do not need an entry here -- they are already in the shared
# `GENERIC_KEYS`, being real, identically-named, identically-meant keys on
# both sides.
USERMOD_ONLY_GENERIC_KEYS: frozenset[str] = frozenset(
    {"user-c-modules", "manifest", "extra-cmake-args"}
)

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


def _as_list_or_str(value: Any, key: str) -> list[str]:
    """Like `_as_list()`, but a string is shell-split rather than
    rejected -- for `build_options()`'s own per-target resolution, where
    a value can come from the environment (always a string) as well as
    the file, the same shape natmod's own `_as_list` already has."""
    if isinstance(value, str):
        return shlex.split(value)
    return _as_list(value, key)


@dataclass
class UsermodBuildOptions:
    """Ingredients for one target's build, not yet the port-specific
    `*BuildOptions` each `usermod/build_<port>.py` wants -- `usermod/orchestrate.py`
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
    # CMake-only, unlike extra_make_args above: no `[esp32]`/`[rp2]` table
    # exists to scope it, so it resolves through the same generic/override
    # cascade and is simply ignored by the four Make ports (unix, windows,
    # webassembly, qemu) -- their own build_<port>() functions never read
    # it. See build_common.cmake_extra_args_env() for why this can't just
    # ride the make command line the way extra_make_args does.
    extra_cmake_args: list[str] = field(default_factory=list)

    @property
    def identifier(self) -> str:
        return self.target.identifier

    @property
    def port(self) -> str:
        return self.target.port


def _foreign_override_identifiers(cfg: UsermodOptions) -> list[str]:
    """`[override]` is shared with natmod (Phase G) -- an entry meant
    only for natmod (`select = "*-armv7emsp"`, an arch identifier no
    usermod port ever produces) must not fail *this* family's own
    reachability audit just because a *direct*, usermod-only caller
    (bypassing `cli.py`, as most tests do) never loads natmod's own
    config at all (task #66, first reported live against the root
    `cibuildmp.toml` back when `--platform` could still scope one family
    out of an invocation -- `cli.py` itself now always resolves both
    families, so this widening only still matters for a standalone
    `UsermodOptions.load()` caller).

    `usermod/options.py` already imports from `natmod/options.py` (the
    established one-way direction -- natmod must never import usermod
    back), so this family alone can widen its own check to include
    natmod's real identifier space too, computed from the very same raw
    config (`cfg._cascade.global_table`) natmod would load if it were
    active this invocation. `NatmodOptions.load()` never calls its own
    `check_reachable()` (that only runs from `targets()`, not `load()`),
    so this cannot recurse into natmod's own reachability errors -- only
    its plain identifier space is used here.

    Best-effort and asymmetric, not yet a full fix: if natmod's own load
    fails for a reason that has nothing to do with reachability (a
    genuine `[natmod]` config mistake), that failure is natmod's own to
    report when natmod is actually loaded -- swallowed here rather than
    surfacing as a confusing failure from an unrelated usermod-only
    invocation. The mirror direction (a natmod-only invocation flagged by
    a usermod-only override) is not fixed by this -- natmod must not
    import usermod back, so it has no equivalent widening available to
    it. Left as task #66's own residual, not solved here.
    """
    try:
        natmod_cfg = NatmodOptions.load(
            cfg.package_dir, preread=(cfg.config_path, dict(cfg._cascade.global_table))
        )
        return [t.identifier for t in natmod_cfg.all_targets()]
    except NatmodConfigError:
        return []


def check_reachable(
    cfg: UsermodOptions, *, foreign_identifiers: Sequence[str] = ()
) -> None:
    """Pre-build reachability audit -- the usermod half of record 0052's
    A5 (see `natmod/options.py`'s own `check_reachable()` for the full
    reasoning, unchanged here): every `build`/`skip`/`[override]`
    `select` pattern must be capable of matching at least one identifier
    in `all_targets()` (every known port, every real tag
    `build-platforms.toml` has ever walked), checked before `targets()`'s
    own `build`/`skip` narrowing -- which legitimately reaching zero
    *selected* targets (a deliberate `skip = "*"`) must stay a valid,
    ordinary outcome, never confused with a pattern that could never have
    matched anything at all.

    `build`/`skip`/`[override]` are shared, top-level config now (every
    per-platform table is retired) -- a pattern can legitimately be meant
    for natmod alone (`build = "mpy6.3-*"` with a usermod port also in
    scope), and that must not read as a mistake just because it matches
    nothing among usermod's own identifiers. `foreign_identifiers` is
    `cli.py`'s own coordinator supplying natmod's (and any other active
    family's) own `all_targets()` identifiers; `_foreign_override_identifiers()`
    is this module's own independent way of getting the same thing for a
    direct, usermod-only caller (bypassing `cli.py`, as most tests do) --
    both are combined below rather than one replacing the other, since a
    real caller only ever supplies one of the two.

    Each port's own `build`/`skip` -- **only when a per-platform
    environment override (`CIBMP_BUILD_<PORT>`/`CIBMP_SKIP_<PORT>`)
    actually sets one** -- is checked a second time, scoped to *that
    port's own* identifiers (not widened): an env-var value scoped to one
    port is unambiguous by construction, unlike the shared `build`/`skip`/
    `[override]` above. Deliberately skipped when the port sets neither:
    `cfg._port_build_skip(port)` then falls back to `cfg.build`/
    `cfg.skip`, which may itself be a family-wide pattern meaning "every
    port, some of which are not this one" (`skip = "*wasm*"` legitimately
    matches nothing among `unix`'s own identifiers) -- re-checking it
    against one port's own narrow subset would be a false positive, not a
    stricter check; the equality test below is what tells "this port
    genuinely has its own env override" apart from "this is only the
    inherited default resolving here too."
    """
    all_targets = cfg.all_targets()
    identifiers = [t.identifier for t in all_targets]
    foreign = list(foreign_identifiers) + _foreign_override_identifiers(cfg)
    combined = identifiers + foreign
    check_selector_reachable(cfg.build, "build", combined, error=UsermodConfigError)
    check_selector_reachable(cfg.skip, "skip", combined, error=UsermodConfigError)
    for port in cfg.ports:
        port_build, port_skip = cfg._port_build_skip(port)
        port_identifiers = [t.identifier for t in all_targets if t.port == port]
        if port_build != cfg.build:
            check_selector_reachable(
                port_build,
                f"[{port}] build",
                port_identifiers,
                error=UsermodConfigError,
            )
        if port_skip != cfg.skip:
            check_selector_reachable(
                port_skip, f"[{port}] skip", port_identifiers, error=UsermodConfigError
            )
    for override in cfg.overrides:
        selector = override.get("select")
        if selector is None:
            continue  # a missing select is its own, separate error elsewhere
        check_selector_reachable(
            parse_selector(selector),
            f'[override."{selector}"]',
            combined,
            error=UsermodConfigError,
        )


@dataclass
class UsermodOptions:
    """Every usermod port's config, before it is narrowed to a single
    target. Every port in `KNOWN_PORTS` is always in scope -- there is no
    activation concept left to narrow `ports` below that constant."""

    package_dir: Path
    config_path: Path | None
    output_dir: Path
    ports: list[str]
    build: list[str]
    skip: list[str]
    name: str
    version: str
    # The shared, top-level [override] list (0051 point 7, merged with
    # natmod's own in Phase G) -- per-target *option* overrides layered
    # over user-c-modules/manifest/extra-make-args, the same "file ->
    # matching override (each with its own inherit rule) -> environment"
    # shape natmod's own Options.build_options() already has.
    overrides: list[dict[str, Any]] = field(default_factory=list)
    # The cascade instance backing build_options()'s own per-target
    # resolution of user-c-modules/manifest/extra-make-args -- env excluded
    # here (build_options() checks the environment itself, after
    # overrides, matching the precedence it has always had).
    _cascade: OptionCascade = field(default=None, repr=False, compare=False)  # type: ignore[assignment]
    # A second instance over the same tables, env included -- build/skip's
    # own per-port resolution (targets() below, record 0052's own
    # per-platform build/skip addendum) has no per-target opt() closure of
    # its own the way build_options() does, so it reads straight through a
    # real env-aware cascade instead, the same way natmod/options.py's own
    # cascade_env already does for build/skip.
    _cascade_env: OptionCascade = field(default=None, repr=False, compare=False)  # type: ignore[assignment]

    @classmethod
    def load(
        cls,
        package_dir: Path,
        config_file: Path | None = None,
        preread: tuple[Path | None, dict[str, Any]] | None = None,
    ) -> UsermodOptions:
        """`preread`, when given, is `(config_path, raw)` the caller
        already got from `read_config()` -- `cli.py` already reads the
        file once for `natmod`'s own load too, so this avoids parsing the
        same TOML file a second time.
        """
        if preread is None:
            config_path, raw = read_config(package_dir, config_file)
        else:
            config_path, raw = preread

        # Environment beats the file for the two genuinely shared
        # top-level keys, the same way `natmod/options.py`'s own `opt()`
        # does.
        def opt(key: str, default: Any = None) -> Any:
            env_value = os.environ.get("CIBMP_" + key.replace("-", "_").upper())
            if env_value is not None:
                return env_value
            return raw.get(key, default)

        cascade = OptionCascade(global_table=raw, env={})
        # Env-aware sibling of `cascade` above -- build/skip's own
        # resolution (targets() below) reads through this one directly,
        # the same way natmod/options.py's own cascade_env already does.
        cascade_env = OptionCascade(global_table=raw, env=os.environ)

        overrides = load_overrides(raw, error=UsermodConfigError)

        # `self.build`/`self.skip` are the global-resolved baseline. No
        # implicit "*" default any more (record 0052's own live-caught
        # correction): an unconfigured build selects nothing, the same
        # retraction natmod's own default got.
        build_value = cascade_env.get("build", default="")
        skip_value = cascade_env.get("skip", default="")

        return cls(
            package_dir=package_dir,
            config_path=config_path,
            output_dir=Path(str(opt("output-dir", DEFAULT_OUTPUT_DIR))),
            ports=list(KNOWN_PORTS),
            build=parse_selector(build_value),
            skip=parse_selector(skip_value),
            name=str(opt("name", "")),
            version=str(opt("version", "")),
            overrides=overrides,
            _cascade=cascade,
            _cascade_env=cascade_env,
        )

    def _port_build_skip(self, port: str) -> tuple[list[str], list[str]]:
        """This port's own `build`/`skip` -- `self.build`/`self.skip` (the
        global-resolved baseline, already reflecting `--build`/
        `--skip` CLI overrides applied after `load()`) unless a
        per-platform environment override (`CIBMP_BUILD_<PORT>`/
        `CIBMP_SKIP_<PORT>`) is set. No `[port]`-table tier any more
        (record 0052's own live-caught correction, retracting the earlier
        "per-platform build/skip" addendum): `[unix] build = "..."` was
        always exactly a sufficiently-scoped global `build` pattern
        restated, since unix's own real identifiers already carry
        `manylinux`/`musllinux` as a marker no other platform's own
        identifiers share. The env-var tier survives -- a real, distinct
        capability (a one-off CI override with no config-file edit), not
        a TOML duplication of anything a glob already expresses.

        Reads the env var directly rather than through
        `self._cascade_env.get(..., default=self.build)`: that cascade
        call re-derives its own "no env override" fallback from the raw
        file table it was built from, which -- once `self.build`
        has been reassigned after `load()` (`resolve_options()`'s own
        `--build`/`--skip` handling) -- disagrees with the value actually
        meant to apply. Reading the env var alone and falling back to the
        already-fully-resolved `self.build` sidesteps that staleness
        entirely.
        """
        env = self._cascade_env.env
        build_key = f"CIBMP_BUILD_{port.upper()}"
        skip_key = f"CIBMP_SKIP_{port.upper()}"
        build = parse_selector(env[build_key]) if build_key in env else self.build
        skip = parse_selector(env[skip_key]) if skip_key in env else self.skip
        return build, skip

    def targets(
        self, *, foreign_identifiers: Sequence[str] = ()
    ) -> list[UsermodTarget]:
        """`foreign_identifiers`: every other active platform family's own
        `all_targets()` identifiers, widening the reachability audit below
        to the true combined domain -- see `check_reachable()`'s own
        docstring. `cli.py`'s own coordinator always supplies this; a
        direct caller bypassing `cli.py` (most tests) gets the same
        widening anyway, from this module's own `_foreign_override_identifiers()`.
        """
        check_reachable(self, foreign_identifiers=foreign_identifiers)
        all_targets = all_usermod_targets()
        # build/skip resolve per port -- selecting per port-group and
        # reassembling in all_targets' own original order (port-outer,
        # per-port row order) rather than concatenating groups, which
        # would reorder every multi-port config's own output.
        selected: list[UsermodTarget] = []
        for port in self.ports:
            build, skip = self._port_build_skip(port)
            group = [t for t in all_targets if t.port == port]
            selected.extend(select(group, build, skip))
        position = {t: i for i, t in enumerate(all_targets)}
        return sorted(selected, key=lambda t: position[t])

    def all_targets(self) -> list[UsermodTarget]:
        """Every identifier this config can name, across every known port
        -- independent of `build`/`skip`. A thin wrapper around the free
        function of the same job (`all_usermod_targets()`) so `cli.py`'s
        own dispatch can call `resolve_options(...).all_targets()` the
        same way for every family -- mirrors natmod's own
        `Options.all_targets()` method, which had no free-function
        equivalent to begin with.
        """
        return all_usermod_targets()

    def build_options(
        self, target: UsermodTarget, env: Mapping[str, str] | None = None
    ) -> UsermodBuildOptions:
        """Resolve per-target options: file (global -> that target's own
        port table) -> matching [override] (each layered per its own
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
                where=f"[override] matching {target.identifier!r} (platform {target.port!r})",
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
            extra_cmake_args=_as_list_or_str(
                opt("extra-cmake-args"), "extra-cmake-args"
            ),
        )

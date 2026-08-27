"""Cascade-based option resolution (record 0051, points 4/6 -- Phase E).

Record 0048 fixed "a key placed in the wrong table is silently ignored"
(`build`/`skip` read from the top level by natmod and from `[usermod]` by
usermod) by giving every key exactly one correct location and making every
other location a loud error (`TOP_LEVEL_ONLY_KEYS`, `NATMOD_TABLE_KEYS`,
`check_table_keys()` in `natmod/options.py`). That works, but it does not
generalise to six platforms sharing option keys (`module-dir`, `manifest`,
`extra-make-args`) the way natmod and the five usermod ports would need to
once natmod stops being "a mode with its own table" and becomes one of six
platform tables, all structurally identical.

Read from `cibuildwheel/options.py` directly this session, not recalled:
upstream's own `Options.get()` -> `_resolve_cascade()` resolves every
option as `default -> global config -> platform config -> environment ->
CLI`, most-specific-wins, and nothing is an error to place at any layer --
there is no "wrong location" to begin with. That is a different, more
general way to satisfy 0048's own constraint (a misplaced key must never
silently do nothing): under a cascade, every placement is *some* real
layer, so "misplaced" stops being a category. What stays a real error is a
key unknown to *every* layer's own schema at once -- a genuine typo, not a
placement choice. See `docs/records/0048-build-skip-live-in-opposite-tables.md`'s
own addendum for the full argument, and
`docs/records/0051-usermod-identifiers-have-no-version-axis.md`'s addendum
for how this fits points 4/6.

Wired into `natmod/options.py`'s and `usermod/options.py`'s own
`build_options()` as of Phase G (record 0051's own fourth/fifth addenda):
`matching_overrides()`/`override_extra_layers()` below turn a config's
`[[overrides]]` list into the `(value, inherit_rule)` layers `Options.get()`'s
own `extra_layers` parameter already knew how to consume -- the whole
mechanism was built ahead of having a real caller for it (Phase E), and
this is that caller.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .selector import matches, parse_selector


class ConfigError(Exception):
    pass


class InheritRule:
    """Upstream's own `InheritRule` (`cibuildwheel/options.py`), the same
    three values, spelled as plain strings rather than an enum since every
    caller here already works with kebab-case TOML strings elsewhere in
    this project. `NONE` (the default) replaces the running value; the
    other two only apply when both the running value and the new layer
    are lists -- `extra-make-args` is the one option this project has that
    is genuinely list-shaped across every platform's own override surface
    (Phase G); scalar options (`module-dir`, `manifest`, ...) only ever
    take `NONE`.
    """

    NONE = "none"
    APPEND = "append"
    PREPEND = "prepend"
    ALL: frozenset[str] = frozenset({NONE, APPEND, PREPEND})


def resolve_cascade(*layers: tuple[Any | None, str]) -> Any | None:
    """Resolve `(value, inherit_rule)` pairs, lowest priority first, into
    one final value -- upstream's own `_resolve_cascade()` shape, adapted:
    no `OptionFormat` class hierarchy, just Python `str`/`list[str]`
    values, since that already covers every option shape this project has.

    A `None` value means "this layer did not set anything" and is skipped
    entirely -- not the same as an explicit empty string/list, which does
    replace. Layers evaluate left to right; `NONE` fully replaces the
    running result, `APPEND`/`PREPEND` only apply when both the running
    result and the new layer are lists (a scalar layer requesting append
    is a config error, not silently coerced).
    """
    result: Any | None = None
    for value, rule in layers:
        if value is None:
            continue
        if rule not in InheritRule.ALL:
            raise ConfigError(
                f"unknown inherit rule {rule!r}. Known: "
                f"{', '.join(sorted(InheritRule.ALL))}"
            )
        if result is None or rule == InheritRule.NONE:
            result = value
            continue
        if not (isinstance(result, list) and isinstance(value, list)):
            raise ConfigError(
                f"inherit={rule!r} only applies to list-valued options, got "
                f"{type(value).__name__}"
            )
        result = result + value if rule == InheritRule.APPEND else value + result
    return result


def known_option_names(
    schemas: Mapping[str, frozenset[str]], generic: frozenset[str] = frozenset()
) -> frozenset[str]:
    """The union of every platform's own known option keys plus the
    generic (platform-agnostic) ones -- replaces 0048's
    `TOP_LEVEL_ONLY_KEYS`/`NATMOD_TABLE_KEYS`/`USERMOD_TABLE_KEYS` as the
    "is this a real key at all" check. `schemas` maps a platform name to
    that platform's own option-key set (e.g. `{"natmod": NATMOD_KEYS,
    "unix": UNIX_KEYS, ...}`); under the cascade every one of those keys
    is nominally valid at the global level too, since the global layer is
    just every platform's own default.
    """
    names = set(generic)
    for keys in schemas.values():
        names |= keys
    return frozenset(names)


def suggest(name: str, known: frozenset[str]) -> str | None:
    """A close-match suggestion for an unknown key, the same
    `difflib.get_close_matches` upstream's own `_validate_global_option()`
    uses (`cibuildwheel/options.py`, confirmed this session) -- and the
    same library `check_table_keys()` could adopt but does not yet."""
    matches = difflib.get_close_matches(name, known, n=1, cutoff=0.7)
    return matches[0] if matches else None


def check_known_keys(
    table: Mapping[str, Any], known: frozenset[str], *, where: str
) -> None:
    """Reject any key in `table` that is not in `known` anywhere -- the
    one placement-independent error the cascade still needs: a key no
    platform's schema recognises at all is a typo, not a location choice.
    """
    for key in table:
        if key in known:
            continue
        msg = f"{where}: unknown key `{key}`."
        hint = suggest(key, known)
        if hint:
            msg += f" Perhaps you meant `{hint}`?"
        raise ConfigError(msg)


def matching_overrides(
    overrides: Sequence[Mapping[str, Any]],
    identifier: str,
    *,
    tree_path: str | None = None,
    error: type[Exception] = ConfigError,
) -> list[Mapping[str, Any]]:
    """Every override table (file order) whose `select` matches
    `identifier` -- shared by `natmod/options.py`'s and
    `usermod/options.py`'s own `build_options()`, replacing the hand-rolled
    loop each had before Phase G. `error` lets each caller raise its own
    exception class for a missing `select` (`natmod.options.ConfigError`
    / `usermod.options.UsermodConfigError`), since existing tests assert
    the specific class each mode already raises.

    `tree_path` (record 0052, Track B, B2/B4.3) is a second, additive way
    for `select` to match: the target's own dotted tree-node address
    (`"natmod"`, `"usermod.unix"`, `"usermod.esp32.ESP32_GENERIC_S3"`),
    matched as one whole string against each `select` pattern the exact
    same way `identifier` already is -- fnmatch's own `*` already crosses
    a `.` the way a real path glob would, so `select = "usermod.esp32.*"`
    matches every board under that port with no separator-aware matching
    needed here. An override applies if *either* mode matches (an OR, not
    a "try tree-path, fall back to identifier" priority order) -- the two
    modes answer genuinely different questions (address a tree node vs.
    address a compatibility-axis subset) and neither subsumes the other,
    so a `select` ambiguous between the two is intentionally allowed to
    match via both without being counted twice (this loop appends an
    override once per matching call, regardless of how many of its own
    patterns matched or which mode each one matched through).
    `build`/`skip` never gain this second mode -- scoped to `[[overrides]]`'s
    own `select` only, the residual case B0's own tree-node-presence
    mechanism cannot express by construction.
    """
    result = []
    for override in overrides:
        selector = override.get("select")
        if selector is None:
            raise error("every [[overrides]] table needs a `select` key")
        patterns = parse_selector(selector)
        if matches(identifier, patterns) or (
            tree_path is not None and matches(tree_path, patterns)
        ):
            result.append(override)
    return result


def check_selector_reachable(
    patterns: Sequence[str],
    where: str,
    identifiers: Sequence[str],
    *,
    tree_paths: Iterable[str] | None = None,
    error: type[Exception] = ConfigError,
) -> None:
    """Raise unless every pattern in `patterns` matches at least one of
    `identifiers` (record 0052, A5) -- checked individually per pattern
    rather than as one OR'd whole, so a group with one working pattern
    and one typo'd one does not hide the typo behind the pattern that
    still matches something. Shared by `natmod/options.py`'s and
    `usermod/options.py`'s own `check_reachable()`, each of which calls
    this once for `build`, once for `skip`, and once per `[[overrides]]`
    table's own `select` -- `identifiers` is always that caller's own
    `all_targets()`, the full, unfiltered domain, never the already-
    selected result, so a deliberate `skip = "*"` narrowing a real domain
    to zero *selected* targets stays legitimate and is never confused
    with a pattern that could never have matched anything in the first
    place.

    `tree_paths` (record 0052, Track B, B4.3), when given, is a second,
    additive set a pattern may match against instead of an identifier --
    the same OR `matching_overrides()` itself now applies at
    `build_options()` time. Passed only for `[[overrides]]`'s own
    `select` (which gained tree-path matching under B2/B4.3); omitted for
    `build`/`skip`, which never did and still only match identifiers. Not
    passing it here is not merely "no extra layer" the way an empty
    `family_table` was for `Options.get()` -- omitting it for `select`
    would make a legitimately tree-path-reachable pattern (`select =
    "usermod.esp32.*"`) a false-positive "matches nothing" error, since
    no identifier ever looks like a dotted tree path.
    """
    for pattern in patterns:
        reachable = any(matches(identifier, [pattern]) for identifier in identifiers)
        if not reachable and tree_paths is not None:
            reachable = any(matches(path, [pattern]) for path in tree_paths)
        if not reachable:
            raise error(
                f"{where}: {pattern!r} matches no known identifier -- a typo, "
                f"or an axis value this project has never verified"
            )


def override_extra_layers(
    matching: Sequence[Mapping[str, Any]], key: str
) -> list[tuple[Any | None, str]]:
    """`(value, inherit_rule)` per matching override that sets `key`, in
    file order -- exactly the shape `Options.get()`'s own `extra_layers`
    wants. `inherit` defaults to `InheritRule.NONE` (replace) when a
    matching override has none, so every override written before `inherit`
    existed keeps its exact "last matching override wins outright" result.
    """
    layers: list[tuple[Any | None, str]] = []
    for override in matching:
        if key not in override:
            continue
        rule = (override.get("inherit") or {}).get(key, InheritRule.NONE)
        layers.append((override[key], rule))
    return layers


@dataclass(frozen=True)
class Options:
    """One config's worth of cascade-resolvable option tables.

    `global_table` is the top-level config dict, meaningful to *every*
    family (natmod included) -- the tree's own root. `tree` is everything
    below root, recursively addressed (record 0052, Track B, B0/B4.1):
    `tree["usermod"]` is what used to be the separate `family_table`
    (record 0051's ninth addendum) -- usermod's own `[usermod]` table,
    `user-c-modules`/`manifest`/`extra-make-args` defaults for every port
    at once -- and `tree["usermod"]["unix"]` is what used to be
    `platform_tables["unix"]`, a real *sibling key inside that same dict*,
    not a second field, the same way a real nested TOML table
    (`[usermod.unix]`) would parse. `tree["natmod"]` is natmod's own
    `[natmod]` table -- natmod has no family tier of its own (its one
    platform already *is* its only family), so its own path is one
    segment deep, not two. `get()`'s own `platform` parameter is a single
    string (unchanged for natmod's own callers -- `"natmod"`, one
    segment) or a tuple of segments walked root-to-leaf (`("usermod",
    "unix")` today; `("usermod", "esp32", "SOME_BOARD")` once B4.2 wires
    boards as tree nodes) -- deciding the exact signature by writing both
    real call sites first, per B4.1's own instruction, is what settled on
    reusing the existing `platform` name widened to accept either shape,
    rather than a new `path`-named parameter: natmod's own call sites
    (`platform="natmod"`) stay byte-identical, and usermod's one call site
    that needs the new depth changes from a bare string to a 2-tuple, the
    smallest change either caller needs.

    `env` is the environment mapping (`os.environ` by default, injectable
    so tests never touch the real process environment). Neither
    CLI-supplied values nor `[[overrides]]` matches live here -- both are
    the caller's own, layered in via `get()`'s own `extra_layers`, so
    this class stays config-file-and-environment-only, the same split
    upstream keeps between its own `Options` (file + env) and `argparse`
    (CLI).
    """

    global_table: Mapping[str, Any]
    tree: Mapping[str, Any] = field(default_factory=dict)
    env: Mapping[str, str] = field(default_factory=dict)

    def get(
        self,
        name: str,
        *,
        platform: str | Sequence[str] | None = None,
        default: Any = None,
        env_plat: bool = True,
        extra_layers: Sequence[tuple[Any | None, str]] = (),
    ) -> Any:
        """`default -> global -> tree (root to leaf, one layer per path
        segment) -> env -> env(leaf) -> extra_layers`, most-specific-wins.
        `extra_layers` is where a caller threads in CLI-supplied values or
        matching `[[overrides]]` entries (Phase G), each with its own
        inherit rule -- this method does not know about either.

        `platform=None` (or an empty tuple) walks nothing beyond root --
        exactly today's "no platform table for this platform" shape, an
        empty `Mapping.get()` always contributing `None`, which
        `resolve_cascade()` skips. `platform="natmod"` walks one segment
        (`tree["natmod"]`); `platform=("usermod", "unix")` walks two
        (`tree["usermod"]`, then `tree["usermod"]["unix"]`) -- a missing
        segment anywhere along the walk contributes `{}` for every
        segment from there on, the same silent-miss behaviour
        `platform_tables.get(platform, {})` always had, generalised to
        arbitrary depth rather than hardcoded to exactly one hop.

        Env var names are `CIBMP_<KEY>` and, when a path is given and
        `env_plat` is true, `CIBMP_<KEY>_<LEAF>` too -- keyed by the
        path's own last segment, not the whole joined path, so
        `CIBMP_ARCHS_NATMOD`/`CIBMP_EXTRA_MAKE_ARGS_UNIX` stay exactly the
        env var names they always were even though `unix`'s own path grew
        a `usermod` segment in front of it; `CIBMP_EXTRA_MAKE_ARGS_
        ESP32_GENERIC_S3`-shaped names are what a three-segment board path
        would produce once one exists.
        """
        env_key = "CIBMP_" + name.replace("-", "_").upper()
        layers: list[tuple[Any | None, str]] = [
            (default, InheritRule.NONE),
            (self.global_table.get(name), InheritRule.NONE),
        ]
        path: tuple[str, ...] = ()
        if platform is not None:
            path = (platform,) if isinstance(platform, str) else tuple(platform)
        node: Mapping[str, Any] = self.tree
        for segment in path:
            node = node.get(segment) or {}
            layers.append((node.get(name), InheritRule.NONE))
        layers.append((self.env.get(env_key), InheritRule.NONE))
        if path and env_plat:
            plat_env_key = f"{env_key}_{path[-1].upper()}"
            layers.append((self.env.get(plat_env_key), InheritRule.NONE))
        layers.extend(extra_layers)
        return resolve_cascade(*layers)

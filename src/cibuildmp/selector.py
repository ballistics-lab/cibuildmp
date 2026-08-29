"""Identifier globbing, shared by natmod and usermod (**0051**).

`select()`/`matches()`/`parse_selector()` used to live once in
`natmod/targets.py` and be hand-duplicated in `usermod/targets.py`, with
a docstring on the usermod copy admitting the duplication was
deliberate. That is the same shape `dockerrun.py` was in before record
0050 moved it to the package root "the moment both used it" -- and the
duplication here is how the two modes already drifted once, reading
`build`/`skip` from opposite config tables (record 0048). One copy
closes the door on that happening again.

Generic over anything with a string `.identifier` property -- both
natmod's `Target` and usermod's `UsermodTarget` already have one, so a
`Protocol` is enough; no shared base class is needed.

Mechanism lives here; which identifiers exist and what a config's
`build`/`skip`/`[override]` mean stays entirely in each mode's own
`targets.py`/`options.py` -- this module knows nothing about ABIs,
ports, or axes.
"""

from __future__ import annotations

import fnmatch
from typing import Protocol, TypeVar


class _HasIdentifier(Protocol):
    @property
    def identifier(self) -> str: ...


T = TypeVar("T", bound=_HasIdentifier)


def parse_selector(value: str | list[str] | None) -> list[str]:
    """Accept either a space-separated string or a list of globs."""
    if value is None:
        return []
    if isinstance(value, str):
        return value.split()
    return [str(v) for v in value]


def _expand_braces(pattern: str) -> list[str]:
    """Shell-like `{a,b,c}` expansion, e.g. `cp{36,37}-*` -> `cp36-*`,
    `cp37-*` -- the gap [0051] flagged against upstream's own
    `bracex`-based `selector_matches()`. Hand-rolled rather than a new
    dependency, the same reasoning `natmod.targets`' own tag-sort key
    uses: this project vendors small, self-contained pieces of what it
    needs rather than depending on them for a handful of lines (D7, D12).

    Expands the first `{...}` group found and recurses for any more,
    so nested or multiple groups in one pattern both work. A pattern
    with no (or an unterminated) `{` is returned unchanged, as the
    one-item list `fnmatch` already expects.
    """
    start = pattern.find("{")
    if start == -1:
        return [pattern]
    end = pattern.find("}", start)
    if end == -1:
        return [pattern]
    prefix, body, suffix = pattern[:start], pattern[start + 1 : end], pattern[end + 1 :]
    return [
        expanded
        for option in body.split(",")
        for expanded in _expand_braces(f"{prefix}{option}{suffix}")
    ]


def matches(identifier: str, patterns: list[str]) -> bool:
    return any(
        fnmatch.fnmatch(identifier, expanded)
        for pattern in patterns
        for expanded in _expand_braces(pattern)
    )


def select(
    targets: list[T],
    build: str | list[str],
    skip: str | list[str],
) -> list[T]:
    """Apply build/skip globs, skip last -- same order as cibuildwheel.

    No implicit "*" fallback for an unconfigured build -- a real,
    live-caught correction: this was the actual mechanism behind "an
    empty config still builds everything," and the whole point of
    removing every implicit default elsewhere (archs, platform tables,
    ...) is that a config now says what it wants, explicitly, via a
    glob, or gets nothing. An empty build_patterns list matches()
    correctly returns False for every identifier.

    No `enable`/`groups` opt-in-group layer any more either (record
    0051 point 8 introduced it, retracted live in the same session that
    removed `archs`/`platform_tables`/table-presence activation): a
    named group of patterns was itself exactly the kind of second,
    parallel selection mechanism this whole retraction keeps arguing
    against -- everything a group could reach, an ordinary `build`/
    `skip` glob already reaches directly against the real identifier,
    with no separate vocabulary to document or opt into. Callers that
    want the six emulated-everywhere `unix` cells write
    `build = "*_{ppc64le,s390x,riscv64}"` (or add it to whatever glob
    they already have) instead of `--enable unix-emulated-everywhere`.
    """
    build_patterns = parse_selector(build)
    skip_patterns = parse_selector(skip)
    return [
        t
        for t in targets
        if matches(t.identifier, build_patterns)
        and not matches(t.identifier, skip_patterns)
    ]

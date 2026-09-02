"""Access to the pinned data tables in resources/.

Kept as data rather than Python for the same reason cibuildwheel keeps
build-platforms.toml and pinned_docker_images.cfg out of its source: every
value in there goes stale on an upstream's schedule, so bumping one should
be a reviewable data diff, not a patch to resolver logic.
"""

from __future__ import annotations

import tomllib
from functools import cache
from importlib.resources import files
from typing import Any

# Anchored to the literal top-level package, deliberately **not** to
# `__package__` -- and kept literal even now that this module is back at
# `cibuildmp/resources.py`, where the two happen to agree again.
#
# The history is the argument for keeping it. This module started here,
# moved to `cibuildmp/natmod/resources.py`, and has now moved back. While
# it lived under `natmod/`, `__package__` silently read
# `"cibuildmp.natmod"` and sent every lookup at
# `cibuildmp/natmod/resources/natmod.toml`, which does not exist. The data
# directory never moved and never should: `cibuildmp/resources/` is shared
# rather than natmod-only -- `usermod/portinfo.py` reads `usermod.toml`
# and `usermod/dockerrun.py` reads both pin tables out of it. A literal
# anchor is what makes this file's own location irrelevant to where the
# data is found, which is precisely the property that was missing the last
# time it moved.
_PACKAGE = "cibuildmp"


@cache
def _load(resource: str) -> dict[str, Any]:
    raw = (files(_PACKAGE).joinpath("resources", resource)).read_bytes()
    return tomllib.loads(raw.decode())


def natmod_data() -> dict[str, Any]:
    return _load("natmod.toml")


def usermod_data() -> dict[str, Any]:
    return _load("usermod.toml")


def build_platforms_data() -> dict[str, Any]:
    """`resources/build-platforms.toml` -- the packaged, fact-first source
    of truth `platforms/natmod/targets.py`/`platforms/usermod/boards.py`
    resolve tags, archs and boards against (record 0052, Track C).

    One row per independently-verified `(tag, arch[, arch_flags])` or
    `(tag, board)` fact, walked by `bin/refresh_natmod_archs.py`/
    `bin/refresh_usermod_boards.py` against real MicroPython checkouts --
    never an assumed axis product. A tag this table has never walked is a
    loud error at resolution time, not a silent guess: refreshing this
    file is what fixes it, the same discipline `natmod.toml`/
    `pinned_docker_images.toml` already have for their own pinned data.
    """
    return _load("build-platforms.toml")


def pinned_docker_images() -> dict[str, Any]:
    """`resources/pinned_docker_images.toml` -- the digest-pinned base and
    published container images `usermod/dockerrun.py` resolves against
    (**record 0043**).

    Named after cibuildwheel's own `resources/pinned_docker_images.cfg`,
    which is the same table doing the same job, and lives here for the
    reason this module's own docstring already gave for `natmod.toml`:
    those values go stale on pypa's schedule, so bumping one has to be a
    reviewable data diff rather than a patch to resolver logic. It was a
    `resources/pinned_docker_images.toml` dict literal inside `dockerrun.py` until 0043 -- the one
    pinned table that had escaped **record 0010**'s own rule.
    """
    return _load("pinned_docker_images.toml")


def pinned_pypa_images() -> dict[str, Any]:
    """`resources/pinned_pypa_images.toml` -- upstream pypa's own
    manylinux/musllinux images, a faithful mirror of cibuildwheel's
    `resources/pinned_docker_images.cfg` (**record 0043**).

    Base images only: nothing runs a build in one of these directly, they
    are what `docker/<tag>.Dockerfile` says `FROM`. The published result
    of that `FROM` is the separate `pinned_docker_images()` table above.
    Kept as a whole mirror rather than a filtered subset so re-syncing is
    a diff against one upstream file.
    """
    return _load("pinned_pypa_images.toml")

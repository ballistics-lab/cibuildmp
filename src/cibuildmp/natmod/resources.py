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
# `__package__`. This module used to live at `cibuildmp/resources.py`,
# where `files(__package__)` and `files("cibuildmp")` were the same
# thing; moving it into `cibuildmp/natmod/` silently made `__package__`
# read `"cibuildmp.natmod"` and sent the lookup at
# `cibuildmp/natmod/resources/natmod.toml`, which does not exist. The
# data directory itself stays at `cibuildmp/resources/` and is shared,
# not natmod-only -- `usermod/portinfo.py` reads `usermod.toml` out of
# the same directory -- so it is the anchor that had to stop moving with
# this file, not the data that should follow it.
_PACKAGE = "cibuildmp"


@cache
def _load(resource: str) -> dict[str, Any]:
    raw = (files(_PACKAGE).joinpath("resources", resource)).read_bytes()
    return tomllib.loads(raw.decode())


def natmod_data() -> dict[str, Any]:
    return _load("natmod.toml")


def usermod_data() -> dict[str, Any]:
    return _load("usermod.toml")

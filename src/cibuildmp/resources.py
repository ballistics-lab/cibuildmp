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

RESOURCE = "natmod.toml"


@cache
def natmod_data() -> dict[str, Any]:
    raw = (files(__package__).joinpath("resources", RESOURCE)).read_bytes()
    return tomllib.loads(raw.decode())

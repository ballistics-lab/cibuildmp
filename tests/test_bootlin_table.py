"""`resources/bootlin.toml` is well-formed, as a table.

Deliberately *not* a test that some `build-platforms.toml` row's
`bootlin_native`/`bootlin_cross` resolves here: no row names one yet, so
that test would pass by matching nothing -- which is exactly the failure
[0045] recorded ("a test asserting the behaviour passed vacuously for
months"). It comes with the first real row.

What is checked here has content today: three conditions that were
verified by hand while the generator was being written, and that stop
being a one-off by living here.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

# Evidence under `docs/reference/`, not a packaged resource -- nothing in
# `src/cibuildmp` loads it, so it is read by path here.
FACTS = (
    Path(__file__).resolve().parent.parent / "docs" / "reference" / "toolchain-facts"
)
with (FACTS / "bootlin.toml").open("rb") as _handle:
    RELEASES = tomllib.load(_handle)["bootlin"]["releases"]


def test_table_is_not_empty():
    # The guard that keeps every other test in this file from passing
    # vacuously if the generator ever writes an empty table.
    assert len(RELEASES) > 200


def test_name_is_unique():
    names = [row["name"] for row in RELEASES]
    assert len(set(names)) == len(names)


def test_name_matches_its_own_url():
    """`name` is read off the real filename, never composed from the
    other fields -- so it must round-trip to the URL it came from."""
    for row in RELEASES:
        assert row["url"].endswith(f"{row['name']}.{row['format']}"), row["name"]


def test_every_release_carries_a_checksum():
    for row in RELEASES:
        assert len(row["sha256"]) == 64, row["name"]
        assert set(row["sha256"]) <= set("0123456789abcdef"), row["name"]


def test_dockerfile_pins_resolve_to_a_row():
    """The two Bootlin tarballs already pinned in `docker/` must be in
    this table, with the same checksum -- the one check here that
    compares against something outside the generated file itself."""
    import re
    from pathlib import Path

    by_name = {row["name"]: row for row in RELEASES}
    root = Path(__file__).resolve().parent.parent
    pinned = 0
    for dockerfile in sorted((root / "docker").glob("*.Dockerfile")):
        text = dockerfile.read_text()
        release = re.search(r"BOOTLIN_RELEASE=([^\s\\]+)", text)
        digest = re.search(r"BOOTLIN_SHA256=([0-9a-f]{64})", text)
        if not release:
            continue
        row = by_name.get(release.group(1))
        assert row is not None, (
            f"{dockerfile.name}: {release.group(1)} not in bootlin.toml"
        )
        assert digest is not None, f"{dockerfile.name}: no BOOTLIN_SHA256"
        assert digest.group(1) == row["sha256"], dockerfile.name
        pinned += 1
    # Same anti-vacuity guard: a rename that stopped matching any
    # Dockerfile would otherwise turn this into a test of nothing.
    assert pinned >= 2

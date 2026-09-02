"""The per-row facts in `resources/build-platforms.toml` that no
generator produces, and the carry-forward that keeps a regeneration from
dropping them.

`gcc`, `idf_version` and `toolchain_version` are resolved by
`bin/refresh_toolchain_pins.py`, which "reads both files; it writes
neither" -- so they reach `build-platforms.toml` by hand.
`refresh_usermod_boards.py`/`refresh_natmod_archs.py` print a whole
section from scratch, and before `carry_forward()` existed a plain
regeneration silently deleted every one of them (374 `gcc` values for
`rp2` alone). Nothing would have caught it: no refresh script runs in CI,
in the tests, or in pre-commit.

Both scripts are loaded by path, the same way
`tests/test_render_test_summary.py` already loads its own.
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TABLE = REPO_ROOT / "src" / "cibuildmp" / "resources" / "build-platforms.toml"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, REPO_ROOT / "bin" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


usermod_boards = _load("refresh_usermod_boards")
natmod_archs = _load("refresh_natmod_archs")

with TABLE.open("rb") as handle:
    DATA = tomllib.load(handle)

# Today's real inventory, locked deliberately. This is the half that has
# to be edited by hand when a new per-row fact lands (record 0084's own
# `bootlin_native`/`bootlin_cross` will be the next), and that is the
# point: a fact appearing or vanishing should be a diff someone signs,
# not something a regeneration decides.
# Counts, not "every row": `natmod`'s `xtensa`/`xtensawin` carry no `gcc`
# at all, and that is a real fact rather than a half-finished merge --
# their toolchains come from Espressif and are not versioned by a gcc
# major. Locking the count still catches the failure this file exists for
# (374 -> 0 on a regeneration) without asserting something untrue about
# the data.
HAND_MERGED = {
    ("natmod",): {"gcc": 157},
    ("usermod", "alif"): {"toolchain_version": 6},
    ("usermod", "cc3200"): {"gcc": 18},
    ("usermod", "esp32"): {"idf_version": 442},
    ("usermod", "mimxrt"): {"gcc": 189},
    ("usermod", "nrf"): {"gcc": 408},
    ("usermod", "renesas-ra"): {"gcc": 113},
    ("usermod", "rp2"): {"gcc": 374},
    ("usermod", "samd"): {"gcc": 211},
    ("usermod", "stm32"): {"gcc": 1016},
    # `unix` carries no hand-merged fact at all now (record 0084). `gcc` went
    # because the image fixes the compiler; the relaxation that briefly
    # replaced it went too, to `build_common.TAG_CFLAGS` -- it protects `py/`,
    # which every port compiles, so a row in this one section could not say
    # it. An empty entry rather than a deleted one: "this section is known to
    # carry nothing" is the claim being locked.
    ("usermod", "unix"): {},
    ("usermod", "windows"): {"gcc": 45},
}


def _rows(section: tuple[str, ...]) -> list[dict]:
    data = DATA
    for key in section:
        data = data[key]
    return data["identifiers"]


def test_hand_merged_fact_coverage_is_locked():
    """A regeneration that dropped these would change the count, which is
    what this notices. Fewer *or* more is a diff someone has to sign."""
    for section, facts in HAND_MERGED.items():
        rows = _rows(section)
        assert rows, section
        for fact, expected in facts.items():
            actual = sum(1 for row in rows if fact in row)
            assert actual == expected, (
                f"{'.'.join(section)}: {fact} on {actual} rows, expected {expected}"
            )


def test_no_section_carries_an_unlisted_hand_merged_fact():
    """The other direction: a new per-row fact must be added above, so it
    cannot arrive unnoticed and then be lost the same way."""
    generated = {
        "tag",
        "arch",
        "arch_code",
        "arch_flags",
        "mpy",
        "cross",
        "identifier",
        "board",
        "mcu",
        "product",
        "vendor",
        "variants",
    }
    for scope, section in [(("natmod",), DATA["natmod"])] + [
        (("usermod", name), body) for name, body in sorted(DATA["usermod"].items())
    ]:
        rows = section.get("identifiers") or []
        found = {key for row in rows for key in row} - generated
        assert found == set(HAND_MERGED.get(scope, {})), f"{'.'.join(scope)}: {found}"


def test_identifier_is_unique_per_section():
    """`carry_forward()` matches on `identifier`; a duplicate would make
    it attach one row's facts to another."""
    for scope, section in [(("natmod",), DATA["natmod"])] + [
        (("usermod", name), body) for name, body in sorted(DATA["usermod"].items())
    ]:
        rows = section.get("identifiers") or []
        names = [row["identifier"] for row in rows]
        assert len(set(names)) == len(names), scope


def test_carry_forward_reattaches_what_a_generator_does_not_produce():
    """The real regression: rows shaped exactly as the generator emits
    them (no `gcc`) must come back with it."""
    for module, section, fact in (
        (usermod_boards, ("usermod", "rp2"), "gcc"),
        (usermod_boards, ("usermod", "esp32"), "idf_version"),
        (natmod_archs, ("natmod",), "gcc"),
    ):
        real = _rows(section)
        stripped = [
            {key: value for key, value in row.items() if key != fact} for row in real
        ]
        assert all(fact not in row for row in stripped)
        merged = module.carry_forward(stripped, section, TABLE)
        assert [row.get(fact) for row in merged] == [row.get(fact) for row in real]
        assert any(fact in row for row in merged), f"{section}: nothing carried"


def test_carry_forward_never_overwrites_a_generated_value():
    rows = [
        {"identifier": _rows(("usermod", "rp2"))[0]["identifier"], "gcc": "sentinel"}
    ]
    merged = usermod_boards.carry_forward(rows, ("usermod", "rp2"), TABLE)
    assert merged[0]["gcc"] == "sentinel"


def test_carry_forward_leaves_an_unknown_identifier_alone():
    rows = [{"identifier": "no-such-row"}]
    merged = usermod_boards.carry_forward(rows, ("usermod", "rp2"), TABLE)
    assert merged == [{"identifier": "no-such-row"}]

"""Usermod build identifiers, read straight from `resources/build-platforms.
toml`'s own real `(port, tag, arch/board)` rows -- the identical treatment
`natmod/targets.py`'s own `natmod_all_targets()` already has (record 0052's
Track C for natmod; this module's own live-caught correction, retracting
every axis-config concept -- `_PORT_AXES`, `archs =`/`boards =`, `auto`/
`native`/`all`, `GROUPS`/`--enable` -- in the same session that removed
them from natmod). Deliberately *not* natmod's own `Target` shape
(`mpy{abi}-{tag}-{arch}`): a usermod build carries no `.mpy` ABI axis at
all, it is not a module compiled against a running MicroPython's
compatibility tag, it *is* the MicroPython -- a full port binary meant to
be flashed or run directly. That is also why `usermod/orchestrate.py`
writes straight into `output-dir/<identifier>/` with no `package.json` next
to it (D14's own mip-install manifest does not apply here; confirmed with
the user before building this rather than assumed).

There is no version-axis narrowing step here the way natmod needs
`narrow_to_newest_tag()`: natmod's identifier leads with an ABI that
several distinct MicroPython tags can share, so an ABI-only glob has to be
told which of them is "the" one; a usermod identifier's own leading tag
(or, for `unix`/`windows`/`webassembly`, its own real `identifier` value
straight off the row -- see `_row_axis_value()`) already names one exact
release with nothing left to disambiguate. Candidates = every real row,
always; `build`/`skip` narrow them directly.

Nothing here touches the filesystem or network, the same discipline
`natmod/targets.py` already holds itself to: deriving the identifier set a
config selects has to stay usable for `--print-build-identifiers` without a
MicroPython checkout.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...resources import build_platforms_data

# The five ports with a real `build_<port>()` driver in usermod/build.py --
# the other ten `resources/build-platforms.toml` already carries real,
# verified rows for (rp2, mimxrt, samd, stm32, psoc-edge, alif, esp8266,
# cc3200, renesas-ra, nrf) are a separate, much larger piece of unstarted
# work (writing each one's own build pipeline), not a config-surface gap
# this module could close by itself.
KNOWN_PORTS: tuple[str, ...] = ("unix", "windows", "qemu", "webassembly", "esp32")

_USERMOD_ROWS: dict[str, list[dict[str, Any]]] = {
    port: build_platforms_data()["usermod"][port]["identifiers"] for port in KNOWN_PORTS
}


def _row_axis_value(row: dict[str, Any]) -> str:
    """`unix`/`windows`/`webassembly` rows key their own per-build cell
    `"arch"`; `qemu`/`esp32` key it `"board"` -- `UsermodTarget.arch` is
    this project's own generic name for either, matching what it has
    always meant on this dataclass."""
    return str(row.get("board", row.get("arch", "")))


# (port, tag, arch/board) -> that row's own real `identifier`, straight
# from `resources/build-platforms.toml` -- matched against a real fact,
# never rebuilt from a guessed format (mirrors natmod/targets.py's own
# `_IDENTIFIER_BY_TAG_ARCH`, cross-checked against cibuildwheel's real
# `PythonConfiguration.identifier`, a literal field, never computed). Each
# port's own `identifier_format` in the source TOML is not uniform --
# `unix`/`windows`/`webassembly` carry no port name at all
# (`"{tag}-{arch}"`, e.g. `v1.20.0-manylinux_2_28_x86_64`), `qemu`/`esp32`
# do (`"{tag}-{port}-{board}"`, e.g. `v1.24.0-qemu-MICROBIT`) -- this table
# does not need to know that difference exists, since it stores and looks
# up each row's own already-formatted value directly.
_IDENTIFIER_BY_PORT_TAG_AXIS: dict[tuple[str, str, str], str] = {
    (port, row["tag"], _row_axis_value(row)): row["identifier"]
    for port, rows in _USERMOD_ROWS.items()
    for row in rows
}

# (tag, board) -> (idf_version, mcu) -- esp32-only, since it is the one
# port whose own board axis carries a real per-row toolchain fact
# `UsermodTarget` itself does not (D19: eight distinct `idf_version`
# values across this table, and `mcu` is `idf_tools.py install
# --targets=`'s own real vocabulary, e.g. "esp32"/"esp32c3"/"esp32s3").
# `UsermodTarget` stays `port`/`arch`/`tag` only -- widening it for one
# port's own extra axis would put a field every other port's own target
# carries and ignores on the shared dataclass; a lookup keyed the same
# way `_IDENTIFIER_BY_PORT_TAG_AXIS` already is keeps that fact where it
# belongs, resolved from `board`/`tag` rather than carried on the target.
_ESP32_IDF_INFO_BY_TAG_BOARD: dict[tuple[str, str], tuple[str, str]] = {
    (row["tag"], row["board"]): (row["idf_version"], row["mcu"])
    for row in _USERMOD_ROWS["esp32"]
}


def esp32_idf_info(tag: str, board: str) -> tuple[str, str]:
    """This `(tag, board)`'s own real `(idf_version, idf_target)` --
    `usermod/orchestrate.py`'s `_port_build_options()` is the one real
    caller, resolving what `Esp32BuildOptions` needs from a target that
    itself carries only `board`/`tag`. `KeyError` here means a hand-built
    target naming a combination the file has never walked, the same
    class of caller `UsermodTarget.identifier`'s own docstring already
    covers for the identifier lookup."""
    return _ESP32_IDF_INFO_BY_TAG_BOARD[(tag, board)]


class UnknownPortError(ValueError):
    pass


@dataclass(frozen=True)
class UsermodTarget:
    port: str
    arch: str = ""
    # The MicroPython release this target is built against -- the
    # compatibility axis usermod was entirely missing before 0051 (a
    # second release's build silently overwrote the first's, since
    # nothing distinguished them: not the identifier, not the output
    # filename, not the directory). Leads the identifier, unconditionally,
    # the same position natmod's own `mpy6.3-` slot holds -- see D51's own
    # "not conditional" argument.
    #
    # Defaults empty only for targets built by hand -- most existing
    # tests, which are not about versioning. Every target
    # `all_usermod_targets()` produces always has a real one.
    tag: str = ""

    @property
    def identifier(self) -> str:
        # Matched against `_IDENTIFIER_BY_PORT_TAG_AXIS` (a real row's own
        # `identifier` field) when a tag is given -- every real caller only
        # ever builds a `UsermodTarget` from `all_usermod_targets()` below,
        # itself reading straight off real rows, so `KeyError` here can
        # only fire for a hand-built `UsermodTarget` naming a
        # (port, tag, arch) combination the file has never walked, and
        # should. A target built by hand with no tag at all (most of this
        # project's own build/orchestrate tests, which are about build
        # mechanics rather than real-row verification) falls back to the
        # plain, pre-0052 `{port}-{arch}` shape instead of a lookup.
        if self.tag:
            return _IDENTIFIER_BY_PORT_TAG_AXIS[(self.port, self.tag, self.arch)]
        return f"{self.port}-{self.arch}" if self.arch else self.port

    def __str__(self) -> str:
        return self.identifier


def all_usermod_targets() -> list[UsermodTarget]:
    """One `UsermodTarget` per real `(port, tag, arch/board)` row in
    `build-platforms.toml` -- the raw fact list `UsermodOptions.targets()`/
    `all_targets()` glob-match `build`/`skip`/`[override]` against
    directly, the identical shape `natmod_all_targets()` already has (and,
    through it, cibuildwheel's own real `get_python_configurations()`:
    filter a literal row list read straight from data). No axis config, no
    per-port table, no tag-list config, no narrowing step of any kind --
    every row's own tag is already a distinct, explicit part of its own
    identity, so there is nothing left here to disambiguate the way
    natmod's `narrow_to_newest_tag()` still has to.
    """
    return [
        UsermodTarget(port=port, arch=_row_axis_value(row), tag=row["tag"])
        for port in KNOWN_PORTS
        for row in _USERMOD_ROWS[port]
    ]


# select() moved to cibuildmp.selector in 0051: it was duplicated here
# rather than shared, typed list[Target] there vs list[UsermodTarget]
# here, and that duplication is exactly the shape record 0048's drift
# (build/skip read from opposite config tables) came from. The shared
# version is generic (a Protocol, not a concrete Target type), so both
# modes now import the one copy.

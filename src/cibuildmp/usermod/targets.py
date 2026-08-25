"""Usermod build identifiers: `{port}`, or `{port}-{arch}` when the port
has a real per-build axis (`unix`/`windows`'s arch, `esp32`'s board) --
deliberately *not* natmod's own `Target` shape (`mpy{abi}-{mode}-{arch}`).
A usermod build carries no `.mpy` ABI axis at all: it is not a module
compiled against a running MicroPython's compatibility tag, it *is* the
MicroPython -- a full port binary meant to be flashed or run directly.
That is also why `usermod/orchestrate.py` writes straight into
`output-dir/<identifier>/` with no `package.json` next to it (D14's own
mip-install manifest does not apply here; confirmed with the user before
building this rather than assumed).

Nothing here touches the filesystem or network, the same discipline
`targets.py` already holds itself to: deriving the identifier set a
config selects has to stay usable for `--print-build-identifiers`
without a MicroPython checkout.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..targets import matches, parse_selector
from .build import UNIX_RUNNABLE_ARCHS, WINDOWS_ARCH_SETTINGS

# port -> (config axis key, every axis value this project can currently
# build, in identifier order). A `None` key means the port has no
# configurable axis at all yet -- qemu only wires MPS2_AN385
# (usermod/build.py's own QemuBuildOptions), webassembly only the
# "pyscript" variant -- represented as the single "" axis value so
# UsermodTarget.identifier stays just the bare port name rather than a
# fake `qemu-` suffix. `esp32`'s default is ESP32_GENERIC only, even
# though other ESP32-family boards are selectable (README's own
# usermod table footnote: selectable, not itself live-verified) --
# not defaulted to, the same "default = everything actually proven"
# rule `unix`'s own default (excluding armhf/mipsel) already follows.
_PORT_AXES: dict[str, tuple[str | None, tuple[str, ...]]] = {
    "unix": ("archs", UNIX_RUNNABLE_ARCHS),
    "windows": ("archs", tuple(WINDOWS_ARCH_SETTINGS)),
    "qemu": (None, ("",)),
    "webassembly": (None, ("",)),
    "esp32": ("boards", ("ESP32_GENERIC",)),
}

KNOWN_PORTS: tuple[str, ...] = tuple(_PORT_AXES)


class UnknownPortError(ValueError):
    pass


class UnknownAxisError(ValueError):
    pass


def axis_key(port: str) -> str | None:
    """The `[usermod.<port>]` key this port's axis is configured under
    (`"archs"`/`"boards"`), or `None` if it has none yet."""
    try:
        return _PORT_AXES[port][0]
    except KeyError:
        raise UnknownPortError(
            f"unknown usermod port {port!r}. Known: {', '.join(KNOWN_PORTS)}"
        ) from None


def default_axis_values(port: str) -> tuple[str, ...]:
    try:
        return _PORT_AXES[port][1]
    except KeyError:
        raise UnknownPortError(
            f"unknown usermod port {port!r}. Known: {', '.join(KNOWN_PORTS)}"
        ) from None


@dataclass(frozen=True)
class UsermodTarget:
    port: str
    arch: str = ""

    @property
    def identifier(self) -> str:
        return f"{self.port}-{self.arch}" if self.arch else self.port

    @property
    def default_runner(self) -> str:
        # Every port here builds on a plain ubuntu-latest host today --
        # D18's own windows conclusion (Linux-hosted cross-compile, all
        # three arches) and this session's own unix/aarch64 correction
        # both collapsed what first looked like a structural
        # runner-selection need (D20) into "building, unlike executing,
        # needs no special host at all." D21's own execution axis (D6,
        # not scheduled) is the one that will actually need
        # aarch64/windows/etc runners -- not this, which is build-only.
        return "ubuntu-latest"

    def __str__(self) -> str:
        return self.identifier


def usermod_targets(
    ports: list[str], axis_overrides: dict[str, list[str]]
) -> list[UsermodTarget]:
    """One `UsermodTarget` per (port, axis value).

    Axis values come from `axis_overrides[port]` when given, this port's
    own `default_axis_values()` otherwise -- the same "config overrides
    the built-in default list" shape `natmod_targets()`'s own `archs`
    parameter already has. Preserves `ports`' own order, then each port's
    axis-value order.
    """
    unknown = [p for p in ports if p not in _PORT_AXES]
    if unknown:
        raise UnknownPortError(
            f"unknown usermod port(s): {', '.join(sorted(unknown))}. Known: "
            f"{', '.join(KNOWN_PORTS)}"
        )
    targets = []
    for port in ports:
        key, defaults = _PORT_AXES[port]
        values = axis_overrides.get(port) or list(defaults)
        if key is None and values != [""]:
            raise UnknownAxisError(
                f"usermod/{port} has no configurable axis yet -- remove "
                f"[usermod.{port}] from the config"
            )
        for value in values:
            targets.append(UsermodTarget(port=port, arch=value))
    return targets


def select(
    targets: list[UsermodTarget], build: str | list[str], skip: str | list[str]
) -> list[UsermodTarget]:
    """Apply build/skip globs, skip last -- same shape `targets.select()`
    already has for natmod, kept as its own copy rather than a shared
    generic: `targets.select()`'s own signature is typed `list[Target]`,
    and reusing it here for `UsermodTarget` would only typecheck via a
    reworked, more general signature there, for four lines of logic that
    are just as clear duplicated."""
    build_patterns = parse_selector(build) or ["*"]
    skip_patterns = parse_selector(skip)
    return [
        t
        for t in targets
        if matches(t.identifier, build_patterns)
        and not matches(t.identifier, skip_patterns)
    ]

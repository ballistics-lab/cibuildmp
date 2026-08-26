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

from ..natmod.targets import matches, parse_selector
from .build import WINDOWS_ARCH_SETTINGS

# port -> (config axis key, every axis value this project can currently
# build, in identifier order). A `None` key means the port has no
# configurable axis at all yet -- webassembly only the "pyscript" variant
# -- represented as the single "" axis value so UsermodTarget.identifier
# stays just the bare port name rather than a fake `-` suffix.
#
# `qemu`'s own default stays the single `""` sentinel, not `MPS2_AN385`,
# even though it now has a real `"boards"` axis (build_qemu() also
# resolves VIRT_RV32/VIRT_RV64, each its own natmod RISC-V toolchain) --
# a real, live-verified `board` value here would rename every existing
# caller's own default identifier from bare `qemu` to `qemu-MPS2_AN385`,
# breaking a7p's own already-wired `build-usermod-armv7m` action for no
# behavioural gain (still the same board, same toolchain). Opting into
# `[usermod.qemu] boards = [...]` (with a real board name) is what
# switches to the `qemu-<board>` identifier shape -- the same "default
# preserved, opt-in gets the new shape" rule **D15**'s own `+0x..` suffix
# already follows for rv32imc's arch-flags.
#
# `esp32`'s default is ESP32_GENERIC only, even though other ESP32-family
# boards are selectable (README's own usermod table footnote: selectable,
# not itself live-verified) -- not defaulted to, the same "default =
# everything actually proven" rule `unix`'s own default below already
# follows.
#
# `unix`'s own default is a deliberate subset of what it can build, not
# `unix_targets()` in full -- **record 0043**, which took that matrix from
# five cells to fifteen (seven architectures under pypa's own names x
# manylinux/musllinux, plus `manylinux_2_39_mipsel`). Defaulting to all fifteen
# would silently turn every existing consumer's single `[usermod] ports =
# ["unix"]` line into fifteen emulated container builds.
#
# What is listed is the *previous* default, translated one-for-one into
# the new names and floors -- `x64`->`manylinux_2_28_x86_64`,
# `x86`->`manylinux_2_28_i686`, `aarch64`->`manylinux_2_28_aarch64`,
# `armhf`->`manylinux_2_31_armv7l` (armv7l's lowest floor upstream
# publishes), `mipsel`->`manylinux_2_39_mipsel`. Nothing newly gained a default:
# `ppc64le`/`s390x`/`riscv64` and the whole musllinux column are
# selectable via `[usermod.unix] archs = [...]`, which is the same
# "default = everything actually proven at the time it became the
# default" rule `qemu`'s own boards and `esp32`'s own single board
# already follow.
_UNIX_DEFAULT_TARGETS: tuple[str, ...] = (
    "manylinux_2_28_x86_64",
    "manylinux_2_28_i686",
    "manylinux_2_28_aarch64",
    "manylinux_2_31_armv7l",
    "manylinux_2_39_mipsel",
)

_PORT_AXES: dict[str, tuple[str | None, tuple[str, ...]]] = {
    "unix": ("archs", _UNIX_DEFAULT_TARGETS),
    "windows": ("archs", tuple(WINDOWS_ARCH_SETTINGS)),
    "qemu": ("boards", ("",)),
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

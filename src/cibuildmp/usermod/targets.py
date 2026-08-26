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

# Platform-tag suffixes whose builds want an arm64 runner -- matched on
# the tag's own end (`manylinux_2_28_aarch64`, `musllinux_1_2_armv7l`)
# rather than by splitting it, so this stays pure and needs no pin-table
# read. See `UsermodTarget.default_runner` for why `armv7l` is in here
# despite being the uncertain half.
_ARM_RUNNER_ARCHS = ("_aarch64", "_armv7l")


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


def all_axis_values(port: str) -> tuple[str, ...]:
    """Every axis value that *exists* for this port, not the subset it
    defaults to -- cibuildmp's own `read_all_configs()` (**0045**).

    The two differ for exactly one port today, and only since [0044]:
    `unix` declares fifteen cells and defaults to five, so
    `default_axis_values("unix")` is deliberately not the answer to "what
    can be named". Every other port defaults to everything it has.

    `unix`'s full list comes from the pin table rather than from a
    literal here, for the same reason `UNIX_RUNNABLE_ARCHS` is derived:
    `resources/pinned_docker_images.toml`'s own `[image.<arch>]` keys are
    the matrix, and a second hand-maintained copy would only be a place
    for the two to drift. That does mean this one function reads a
    packaged resource, unlike the rest of this module -- acceptable, and
    the same thing `usermod/portinfo.py` already does with `usermod.toml`;
    what this module actually promises is that naming targets needs no
    MicroPython checkout, and that still holds.
    """
    if port == "unix":
        from .dockerrun import unix_targets

        return unix_targets()
    return default_axis_values(port)


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
        """The GitHub runner label a matrix leg for this target should use.

        Arch-aware since records 0043/0044 made every `unix` image native
        to its own architecture. Before that this was a hardcoded
        `ubuntu-latest` and correctly so: every port cross-compiled from
        amd64, so no target cared what the host was. Now two of them do --
        an `aarch64` image on an amd64 runner runs under binfmt/QEMU, and
        that is measured at roughly 20x a native build (0044: 46s native
        x86_64 against 1041s emulated aarch64 on the same machine).
        Naming an arm64 runner for those makes the build native instead.

        0043's own opening observation was that this hardcode existed and
        that natmod had a `runs-on` knob while usermod did not. This
        closes half of it: cibuildmp can now *emit* an arm64 runner. There
        is still no per-target config override, which is the other half.

        **`armv7l` was a bet when it was added here, and it paid off.**
        A 32-bit ARM binary is native on an arm64 host only if that CPU
        implements AArch32 at EL0, and the server-class parts GitHub uses
        (Graviton, Ampere Altra) were expected not to -- which would have
        left this target emulated, just on a different host. Run
        32958683512 settles it: the `manylinux_2_31_armv7l` leg on
        `ubuntu-24.04-arm` built in **59.5s, faster than the native
        `aarch64` leg's own 88.8s on the same runner class**. Emulation
        costs a multiple, not two thirds, so those parts do implement
        AArch32 at EL0 and this entry stays.

        Recorded as timing evidence rather than as a direct capability
        check, and the distinction still matters: cibuildwheel's own
        `Architecture.bitness_archs()` carries an explicit AArch32 EL0
        check for exactly ARM64 Linux, which remains the more careful
        thing for a tool that must be right on *any* arm64 host. What is
        settled here is GitHub's runners specifically. If that ever stops
        being true the cost is nil -- emulated either way -- and this
        entry moves back.

        Only `unix` is arch-aware. `windows`, `qemu`, `webassembly` and
        `esp32` cross-compile to Windows, bare metal and wasm from an
        amd64 Linux toolchain host, so an arm64 runner would only emulate
        their images for no gain.
        """
        if self.port == "unix" and self.arch.endswith(_ARM_RUNNER_ARCHS):
            return "ubuntu-24.04-arm"
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


def all_usermod_targets() -> list[UsermodTarget]:
    """Every identifier this project can name, across every known port --
    what `--only` resolves against (**0045**).

    Deliberately independent of any config: not the ports it selects, not
    its axis overrides, not its `build`/`skip`. Upstream's `--only` takes
    its `choices` from `read_all_configs()` for the same reason -- "force
    exactly this one build" should not be answerable with "your config
    does not select that".
    """
    return [
        UsermodTarget(port=port, arch=value)
        for port in KNOWN_PORTS
        for value in all_axis_values(port)
    ]


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

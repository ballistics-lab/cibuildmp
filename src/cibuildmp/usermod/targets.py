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

import platform
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
# The five manylinux entries are the *previous* default translated
# one-for-one into the new names and floors -- `x64`->`manylinux_2_28_x86_64`,
# `x86`->`manylinux_2_28_i686`, `aarch64`->`manylinux_2_28_aarch64`,
# `armhf`->`manylinux_2_31_armv7l` (armv7l's lowest floor upstream
# publishes), `mipsel`->`manylinux_2_39_mipsel`.
#
# **The four musllinux entries were added on 2026-08-26, when the rule
# above started requiring them.** They are exactly the musl cells with a
# runner they are native to, and all four are green and required in CI
# (run 32961216804) -- so by "default = everything actually proven" they
# qualified, and leaving them out would have meant the rule said one
# thing and the list another.
#
# The argument for holding them back was cost, and it did not survive
# being stated: the default CI layout is one job looping over every
# target (**D9**), where nothing is native to anything and `aarch64`/
# `armv7l` are emulated regardless of which libc column they are in. The
# default already carried two such cells before this change. Adding two
# more of the same shape is a quantitative difference in an already-known
# cost, not a new kind of cost -- and the *right* fix for it is 0045's
# `auto`/`native` vocabulary, which makes "which cells does a bare
# `ports = ["unix"]` mean" a question about the host rather than a
# hardcoded list. Until that exists, the rule as written wins.
#
# Still not defaulted to, and for the original reason: `ppc64le`,
# `s390x`, `riscv64` (both columns) are emulated on every runner GitHub
# offers, have never been built, and Alpine's own `community/micropython`
# excludes the first two outright. They stay selectable via
# `[usermod.unix] archs = [...]` or `--only`.
#
# Ordered the way `dockerrun.unix_targets()` orders the full matrix --
# by architecture, both libcs together, `mipsel` last -- so there is one
# ordering rule in the codebase rather than two.
_UNIX_DEFAULT_TARGETS: tuple[str, ...] = (
    "manylinux_2_28_x86_64",
    "musllinux_1_2_x86_64",
    "manylinux_2_28_i686",
    "musllinux_1_2_i686",
    "manylinux_2_28_aarch64",
    "musllinux_1_2_aarch64",
    "manylinux_2_31_armv7l",
    "musllinux_1_2_armv7l",
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

# Ports a bare `[usermod]` with no `ports` key does *not* select.
#
# `esp32` is temporarily out. It is the one port with no Docker path at
# all ([0028]) -- no `esp32.Dockerfile`, no pinned image -- so it is also
# the one port that cannot satisfy the Docker-only rule D30 states and
# every other port now follows. Its build provisions ESP-IDF onto the
# host instead (clone + tool install, D19), which is precisely the
# bare-host mutation the rest of this module stopped doing.
#
# Out of the *default*, not out of `KNOWN_PORTS`: `esp32-ESP32_GENERIC`
# is still a real identifier, `--only` still reaches it, and a config
# that names it in `ports` still builds it. What changes is that a
# config which says nothing no longer gets it, so the ESP-IDF path stops
# being something every default invocation drags along. [0028] is where
# it comes back, with an image.
_NON_DEFAULT_PORTS: frozenset[str] = frozenset({"esp32"})

DEFAULT_PORTS: tuple[str, ...] = tuple(
    p for p in KNOWN_PORTS if p not in _NON_DEFAULT_PORTS
)

# ── the auto/native/all vocabulary ────────────────────────────────────
#
# Record 0049. cibuildwheel's `Architecture.parse_config()` accepts the
# literal words `auto`, `native` and `all` beside explicit names, and
# that is how upstream distributes work across runners: it emits no
# matrix and has no opinion about hosts, so each job says `CIBW_ARCHS:
# auto` and the runner it happens to be on decides what that means.
# cibuildmp had neither -- no vocabulary, and a `default_runner` that
# routed targets to hosts instead. The routing is gone; this is what
# replaces it.
#
# **Only `unix` has a host-dependent axis, and that is not a
# simplification.** Its cells are native containers for their own
# architecture (0043), so which of them this machine runs without
# emulation is a real question. No other port's axis is: `windows`
# cross-compiles to three Windows arches out of one amd64 image, `qemu`
# and `esp32` name boards, `webassembly` has no axis at all. For those,
# `auto` and `native` mean the same as `all` -- which is natmod's own
# recorded argument for having no `auto` ("every natmod arch is a
# cross-compile, so none of them depends on what this machine is",
# 0045), applied where it also holds.
#
# **Nothing here decides what *can* be built.** A non-native cell still
# builds anywhere: `dockerrun.run()` passes `--platform` and binfmt does
# the rest, which is the entire mechanism and needs no host knowledge at
# all. These words choose a *subset to build here*, on this machine, and
# are re-decided on every machine -- the distinction 0045 drew when it
# reconciled this with 0043's rule that host architecture appears in no
# identifier, image name or pin key. Those are facts that must mean the
# same thing everywhere; this is a local convenience.
#
# ── where the native table is a bet, and why that is affordable ───────
#
# `native` is exactly this machine's architecture. `auto` adds the
# 32-bit sibling it can also execute directly -- `i686` on `x86_64`,
# `armv7l` on `aarch64` -- which is the only difference between the two
# words upstream, too.
#
# The `aarch64` -> `armv7l` entry can be wrong: 32-bit ARM runs natively
# on an arm64 host only if the CPU implements AArch32 at EL0, and not
# every server part does. cibuildwheel carries a runtime check for
# exactly this. A static table is enough here because **the cost of
# being wrong is bounded to speed**: a cell wrongly called native still
# builds, emulated, since `--platform` is passed either way. That is a
# different kind of mistake from one that produces a wrong binary, and
# it is why the same shortcut would not be acceptable in `dockerrun`.
#
# On the hosts that matter it is measured rather than assumed: GitHub's
# `ubuntu-24.04-arm` runners do implement AArch32 at EL0 -- an `arm/v7`
# container there reports `armv8l` (a 64-bit ARMv8 kernel's name for a
# 32-bit process; `qemu-arm` reports `armv7l`) and builds that cell in
# 59.5s against the native `aarch64` build's own 88.8s (0044).
#
# This module still touches no filesystem and no network.
# `platform.machine()` is a process-local fact and does not break that.
_NATIVE_SIBLINGS: dict[str, tuple[str, ...]] = {
    "x86_64": ("i686",),
    "aarch64": ("armv7l",),
}

# `platform.machine()` spellings that name an architecture this project
# already has a name for. pypa's names are the project's (0043), and a
# kernel does not always agree with them.
_MACHINE_ALIASES: dict[str, str] = {
    "amd64": "x86_64",
    "arm64": "aarch64",
    "i386": "i686",
    "i586": "i686",
    "i686": "i686",
    "armv7l": "armv7l",
    "armv8l": "armv7l",
}

# The OCI platform each architecture name means, for asking "is this
# image native here". `dockerrun` owns the target->platform direction and
# is deliberately not asked for the inverse: it has no reason to know
# what a *host* is beyond `host_oci_platform()`, which never leaves that
# module (0043).
_ARCH_OCI_PLATFORMS: dict[str, str] = {
    "x86_64": "linux/amd64",
    "i686": "linux/386",
    "aarch64": "linux/arm64",
    "armv7l": "linux/arm/v7",
    "ppc64le": "linux/ppc64le",
    "s390x": "linux/s390x",
    "riscv64": "linux/riscv64",
}

ARCH_KEYWORDS: tuple[str, ...] = ("auto", "native", "all")


def host_arch(machine: str | None = None) -> str:
    """This machine's architecture under the project's own names.

    `machine` is injectable so a test can ask about a host it is not
    running on; the alternative is monkeypatching `platform.machine`,
    which makes every such test order-dependent.
    """
    raw = (machine if machine is not None else platform.machine()).lower()
    return _MACHINE_ALIASES.get(raw, raw)


def resolve_axis_keyword(
    port: str, keyword: str, *, machine: str | None = None
) -> list[str]:
    """Expand `auto`/`native`/`all` into this port's own axis values.

    Unknown words are returned unexpanded by the caller, not here: a
    keyword and an explicit axis value share one namespace, and deciding
    which a string is belongs with the rest of axis parsing.
    """
    from .dockerrun import platform_for

    values = list(all_axis_values(port))
    if keyword == "all":
        return values
    wanted = (host_arch(machine),)
    if keyword == "auto":
        wanted = (*wanted, *_NATIVE_SIBLINGS.get(wanted[0], ()))
    native = {
        _ARCH_OCI_PLATFORMS[arch] for arch in wanted if arch in _ARCH_OCI_PLATFORMS
    }
    # Asked of the **image**, not of the tag. `manylinux_2_39_mipsel` is
    # the case that makes the difference: it names `mipsel` and runs in a
    # `linux/amd64` container, because pypa publishes no mipsel image and
    # there is nothing for it to be native to (0044), so it cross-compiles
    # from an amd64 base like the non-`unix` ports do. Matching on the
    # tag's own suffix would call it non-native on the one host it is
    # actually native on. `platform_for()` reads the same bundled pin
    # table `all_axis_values()` already went through, so this adds no new
    # kind of dependency.
    # **One rule for every port, asked of the image.** An earlier draft
    # exempted the ports with no architecture axis -- `windows`, `qemu`,
    # `webassembly` -- on the grounds that "what runs natively here" is
    # not a question they have. That was wrong in the way that costs
    # wall-clock: their images are `linux/amd64`, so on an arm64 runner
    # they run emulated exactly like a non-native `unix` cell does, and
    # `auto` kept selecting them anyway. `webassembly` was being built
    # three times in one CI run as a result -- twice by `auto` and once
    # more by the job that deliberately tests it emulated.
    #
    # The question those ports do not have is which *axis value* is
    # native; the question they very much do have is whether their one
    # image is. `platform_for()` answers both -- per cell for `unix`,
    # per port for everything else -- so the same expression covers them
    # and there is no port-name special case left here at all.
    #
    # A port whose image *platform* cannot be resolved at all is kept
    # rather than dropped: "cannot tell" is not "not native", and it
    # will fail with its own clear error the moment something tries to
    # build it. That is not the same as having no image published --
    # `esp32` has a platform (`linux/amd64`) and no image yet, so `auto`
    # treats it like any other amd64 port and it is filtered normally.
    return [
        v for v in values if (plat := platform_for(port, v)) is None or plat in native
    ]


def parse_axis_values(
    port: str, values: list[str], *, machine: str | None = None
) -> list[str]:
    """A configured or `--archs` axis list, with keywords expanded.

    Order is the axis's own, not the caller's, and duplicates collapse:
    `["auto", "manylinux_2_28_s390x"]` is a legitimate thing to write --
    "what runs here, plus this one" -- and it should not depend on which
    side of the comma a cell appeared on.
    """
    expanded: list[str] = []
    for value in values:
        expanded.extend(
            resolve_axis_keyword(port, value, machine=machine)
            if value in ARCH_KEYWORDS
            else [value]
        )
    axis_order = list(all_axis_values(port))
    ordered = [v for v in axis_order if v in expanded]
    # Anything the axis does not know stays, in the order given, so the
    # existing "unknown axis value" error still fires where it did.
    return ordered + [v for v in expanded if v not in axis_order]


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

    `auto`/`native`/`all` are expanded here, so every caller gets the
    vocabulary for free and none of them has to know it exists.
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
        # One place for keyword expansion, so `[usermod.<port>] archs =
        # ["auto"]` and `--archs auto` mean the same thing without either
        # caller knowing the vocabulary exists (record 0049).
        values = parse_axis_values(port, values)
        # `[]` is a legitimate outcome, not a misconfiguration: `auto` on
        # a host this port's image is not native to selects nothing here,
        # and the port is simply skipped. Only a *populated* axis on a
        # port that has none is the error this guard was written for.
        if key is None and values not in ([""], []):
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

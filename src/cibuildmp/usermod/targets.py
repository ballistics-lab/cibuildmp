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
# `unix`'s own default used to be a hardcoded nine-cell subset of the
# fifteen `unix_targets()` declares (`_UNIX_DEFAULT_TARGETS`, deleted in
# **0051** point 8). As of that record, `default_axis_values("unix")`
# below is the *full* fifteen -- the axis itself no longer holds any cell
# out. What still keeps `build = "*"` at nine cells by default is
# `GROUPS["unix-emulated-everywhere"]` further down: a target matching an
# unenabled group is dropped before `build`/`skip` is even checked
# (`cibuildmp.selector.select()`), so nothing observable changes for a
# bare `ports = ["unix"]` config -- only the mechanism keeping the other
# six out changed, from "not in the axis" to "in the axis, ungrouped-in".
# See the `GROUPS` table below for which six and why.
_PORT_AXES: dict[str, tuple[str | None, tuple[str, ...]]] = {
    "unix": ("archs", ()),  # default is derived -- see default_axis_values()
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

# ── opt-in groups (0051 point 8, upstream's own EnableGroup) ────────────
#
# `ppc64le`/`s390x`/`riscv64` (both libcs) are native to no runner GitHub
# offers and have never been built, here or by hand -- tracker [0044]'s
# own "the six emulated-everywhere cells: build them or descope" is what
# this answers. They stopped being absent from `unix`'s own axis (see
# `_PORT_AXES` above); this is what still keeps a bare `build = "*"` from
# reaching them -- `cibuildmp.selector.select()` drops a target matching
# an unenabled group's patterns before `build`/`skip` is even checked, so
# `enable = ["unix-emulated-everywhere"]` (config) or
# `--enable unix-emulated-everywhere` (CLI, repeatable) is what's needed
# now, in place of a `[usermod.unix] archs = [...]` naming them by hand.
#
# Glob-based, not an enumerated floor list, so a new floor added to
# `pinned_docker_images.toml` for one of these arches is covered without
# an edit here.
GROUPS: dict[str, list[str]] = {
    "unix-emulated-everywhere": [
        f"*-unix-*_{arch}" for arch in ("ppc64le", "s390x", "riscv64")
    ],
}

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
    from ..dockerrun import platform_for

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
    """Every axis value that *exists* for this port -- cibuildmp's own
    `read_all_configs()` (**0045**).

    Equal to `default_axis_values(port)` for every port, `unix` included
    as of **0051** point 8 (previously the one exception: `unix` declared
    fifteen cells and defaulted to nine, so the two functions disagreed).
    Kept as a separate name because the two questions are conceptually
    different -- "what can `--only` name" versus "what does a bare
    `build = '*'` build" -- even though the answer is the same list now
    that a `GROUPS` entry, not axis membership, is what still holds six
    `unix` cells out of the second one.

    `unix`'s list comes from the pin table rather than from a literal
    here, for the same reason `UNIX_RUNNABLE_ARCHS` is derived:
    `resources/pinned_docker_images.toml`'s own `[image.<arch>]` keys are
    the matrix, and a second hand-maintained copy would only be a place
    for the two to drift. That does mean this one function reads a
    packaged resource, unlike the rest of this module -- acceptable, and
    the same thing `usermod/portinfo.py` already does with `usermod.toml`;
    what this module actually promises is that naming targets needs no
    MicroPython checkout, and that still holds.
    """
    if port == "unix":
        from ..dockerrun import unix_targets

        return unix_targets()
    return default_axis_values(port)


def default_axis_values(port: str) -> tuple[str, ...]:
    if port == "unix":
        from ..dockerrun import unix_targets

        return unix_targets()
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
    # The MicroPython release this target is built against -- the
    # compatibility axis usermod was entirely missing before 0051 (a
    # second release's build silently overwrote the first's, since
    # nothing distinguished them: not the identifier, not the output
    # filename, not the directory). Leads the identifier, unconditionally,
    # the same position natmod's own `mpy6.3-` slot holds -- see D51's own
    # "not conditional" argument: a component that only appears once more
    # than one tag is selected makes a glob like `build = "*-v1.29.0"`
    # match in some configs and nothing in others.
    #
    # Defaults empty only for targets built by hand -- most existing
    # tests, which are not about versioning. Every target
    # `usermod_targets()`/`all_usermod_targets()` produce always has a
    # real one: `micropython` always defaults to a non-empty list.
    tag: str = ""

    @property
    def identifier(self) -> str:
        base = f"{self.port}-{self.arch}" if self.arch else self.port
        return f"{self.tag}-{base}" if self.tag else base

    def __str__(self) -> str:
        return self.identifier


def usermod_targets(
    tags: list[str], ports: list[str], axis_overrides: dict[str, list[str]]
) -> list[UsermodTarget]:
    """One `UsermodTarget` per (tag, port, axis value) (**0051**) -- the
    MicroPython release is the leading axis, matching natmod's own
    per-ABI grouping (`natmod_targets()`/`cli.build()`'s tag_groups()).

    Axis values come from `axis_overrides[port]` when given, this port's
    own `default_axis_values()` otherwise -- the same "config overrides
    the built-in default list" shape `natmod_targets()`'s own `archs`
    parameter already has. Preserves `tags`' own order, then `ports`' own
    order, then each port's axis-value order.

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
    for tag in tags:
        for port in ports:
            key = _PORT_AXES[port][0]
            values = axis_overrides.get(port) or list(default_axis_values(port))
            # One place for keyword expansion, so `[usermod.<port>] archs
            # = ["auto"]` and `--archs auto` mean the same thing without
            # either caller knowing the vocabulary exists (record 0049).
            values = parse_axis_values(port, values)
            # `[]` is a legitimate outcome, not a misconfiguration: `auto`
            # on a host this port's image is not native to selects
            # nothing here, and the port is simply skipped. Only a
            # *populated* axis on a port that has none is the error this
            # guard was written for.
            if key is None and values not in ([""], []):
                raise UnknownAxisError(
                    f"usermod/{port} has no configurable axis yet -- "
                    f"remove [usermod.{port}] from the config"
                )
            for value in values:
                targets.append(UsermodTarget(port=port, arch=value, tag=tag))
    return targets


def all_usermod_targets(tags: list[str]) -> list[UsermodTarget]:
    """Every identifier this project can name, across every known port and
    every configured tag -- what `--only` resolves against (**0045**).

    Independent of ports/axis-overrides/build/skip, same as before 0051:
    "force exactly this one build" should not be answerable with "your
    config does not select that". `tags` stays, though -- the same reason
    natmod's own `all_targets()` keeps `tag_groups()`: which releases
    exist is a config statement, not a filter over a fixed set, since an
    identifier's leading slot genuinely depends on `micropython`.
    """
    return [
        UsermodTarget(port=port, arch=value, tag=tag)
        for tag in tags
        for port in KNOWN_PORTS
        for value in all_axis_values(port)
    ]


# select() moved to cibuildmp.selector in 0051: it was duplicated here
# rather than shared, typed list[Target] there vs list[UsermodTarget]
# here, and that duplication is exactly the shape record 0048's drift
# (build/skip read from opposite config tables) came from. The shared
# version is generic (a Protocol, not a concrete Target type), so both
# modes now import the one copy.

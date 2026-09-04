#!/usr/bin/env -S uv run --script

"""Print the real, per-`(tag, scope)` compiler pin as TOML rows -- the fact
`build-platforms.toml`'s own per-row `gcc` field already is for `embedded_base`'s
two toolchain families, the same way `idf_version` already is a per-row fact for
`esp32`. `gcc` predates this script's own first landing; the docstring here used
to describe it as a future column nothing read yet ("no resolver shipped in the
package at all") -- untrue since [0087]/[0089]: `toolchain_fetch.resolve_toolchain()`,
reached through `usermod/targets.py`'s `rp2_toolchain()`/`qemu_toolchain()` and
`natmod/targets.py`'s `natmod_toolchain()`, reads exactly this field at build time.
What is still true, and still this script's own reason to exist: nothing in
`src/cibuildmp` *computes* a floor/ceiling window from `toolchains.toml`'s own raw
facts -- that happens here, once, by hand-reviewed generation, never live.

Third stage of the pipeline `docs/reference/toolchain-facts/toolchains.toml`'s own header
already describes: `[tags]` names a MicroPython release ->
`refresh_natmod_archs.py`/`refresh_usermod_boards.py` walk it into
`build-platforms.toml`'s real `(tag, scope, arch/board)` rows ->
`refresh_toolchains.py` walks the same tags into `toolchains.toml`'s own
compiler facts -> **this script** resolves those facts down to one pin per
row that already exists in `build-platforms.toml`. It reads both files; it
writes neither -- `redirect and review by hand`, the same convention every
script in this pipeline already holds itself to (`toolchains.toml`'s own
header states it explicitly, for the same reason).

    bin/refresh_toolchain_pins.py                    # every row, every scope
    bin/refresh_toolchain_pins.py --scope usermod.rp2
    bin/refresh_toolchain_pins.py --check             # see below

## Why this is a separate stage, not a runtime function

Nothing in `src/cibuildmp` should compute a floor/ceiling intersection at
build time -- that logic (this script's own `resolve_row`) belongs at
*generation* time only, same as `idf_version` was never computed live from
`tools/ci.sh` inside `usermod/build_esp32.py`; it was read once, by a
script, into a static TOML fact `Esp32BuildOptions.idf_version` just reads.
`gcc` is exactly that: a plain string `rp2_toolchain()`/`qemu_toolchain()`/
`natmod_toolchain()` read straight off the row, no resolver shipped in the
package at all -- this script is where a human decides what value goes into
that field, never where a build recomputes one.

## What "resolve" means, per `(tag, scope)`

- **floor** = the highest `guard-error`/`guard-branch` threshold for that
  tag, in `{scope, "any", "mpy-cross"}` -- the port's own build refuses (or
  miscompiles) below this.
- **ceiling** = the lowest `breaks-with` threshold for that tag, same scope
  set -- `toolchains.toml`'s own `breaks-with` rows are already emitted only
  for tags that do not yet contain the fix, so no separate ancestry check is
  needed here.
- **pin** = the newest `apt-resolved`/`ci-tarball`/`ci-idf` value for that
  exact `(tag, scope)` that upstream's own CI is confirmed to have actually
  used, snapped inside `[floor, ceiling)` -- never a bare arithmetic mean of
  the window, because a number nobody has verified builds is not a fact,
  it's a guess wearing this table's clothing. A window with no verified
  value inside it prints `pin = null` and a reason, rather than inventing
  one.

## `--check`: the drift `bin/update_toolchains.py`'s own shape does not catch

`bin/update_toolchains.py` (record [0046]) reports when a pin falls behind
its own upstream's latest release. It has nothing to say about whether that
pin is still *inside* every row's own window -- confirmed live, back when
`arm_embedded.Dockerfile`/`riscv_embedded.Dockerfile` still baked one shared
version each: both were pinned at xpack `15.2.1`/`15.2.0`,
`update_toolchains.py` reported them as current (they *are* the newest
xpack release), and both were still **above every `usermod.rp2`/
`usermod.samd`/`usermod.nrf`/pre-`v1.27.0` `usermod.stm32` tag's own
`<15.1` ceiling** -- a real, live, silent breakage `update_toolchains.py`'s
own "is there a newer release" question was never built to see.

`--check` here re-resolves every row from the *current* `toolchains.toml`
and compares against `build-platforms.toml`'s own already-committed `gcc`
field for that exact `(tag, scope)` row -- exit nonzero and name every row
outside its own window, so this class of drift fails a build instead of
shipping silently the way it did above. **This is [0090]'s own fix, not
[0086]'s original design**: `[0087]`/`[0089]` deleted the baked `ARG
TOOLCHAIN_URL=` line the first version of this flag read out of
`arm_embedded.Dockerfile`/`riscv_embedded.Dockerfile`, which meant `--check`
silently stopped comparing against anything at all the moment those two
records landed -- exit 0, "ok", regardless of what `build-platforms.toml`
actually held. `[0088]`'s own `mimxrt` `v1.20.0` row is the case that check
exists to catch: `gcc = "13.3.1-1.1"` (record [0088]'s own first, wrong
answer) sits inside `[floor, ceiling)` for every scope's ordinary `<15.1`
window and would pass a check that only asked that question -- it is
`mimxrt`'s own disjoint `<13` ceiling that rejects it, the one window this
tool's real value ([0088]'s corrected `12.3.1-1.2`) had to be re-derived
from `toolchains.toml`'s own facts to satisfy, not assumed from the ordinary
ladder every other row here follows.

Needs `docs/reference/toolchain-facts/toolchains.toml` already generated (`bin/refresh_toolchains.py`)
and current -- this script trusts it, it does not regenerate it.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RESOURCES = REPO / "src" / "cibuildmp" / "resources"
# The compiler-fact table is evidence, not a packaged resource: nothing in
# `src/cibuildmp` loads it at runtime, and its own header has always said so.
# It lives under `docs/reference/` for that reason.
FACTS = REPO / "docs" / "reference" / "toolchain-facts"

# The usermod/natmod image groups this script knows how to validate a
# per-row `gcc` fact for. Just the one: [0087] only gave `embedded_base`'s
# two toolchain families a real, varying per-row `gcc` field -- every other
# image group either bakes one fixed version with nothing per-row to check
# (`xtensa_lx106`/`xtensa_esp`), is native (`natmod_host`), or carries a
# different per-row fact this script does not resolve a window for at all
# (`esp32`'s own `idf_version`, `unix`'s own pypa image floor -- neither is
# a compiler-threshold window `toolchains.toml` has facts for).
CHECKABLE_IMAGES = frozenset({"embedded_base"})

# Which of the two toolchain families `toolchain_fetch.TOOLCHAIN_CROSS_PREFIX`
# names each natmod arch needs -- duplicated from `natmod/targets.py`'s own
# `_NATMOD_ARCH_TOOLCHAIN_FAMILY` rather than imported (this script stays
# decoupled from `src/cibuildmp` by design, see this file's own header) --
# keep both in sync by hand if a new arch is ever added to either family.
# **Not** `images[arch]` any more: record 0096 merged `arm_embedded`/
# `riscv_embedded` into one Docker image (`embedded_base`), so grouping by
# image name can no longer tell the two toolchain families' own separate
# `gcc` facts apart the way it could through record 0090's own first draft.
NATMOD_ARCH_FAMILY = {
    "armv6m": "arm_embedded",
    "armv7m": "arm_embedded",
    "armv7emsp": "arm_embedded",
    "armv7emdp": "arm_embedded",
    "rv32imc": "riscv_embedded",
    "rv64imc": "riscv_embedded",
}


def _load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def parse_ver(value: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", value.lstrip(">="))[:3])


def vstr(v: tuple[int, ...] | None) -> str:
    return ".".join(map(str, v)) if v else "-"


def _is_gcc_family(tool_name: str) -> bool:
    """`breaks-with`/`guard-*` rows are recorded under the bare compiler
    family (`tool = "gcc"`) -- the warning class they describe fires
    regardless of which cross-prefix wraps the same gcc. The *verified*
    apt/tarball facts, by contrast, are recorded under the real package
    name CI actually installs (`gcc-arm-none-eabi`, `gcc-x86-64-linux-gnu`,
    ...). A floor/ceiling fact and a verified-value fact for the same real
    compiler therefore never share one `tool` string -- match on "is this
    some gcc" instead of exact equality wherever a fact is a *threshold*
    (a version number MicroPython's own code reacts to, true of any gcc),
    and keep exact-name matching only for picking *which* verified package
    to report as the pin."""
    return tool_name == "gcc" or bool(re.search(r"\bgcc\b|-gcc(?:-|$)", tool_name))


def resolve_row(
    rows: list[dict], tag: str, scope: str, tool: str
) -> tuple[tuple[int, ...] | None, tuple[int, ...] | None, dict | None]:
    """`(floor, ceiling, pin_row)` for this exact `(tag, scope)` -- `pin_row`
    is the real fact row the pin came from (`None` if the window has no
    verified value inside it), never a synthesised one."""
    same_scope = [
        r for r in rows if r["tag"] == tag and r["scope"] in (scope, "any", "mpy-cross")
    ]
    thresholds = [r for r in same_scope if _is_gcc_family(r["tool"])]
    floor = max(
        (
            parse_ver(r["value"])
            for r in thresholds
            if r["kind"] in ("guard-error", "guard-branch")
        ),
        default=None,
    )
    ceiling = min(
        (parse_ver(r["value"]) for r in thresholds if r["kind"] == "breaks-with"),
        default=None,
    )
    verified = [
        r
        for r in same_scope
        if r["tool"] == tool
        and r["kind"] in ("apt-resolved", "ci-tarball", "ci-idf")
        and r.get("pinned", True)
    ]
    candidates = [
        r
        for r in verified
        if (floor is None or parse_ver(r["value"]) >= floor)
        and (ceiling is None or parse_ver(r["value"]) < ceiling)
    ]
    pin_row = (
        max(candidates, key=lambda r: parse_ver(r["value"])) if candidates else None
    )
    return floor, ceiling, pin_row


def real_rows(build_platforms: dict, scope: str) -> list[tuple[str, str]]:
    """Every real `(tag, scope)` pair `build-platforms.toml` actually
    carries a row for -- never a synthesised tag range, so a port that
    starts later than `[tags]`'s own floor (`nrf` at `v1.18`, `qemu` at
    `v1.24.0`) is never asked about a tag it never shipped a row for."""
    if scope.startswith("natmod."):
        # natmod is not an upstream port -- it has no `ports_<port>.yml` of
        # its own for `refresh_toolchains.py` to read, so `toolchains.toml`
        # carries no fact row whose `scope` is ever this exact string. What
        # still applies is every `any`/`mpy-cross` threshold (`resolve_row`
        # matches those regardless of `scope`), which is the real
        # compiler-family constraint natmod's own cross-compiled arches hit.
        # Passing this string through as `real_scope` -- rather than folding
        # natmod into the `unix` scope the way this used to -- is what keeps
        # a genuinely port-specific fact (`usermod.rp2`'s pico-sdk
        # workaround) from leaking into an arch natmod builds itself.
        #
        # `natmod.<family>` (`arm_embedded`/`riscv_embedded`, see
        # `NATMOD_ARCH_FAMILY`), not `natmod.<image>` -- both families
        # share one Docker image (`embedded_base`, record 0096) but keep
        # two distinct `gcc` facts, and grouping by image would merge them.
        family = scope.removeprefix("natmod.")
        section = build_platforms["natmod"]
        tags = sorted(
            {
                r["tag"]
                for r in section["identifiers"]
                if NATMOD_ARCH_FAMILY.get(r["arch"]) == family and "gcc" in r
            }
        )
        return [(t, scope) for t in tags]
    if scope == "unix":
        section = build_platforms["natmod"]
        tags = sorted({r["tag"] for r in section["identifiers"]})
        return [(t, "unix") for t in tags]
    port = scope.removeprefix("usermod.")
    section = build_platforms.get("usermod", {}).get(port)
    if section is None:
        return []
    tags = sorted({r["tag"] for r in section["identifiers"]})
    return [(t, scope) for t in tags]


def usermod_image_for(build_platforms: dict, port: str) -> str | None:
    """The Docker image group `port`'s own build actually runs in --
    several ports share one (`rp2`/`samd`/`nrf`/`stm32`/`mimxrt` all
    resolve to `embedded_base`, record 0058/0096)."""
    return build_platforms.get("usermod", {}).get(port, {}).get("image")


def natmod_image_for_family(build_platforms: dict, family: str) -> str | None:
    """The Docker image group `family`'s own natmod rows actually run in
    -- `embedded_base` for both `arm_embedded`/`riscv_embedded` since
    record 0096, read off a real row (any arch `NATMOD_ARCH_FAMILY` maps
    to `family`) rather than hardcoded, so a future re-split still
    resolves correctly here with no change to this function."""
    images = build_platforms["natmod"]["images"]
    for arch, fam in NATMOD_ARCH_FAMILY.items():
        if fam == family and arch in images:
            return images[arch]
    return None


def current_row_pin(
    build_platforms: dict, scope: str, tag: str
) -> tuple[int, ...] | None:
    """`build-platforms.toml`'s own already-committed `gcc` value for this
    exact `(scope, tag)` -- what `--check` compares against the window
    `resolve_row()` resolves, now that this is a real per-row fact
    ([0087]/[0089]) rather than one shared Dockerfile `ARG` ([0090]).
    Every row sharing a `(scope, tag)` carries the same value (checked
    directly, every ARM/RISC-V-family port and natmod arch, at every
    tag) -- the first matching row's own value is `the` value, not one of
    several to reconcile. `None` when this `(scope, tag)` has no `gcc`
    field at all: nothing to check, not a violation."""
    if scope.startswith("natmod."):
        family = scope.removeprefix("natmod.")
        for row in build_platforms["natmod"]["identifiers"]:
            if (
                row["tag"] == tag
                and NATMOD_ARCH_FAMILY.get(row["arch"]) == family
                and row.get("gcc")
            ):
                return parse_ver(row["gcc"])
        return None
    port = scope.removeprefix("usermod.")
    section = build_platforms.get("usermod", {}).get(port)
    if section is None:
        return None
    for row in section.get("identifiers", []):
        if row["tag"] == tag and row.get("gcc"):
            return parse_ver(row["gcc"])
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--scope", help="Limit to one scope, e.g. usermod.rp2")
    parser.add_argument("--tool", default="gcc")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit nonzero if any row's currently pinned compiler falls "
        "outside the window this script would resolve for it right now.",
    )
    args = parser.parse_args(argv)

    facts = _load_toml(FACTS / "toolchains.toml")["toolchains"]["requirements"]
    build_platforms = _load_toml(RESOURCES / "build-platforms.toml")

    # natmod contributes no `toolchains.toml` fact rows of its own (it is
    # not an upstream port `refresh_toolchains.py` can read a workflow for),
    # so its scopes never appear in `facts` -- added here from
    # `NATMOD_ARCH_FAMILY`'s own two families, narrowed to the ones this
    # script actually knows how to check (`CHECKABLE_IMAGES`).
    natmod_families = {
        family
        for family in NATMOD_ARCH_FAMILY.values()
        if natmod_image_for_family(build_platforms, family) in CHECKABLE_IMAGES
    }
    scopes = (
        [args.scope]
        if args.scope
        else sorted(
            {r["scope"] for r in facts if r["scope"] not in ("any", "mpy-cross")}
            | {f"natmod.{family}" for family in natmod_families}
        )
    )

    problems: list[str] = []
    for scope in scopes:
        pairs = real_rows(build_platforms, scope)
        if not pairs:
            continue
        for tag, real_scope in pairs:
            floor, ceiling, pin_row = resolve_row(facts, tag, real_scope, args.tool)
            pin = parse_ver(pin_row["value"]) if pin_row else None
            print(
                f'{{ tag = "{tag}", scope = "{scope}", tool = "{args.tool}", '
                f'floor = "{vstr(floor)}", ceiling = "{vstr(ceiling)}", '
                f'pin = "{vstr(pin)}", '
                f'source = "{pin_row["source"] if pin_row else "no verified value in window"}" }}'
            )
            if args.check:
                if scope.startswith("natmod."):
                    image = natmod_image_for_family(
                        build_platforms, scope.removeprefix("natmod.")
                    )
                else:
                    image = usermod_image_for(
                        build_platforms, scope.removeprefix("usermod.")
                    )
                if image not in CHECKABLE_IMAGES:
                    continue
                current = current_row_pin(build_platforms, scope, tag)
                if current is None:
                    continue
                if floor and current < floor:
                    problems.append(
                        f"{tag} {scope}: pinned {vstr(current)} < floor {vstr(floor)}"
                    )
                if ceiling and current >= ceiling:
                    problems.append(
                        f"{tag} {scope}: pinned {vstr(current)} >= ceiling {vstr(ceiling)}"
                    )

    if args.check:
        if problems:
            print("\n-- outside window --", file=sys.stderr)
            for line in problems:
                print(f"  {line}", file=sys.stderr)
            return 1
        print(
            "ok: every checked row's own gcc pin is inside its own window",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env -S uv run --script

"""Print the real, per-`(tag, scope)` compiler pin as TOML rows -- the fact
that would fill a new `toolchain` column in `build-platforms.toml`'s own
`identifiers`, the same way `idf_version` already is a per-row fact for
`esp32`.

Third stage of the pipeline `resources/toolchains.toml`'s own header
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
A `toolchain` field here is meant to be exactly that: a plain string a
future `dockerrun`/`build_<port>.py` reads off the row, no resolver shipped
in the package at all.

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

`bin/update_toolchains.py` (record [0046]) reports when a *shared* pin
(one `ARG` in one Dockerfile) falls behind its own upstream's latest
release. It has nothing to say about whether that pin is still *inside*
every row's own window -- confirmed live, this session, against
`docker/arm_embedded.Dockerfile`/`docker/riscv_embedded.Dockerfile`: both
are pinned at xpack `15.2.1`/`15.2.0`, `update_toolchains.py` reports them
as current (they *are* the newest xpack release), and both are still
**above every `usermod.rp2`/`usermod.samd`/`usermod.nrf`/pre-`v1.27.0`
`usermod.stm32` tag's own `<15.1` ceiling** -- a real, live, silent breakage
`update_toolchains.py`'s own "is there a newer release" question was never
built to see. `--check` here re-resolves every row from the *current*
`toolchains.toml` and compares against `build-platforms.toml`'s own
committed `toolchain` field (once one exists) or, absent that field, against
whatever a Dockerfile currently pins for that row's own image -- exit
nonzero and name every row outside its own window, so this class of drift
fails a build instead of shipping silently the way it did here.

Needs `resources/toolchains.toml` already generated (`bin/refresh_toolchains.py`)
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

# The currently-shared, image-level pins this script's own `--check` can
# compare a resolved window against until a real `toolchain` column exists
# in `build-platforms.toml` -- read here, not imported from
# `bin/update_toolchains.py`, because that script's own `PINS` tracks
# *upstream freshness* (does a newer release exist), a different question
# from *does this version sit inside this row's own window*.
DOCKERFILE_PIN = {
    "arm_embedded": (REPO / "docker" / "arm_embedded.Dockerfile", "gcc-arm-embedded"),
    "riscv_embedded": (
        REPO / "docker" / "riscv_embedded.Dockerfile",
        "gcc-riscv-embedded",
    ),
}
DOCKERFILE_VERSION_RE = re.compile(r"xpack-\S+?-gcc-xpack/releases/download/v([\d.]+)")


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
    if scope == "unix" or scope.startswith("natmod"):
        section = build_platforms["natmod"]
        tags = sorted({r["tag"] for r in section["identifiers"]})
        return [(t, "unix") for t in tags]
    port = scope.removeprefix("usermod.")
    section = build_platforms.get("usermod", {}).get(port)
    if section is None:
        return []
    tags = sorted({r["tag"] for r in section["identifiers"]})
    return [(t, scope) for t in tags]


def image_for(build_platforms: dict, port: str) -> str | None:
    """The `image` a usermod port's own build actually runs in -- several
    ports share one (`rp2`/`samd`/`nrf`/`stm32`/`mimxrt` all resolve to
    `arm_embedded`, record 0058), so the Dockerfile to check is never the
    port's own name."""
    return build_platforms.get("usermod", {}).get(port, {}).get("image")


def current_dockerfile_pin(image: str) -> tuple[int, ...] | None:
    entry = DOCKERFILE_PIN.get(image)
    if entry is None:
        return None
    path, _ = entry
    match = DOCKERFILE_VERSION_RE.search(path.read_text())
    return parse_ver(match.group(1)) if match else None


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

    facts = _load_toml(RESOURCES / "toolchains.toml")["toolchains"]["requirements"]
    build_platforms = _load_toml(RESOURCES / "build-platforms.toml")

    scopes = (
        [args.scope]
        if args.scope
        else sorted(
            {r["scope"] for r in facts if r["scope"] not in ("any", "mpy-cross")}
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
                port = scope.removeprefix("usermod.")
                image = image_for(build_platforms, port)
                shared = current_dockerfile_pin(image) if image else None
                if shared is None:
                    continue
                if floor and shared < floor:
                    problems.append(
                        f"{tag} {scope}: pinned {vstr(shared)} < floor {vstr(floor)}"
                    )
                if ceiling and shared >= ceiling:
                    problems.append(
                        f"{tag} {scope}: pinned {vstr(shared)} >= ceiling {vstr(ceiling)}"
                    )

    if args.check:
        if problems:
            print("\n-- outside window --", file=sys.stderr)
            for line in problems:
                print(f"  {line}", file=sys.stderr)
            return 1
        print(
            "ok: every checked row's shared pin is inside its own window",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

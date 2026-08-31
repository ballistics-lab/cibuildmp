#!/usr/bin/env python3
"""Regenerate the parts of the living docs that are pure functions of
`resources/build-platforms.toml` and `resources/pinned_docker_images.toml`
(record 0077's own second half).

`tests/test_docs.py` turns a *wrong* documented fact into a failing build.
This turns a whole class of them into a fact that cannot be written by hand
at all: an identifier shape, a port/arch -> image-group mapping. Both were
hand-maintained tables sitting next to a sentence promising they were
"current as of this file's own last edit", which is precisely the promise
that goes stale silently.

Each generated block lives between a matching pair of HTML comments:

    <!-- generated: <name> -- bin/refresh_docs.py, do not edit by hand -->
    ...
    <!-- /generated: <name> -->

Run `bin/refresh_docs.py` to rewrite them, `--check` to fail if any is out
of date (what `tests/test_docs.py` calls). Prose around a block stays
hand-written -- only the mechanical part is generated, because only the
mechanical part can be.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RESOURCES = REPO / "src" / "cibuildmp" / "resources"

BLOCK = (
    "<!-- generated: {name} -- bin/refresh_docs.py, do not edit by hand -->\n"
    "{body}\n"
    "<!-- /generated: {name} -->"
)


def _load(name: str) -> dict:
    with (RESOURCES / name).open("rb") as handle:
        return tomllib.load(handle)


def _newest_stable_tag(rows: list[dict]) -> str:
    """The newest non-preview tag among `rows`, by the `[tags]` date rather
    than by string order -- `v1.9.0` sorts after `v1.28.0` as a string, and
    the table goes back to v1.12."""
    dates = _load("build-platforms.toml")["tags"]
    stable = {row["tag"] for row in rows if "preview" not in row["tag"]}
    return max(stable, key=lambda tag: dates[tag]["date"])


def _example(port: str, table: dict) -> str:
    """One real identifier for `port`, at its own newest stable tag.

    Picked from the real rows rather than composed from the format string:
    a composed example can be well-formed and still name nothing, which is
    the exact failure `docs/reference/design.md` shipped
    (`v1.29.0-unix-manylinux_2_28_x86_64`).
    """
    rows = table["identifiers"]
    tag = _newest_stable_tag(rows)
    candidates = sorted(row["identifier"] for row in rows if row["tag"] == tag)
    return candidates[0]


def identifier_shapes() -> str:
    """README's own "Identifier shapes, one per platform" table."""
    data = _load("build-platforms.toml")
    natmod = data["natmod"]
    lines = [
        "| Platform | Shape | Example |",
        "| --- | --- | --- |",
        "| natmod | `{}` | `{}` |".format(
            natmod["identifier_format"].replace("{mpy}", "{abi}"),
            _example("natmod", natmod),
        ),
    ]
    # Driver-backed ports only: a port with rows but no `build_<port>()` has
    # an identifier nothing can build yet, and listing it here would read as
    # an offer.
    from cibuildmp.platforms.usermod.targets import KNOWN_PORTS

    for port in sorted(KNOWN_PORTS):
        table = data["usermod"][port]
        lines.append(
            f"| usermod `{port}` | `{table['identifier_format']}` "
            f"| `{_example(port, table)}` |"
        )
    return "\n".join(lines)


def image_group_mapping() -> str:
    """`vendored-images.md`'s own port/arch -> group tables."""
    data = _load("build-platforms.toml")
    groups = set(_load("pinned_docker_images.toml").get("image_group", {}))
    out: list[str] = []

    def table(title: str, mapping: dict[str, str], column: str) -> None:
        out.append(f"**{title}**\n")
        out.append(f"| {column} | Group |")
        out.append("| --- | --- |")
        for key, group in sorted(mapping.items()):
            mark = "" if group in groups else " ⚠️ *(no such image group)*"
            out.append(f"| `{key}` | `{group}`{mark} |")
        out.append("")

    table("natmod (`images.<arch>`)", data["natmod"]["images"], "Arch")

    scalar: dict[str, str] = {}
    for port, port_table in sorted(data["usermod"].items()):
        if "image" in port_table:
            scalar[port] = port_table["image"]
    table('usermod, one image for the whole port (`image = "..."`)', scalar, "Port")

    for port, port_table in sorted(data["usermod"].items()):
        if "images" in port_table:
            axis = "Board" if "{board}" in port_table["identifier_format"] else "Target"
            table(f"usermod `{port}` (`images.<target>`)", port_table["images"], axis)

    return "\n".join(out).rstrip()


def toolchain_map() -> str:
    """`design.md`'s own ARCH -> `CROSS` table, for the newest stable tag.

    Per tag, not global, which is what made the hand-written version wrong:
    v1.29.0 gave `x64`/`x86` real prefixes (`x86_64-linux-gnu-`,
    `i686-linux-gnu-`) where v1.28.0 had an empty `CROSS` and a `-m32`, so
    any single table is only ever true for the tag it was written against.
    """
    data = _load("build-platforms.toml")
    rows = data["natmod"]["identifiers"]
    tag = _newest_stable_tag(rows)
    by_prefix: dict[str, list[str]] = {}
    for row in rows:
        if row["tag"] != tag:
            continue
        # A genuinely absent `cross` is not the same fact as an empty one:
        # the tag ranges that predate a CROSS line for that branch have no
        # key at all (see the table's own header comment).
        prefix = row.get("cross")
        key = (
            "*(none)*"
            if prefix == ""
            else "*(absent)*"
            if prefix is None
            else f"`{prefix}`"
        )
        by_prefix.setdefault(key, []).append(row["arch"])
    lines = [
        f"For MicroPython **{tag}** — this is a per-tag fact, not a global one:",
        "",
        "| ARCH | `CROSS` |",
        "| --- | --- |",
    ]
    for prefix, arches in sorted(by_prefix.items(), key=lambda kv: kv[1]):
        lines.append(f"| {' '.join(f'`{a}`' for a in sorted(arches))} | {prefix} |")
    return "\n".join(lines)


GENERATED = {
    ("README.md", "identifier-shapes"): identifier_shapes,
    ("docs/reference/vendored-images.md", "image-group-mapping"): image_group_mapping,
    ("docs/reference/design.md", "toolchain-map"): toolchain_map,
}


def _replace(text: str, name: str, body: str) -> str:
    pattern = re.compile(
        rf"<!-- generated: {re.escape(name)} .*?-->\n.*?\n<!-- /generated: {re.escape(name)} -->",
        re.DOTALL,
    )
    if not pattern.search(text):
        raise SystemExit(f"no `{name}` generated block found -- add the marker pair")
    return pattern.sub(lambda _: BLOCK.format(name=name, body=body), text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if any generated block is out of date, without writing",
    )
    args = parser.parse_args(argv)

    stale: list[str] = []
    for (relative, name), build in GENERATED.items():
        path = REPO / relative
        before = path.read_text(encoding="utf-8")
        after = _replace(before, name, build())
        if before == after:
            continue
        if args.check:
            stale.append(f"{relative}: `{name}`")
        else:
            path.write_text(after, encoding="utf-8")
            print(f"refreshed {relative}: {name}")

    if stale:
        print(
            "out of date, run bin/refresh_docs.py:\n  " + "\n  ".join(stale),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

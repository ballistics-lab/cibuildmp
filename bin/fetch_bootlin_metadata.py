#!/usr/bin/env -S uv run --script

"""Print Bootlin's own toolchain release metadata as TOML.

    bin/fetch_bootlin_metadata.py                  # rewrites resources/bootlin.toml
    bin/fetch_bootlin_metadata.py --stdout         # print instead, review before writing
    bin/fetch_bootlin_metadata.py --arch x86-64 --flavour stable --stdout
    bin/fetch_bootlin_metadata.py --sizes          # adds size_bytes, one HEAD per tarball

Record 0084 makes every compiler this project uses a per-identifier
Bootlin tarball rather than something baked into a shared image. That
turns "which Bootlin release do I want" into a question asked per row,
and this is the table it is answered against: every published release for
every architecture this project needs, with the gcc/binutils/libc
versions inside it and the URL + sha256 to fetch it by.

**Read from Bootlin's own machine-readable manifests, not from its
website's prose or its release-table HTML.** Two sources per release,
both published by Bootlin next to the tarball itself:

- `summaries/<name>.csv` -- Buildroot's own generated package manifest for
  that exact build (`PACKAGE,VERSION,...` rows for `gcc-final`, `binutils`,
  `gdb`, `linux-headers` and the libc). This is the build system's own
  output, the same class of source `bin/refresh_toolchains.py` insists on
  for MicroPython's side: what the build actually produced, never what a
  page says about it.
- `tarballs/<name>.sha256` -- the vendor's own checksum. It is also the
  only reliable statement of the **file extension**: releases through
  `2024.02` are `.tar.bz2` and everything from `2024.05` on is `.tar.xz`,
  so a URL built from a template guesses wrong for half the table. The
  sha256 file names the real artifact; this script reads that name rather
  than assuming one.

**Both flavours are captured, `stable` and `bleeding-edge`, and that is
deliberate.** "Use stable only" is a *policy* -- and an argued one, since
`bleeding-edge`'s sole exclusive offering at the top of the ladder is
gcc 15.1.0, which is precisely the version every `breaks-with` row in
`resources/toolchains.toml` names as breaking MicroPython before v1.26.0.
A policy is not evidence, and a table that silently omitted what was
rejected could not be used to re-check the argument later. `uclibc` is
excluded by default because nothing here targets it -- pass `--libc
uclibc` if that ever changes.

Nothing loads this file yet. That is the same order every other pinned
table here arrived in (`toolchains.toml`, `pinned_docker_images.toml`):
the facts land first and get reviewed, then a consumer is written against
them.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "https://toolchains.bootlin.com/downloads/releases/toolchains"

# Written in place, unlike `bin/refresh_toolchains.py`'s own
# print-and-redirect shape. That script prints because its output needs
# reading before it is trusted -- it parses MicroPython's own build
# machinery, where a mis-parse looks exactly like a fact. Nothing here is
# inferred: every field is copied out of a manifest the vendor publishes,
# so there is no judgement call for a human to review in the middle, and
# `bin/refresh_docs.py`'s own rewrite-in-place shape is the right one.
# `--stdout` is still there for the case where a diff is wanted first.
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parent.parent / "src/cibuildmp/resources/bootlin.toml"
)

# Every architecture this project has a real target for, and why. Bootlin
# publishes Linux toolchains only, so the bare-metal groups
# (`arm_embedded`, `riscv_embedded`, `xtensa_esp`, `xtensa_lx106`) are
# absent by construction -- they stay on xpack/Espressif tarballs, which
# record 0084's "Bootlin uniformly" does not reach and was never claimed to.
DEFAULT_ARCHES = (
    "x86-64",  # usermod.unix x86_64; natmod x64
    "x86-i686",  # usermod.unix i686; natmod x86
    "aarch64",  # usermod.unix aarch64
    "powerpc64le-power8",  # usermod.unix ppc64le; usermod.qemu POWERNV9
    "s390x-z13",  # usermod.unix s390x
    "mips32el",  # the mipsel image record 0068 already pins a Bootlin tarball for
)
DEFAULT_LIBCS = ("glibc", "musl")
DEFAULT_FLAVOURS = ("stable", "bleeding-edge")

# CSV `PACKAGE` name -> the field name emitted here. `gcc-final` is the
# cross compiler that ends up in the SDK; a `gcc-initial` row (the
# bootstrap pass) sits beside it in every summary and is not what a build
# ever runs.
PACKAGES = {
    "gcc-final": "gcc",
    "binutils": "binutils",
    "gdb": "gdb",
    "linux-headers": "linux_headers",
}

FLAVOURS = ("bleeding-edge", "stable")


class BootlinError(Exception):
    pass


def fetch(url: str, *, optional: bool = False) -> str | None:
    try:
        with urllib.request.urlopen(url) as response:
            return response.read().decode()
    except urllib.error.HTTPError as exc:
        if optional and exc.code == 404:
            return None
        raise BootlinError(f"fetching {url} failed: {exc}") from exc
    except urllib.error.URLError as exc:
        raise BootlinError(f"fetching {url} failed: {exc}") from exc


def content_length(url: str, *, attempts: int = 3) -> int | None:
    """The tarball's size, by HEAD, retried before it is given up on.

    Retried rather than caught-and-ignored because the first version of
    this did the latter, and a run that had already made several hundred
    requests came back with `size_bytes` missing from *every one* of 321
    rows -- silently, since a swallowed exception and a server that does
    not report a length are indistinguishable at the call site. The same
    HEADs succeeded immediately when re-run by hand, so it is throttling,
    not an unsupported method. A failure that survives the retries is
    reported to stderr and leaves the field out, never a zero.
    """
    request = urllib.request.Request(url, method="HEAD")
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request) as response:
                value = response.headers.get("Content-Length")
            return int(value) if value else None
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            if attempt == attempts - 1:
                print(f"!! HEAD {url.rsplit('/', 1)[-1]}: {exc}", file=sys.stderr)
                return None
            time.sleep(1 + attempt)
    return None


def list_tarballs(arch: str) -> list[str]:
    """Every tarball basename published for `arch`, from the directory index."""
    listing = fetch(f"{BASE}/{arch}/tarballs/")
    assert listing is not None
    names = re.findall(r'href="([^"]+\.tar\.(?:xz|bz2|gz))"', listing)
    # A directory index can list the same href twice (name column and a
    # sorted-by-date column); order is restored by the caller's own sort.
    return sorted(set(names))


def split_name(basename: str) -> tuple[str, str, str, str, str]:
    """`x86-64--glibc--stable-2025.08-1.tar.xz` -> its five parts.

    Split on `--`, not on `-`: every architecture name here contains
    single hyphens (`powerpc64le-power8`, `x86-i686`) and so does every
    release (`2025.08-1`, `2017.05-toolchains-1-1`), while `--` separates
    only the three real fields.
    """
    stem, _, ext = basename.partition(".tar.")
    parts = stem.split("--")
    if len(parts) != 3:
        raise BootlinError(f"cannot parse toolchain name: {basename}")
    arch, libc, tail = parts
    for flavour in FLAVOURS:
        if tail.startswith(f"{flavour}-"):
            return arch, libc, flavour, tail[len(flavour) + 1 :], ext
    raise BootlinError(f"unknown flavour in {basename}")


def release_key(release: str) -> tuple[int, int, str]:
    match = re.match(r"^(\d{4})\.(\d{2})-(.*)$", release)
    if not match:
        return (0, 0, release)
    return (int(match.group(1)), int(match.group(2)), match.group(3))


def read_sha256(arch: str, basename: str) -> str:
    """The vendor's own checksum, checked to be *for this file*.

    A `.sha256` naming a different artifact would mean the listing and the
    checksum have drifted apart, which is exactly the case a build must
    not silently accept -- so it is an error here rather than a warning.
    """
    stem = basename.partition(".tar.")[0]
    text = fetch(f"{BASE}/{arch}/tarballs/{stem}.sha256")
    assert text is not None
    for line in text.splitlines():
        digest, _, named = line.partition("  ")
        if named.strip() == basename:
            return digest.strip()
    raise BootlinError(f"{stem}.sha256 does not name {basename}")


def read_summary(arch: str, basename: str) -> dict[str, str]:
    """Package versions out of Buildroot's own manifest for this build."""
    stem = basename.partition(".tar.")[0]
    text = fetch(f"{BASE}/{arch}/summaries/{stem}.csv", optional=True)
    if text is None:
        print(f"!! {stem}: no summary published", file=sys.stderr)
        return {}
    if not text.strip():
        # Published, fetched, HTTP 200 -- and zero bytes long. Every
        # `2021.05-1` summary is like this, so checking only for a 404
        # reports the table as complete while twelve of its rows carry no
        # versions at all. Caught by counting rows with no `gcc` field,
        # which is why that check is worth running rather than trusting
        # the fetch's own status code.
        print(f"!! {stem}: summary is empty, no versions recorded", file=sys.stderr)
        return {}
    found: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(text)):
        package = (row.get("PACKAGE") or "").strip()
        version = (row.get("VERSION") or "").strip()
        if not version:
            continue
        field = PACKAGES.get(package)
        # First occurrence wins: newer summaries carry `gcc-final` twice
        # (the SDK's compiler and the host build of it), same version.
        if field and field not in found:
            found[field] = version
        elif package in ("glibc", "musl", "uclibc") and "libc_version" not in found:
            found["libc_version"] = version
    if not found:
        print(f"!! {stem}: summary names no known package", file=sys.stderr)
    return found


def collect(arch: str, basename: str, *, want_size: bool) -> dict[str, object]:
    _, libc, flavour, release, ext = split_name(basename)
    url = f"{BASE}/{arch}/tarballs/{basename}"
    row: dict[str, object] = {
        # Bootlin's own name for the release, and the row's identity --
        # not a convenience join of the four fields after it. It is what
        # `BOOTLIN_RELEASE=` already is in `docker/ppc64le_linux.Dockerfile`
        # and `docker/manylinux_2_41_mipsel.Dockerfile`, it is the
        # tarball's own single top-level directory (so it is the path
        # `relocate-sdk.sh` runs at), and it is the obvious cache key
        # under `cache_root()`. Derived here once, from the real filename,
        # rather than re-joined by every consumer with the `--`/`-`
        # separators to get wrong.
        "name": basename.partition(".tar.")[0],
        "arch": arch,
        "libc": libc,
        "flavour": flavour,
        "release": release,
    }
    summary = read_summary(arch, basename)
    raw_libc = summary.pop("libc_version", None)
    for field in ("gcc", "binutils", "gdb", "linux_headers"):
        if field in summary:
            row[field] = summary[field]
    if raw_libc:
        # glibc reports a git description (`2.41-70-g1502c24...`); the
        # part before the first `-` is the release, and the release is
        # what a libc *floor* claim is made of ([0044]'s own
        # `verify_unix_floor()` compares against exactly that). The full
        # string is kept beside it when it says more, never instead of it.
        floor = raw_libc.split("-")[0]
        row["libc_version"] = floor
        if floor != raw_libc:
            row["libc_version_detail"] = raw_libc
    row["format"] = f"tar.{ext}"
    row["url"] = url
    row["sha256"] = read_sha256(arch, basename)
    if want_size:
        size = content_length(url)
        if size is not None:
            row["size_bytes"] = size
    return row


def inline(row: dict[str, object]) -> str:
    parts = []
    for key, value in row.items():
        rendered = str(value) if isinstance(value, int) else f'"{value}"'
        parts.append(f"{key} = {rendered}")
    return "{ " + ", ".join(parts) + " }"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--arch",
        action="append",
        metavar="NAME",
        help="repeatable; default: every arch this project targets",
    )
    parser.add_argument(
        "--libc",
        action="append",
        metavar="NAME",
        help="repeatable; default: glibc, musl",
    )
    parser.add_argument(
        "--flavour",
        action="append",
        metavar="NAME",
        help="repeatable; default: stable, bleeding-edge",
    )
    parser.add_argument(
        "--sizes",
        action="store_true",
        help="include size_bytes (one HEAD request per tarball)",
    )
    parser.add_argument("--jobs", type=int, default=8, metavar="N")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        metavar="PATH",
        help=f"default: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--stdout", action="store_true", help="print instead of writing --output"
    )
    args = parser.parse_args()

    arches = tuple(args.arch or DEFAULT_ARCHES)
    libcs = set(args.libc or DEFAULT_LIBCS)
    flavours = set(args.flavour or DEFAULT_FLAVOURS)

    wanted: list[tuple[str, str]] = []
    for arch in arches:
        names = list_tarballs(arch)
        print(f"{arch}: {len(names)} tarball(s) published", file=sys.stderr)
        for basename in names:
            _, libc, flavour, _, _ = split_name(basename)
            if libc in libcs and flavour in flavours:
                wanted.append((arch, basename))

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        rows = list(pool.map(lambda pair: collect(*pair, want_size=args.sizes), wanted))

    rows.sort(
        key=lambda r: (
            arches.index(str(r["arch"])),
            str(r["libc"]),
            str(r["flavour"]),
            release_key(str(r["release"])),
        )
    )

    lines = [
        "# Bootlin's own toolchain release metadata -- every published release",
        "# for every architecture this project targets, with the versions inside",
        "# it and the URL + sha256 to fetch it by (record 0084).",
        "#",
        "# Generated, never hand-written:",
        "#",
        "#     bin/fetch_bootlin_metadata.py",
        "#",
        "# Read from Bootlin's own machine-readable manifests -- Buildroot's",
        "# generated `summaries/<name>.csv` for the versions, the vendor's own",
        "# `tarballs/<name>.sha256` for the checksum and the real file extension",
        "# (.tar.bz2 through 2024.02, .tar.xz from 2024.05) -- never its website's",
        "# release-table prose. See the script's own docstring for why both",
        "# `stable` and `bleeding-edge` are here when only `stable` is wanted.",
        "#",
        "# A row with no `gcc`/`binutils` field is not an omission here: Bootlin",
        "# publishes an empty summary for every `2021.05-1` release, so those",
        "# releases have a tarball and a checksum but no recorded versions.",
        "",
        "[bootlin]",
        f'source = "{BASE}"',
        "releases = [",
        *("    " + inline(row) + "," for row in rows),
        "]",
    ]
    text = "\n".join(lines) + "\n"

    if args.stdout:
        sys.stdout.write(text)
        return 0
    args.output.write_text(text)
    without_versions = sum(1 for row in rows if "gcc" not in row)
    print(
        f"wrote {args.output} -- {len(rows)} release(s)"
        + (
            f", {without_versions} with no versions published"
            if without_versions
            else ""
        ),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Drift guards for the *living* docs (record 0077).

`README.md`, `docs/ACTIONS.md` and `docs/reference/*.md` describe what is
true today. Nothing about closing a record, bumping a pinned tag or
renaming an option makes any of them update, so every one of them has
drifted from real project state at least once -- `CLAUDE.md` keeps the
list, and it is a list of things a reader downstream then repeated.

These tests turn the checkable half of that into a failing build: an
identifier that no longer exists, an option key that was renamed, a
`CIBMP_*` variable nothing reads, a file path that was deleted, a record
link pointing nowhere. What they cannot check is prose making a *claim*
about behaviour -- that still needs a person -- but the four real drift
incidents this suite was written after were all of the mechanical kind.

**`docs/records/` is deliberately out of scope.** Records are append-only
history: a record describing the state at the time it was written is
correct *as history* even when that state is long gone, and "fixing" one
to satisfy a test would destroy the thing it exists to preserve.
`docs/0000-TRACKER.md` is in scope for link resolution only, for the same
reason -- its rows describe past states on purpose.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

import pytest

from cibuildmp.platforms import FAMILIES
from cibuildmp.platforms.natmod.options import OVERRIDE_UNION_KEYS

REPO = Path(__file__).resolve().parent.parent

# The living docs: kept current with what is true today, by hand.
LIVING_DOCS = [
    REPO / "README.md",
    REPO / "docs" / "ACTIONS.md",
    *sorted((REPO / "docs" / "reference").glob("*.md")),
]

# Every markdown file whose links should resolve, living or not -- a
# broken link is broken regardless of whether the prose around it is
# history.
ALL_DOCS = [
    *LIVING_DOCS,
    REPO / "docs" / "0000-TRACKER.md",
    REPO / "CHANGELOG.md",
    REPO / "CONTRIBUTING.md",
    REPO / "CLAUDE.md",
]

# A token carrying any of these is a shape, not a value: `{tag}-{arch}`,
# `CIBMP_<KEY>`, `mpy6.3-*`. Globs are checked against the real set
# separately; the rest are skipped outright.
PLACEHOLDER = re.compile(r"[<>{}…]")
GLOB = re.compile(r"[*?\[]")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _code_spans(text: str) -> list[str]:
    """Every inline `code span` and fenced block body.

    Only code is checked, deliberately: prose says "the v1.29.0 tree" and
    means the tree, while `v1.29.0-wasm32` in backticks is being offered
    to the reader as something to type.
    """
    fenced = re.findall(r"```[a-zA-Z]*\n(.*?)```", text, re.DOTALL)
    inline = re.findall(r"`([^`\n]+)`", text)
    return [*inline, *fenced]


def _identifiers() -> set[str]:
    data = tomllib.loads(
        _text(REPO / "src" / "cibuildmp" / "resources" / "build-platforms.toml")
    )
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            value = node.get("identifier")
            if isinstance(value, str):
                found.add(value)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(data)
    return found


def _image_groups() -> set[str]:
    data = tomllib.loads(
        _text(REPO / "src" / "cibuildmp" / "resources" / "pinned_docker_images.toml")
    )
    return set(data.get("image_group", {}))


IDENTIFIERS = _identifiers()

# `mpy6.3-v1.29.0-x64`, `v1.29.0-manylinux_2_28_x86_64`,
# `v1.29.0-qemu-MPS2_AN385`, and the `+0x3` arch-flags suffix
# (natmod/targets.py). Anchored on the leading tag every identifier has
# carried since record 0051, which is what keeps ordinary prose versions
# ("MicroPython v1.29.0") from matching: they have no `-<something>`.
IDENTIFIER_SHAPED = re.compile(
    r"(?:mpy[\d.]+-)?v\d+\.\d+(?:\.\d+)?(?:-preview)?(?:-[A-Za-z0-9_.+*?]+)+"
)

ENV_VAR = re.compile(r"CIBMP_[A-Z0-9_]+")

# A path is only worth checking when it looks like one this repo owns.
REPO_PATH = re.compile(
    r"(?:src|tests|docs|bin|examples|resources|\.github)/[A-Za-z0-9_./-]+"
)

# Paths that look like this repo's and belong to someone else. Every entry
# is a real one a person confirmed, not a guess -- the docs legitimately
# name MicroPython's own tree and a hypothetical consumer's layout, and
# both collide with directory names this repo also has.
FOREIGN_PATHS = {
    "docs/develop/cmodules.rst",  # MicroPython's own docs
    "examples/natmod/btree",  # MicroPython's examples/, not cibuildmp's
    "src/mymod.py",  # a consumer's module, in an illustrative config
    "bin/sh",  # from a `#!/bin/sh` shebang
    "docs/tasks/",  # an open question's proposed, not-yet-created directory
}

# `resources/x.toml` in the docs means the packaged resource, whose real
# path is `src/cibuildmp/resources/x.toml`. Both roots are tried.
PATH_ROOTS = (REPO, REPO / "src" / "cibuildmp")


def _source_text() -> str:
    """Every Python source, resource and workflow, concatenated -- what an
    environment variable or a documented default has to appear in
    somewhere to be real."""
    parts = []
    for pattern in ("src/**/*.py", "src/**/*.toml", "action.yml", ".github/**/*.yml"):
        for path in sorted(REPO.glob(pattern)):
            parts.append(_text(path))
    return "\n".join(parts)


SOURCE = _source_text()


def _latest_released_version() -> str:
    """The newest `## [X.Y.Z]` heading in `CHANGELOG.md`, skipping
    `[Unreleased]` -- file order, since the changelog is newest-first."""
    match = re.search(
        r"^## \[(\d+\.\d+\.\d+[^\]]*)\]", _text(REPO / "CHANGELOG.md"), re.MULTILINE
    )
    assert match, "CHANGELOG.md has no released version heading"
    return match.group(1)


def _constructed_env_names() -> set[str]:
    """Env names built at runtime, so never present in source literally.

    Three shapes, each from a real construction site: an option key's own
    form (`"CIBMP_" + key.upper()`, both families' `opt()`), the
    per-platform `build`/`skip` tier (`OptionCascade.get()` and
    `usermod/options.py`'s `_port_build_skip()`), and the per-container
    Docker/timeout keys (`dockerrun._env_name()`).
    """
    names = {
        "CIBMP_" + key.replace("-", "_").upper()
        for family in FAMILIES
        for key in family.OPTION_KEYS
    }
    ports = _ports()
    names |= {
        f"CIBMP_{key}_{port.replace('-', '_').upper()}"
        for key in ("BUILD", "SKIP", "ARCH_FLAGS")
        for port in ports
    }
    # `CIBMP_<PORT>_<TARGET>_<SUFFIX>`, and the target-less form for a
    # port with no per-build image axis (`CIBMP_WEBASSEMBLY_DOCKER_IMAGE`).
    keys = {port.replace("-", "_").upper() for port in ports}
    keys |= {
        f"{port.replace('-', '_').upper()}_{target.replace('-', '_').upper()}"
        for port, target in _port_targets()
    }
    names |= {
        f"CIBMP_{key}_{suffix}"
        for key in keys
        for suffix in ("TIMEOUT", "DOCKER_IMAGE", "DOCKER_PLATFORM")
    }
    return names


def _ports() -> set[str]:
    """Every real platform name an env var can be scoped to: `natmod`,
    plus every `[usermod.<port>]` section in the fact table."""
    data = tomllib.loads(
        _text(REPO / "src" / "cibuildmp" / "resources" / "build-platforms.toml")
    )
    return {"natmod", *data.get("usermod", {})}


def _port_targets() -> set[tuple[str, str]]:
    """Every (port, target) pair `dockerrun._key_parts()` can be called
    with -- the arch/board/platform-tag segment of each identifier, paired
    with the port whose table it came from."""
    data = tomllib.loads(
        _text(REPO / "src" / "cibuildmp" / "resources" / "build-platforms.toml")
    )
    pairs: set[tuple[str, str]] = set()
    sections = {"natmod": data.get("natmod", {})}
    sections.update(data.get("usermod", {}))
    for port, table in sections.items():
        for row in table.get("identifiers", []):
            for field in ("arch", "board"):
                if field in row:
                    pairs.add((port, str(row[field])))
    return pairs


@pytest.mark.parametrize("doc", LIVING_DOCS, ids=lambda p: p.name)
def test_identifiers_in_living_docs_are_real(doc: Path) -> None:
    """An identifier offered in a code span must exist, or -- if it is a
    glob -- match something that does.

    This is the check that catches a pinned-tag bump leaving one example
    behind, and the one that caught `design.md` claiming usermod
    identifiers carry a port segment (`v1.29.0-unix-manylinux_2_28_x86_64`)
    when `unix`/`windows`/`webassembly` all use a bare `{tag}-{arch}`.
    """
    unknown = []
    for span in _code_spans(_text(doc)):
        # The whole span, not the token: `v1.29.0-qemu-{board}` truncates
        # to a `v1.29.0-qemu` that is not an identifier and was never
        # offered as one.
        if PLACEHOLDER.search(span):
            continue
        for token in IDENTIFIER_SHAPED.findall(span):
            token = token.rstrip(".,;:")
            # natmod appends `+0x<flags>` at runtime when arch-flags is
            # set (targets.py) -- a real identifier, but not a table row.
            token = re.sub(r"\+0x[0-9a-f]+$", "", token)
            # Collected artifacts are named `{name}-{version}-{identifier}`
            # plus an extension, so a filename in the docs carries a real
            # identifier with a suffix glued on -- strip it rather than
            # report `...-x64.mpy` as an identifier that does not exist.
            token = re.sub(r"\.(mpy|exe|elf|uf2|bin|mjs|wasm|json)$", "", token)
            if GLOB.search(token):
                if not any(
                    re.fullmatch(re.escape(token).replace(r"\*", ".*"), real)
                    for real in IDENTIFIERS
                ):
                    unknown.append(f"{token} (glob matches no real identifier)")
                continue
            if token not in IDENTIFIERS:
                unknown.append(token)
    assert not unknown, (
        f"{doc.relative_to(REPO)} names identifiers that "
        f"resources/build-platforms.toml does not have: {sorted(set(unknown))}"
    )


def test_readme_documents_exactly_the_real_option_keys() -> None:
    """README's own option table must list every real key and no others.

    Bidirectional on purpose: a key that was renamed leaves a row behind,
    and a key that was *added* never grows one at all -- the second is the
    quieter failure, since nothing about it looks wrong on the page.
    """
    real = set().union(*(family.OPTION_KEYS for family in FAMILIES))
    readme = _text(REPO / "README.md")
    table = readme.split("### Every key", 1)[1].split("###", 1)[0]
    documented = {
        row.split("|")[1].strip().strip("`")
        for row in table.splitlines()
        if row.startswith("| `")
    }
    assert documented == real, (
        f"README's option table is out of step with FAMILIES' own OPTION_KEYS. "
        f"Documented but not real: {sorted(documented - real)}. "
        f"Real but undocumented: {sorted(real - documented)}."
    )


def test_readme_override_column_matches_the_real_override_schema() -> None:
    """The table's own "Also in `[override]`?" column, against the real
    per-target schema rather than against what the row's prose asserts."""
    real = OVERRIDE_UNION_KEYS - {"select", "inherit"}
    readme = _text(REPO / "README.md")
    table = readme.split("### Every key", 1)[1].split("###", 1)[0]
    marked = set()
    for row in table.splitlines():
        if not row.startswith("| `"):
            continue
        cells = [c.strip() for c in row.split("|")]
        if cells[4].startswith("✓"):
            marked.add(cells[1].strip("`"))
    assert marked == real, (
        f"README marks {sorted(marked)} as valid in [override]; the real "
        f"schema (OVERRIDE_UNION_KEYS) is {sorted(real)}."
    )


@pytest.mark.parametrize("doc", LIVING_DOCS, ids=lambda p: p.name)
def test_env_vars_in_living_docs_exist_in_source(doc: Path) -> None:
    """Every `CIBMP_*` a living doc names must be one something reads.

    Placeholder forms (`CIBMP_<KEY>`, `CIBMP_<PORT>_<TARGET>_TIMEOUT`) are
    skipped by the `<`/`>` test before they get here; what is left is a
    literal name a reader would export verbatim.
    """
    documented = set()
    for span in _code_spans(_text(doc)):
        if PLACEHOLDER.search(span):
            continue
        documented.update(ENV_VAR.findall(span))
    unknown = sorted(
        name
        for name in documented
        if name not in SOURCE and name not in _constructed_env_names()
    )
    assert not unknown, (
        f"{doc.relative_to(REPO)} documents environment variables nothing reads: "
        f"{unknown}"
    )


@pytest.mark.parametrize("doc", LIVING_DOCS, ids=lambda p: p.name)
def test_repo_paths_in_living_docs_exist(doc: Path) -> None:
    """A living doc pointing at a file this repo does not have is the
    exact shape `design.md` had for weeks after record 0050 deleted the
    natmod toolchain resolver it kept describing."""
    missing = []
    for span in _code_spans(_text(doc)):
        for candidate in REPO_PATH.findall(span):
            candidate = candidate.rstrip(".,;:)")
            if PLACEHOLDER.search(candidate) or GLOB.search(candidate):
                continue
            if candidate in FOREIGN_PATHS:
                continue
            if not any((root / candidate).exists() for root in PATH_ROOTS):
                missing.append(candidate)
    assert not missing, (
        f"{doc.relative_to(REPO)} points at paths that do not exist: "
        f"{sorted(set(missing))}"
    )


def test_vendored_images_reference_names_real_image_groups() -> None:
    """`vendored-images.md`'s own group names, against the table it
    documents. A Dockerfile split, a group rename or a
    `publish-docker-images.yml` change invalidates that file's mapping
    directly."""
    groups = _image_groups()
    doc = REPO / "docs" / "reference" / "vendored-images.md"
    # The six toolchain groups plus the non-unix ones are named in prose
    # as bare `code` spans; unix cells are PEP 600 tags, also group names.
    # A full PEP 600/656 platform tag (`manylinux_2_28_x86_64`) is a group
    # name; a bare family (`manylinux_2_28`, as in "a stock manylinux_2_28
    # image") is prose about the base image and names no group at all.
    platform_tag = re.compile(r"(?:many|musl)linux_\d+_\d+_[a-z0-9_]+")
    named = {
        span
        for span in _code_spans(_text(doc))
        if re.fullmatch(r"[a-z][a-z0-9_]{2,}", span)
        and (span in groups or platform_tag.fullmatch(span))
    }
    unknown = sorted(name for name in named if name not in groups)
    assert not unknown, (
        f"vendored-images.md names image groups that "
        f"resources/pinned_docker_images.toml does not have: {unknown}"
    )


@pytest.mark.parametrize("doc", LIVING_DOCS, ids=lambda p: p.name)
def test_action_pins_match_the_current_version(doc: Path) -> None:
    """Every `ballistics-lab/cibuildmp...@vX.Y.Z` a living doc shows must be
    the version this tree actually is.

    `CLAUDE.md` names this pin as a repeat offender by itself: it sat on
    `@v0.3.0` for weeks after `v0.4.0` shipped, and was found again at
    `@v0.4.1` across four places in `README.md` and `docs/ACTIONS.md` with
    `v0.4.2` released.

    The expected value comes from `CHANGELOG.md`'s own newest released
    heading, not from `cibuildmp.__version__` and not from `git tag`. Both
    of those are derived from the checkout: this test's first version used
    `__version__` and passed locally while failing on CI, where a shallow
    clone with no tags makes it `0.0.0.dev1+g<sha>`. The changelog is
    committed data, identical in every checkout, and a release moves it in
    the same commit that moves the docs.
    """
    current = f"v{_latest_released_version()}"
    wrong = sorted(
        {
            pin
            for pin in re.findall(
                r"ballistics-lab/cibuildmp[^\s`]*@(v\d+\.\d+\.\d+)", _text(doc)
            )
            if pin != current
        }
    )
    assert not wrong, (
        f"{doc.relative_to(REPO)} pins {wrong}; this tree is {current}. "
        f"An example nobody can copy is worse than no example."
    )


def test_generated_doc_blocks_are_current() -> None:
    """The blocks `bin/refresh_docs.py` owns must match what it produces.

    The stronger half of this suite: the checks above catch a documented
    fact that became wrong, while this one removes the chance to write it
    by hand at all. Both blocks under it were hand-maintained tables
    carrying a promise that they were current -- `vendored-images.md`'s
    said so in as many words -- which is the promise that goes stale with
    nobody noticing.
    """
    sys.path.insert(0, str(REPO / "bin"))
    import refresh_docs

    assert refresh_docs.main(["--check"]) == 0, (
        "a generated doc block is out of date -- run bin/refresh_docs.py"
    )


@pytest.mark.parametrize("doc", ALL_DOCS, ids=lambda p: p.name)
def test_record_links_resolve(doc: Path) -> None:
    """Every `[NNNN]` is defined, and every definition points at a file
    that exists.

    Both halves have failed for real: `README.md` used nine record numbers
    with no definition at all, rendering them as literal `[0043]`.
    """
    text = _text(doc)
    defined = dict(re.findall(r"^\[(\d{4})\]:\s*(\S+)$", text, re.MULTILINE))
    used = set(re.findall(r"\[(\d{4})\]", text)) - set(defined)
    assert not used, (
        f"{doc.relative_to(REPO)} cites records with no link definition: {sorted(used)}"
    )
    broken = sorted(
        f"{number} -> {target}"
        for number, target in defined.items()
        if not (doc.parent / target).resolve().is_file()
    )
    assert not broken, (
        f"{doc.relative_to(REPO)} has record links to missing files: {broken}"
    )

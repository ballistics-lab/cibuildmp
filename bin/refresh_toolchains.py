#!/usr/bin/env -S uv run --script

"""Print the real, per-tag, per-port compiler-toolchain fact table as TOML.

Fact-first, not axis-first (record 0052), and the same shape as
`bin/refresh_natmod_archs.py`/`bin/refresh_usermod_boards.py`: rather than
declaring "MicroPython needs gcc N" once and applying it everywhere, this
walks each MicroPython tag's own tree and prints one row per
compiler-version fact it actually found there, per port.

    bin/refresh_toolchains.py --repo ~/pyproj/micropython > /tmp/toolchains.toml
    bin/refresh_toolchains.py --repo ~/pyproj/micropython --resolve-apt
    bin/refresh_toolchains.py --repo ~/pyproj/micropython v1.26.0 v1.29.0 --audit

Output is `[toolchains]` / `requirements = [ {...}, ... ]`, one compact
inline table per fact. This script does not write build-platforms.toml
itself -- redirect and review by hand. With no tags given it walks exactly
the tags `resources/build-platforms.toml`'s own `[tags]` table already
knows, so the two stay in step rather than drifting apart.

**Only machine-readable sources are parsed. Port `README.md` prose is
deliberately not one of them.** Every port README states a toolchain
somewhere and none of those statements is maintained against the build:
`ports/nrf/README.md` still recommends "a toolchain after 7.2.1/4Q17" at
v1.30.0-preview, `docs/develop/gettingstarted.rst` still prints a
`gcc 9.3.0` transcript on every tag from v1.20.0 to today, and
`ports/psoc-edge/README.md`'s "minimum required version is 14.2.1" is a
sentence no build step ever checks. A claim nothing enforces goes stale
silently -- which is what record 0077 was written about. What is parsed
instead is what fails a build, or what actually ran:

- **`guard-error` / `guard-branch`** -- a port's own makefile/CMake asking
  the compiler its version (`gcc -dumpversion`, `CMAKE_C_COMPILER_VERSION`)
  and then erroring out or switching flags on the answer.
  `ports/stm32/stm32.mk`'s Cortex-M55 check (`$(error ... upgrade to GCC
  14.3+ ...)` under `MCU_SERIES=n6`) is a hard floor a real build hits;
  `ports/qemu/Makefile`'s `test $(GCC_VERSION) -le 10` picks `rv32imac`
  over `rv32imac_zicsr`, which is not a floor but is why a too-old RISC-V
  gcc miscompiles instead of complaining.
- **`ci-apt` / `ci-tarball` / `ci-idf` / `ci-runner`** -- the whole chain
  upstream CI executes for that port at that tag, followed rather than
  guessed: each port's own `ports_<port>.yml` workflow names its `runs-on:`
  image *and* the `ci_<name>_setup` function it sources out of
  `tools/ci.sh`; that function is what installs the compiler. So the port
  -> toolchain link is read from the two files that implement it. On
  v1.12/v1.13, which have no `tools/ci.sh`, `.travis.yml` is read the same
  way (its `dist:` is the image, its `apt-get install` lines the
  compilers).
- **`apt-resolved`** (`--resolve-apt`, network) -- the number behind a
  `ci-apt` row. `apt-get install gcc-arm-none-eabi` pins nothing by
  itself; the `runs-on:` image decides it. For a concrete `ubuntu-XX.XX`
  runner this asks Launchpad which version that suite actually publishes
  (`changelogs.ubuntu.com/meta-release` for the version -> codename map,
  then the Launchpad API per package), so `ubuntu-22.04` +
  `gcc-arm-none-eabi` becomes `15:10.3-2021.07-4`, i.e. gcc 10. A bare
  `ubuntu-latest` is left unresolved and marked `pinned = false`:
  resolving it needs GitHub's own runner-image rollout dates, which are
  not a fact in the MicroPython tree and are not going to be guessed from
  a tag date.
- **`breaks-with`** -- the ceiling, from git ancestry rather than any
  file's contents: a curated list of upstream commits that exist *because*
  a newer compiler rejected the old code (COMPAT_FIXES below, each entry
  quoting its own commit message). Every tag not containing the fix is a
  tag that does not build with that compiler, whatever its own files say.
  This is the half no in-tree source states at all, and the one that
  answers `docs/reference/open-questions.md`'s "Old tags vs. a modern host
  `gcc`" -- found there by hitting it, resolved here.

Needs a real clone (`--repo`, default: a fresh `--filter=blob:none` clone
into a temp dir): ancestry is what `breaks-with` is computed from, and the
raw-file fetch per tag that `refresh_natmod_archs.py` uses cannot see it.
Nothing here builds anything or runs a compiler -- every row is read out
of the checkout, and `--resolve-apt` reads package metadata, never an
image.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

REPO_URL = "https://github.com/micropython/micropython"
BUILD_PLATFORMS = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "cibuildmp"
    / "resources"
    / "build-platforms.toml"
)
USER_AGENT = "cibuildmp-refresh-toolchains"
META_RELEASE = "https://changelogs.ubuntu.com/meta-release"
LAUNCHPAD = (
    "https://api.launchpad.net/1.0/ubuntu/+archive/primary"
    "?ws.op=getPublishedBinaries&binary_name={pkg}&exact_match=true"
    "&distro_arch_series=https://api.launchpad.net/1.0/ubuntu/{suite}/amd64"
    "&status=Published&order_by_date=true"
)


@dataclass(frozen=True)
class CompatFix:
    """One upstream commit that exists because a compiler got stricter.

    `summary` is the commit's own subject and `evidence` a verbatim
    sentence from its message, so a reader can check the claim without
    trusting this table -- and so an entry cannot be added on a hunch: a
    commit whose own message does not name the compiler version it is
    about does not belong here.
    """

    sha: str
    compiler: str
    version: str
    scope: str
    summary: str
    evidence: str


# Found by searching MicroPython's own log for commit messages naming a
# compiler version, kept only where the message itself says the build
# *failed* (not merely warned). A tag not containing the commit is a tag
# that does not build with that compiler -- that, not a README, is the
# ceiling. Re-run `--audit` after a new tag: a fix landing upstream shows
# up as a subject this table has no row for.
COMPAT_FIXES = (
    CompatFix(
        "9f8600588",
        "gcc",
        "15.1",
        "mpy-cross",
        "py/emitinlinethumb: Refactor string literal as array initializer.",
        "Avoids the new Wunterminated-string-literal when compiled with gcc 15.1.",
    ),
    CompatFix(
        "7d5aba052",
        "gcc",
        "15.1",
        "any",
        "extmod/moductypes: Refactor string literal as array initializer.",
        "Avoids the new Wunterminated-string-literal when compiled with gcc 15.1.",
    ),
    CompatFix(
        "ae6062a45",
        "gcc",
        "15.1",
        "any",
        "lib/littlefs: Fix string initializer in lfs1.c.",
        "Avoids the new Wunterminated-string-literal when compiled with gcc 15.1.",
    ),
    CompatFix(
        "3fa77bdc7",
        "gcc",
        "15.1",
        "usermod.rp2",
        "rp2: Add temporary workaround for GCC 15.1 build failure.",
        "This is a workaround for this upstream issue: "
        "https://github.com/raspberrypi/pico-sdk/issues/2448",
    ),
    CompatFix(
        "0f0dcec98",
        "gcc",
        "13",
        "usermod.mimxrt",
        "mimxrt/sdcard: Fix GCC 13 build error with sdcard_cmd_set_bus_width.",
        "This updates the declaration of 'sdcard_cmd_set_bus_width()' to the "
        "same as its definition.",
    ),
    CompatFix(
        "a254bbca7",
        "clang",
        "19",
        "unix",
        "py/nlrx86: Fix nlr_push to build with Clang 19.",
        "py/nlrx86: Fix nlr_push to build with Clang 19.",
    ),
)

# Where a build really asks about a compiler version. `lib/` is excluded
# wholesale: every vendored submodule (pico-sdk, tinyusb, mbedtls) carries
# its own compiler checks, which are facts about that project's pin, not
# about a MicroPython tag.
GUARD_PATHS = ("ports", "py", "extmod", "shared", "tools", "mpy-cross")
GUARD_TRIGGER = re.compile(
    r"-dumpversion|-dumpfullversion|CMAKE_C_COMPILER_VERSION|GCC_VERSION"
)
# `.+` to end of line, not `[^)]+`: the message itself contains
# `$(GCC_VERSION)`, so stopping at the first `)` truncates it right
# before the version threshold it exists to state.
GUARD_ERROR = re.compile(
    r"\$\(error\s+(?P<text>.+)$|message\s*\(\s*FATAL_ERROR(?P<cmake_text>.+)$",
    re.MULTILINE,
)
GUARD_BRANCH = re.compile(r"^\s*(?:ifeq|ifneq|if)\b.*(?:GCC_VERSION|COMPILER_VERSION)")
GUARD_THRESHOLD = re.compile(
    r"GCC\s+(?P<plus>\d+(?:\.\d+)?)\+"
    r"|(?:-lt|-le|-gt|-ge)\s+(?P<num>\d+)"
    r"|VERSION_(?:LESS|GREATER)(?:_EQUAL)?\s+(?P<cmake>\d+(?:\.\d+)*)"
)

# Compiler-ish apt packages only. Everything else ci.sh installs (qemu,
# protobuf-c-compiler, picotool, python3-*) is not a compiler.
APT_COMPILER = re.compile(
    r"^(?:gcc|g\+\+|clang|libnewlib|picolibc|binutils|libstdc\+\+)[-\w.+]*$"
)
APT_INSTALL = re.compile(r"apt(?:-get)?\s+(?:-y\s+)?install\s+(?P<pkgs>[^\n|&;]+)")
TARBALL_URL = re.compile(r"https?://\S+?\.(?:tar\.gz|tar\.xz|tar\.bz2|tgz|zip)")
IDF_VER = re.compile(r"^\s*IDF_VER=(?P<ver>\S+)", re.MULTILINE)
# Three shapes, all of them real, none of them a README:
#   v1.15-v1.23 -- the version is `ci_esp32_setup_helper`'s argument, and
#                  the calling function's name encodes it too
#                  (`ci_esp32_idf402_setup { ci_esp32_setup_helper v4.0.2 }`)
#   v1.24-v1.26 -- a literal `IDF_VER=v5.2.2` in tools/ci.sh
#   v1.28+      -- the workflow's own `env:` block declares the supported
#                  range (`IDF_OLDEST_VER: &oldest "v5.3"`), and the setup
#                  moved into a composite action, so ci.sh names no version
#                  at all. Reading only the middle shape left every esp32
#                  row before v1.24 and after v1.27 with no IDF pin.
IDF_HELPER = re.compile(r"ci_esp32_setup_helper\s+(?P<ver>v[\d.]+)")
IDF_CHECKOUT = re.compile(r"git -C esp-idf checkout\s+(?P<ver>v[\d.]+)")
# `ports/esp32/lockfiles/dependencies.lock.esp32`'s own `idf:` component,
# which is exactly what v1.27.0's `IDF_VER=v$(grep -A10 "idf:" ...)` line
# reads -- so this parses the file ci.sh parses rather than the shell
# expression that parses it.
IDF_LOCK = re.compile(
    r"^\s{2}idf:\s*$.*?^\s+version:\s*(?P<ver>[\d.]+)", re.MULTILINE | re.DOTALL
)
IDF_ENV = re.compile(
    r"^\s*IDF_(?P<which>OLDEST|NEWEST)_VER:\s*(?:&\w+\s+)?\"?(?P<ver>v[\d.]+)",
    re.MULTILINE,
)
EMSDK = re.compile(r"emsdk\s+(?:install|activate)\s+(?P<ver>[\w.-]+)")
CI_FUNCTION = re.compile(r"^function\s+(?P<name>\w+)\s*\{", re.MULTILINE)
# Two invocation shapes, both real: `source tools/ci.sh && ci_stm32_setup`
# up to v1.26.1, and `tools/ci.sh stm32_setup` (a dispatch wrapper, the
# `ci_` prefix dropped from the caller) from v1.27.0. Matching only the
# first found no compiler at all for every port from v1.27.0 on, and
# said nothing about it -- hence the "calls nothing" audit line below.
# `\w*setup\w*`, not `\w+_setup`: `_setup` is not always the suffix.
# ports_qemu.yml calls `ci_qemu_setup_arm`/`ci_qemu_setup_rv32`, and an
# anchored suffix silently skipped both -- i.e. every qemu row lost its
# toolchain from v1.24.0 on.
CI_CALL = re.compile(r"\bci_(?P<name>\w*setup\w*)\b")
CI_DISPATCH = re.compile(r"tools/ci\.sh\s+(?P<name>\w*setup\w*)\b")
RUNS_ON = re.compile(r"^\s*runs-on:\s*(?P<label>\S.*?)\s*$", re.MULTILINE)
UBUNTU_LABEL = re.compile(r"^ubuntu-(?P<ver>\d\d\.\d\d)(?:-arm)?$")
TRAVIS_DIST = re.compile(r"^dist:\s*(?P<dist>\S+)", re.MULTILINE)


# --------------------------------------------------------------------------
# git plumbing
# --------------------------------------------------------------------------


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=False, capture_output=True, text=True
    )


def git_show(repo: Path, tag: str, path: str) -> str | None:
    """File contents at `tag`, or None where that tag has no such file.

    Absence is a fact every caller records rather than raises past: v1.12
    and v1.13 have no `tools/ci.sh` at all (`.travis.yml` is what they
    have), `ports/psoc-edge` does not exist before v1.29.0, and
    `ports/qemu` was `ports/qemu-arm` until v1.24.0.
    """
    result = git(repo, "show", f"{tag}:{path}")
    return result.stdout if result.returncode == 0 else None


def workflow_files(repo: Path, tag: str) -> list[str]:
    result = git(repo, "ls-tree", "--name-only", tag, ".github/workflows/")
    if result.returncode != 0:
        return []
    return [n for n in result.stdout.split() if n.endswith((".yml", ".yaml"))]


def tag_contains(repo: Path, sha: str, tag: str) -> bool:
    return (
        git(repo, "merge-base", "--is-ancestor", sha, f"{tag}^{{commit}}").returncode
        == 0
    )


@lru_cache(maxsize=64)
def first_tag_with(repo: Path, sha: str) -> str | None:
    """Cached: `git tag --contains` walks every tag in the repo, and the
    answer is a property of the commit alone -- asking it once per (tag,
    fix) pair rather than once per fix was most of this script's own
    runtime."""
    result = git(repo, "tag", "--contains", sha, "--sort=creatordate")
    if result.returncode != 0:
        return None
    for tag in result.stdout.split():
        if re.fullmatch(r"v\d+\.\d+(?:\.\d+)?", tag):
            return tag
    return None


# --------------------------------------------------------------------------
# collectors -- one per machine-readable source
# --------------------------------------------------------------------------


def guard_rows(repo: Path, tag: str, audit: list[str]) -> list[dict]:
    """Compiler-version questions a build asks, from the files that ask.

    One `git grep -n -A6` per tag rather than a `git show` per makefile:
    a tag has ~100 build files under `ports/` and only a handful ever
    mention a compiler version.
    """
    result = git(
        repo,
        "grep",
        "-n",
        "-A6",
        "-E",
        # `-e`, not a bare pattern: the pattern starts with `-dumpversion`
        # and git reads it as its own option otherwise.
        "-e",
        GUARD_TRIGGER.pattern,
        tag,
        "--",
        *GUARD_PATHS,
    )
    if result.returncode not in (0, 1):
        return []

    rows: list[dict] = []
    block: list[tuple[str, int, str]] = []

    def flush() -> None:
        if not block:
            return
        path, line, _ = block[0]
        text = "\n".join(t for _, _, t in block)
        error = GUARD_ERROR.search(text)
        branch = any(GUARD_BRANCH.search(t) for _, _, t in block)
        if not (error or branch):
            audit.append(f"{tag} {path}:{line}: version read but not consumed")
            return
        threshold = GUARD_THRESHOLD.search(error.group(0) if error else text)
        value = ""
        if threshold:
            value = next(g for g in threshold.groups() if g)
        rows.append(
            {
                "tag": tag,
                "scope": scope_for_path(path),
                "tool": "gcc",
                "kind": "guard-error" if error else "guard-branch",
                "value": value,
                "detail": " ".join(
                    (
                        (error.group("text") or error.group("cmake_text") or "")
                        if error
                        else ""
                    )
                    .rstrip(")")
                    .split()
                )[:160]
                or " ".join(block[0][2].split())[:160],
                "source": f"{path}:{line}",
            }
        )

    for raw in result.stdout.splitlines():
        if raw == "--":
            flush()
            block = []
            continue
        match = re.match(
            rf"{re.escape(tag)}:(?P<path>[^:]+)[:-](?P<line>\d+)[:-](?P<text>.*)", raw
        )
        if match:
            block.append((match["path"], int(match["line"]), match["text"]))
    flush()
    return rows


def scope_for_path(path: str) -> str:
    """`ports/stm32/stm32.mk` -> `usermod.stm32`; anything else -> `any`.

    Ports are named the way `resources/build-platforms.toml`'s own
    `[usermod.<port>]` sections name them, so a row here can be lined up
    against that table without a second mapping.
    """
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] == "ports":
        return f"usermod.{parts[1]}"
    if parts[0] == "mpy-cross":
        return "mpy-cross"
    return "any"


def ci_functions(text: str) -> dict[str, str]:
    """`tools/ci.sh` split into its own `function ci_x_setup { ... }`
    bodies, keyed by name."""
    bodies: dict[str, str] = {}
    matches = list(CI_FUNCTION.finditer(text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        bodies[match["name"]] = text[match.end() : end]
    return bodies


def compilers_from(body: str) -> tuple[list[str], list[str]]:
    """(apt compiler packages, toolchain tarball URLs) a ci.sh function
    installs. Non-compiler packages are dropped, not recorded as
    toolchains."""
    packages: list[str] = []
    for install in APT_INSTALL.finditer(body):
        for token in install["pkgs"].split():
            if APT_COMPILER.fullmatch(token) and token not in packages:
                packages.append(token)
    urls = [url for url in TARBALL_URL.findall(body)]
    return packages, urls


def inlined_setup(bodies: dict[str, str], entry: str) -> tuple[str, str]:
    """`ci_stm32_setup`'s body plus the bodies of every `ci_*_setup` it
    calls, and the call chain that reached them.

    Not an optimisation -- it is the only way the arm ports get a
    compiler at all. `ports_stm32.yml` runs `ci_stm32_setup`, and that
    function installs no compiler itself: it calls `ci_gcc_arm_setup`,
    which is where `gcc-arm-none-eabi` comes from. Reading only the
    directly-named function finds nothing and would quietly report every
    ARM port as having no toolchain.
    """
    seen: list[str] = []
    parts: list[str] = []

    def walk(name: str) -> None:
        if name in seen or name not in bodies:
            return
        seen.append(name)
        body = bodies[name]
        parts.append(body)
        for call in CI_CALL.finditer(body):
            walk(f"ci_{call['name']}")

    walk(entry)
    return "\n".join(parts), ">".join(seen)


def idf_pins(
    body: str,
    idf_global: re.Match[str] | None,
    workflow: str,
    lockfile: str | None = None,
) -> list[tuple[str, str]]:
    """(version, where it was read) for every ESP-IDF this tag pins.

    A list, not one value: from v1.28.0 the workflow declares a supported
    *range* (oldest and newest), and both ends are real -- the port is
    built against each. A `IDF_VER=v$(grep ...)` shell expression is not a
    version and is skipped rather than recorded as one; the lockfile it
    reads is the esp-idf component manifest, which pins constraints
    (`>=5.3`) rather than the version CI used.
    """
    pins: list[tuple[str, str]] = []
    helper = IDF_HELPER.search(body)
    if helper:
        pins.append((helper["ver"], "tools/ci.sh:ci_esp32_setup_helper"))
    literal = IDF_VER.search(body) or idf_global
    if literal and "$(" not in literal["ver"]:
        pins.append((literal["ver"].strip('"'), "tools/ci.sh:IDF_VER"))
    checkout = IDF_CHECKOUT.search(body)
    if checkout:
        pins.append((checkout["ver"], "tools/ci.sh:git -C esp-idf checkout"))
    if lockfile:
        lock = IDF_LOCK.search(lockfile)
        if lock:
            pins.append(
                (f"v{lock['ver']}", "ports/esp32/lockfiles/dependencies.lock.esp32")
            )
    for env in IDF_ENV.finditer(workflow):
        pins.append(
            (env["ver"], f".github/workflows/ports_esp32.yml:IDF_{env['which']}_VER")
        )
    seen: set[str] = set()
    return [pin for pin in pins if not (pin[0] in seen or seen.add(pin[0]))]


def ci_rows(repo: Path, tag: str, audit: list[str]) -> list[dict]:
    """The port -> runner -> setup-function -> compiler chain, followed
    through the two files that implement it."""
    ci_sh = git_show(repo, tag, "tools/ci.sh")
    if ci_sh is None:
        return travis_rows(repo, tag, audit)

    bodies = ci_functions(ci_sh)
    idf_global = IDF_VER.search(ci_sh)
    rows: list[dict] = []

    for path in workflow_files(repo, tag):
        name = Path(path).stem
        if not name.startswith("ports_"):
            continue
        port = name[len("ports_") :]
        workflow = git_show(repo, tag, path) or ""
        scope = f"usermod.{port}"

        for label in sorted({m["label"] for m in RUNS_ON.finditer(workflow)}):
            if label.startswith("${{"):  # a matrix indirection, not an image
                continue
            ubuntu = UBUNTU_LABEL.match(label.split("#")[0].strip())
            rows.append(
                {
                    "tag": tag,
                    "scope": scope,
                    "tool": "runner-image",
                    "kind": "ci-runner",
                    "value": label.split("#")[0].strip(),
                    "pinned": bool(ubuntu),
                    "source": path,
                }
            )

        calls = {m["name"] for m in CI_CALL.finditer(workflow)}
        calls |= {m["name"] for m in CI_DISPATCH.finditer(workflow)}
        if not calls:
            pins = idf_pins("", None, workflow)
            for value, origin in pins:
                rows.append(
                    {
                        "tag": tag,
                        "scope": scope,
                        "tool": "esp-idf",
                        "kind": "ci-idf",
                        "value": value,
                        "source": origin,
                    }
                )
            if not pins:
                audit.append(f"{tag} {path}: no ci.sh setup call recognised")
        for call in sorted(calls):
            if f"ci_{call}" not in bodies:
                audit.append(f"{tag} {path}: calls ci_{call}, absent from tools/ci.sh")
                continue
            body, chain = inlined_setup(bodies, f"ci_{call}")
            packages, urls = compilers_from(body)
            for package in packages:
                rows.append(
                    {
                        "tag": tag,
                        "scope": scope,
                        "tool": package,
                        "kind": "ci-apt",
                        "value": package,
                        "source": f"tools/ci.sh:{chain}",
                    }
                )
            for url in urls:
                rows.append(
                    {
                        "tag": tag,
                        "scope": scope,
                        "tool": Path(url).name,
                        "kind": "ci-tarball",
                        "value": url,
                        "source": f"tools/ci.sh:{chain}",
                    }
                )
            emsdk = EMSDK.search(body)
            if emsdk:
                rows.append(
                    {
                        "tag": tag,
                        "scope": scope,
                        "tool": "emsdk",
                        "kind": "ci-tarball",
                        "value": emsdk["ver"],
                        "source": f"tools/ci.sh:{chain}",
                    }
                )
            if port == "esp32":
                lockfile = git_show(
                    repo, tag, "ports/esp32/lockfiles/dependencies.lock.esp32"
                )
                pins = idf_pins(body, idf_global, workflow, lockfile)
                for value, origin in pins:
                    rows.append(
                        {
                            "tag": tag,
                            "scope": scope,
                            "tool": "esp-idf",
                            "kind": "ci-idf",
                            "value": value,
                            "source": origin,
                        }
                    )
                if not pins and not packages and not urls:
                    audit.append(
                        f"{tag} {path}: no compiler and no IDF pin found via ci_{call}"
                    )
    return rows


def travis_rows(repo: Path, tag: str, audit: list[str]) -> list[dict]:
    """v1.12/v1.13 have no `tools/ci.sh` and no workflows -- `.travis.yml`
    is the whole CI, and its per-job `env` matrix does not name ports the
    way `ports_<port>.yml` later does. So these rows are recorded at
    `scope = "any"`: the image and the compilers are real, the per-port
    attribution is not available at those tags and is not invented."""
    travis = git_show(repo, tag, ".travis.yml")
    if travis is None:
        audit.append(f"{tag}: neither tools/ci.sh nor .travis.yml")
        return []
    rows: list[dict] = []
    dist = TRAVIS_DIST.search(travis)
    if dist:
        rows.append(
            {
                "tag": tag,
                "scope": "any",
                "tool": "runner-image",
                "kind": "ci-runner",
                "value": f"travis:{dist['dist']}",
                "pinned": True,
                "source": ".travis.yml",
            }
        )
    packages, urls = compilers_from(travis)
    for package in packages:
        rows.append(
            {
                "tag": tag,
                "scope": "any",
                "tool": package,
                "kind": "ci-apt",
                "value": package,
                "source": ".travis.yml",
            }
        )
    for url in urls:
        rows.append(
            {
                "tag": tag,
                "scope": "any",
                "tool": Path(url).name,
                "kind": "ci-tarball",
                "value": url,
                "source": ".travis.yml",
            }
        )
    return rows


def walk_tag(repo: Path, tag: str) -> tuple[list[dict], list[str]]:
    """Every row for one tag, plus that tag's own audit lines.

    Self-contained on purpose: no collector reads another tag's result,
    which is what lets `main` run tags in a thread pool. The work is
    `git` subprocesses, so threads are the right tool -- the interpreter
    is not what is busy.
    """
    audit: list[str] = []
    rows: list[dict] = []
    rows.extend(guard_rows(repo, tag, audit))
    rows.extend(ci_rows(repo, tag, audit))
    rows.extend(ceiling_rows(repo, tag))
    return rows, audit


def ceiling_rows(repo: Path, tag: str) -> list[dict]:
    """A tag that lacks a compat fix does not build with the compiler that
    fix exists for. Ancestry, not file contents."""
    rows = []
    for fix in COMPAT_FIXES:
        if tag_contains(repo, fix.sha, tag):
            continue
        landed = first_tag_with(repo, fix.sha)
        rows.append(
            {
                "tag": tag,
                "scope": fix.scope,
                "tool": fix.compiler,
                "kind": "breaks-with",
                "value": f">={fix.version}",
                "detail": fix.evidence[:160],
                "source": f"{fix.sha} ({fix.summary}) first in {landed or 'unreleased'}",
            }
        )
    return rows


# --------------------------------------------------------------------------
# optional resolver -- what an apt package name actually resolves to
# --------------------------------------------------------------------------


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read()
    return gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw


@lru_cache(maxsize=1)
def ubuntu_codenames() -> dict[str, str]:
    """`{"22.04": "jammy", ...}` from Ubuntu's own machine-readable
    `meta-release` (plus `-development`, which is where a release that has
    not shipped yet lives). Fetched rather than hardcoded for the reason
    every pinned table in this repo is data: the map grows on Canonical's
    schedule, not this file's."""
    codenames: dict[str, str] = {}
    for suffix in ("", "-development"):
        try:
            text = _get(META_RELEASE + suffix).decode("utf-8", "ignore")
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"!! meta-release{suffix}: {exc}", file=sys.stderr)
            continue
        dist = None
        for line in text.splitlines():
            if line.startswith("Dist:"):
                dist = line.split(":", 1)[1].strip()
            elif line.startswith("Version:") and dist:
                version = line.split(":", 1)[1].strip().split()[0]
                codenames.setdefault(version[:5], dist)
    return codenames


@lru_cache(maxsize=256)
def launchpad_version(package: str, suite: str) -> str | None:
    """The version `suite` publishes for `package`, or None when it
    publishes none (a package can simply not exist in an older suite --
    `gcc-riscv64-unknown-elf` does not, before noble)."""
    try:
        # quote(): a `+` in a query string is a space, so an unencoded
        # `g++-multilib` asks Launchpad about "g  -multilib" and comes
        # back empty -- indistinguishable from "this suite has no such
        # package" unless it is encoded here.
        url = LAUNCHPAD.format(pkg=urllib.parse.quote(package, safe=""), suite=suite)
        data = json.loads(_get(url))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"!! launchpad {package}/{suite}: {exc}", file=sys.stderr)
        return None
    entries = data.get("entries") or []
    return str(entries[0]["binary_package_version"]) if entries else None


def gcc_major(version: str) -> str:
    """`15:10.3-2021.07-4` -> `10`. Debian epochs (`15:`) are packaging
    metadata and famously unrelated to the compiler version -- stripping
    one is the whole reason this is a function and not an inline split."""
    without_epoch = version.split(":", 1)[-1]
    match = re.match(r"(\d+)", without_epoch)
    return match.group(1) if match else ""


def resolve_apt(rows: list[dict], audit: list[str]) -> list[dict]:
    """Turn every (`ci-apt` package, pinned `ci-runner` image) pair at the
    same (tag, scope) into the concrete version that image installs.

    An unpinned `ubuntu-latest` runner resolves nothing here on purpose:
    which image that label meant on a given date is GitHub's fact, not
    MicroPython's, and guessing it from the tag date is exactly the kind
    of plausible-but-unchecked step this table exists to avoid."""
    codenames = ubuntu_codenames()
    runners: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        if row["kind"] != "ci-runner" or not row.get("pinned"):
            continue
        label = UBUNTU_LABEL.match(row["value"])
        if label:
            runners.setdefault((row["tag"], row["scope"]), set()).add(label["ver"])

    # Every (package, suite) pair this run needs, fetched concurrently up
    # front. `launchpad_version` is memoised, so the pass below answers
    # from cache: one round trip per distinct pair rather than one per
    # row (~240 rows, ~40 pairs).
    wanted = {
        (row["value"], codenames[ubuntu])
        for row in rows
        if row["kind"] == "ci-apt"
        for ubuntu in runners.get((row["tag"], row["scope"]), ())
        if ubuntu in codenames
    }
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda pair: launchpad_version(*pair), sorted(wanted)))

    resolved: list[dict] = []
    for row in rows:
        if row["kind"] != "ci-apt":
            continue
        for ubuntu in sorted(runners.get((row["tag"], row["scope"]), ())):
            suite = codenames.get(ubuntu)
            if suite is None:
                audit.append(f"{row['tag']} {row['scope']}: no codename for {ubuntu}")
                continue
            version = launchpad_version(row["value"], suite)
            if version is None:
                audit.append(
                    f"{row['tag']} {row['scope']}: {row['value']} not published in {suite}"
                )
                continue
            resolved.append(
                {
                    "tag": row["tag"],
                    "scope": row["scope"],
                    "tool": row["value"],
                    "kind": "apt-resolved",
                    "value": gcc_major(version),
                    "detail": version,
                    "source": f"launchpad:{suite}/amd64 via {row['source']}",
                }
            )
    return resolved


# --------------------------------------------------------------------------
# TOML output
# --------------------------------------------------------------------------


def _toml_str(value: str) -> str:
    """A TOML basic string, escaped by hand -- same reasoning as
    `refresh_natmod_archs.py`/`refresh_usermod_boards.py`'s own copies of
    this: stdlib has no TOML writer, and this project stays off
    third-party dependencies for anything that isn't the native-.mpy link
    step itself. Third copy, deliberately: these three scripts share no
    import path (`bin/` is not a package), and a shared helper module for
    them would be a fourth file to keep in step."""
    out = ['"']
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _toml_str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"unsupported TOML value type: {type(value)!r}")


def _inline_row(row: dict) -> str:
    parts = [
        f"{key} = {_toml_value(value)}"
        for key, value in row.items()
        if value not in (None, "")
    ]
    return "{ " + ", ".join(parts) + " }"


# --------------------------------------------------------------------------


def dedupe(rows: list[dict]) -> list[dict]:
    """One row per distinct fact. `ports_unix.yml` names `ubuntu-22.04`
    on four separate jobs at v1.26.0 (each with its own trailing `# use
    22.04 to get ...` comment); that is one fact about one image, not
    four."""
    seen: set[tuple] = set()
    out = []
    for row in rows:
        key = (row["tag"], row["scope"], row["tool"], row["kind"], row["value"])
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def default_tags() -> list[str]:
    """Exactly the tags `resources/build-platforms.toml` already walks --
    so refreshing this table cannot silently cover a different tag set
    than the one every other row in that file was verified against."""
    with BUILD_PLATFORMS.open("rb") as handle:
        return list(tomllib.load(handle)["tags"])


def clone(dest: Path) -> None:
    subprocess.run(
        [
            "git",
            "clone",
            "--quiet",
            "--filter=blob:none",
            "--no-checkout",
            REPO_URL,
            str(dest),
        ],
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "tags",
        nargs="*",
        help="MicroPython tags to walk (default: every tag in "
        "resources/build-platforms.toml's own [tags] table)",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="an existing micropython clone to read (default: clone one into a "
        "temp dir; it must have every tag being walked -- `git fetch --tags` "
        "first if a new release is missing)",
    )
    parser.add_argument(
        "--resolve-apt",
        action="store_true",
        help="also ask Launchpad which version each ci-apt package resolves to "
        "on that tag's own pinned runner image (network)",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=8,
        help="how many tags to walk at once (default: 8)",
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="print to stderr every place a compiler version was mentioned but "
        "no row could be made of it -- a parser gap is meant to be loud",
    )
    args = parser.parse_args()

    repo = args.repo
    cleanup = False
    if repo is None:
        repo = Path(tempfile.mkdtemp(prefix="cibuildmp-toolchains-"))
        print("cloning micropython...", file=sys.stderr)
        clone(repo)
        cleanup = True

    tags = args.tags or default_tags()
    audit: list[str] = []
    rows: list[dict] = []
    try:
        for fix in COMPAT_FIXES:
            if git(repo, "cat-file", "-e", f"{fix.sha}^{{commit}}").returncode != 0:
                raise SystemExit(f"COMPAT_FIXES: {fix.sha} not in {repo}")
        present = []
        for tag in tags:
            if git(repo, "rev-parse", f"{tag}^{{commit}}").returncode != 0:
                print(f"!! {tag}: not in {repo}, skipped", file=sys.stderr)
                continue
            present.append(tag)
        # Collected in `present` order, not completion order: the printed
        # table has to be a function of the tag list, not of which thread
        # finished first.
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            for tag, (tag_rows, tag_audit) in zip(
                present, pool.map(lambda t: walk_tag(repo, t), present)
            ):
                print(f"walked {tag}", file=sys.stderr)
                rows.extend(tag_rows)
                audit.extend(tag_audit)
        if args.resolve_apt:
            rows.extend(resolve_apt(rows, audit))
    finally:
        if cleanup:
            shutil.rmtree(repo, ignore_errors=True)

    print("[toolchains]")
    print("requirements = [")
    for row in dedupe(rows):
        print("    " + _inline_row(row) + ",")
    print("]")

    if audit and args.audit:
        print("\n-- audit: mentioned but not parsed --", file=sys.stderr)
        for line in audit:
            print(f"   {line}", file=sys.stderr)
    elif audit:
        print(f"{len(audit)} unparsed mention(s); re-run with --audit", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

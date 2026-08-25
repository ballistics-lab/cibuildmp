"""MSYS2 orchestration for the `windows` usermod port (**D18**).

Genuinely a fourth provisioning story, not a variant of D3's
`host`/`download`/`docker`: MSYS2 is an environment a build must run
*inside* (`bash.exe` under a login shell, with `MSYSTEM=MINGW32|MINGW64|
CLANGARM64` selecting the toolchain PATH's own startup scripts put in
place), not a `<prefix>gcc` this project can just point `CROSS_COMPILE=`
at from a plain `subprocess.run()`.

Detect-first, download-as-fallback, transcribed from `msys2/setup-msys2`'s
own source (`main.js`), not guessed: its default (`release: false`, what
every real caller -- including `a7p`'s own `mp-usermod.yml` -- actually
uses) is `C:\\msys64`, already present on every GitHub-hosted
`windows-latest` runner; it only downloads its own standalone installer
(`msys2-installer` releases, a self-extracting `.sfx.exe`, sha256-pinned)
when asked to install a fresh copy (`release: true`) or when nothing is
there yet -- the local-dev-machine case. `INSTALLER_VERSION`/
`INSTALLER_CHECKSUM` below are that action's own pins, at the commit this
was read from -- see this project's own "nothing checks whether a pinned
version is stale" open question for why that will eventually drift.

Cannot be verified in a Linux sandbox at all, unlike every other resolver
in this package: `usermod-dev.yml`'s `windows` job (a plain on-push
scratch workflow, not a PR) is the only real feedback loop, and it
already caught genuine bugs in the other three ports before any MSYS2
code existed. Expect this module specifically to need CI-driven
correction rounds the others didn't: the shell-invocation details below
(`bash.exe -leo pipefail -c`, `CHERE_INVOKING`) are transcribed from
`setup-msys2`'s own source and MSYS2's own documented Git-for-Windows
convention, not something this project's own CI has confirmed working
yet.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..sources import cache_root, cached_dir, download_file, verify_sha256

# Transcribed from msys2/setup-msys2's own main.js
# (INSTALLER_VERSION/INSTALLER_CHECKSUM), not invented.
INSTALLER_VERSION = "2026-06-11"
INSTALLER_CHECKSUM = "c105946e64e08f099ac0e4647461ce762b95333ad211777666476a9a41451d65"
INSTALLER_URL = (
    "https://github.com/msys2/msys2-installer/releases/download/"
    f"{INSTALLER_VERSION}/msys2-base-x86_64-{INSTALLER_VERSION.replace('-', '')}.sfx.exe"
)

# Where every GitHub-hosted windows-latest runner already has MSYS2 --
# msys2/setup-msys2's own default (release: false) path, not this
# project's own convention.
DEFAULT_ROOT = Path("C:/msys64")


class Msys2Error(Exception):
    pass


def _bash_exe(root: Path) -> Path:
    return root / "usr" / "bin" / "bash.exe"


def find_msys2(root: Path = DEFAULT_ROOT) -> Path | None:
    """The pre-installed MSYS2 root, if this host already has one."""
    return root if _bash_exe(root).exists() else None


def install_msys2(*, root: Path | None = None, quiet: bool = False) -> Path:
    """Download and self-extract MSYS2's own standalone installer.

    Only needed on a host with no pre-existing install (a local dev
    machine, most likely) -- see `find_msys2()` for the case that avoids
    this entirely.
    """
    dest = (root or cache_root()) / "msys2" / INSTALLER_VERSION

    def populate(staging: Path) -> Path:
        installer = staging / "base.exe"
        download_file(INSTALLER_URL, installer, quiet=quiet)
        verify_sha256(installer, INSTALLER_CHECKSUM)
        try:
            subprocess.run([str(installer), "-y"], cwd=staging, check=True)
        except subprocess.CalledProcessError as exc:
            raise Msys2Error(f"MSYS2 installer failed: {exc}") from exc
        installer.unlink()
        return staging / "msys64"

    result, was_cached = cached_dir(dest, populate, force=False)
    if was_cached and not quiet:
        print(f"  MSYS2 {INSTALLER_VERSION}: cached at {result}")
    return result


def resolve_msys2(*, root: Path | None = None, quiet: bool = False) -> Path:
    return find_msys2() or install_msys2(root=root, quiet=quiet)


@dataclass(frozen=True)
class ResolvedMsys2:
    root: Path
    msystem: str

    def run(
        self, command: str, *, cwd: Path | None = None, check: bool = True
    ) -> subprocess.CompletedProcess:
        """Run `command` inside this MSYS2 install's own bash, under
        `msystem` -- the same mechanism `shell: msys2 {0}` itself uses
        (`setup-msys2`'s own `main.js`:
        `bash.exe -leo pipefail <command>`), not a plain
        `subprocess.run([...])` with `PATH` prepended: `MSYSTEM` alone
        does not put the right toolchain on `PATH` without going through
        bash's own login-shell startup scripts, which is what actually
        selects it.

        `CHERE_INVOKING=1` is MSYS2's own convention (shared with
        Git-for-Windows' "Git Bash Here") for keeping the shell in `cwd`
        rather than `cd`-ing to `$HOME` on login -- unverified against
        this project's own CI yet, transcribed from that convention
        rather than confirmed working here.
        """
        env = {**os.environ, "MSYSTEM": self.msystem, "CHERE_INVOKING": "1"}
        try:
            return subprocess.run(
                [str(_bash_exe(self.root)), "-leo", "pipefail", "-c", command],
                cwd=cwd,
                env=env,
                check=check,
            )
        except subprocess.CalledProcessError as exc:
            raise Msys2Error(f"msys2 command failed: `{command}`: {exc}") from exc

    def install_packages(self, packages: list[str]) -> None:
        self.run(f"pacman -S --needed --noconfirm {' '.join(packages)}")

    def to_posix_path(self, native_path: str) -> str:
        """A native Windows path (e.g. `D:\\a\\mpy`), converted to this
        MSYS2 install's own POSIX form (`/d/a/mpy`) via `cygpath -u` --
        the correct way to do this (real drive-letter mapping), not
        string-replacing backslashes with forward slashes the way
        `Path.as_posix()` does elsewhere in this package (that produces
        `D:/a/mpy`, still not a path MSYS2 bash or a Makefile running
        under it can use). Delegated to `cygpath` itself rather than
        reimplemented, matching every other resolver's own D2 split.
        """
        env = {**os.environ, "MSYSTEM": self.msystem}
        try:
            result = subprocess.run(
                [str(_bash_exe(self.root)), "-lc", f'cygpath -u "{native_path}"'],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise Msys2Error(f"cygpath -u {native_path!r} failed: {exc}") from exc
        return result.stdout.strip()

"""cibuildmp -- build MicroPython native C extensions on CI, and locally."""

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("cibuildmp")
except PackageNotFoundError:  # running from a source tree, not installed
    __version__ = "0.0.0.dev0"

from .cli import main as _main

__all__ = ["__version__", "main"]


def main() -> None:
    sys.exit(_main())

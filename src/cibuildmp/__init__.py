"""cibuildmp -- build MicroPython native C extensions on CI, and locally."""

from __future__ import annotations

import sys

from .cli import main as _main

__all__ = ["main"]


def main() -> None:
    sys.exit(_main())

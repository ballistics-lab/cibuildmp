# Companion file for cibuildmp's own D14 test: NOT part of natmod/'s own
# SRC (see natmod/Makefile), so dynruntime.mk never merges it into
# template.mpy -- it stays a separate, arch-independent file, copied into
# every identifier's own directory via `[publish] extra-files` in
# cibuildmp.toml and listed untagged in that identifier's package.json.
# Real-world equivalent: ../micropython-bclibc's ffimod/ffi.py (see
# docs/BACKLOG.md D14).

from template import add  # type: ignore


def add_three(a, b, c):
    return add(add(a, b), c)

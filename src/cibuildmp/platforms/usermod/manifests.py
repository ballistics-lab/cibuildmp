"""Combined `FROZEN_MANIFEST` generation (D17): this port's own default
manifest.py plus a consumer's own module manifest, one `include()` each --
the same two-line shape `a7p`'s own `mp-usermod.yml` hand-writes today, via
`cat > manifest.py <<EOF ... EOF`, once per port-shape (four times over:
unix/webassembly/aarch64 share one step, esp32 and windows each need their
own, qemu drops the first line since it has no default). This is exactly
the class of hand-copied-and-drifting logic Positioning says `cibuildmp`
exists to absorb.

Verified byte-for-byte against that workflow's own literal `cat <<EOF`
bodies, not just against resources/usermod.toml's own paths -- see
tests/test_manifests.py.
"""

from __future__ import annotations

from .portinfo import default_manifest


def combined_manifest(port: str, module_manifest: str) -> str:
    """The text of a combined `manifest.py` for `port`.

    `include("$(PORT_DIR)/<default_manifest>")` first, when `port` has one
    (D17) -- `$(PORT_DIR)` is a substitution MicroPython's own
    `make_manifest.py` resolves at manifest-parse time, to the port's own
    directory; it is written here untouched, not shell- or Python-expanded
    (`a7p`'s own workflow escapes it as `\\$(PORT_DIR)` for the same
    reason, one layer of shell earlier than this function operates at).
    Then `include(module_manifest)`, verbatim -- already resolved to
    whatever path form the caller's environment needs (MSYS2's
    `$(pwd)`-relative POSIX-style path on Windows, a native path
    elsewhere); this function does not know or guess which, the same way
    it does not know which shell will eventually run `cat <<EOF` for it.

    Returns "" when `port` has no default manifest and `module_manifest`
    is also empty -- an absent FROZEN_MANIFEST is valid upstream (no
    frozen modules at all), not an error this should raise on.
    """
    lines = []
    default = default_manifest(port)
    if default:
        lines.append(f'include("$(PORT_DIR)/{default}")')
    if module_manifest:
        lines.append(f'include("{module_manifest}")')
    return "\n".join(lines) + ("\n" if lines else "")

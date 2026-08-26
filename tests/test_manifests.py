from cibuildmp.platforms.usermod.manifests import combined_manifest


def test_unix_matches_a7p_workflow_literal():
    # a7p's "Write combined FROZEN_MANIFEST" step, matrix.port == unix:
    #   include("\$(PORT_DIR)/variants/standard/manifest.py")
    #   include("$GITHUB_WORKSPACE/micropython/usermod/manifest.py")
    # ($GITHUB_WORKSPACE already shell-expanded by the time it reaches the
    # heredoc; \$(PORT_DIR) is the one line MicroPython's own
    # make_manifest.py resolves, escaped there to survive that same shell)
    text = combined_manifest(
        "unix", "/home/runner/work/a7p/a7p/micropython/usermod/manifest.py"
    )

    assert text == (
        'include("$(PORT_DIR)/variants/standard/manifest.py")\n'
        'include("/home/runner/work/a7p/a7p/micropython/usermod/manifest.py")\n'
    )


def test_webassembly_matches_a7p_workflow_literal():
    text = combined_manifest("webassembly", "/gh/ws/micropython/usermod/manifest.py")

    assert text == (
        'include("$(PORT_DIR)/variants/pyscript/manifest.py")\n'
        'include("/gh/ws/micropython/usermod/manifest.py")\n'
    )


def test_esp32_matches_a7p_workflow_literal():
    text = combined_manifest("esp32", "/gh/ws/micropython/usermod/manifest.py")

    assert text == (
        'include("$(PORT_DIR)/boards/manifest.py")\n'
        'include("/gh/ws/micropython/usermod/manifest.py")\n'
    )


def test_qemu_has_no_port_default_line():
    # a7p's own qemu step: no "$(PORT_DIR)/..." line at all -- ports/qemu
    # ships no boards/manifest.py.
    text = combined_manifest("qemu", "/gh/ws/micropython/usermod/manifest.py")

    assert text == 'include("/gh/ws/micropython/usermod/manifest.py")\n'
    assert "$(PORT_DIR)" not in text


def test_no_module_manifest_and_no_default_is_empty():
    assert combined_manifest("qemu", "") == ""


def test_no_module_manifest_still_includes_port_default():
    text = combined_manifest("unix", "")

    assert text == 'include("$(PORT_DIR)/variants/standard/manifest.py")\n'

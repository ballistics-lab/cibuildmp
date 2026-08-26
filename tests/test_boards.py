import json

import pytest

from cibuildmp.platforms.usermod.boards import (
    Board,
    BoardDatabaseError,
    Database,
    Port,
    check_board_json,
)

PYBV11_JSON = {
    "deploy": ["../PYBV10/deploy.md"],
    "docs": "",
    "features": [],
    "images": ["PYBv1_1.jpg", "PYBv1_1-C.jpg", "PYBv1_1-E.jpg"],
    "mcu": "stm32f4",
    "product": "Pyboard v1.1",
    "thumbnail": "",
    "url": "https://store.micropython.org/product/PYBv1.1",
    "variants": {
        "DP": "Double-precision float",
        "DP_THREAD": "Double precision float + Threads",
        "NETWORK": "Wiznet 5200 Driver",
        "THREAD": "Threading",
    },
    "vendor": "George Robotics",
}


def _write_board_json(root, port, board, data):
    board_dir = root / "ports" / port / "boards" / board
    board_dir.mkdir(parents=True)
    (board_dir / "board.json").write_text(json.dumps(data))
    return board_dir


def _make_mpy_root(tmp_path):
    root = tmp_path / "micropython"
    (root / "ports").mkdir(parents=True)
    _write_board_json(root, "stm32", "PYBV11", PYBV11_JSON)
    _write_board_json(
        root,
        "rp2",
        "RPI_PICO",
        {
            "mcu": "rp2040",
            "product": "Raspberry Pi Pico",
            "vendor": "Raspberry Pi",
            "images": [],
            "deploy": [],
            "url": "https://example.invalid/pico",
        },
    )
    return root


def _add_variant_only_port(root, name, variants):
    port_dir = root / "ports" / name
    for v in variants:
        (port_dir / "variants" / v).mkdir(parents=True)
    return port_dir


def test_scans_board_json_into_ports_and_boards(tmp_path):
    root = _make_mpy_root(tmp_path)
    db = Database(mpy_root_directory=root)

    # unix/webassembly/windows are always present too (_VARIANT_ONLY_PORTS),
    # even with no ports/<name>/ directory on disk at all -- variant_names
    # just comes back empty, same as upstream.
    assert set(db.boards) == {"PYBV11", "RPI_PICO", "unix", "webassembly", "windows"}
    assert set(db.ports) == {"stm32", "rp2", "unix", "webassembly", "windows"}
    assert db.ports["stm32"].boards["PYBV11"] is db.boards["PYBV11"]


def test_board_fields_and_variant_sorting(tmp_path):
    root = _make_mpy_root(tmp_path)
    db = Database(mpy_root_directory=root)
    board = db.boards["PYBV11"]

    assert board.mcu == "stm32f4"
    assert board.product == "Pyboard v1.1"
    assert board.physical_board is True
    assert [v.name for v in board.variants] == ["DP", "DP_THREAD", "NETWORK", "THREAD"]


def test_find_variant_hit_and_miss(tmp_path):
    root = _make_mpy_root(tmp_path)
    board = Database(mpy_root_directory=root).boards["PYBV11"]

    assert board.find_variant("THREAD").text == "Threading"
    assert board.find_variant("NOT_A_VARIANT") is None


def test_board_directory_and_deploy_filename(tmp_path):
    root = _make_mpy_root(tmp_path)
    board = Database(mpy_root_directory=root).boards["PYBV11"]

    assert board.directory == root / "ports" / "stm32" / "boards" / "PYBV11"
    assert board.deploy_filename == board.directory / "../PYBV10/deploy.md"


def test_port_filter_scopes_the_scan(tmp_path):
    root = _make_mpy_root(tmp_path)
    db = Database(mpy_root_directory=root, port_filter="rp2")

    assert set(db.boards) == {"RPI_PICO"}
    assert set(db.ports) == {"rp2"}


def test_variant_only_ports_have_no_board_json_but_still_appear(tmp_path):
    root = _make_mpy_root(tmp_path)
    _add_variant_only_port(root, "unix", ["standard", "coverage"])
    _add_variant_only_port(root, "webassembly", ["standard", "pyscript"])
    _add_variant_only_port(root, "windows", [])

    db = Database(mpy_root_directory=root)

    unix_board = db.boards["unix"]
    assert unix_board.physical_board is False
    assert sorted(v.name for v in unix_board.variants) == ["coverage", "standard"]
    assert db.boards["windows"].variants == []


def test_zephyr_has_no_board_json_and_is_never_scanned(tmp_path):
    """D22: zephyr selects boards via <board>.conf, not board.json -- the
    scan must find nothing for it rather than error or guess."""
    root = _make_mpy_root(tmp_path)
    zephyr_boards = root / "ports" / "zephyr" / "boards"
    zephyr_boards.mkdir(parents=True)
    (zephyr_boards / "rpi_pico.conf").write_text("CONFIG_SOMETHING=y\n")

    db = Database(mpy_root_directory=root)

    assert "zephyr" not in db.ports
    assert not any(name.startswith("rpi_pico") for name in db.boards)


def test_rejects_non_micropython_root(tmp_path):
    with pytest.raises(BoardDatabaseError, match="top of a MicroPython"):
        Database(mpy_root_directory=tmp_path)


def test_directory_repo_rejects_non_micropython_root(tmp_path):
    root = _make_mpy_root(tmp_path)
    db = Database(mpy_root_directory=root)
    board = db.boards["PYBV11"]

    assert board.port.directory_repo == root

    # A port whose grandparent is not a MicroPython root at all -- e.g. a
    # boards/ tree copied out on its own -- must fail the same check.
    stray = Port(name="stm32", directory=tmp_path / "elsewhere" / "ports" / "stm32")
    with pytest.raises(BoardDatabaseError, match="top of a MicroPython"):
        _ = stray.directory_repo


def test_check_board_json_flags_missing_keys():
    issues = check_board_json({}, "PYBV11", "stm32")

    assert any("mcu" in i for i in issues)
    assert any("product" in i for i in issues)
    assert any("URL" in i for i in issues)


def test_check_board_json_accepts_the_real_example():
    assert check_board_json(PYBV11_JSON, "PYBV11", "stm32") == []


def test_check_board_json_flags_wrong_types():
    bad = dict(PYBV11_JSON, variants=["not", "a", "dict"], images="not-a-list")
    issues = check_board_json(bad, "PYBV11", "stm32")

    assert any("'variants' is not a dictionary" in i for i in issues)
    assert any("'images' is not a list" in i for i in issues)


def test_board_factory_matches_directory_scan(tmp_path):
    """factory() reads a board.json the same way the directory scan does --
    verified against the exact upstream example, not a paraphrase."""
    root = _make_mpy_root(tmp_path)
    board = Board.factory(
        port=Database(mpy_root_directory=root).ports["stm32"],
        filename_json=root / "ports" / "stm32" / "boards" / "PYBV11" / "board.json",
    )

    assert board.name == "PYBV11"
    assert board.images == ["PYBv1_1.jpg", "PYBv1_1-C.jpg", "PYBv1_1-E.jpg"]

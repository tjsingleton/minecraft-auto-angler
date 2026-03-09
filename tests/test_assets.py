from __future__ import annotations

from importlib import resources


def test_cursor_template_is_packaged() -> None:
    path = resources.files("autoangler.assets").joinpath("minecraft_cursor.png")
    assert path.is_file()


def test_rod_template_is_packaged() -> None:
    path = resources.files("autoangler.assets").joinpath("fishing_rod_slot_template.png")
    assert path.is_file()


def test_cod_icon_is_packaged() -> None:
    path = resources.files("autoangler.assets").joinpath("Cod.gif")
    assert path.is_file()

from __future__ import annotations

from importlib import resources


def test_cursor_template_is_packaged() -> None:
    path = resources.files("autoangler.assets").joinpath("minecraft_cursor.png")
    assert path.is_file()

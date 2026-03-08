from __future__ import annotations

from autoangler.minecraft_window import WindowInfo, choose_minecraft_window, window_center


def test_choose_window_prefers_title_hint() -> None:
    windows = [
        WindowInfo(title="Safari", left=0, top=0, width=1000, height=800),
        WindowInfo(title="Minecraft 1.21.4", left=50, top=50, width=1600, height=900),
    ]
    chosen = choose_minecraft_window(windows, title_hint="minecraft")
    assert chosen is not None
    assert chosen.title == "Minecraft 1.21.4"


def test_fallback_chooses_largest_reasonable_window() -> None:
    windows = [
        WindowInfo(title="Launcher", left=0, top=0, width=600, height=400),
        WindowInfo(title="", left=100, top=100, width=1700, height=1000),
    ]
    chosen = choose_minecraft_window(windows, title_hint=None)
    assert chosen is not None
    assert chosen.width == 1700


def test_window_center_uses_window_bounds() -> None:
    window = WindowInfo(title="Minecraft", left=10, top=20, width=1000, height=800)
    assert window_center(window) == (510, 420)


def test_choose_window_accepts_java_owner_without_title() -> None:
    windows = [
        WindowInfo(title="", owner="java", left=50, top=50, width=1600, height=900),
        WindowInfo(title="", owner="Cursor", left=0, top=0, width=1280, height=800),
    ]
    chosen = choose_minecraft_window(windows, title_hint="minecraft")
    assert chosen is not None
    assert chosen.owner == "java"


def test_fallback_ignores_finder_when_java_exists() -> None:
    windows = [
        WindowInfo(title="", owner="Finder", left=0, top=0, width=1512, height=982),
        WindowInfo(title="", owner="java", left=4, top=33, width=854, height=508),
    ]
    chosen = choose_minecraft_window(windows, title_hint=None)
    assert chosen is not None
    assert chosen.owner == "java"


def test_choose_window_prefers_java_over_minecraft_launcher() -> None:
    windows = [
        WindowInfo(
            title="Minecraft Launcher",
            owner="Minecraft Launcher",
            left=552,
            top=30,
            width=1280,
            height=752,
        ),
        WindowInfo(title="", owner="java", left=0, top=30, width=1280, height=705),
    ]
    chosen = choose_minecraft_window(windows, title_hint=None)
    assert chosen is not None
    assert chosen.owner == "java"

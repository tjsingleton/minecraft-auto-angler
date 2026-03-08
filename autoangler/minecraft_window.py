from __future__ import annotations

import os
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class WindowInfo:
    title: str
    left: int
    top: int
    width: int
    height: int
    owner: str = ""

    @property
    def area(self) -> int:
        return self.width * self.height


def choose_minecraft_window(
    windows: list[WindowInfo], title_hint: str | None = None
) -> WindowInfo | None:
    hint = (title_hint or "").strip().lower()
    reasonable = [window for window in windows if _is_reasonable_window(window)]
    if not reasonable:
        return None

    java_windows = [window for window in reasonable if window.owner.lower() == "java"]
    if java_windows:
        return max(java_windows, key=lambda window: window.area)

    if hint:
        hinted = [window for window in reasonable if hint in window.title.lower()]
        if hinted:
            return max(hinted, key=lambda window: window.area)

    preferred_titles = ("minecraft", "lunar client", "curseforge")
    preferred = [
        window
        for window in reasonable
        if any(token in window.title.lower() for token in preferred_titles)
        or window.owner.lower() == "java"
    ]
    if preferred:
        return max(preferred, key=lambda window: window.area)

    return max(reasonable, key=lambda window: window.area)


def list_candidate_windows() -> list[WindowInfo]:
    if sys.platform == "darwin":
        return _list_candidate_windows_quartz()
    return _list_candidate_windows_pyautogui()


def _list_candidate_windows_pyautogui() -> list[WindowInfo]:
    import pyautogui

    try:
        raw_windows = pyautogui.getAllWindows()
    except Exception:
        return []

    windows: list[WindowInfo] = []
    for raw_window in raw_windows:
        try:
            window = WindowInfo(
                title=str(getattr(raw_window, "title", "") or ""),
                owner="",
                left=int(raw_window.left),
                top=int(raw_window.top),
                width=int(raw_window.width),
                height=int(raw_window.height),
            )
        except Exception:
            continue
        if _is_reasonable_window(window):
            windows.append(window)
    return windows


def _list_candidate_windows_quartz() -> list[WindowInfo]:
    try:
        from Quartz import (  # type: ignore[import-not-found]
            CGWindowListCopyWindowInfo,
            kCGNullWindowID,
            kCGWindowListOptionOnScreenOnly,
        )
    except Exception:
        return []

    windows: list[WindowInfo] = []
    for raw_window in CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID):
        bounds = raw_window.get("kCGWindowBounds")
        if not bounds:
            continue
        try:
            window = WindowInfo(
                title=str(raw_window.get("kCGWindowName") or ""),
                owner=str(raw_window.get("kCGWindowOwnerName") or ""),
                left=int(bounds.get("X", 0)),
                top=int(bounds.get("Y", 0)),
                width=int(bounds.get("Width", 0)),
                height=int(bounds.get("Height", 0)),
            )
        except Exception:
            continue
        if _is_reasonable_window(window):
            windows.append(window)
    return windows


def selected_minecraft_window() -> WindowInfo | None:
    title_hint = os.environ.get("AUTOANGLER_MINECRAFT_WINDOW_HINT")
    return choose_minecraft_window(list_candidate_windows(), title_hint=title_hint)


def window_center(window: WindowInfo) -> tuple[int, int]:
    return (window.left + window.width // 2, window.top + window.height // 2)


def _is_reasonable_window(window: WindowInfo) -> bool:
    if window.width < 700 or window.height < 450:
        return False

    blocked_owners = {
        "finder",
        "window server",
        "dock",
        "control center",
        "notification center",
        "codex",
        "cursor",
        "minecraft launcher",
    }
    return window.owner.lower() not in blocked_owners

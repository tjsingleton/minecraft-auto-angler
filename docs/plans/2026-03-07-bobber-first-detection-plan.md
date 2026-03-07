# Bobber-First Detection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace cursor-first targeting with a bobber-first detection pipeline that anchors on the Minecraft window, captures a stable fishing ROI, and detects bites from bobber motion and disappearance instead of screen-center guesses.

**Architecture:** Keep the local Tk GUI as the operator console. Add a Minecraft window locator, define a fishing region inside that window, and run a dedicated bobber detector over that region. Use a short calibration flow to lock the bobber ROI after the first cast, then use temporal signals between frames to decide when to reel. Do not add a Java mod in this phase; reserve that as a second-stage migration path if screen-based detection remains unreliable.

**Tech Stack:** Python 3.12, Tkinter/ttk, `pyautogui`, `PIL.ImageGrab`, `opencv-python`, `numpy`, `pytest`, `ruff`.

## Problem Statement

The current system fails for two reasons:

1. Cursor matching is unreliable on the user’s machine. It matches UI elements outside the Minecraft window and often lands off-screen.
2. When cursor matching fails, the center fallback captures arbitrary UI pixels. The black-pixel threshold then treats unrelated dark pixels as a bite, so the app reels on a timer instead of on fishing state.

The log confirms this failure mode:

- Best cursor match is near `x=5039`, which is not the Minecraft window.
- The fallback lands at screen center.
- The app immediately enters a repeating cast/reel cycle.

The image preview confirms the same issue: the crop is not over Minecraft water or a bobber.

## Public Interface Changes

- Add a calibration-driven workflow in the GUI:
  - `Locate Minecraft`
  - `Calibrate Bobber`
  - `Start Fishing`
- Add optional environment variables:
  - `AUTOANGLER_MINECRAFT_WINDOW_HINT` to match a window title substring such as `Minecraft`, `CurseForge`, or `Lunar Client`
  - `AUTOANGLER_CAPTURE_DEBUG_DIR` to save ROI snapshots during calibration and bite detection
  - `AUTOANGLER_BOBBER_MOTION_THRESHOLD`
  - `AUTOANGLER_BOBBER_DARKNESS_THRESHOLD`
- Preserve current `F12`, `ESC`, and `F10` hotkeys.

## Detection Strategy

### Recommended Approach

Use a three-stage detector:

1. Locate the Minecraft window and use only that window’s bounds.
2. After the initial cast, search a constrained region below the crosshair for the bobber candidate.
3. Track that bobber candidate frame to frame. Reel only when the tracked blob disappears, drops sharply, or its local darkness profile changes beyond a calibrated threshold.

This is the correct first step because it fixes the worst assumption in the current system: that the cursor must be found before anything else can work. In practice, the Minecraft window is easier to find than the exact cursor pixels, and the bobber is the actual target.

### Rejected Alternatives

1. Continue improving cursor matching.
   - This still depends on UI scale, cursor pack, Retina scaling, and overlays.
   - It may help, but it does not address the core failure mode.

2. Switch immediately to a Java client mod.
   - This is the most robust long-term path.
   - It is a larger rewrite, loader-specific, and should follow only if the screen-based redesign still fails.

## Implementation Tasks

### Task 1: Add Minecraft window detection

**Files:**
- Create: `autoangler/minecraft_window.py`
- Modify: `autoangler/gui_tk.py`
- Test: `tests/test_minecraft_window.py`

**Step 1: Write the failing tests**

```python
def test_choose_window_prefers_title_hint():
    windows = [
        WindowInfo(title="Safari", left=0, top=0, width=1000, height=800),
        WindowInfo(title="Minecraft 1.21.4", left=50, top=50, width=1600, height=900),
    ]
    chosen = choose_minecraft_window(windows, title_hint="minecraft")
    assert chosen.title == "Minecraft 1.21.4"
```

```python
def test_fallback_chooses_largest_reasonable_window():
    windows = [
        WindowInfo(title="Launcher", left=0, top=0, width=600, height=400),
        WindowInfo(title="", left=100, top=100, width=1700, height=1000),
    ]
    chosen = choose_minecraft_window(windows, title_hint=None)
    assert chosen.width == 1700
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_minecraft_window.py -v`
Expected: FAIL with missing module or missing functions.

**Step 3: Write minimal implementation**

Create a `WindowInfo` dataclass and helpers:

- `list_candidate_windows() -> list[WindowInfo]`
- `choose_minecraft_window(...) -> WindowInfo | None`
- `window_center(window) -> tuple[int, int]`
- `window_roi(window) -> tuple[int, int, int, int]`

Use `pyautogui.getAllWindows()` first. Match title hint case-insensitively. If nothing matches, pick the largest visible window whose size exceeds a minimum threshold such as `800x600`.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_minecraft_window.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add autoangler/minecraft_window.py tests/test_minecraft_window.py autoangler/gui_tk.py
git commit -m "feat: add minecraft window detection"
```

### Task 2: Add ROI capture anchored to the Minecraft window

**Files:**
- Modify: `autoangler/cursor_camera.py`
- Modify: `autoangler/gui_tk.py`
- Create: `autoangler/roi.py`
- Test: `tests/test_roi.py`

**Step 1: Write the failing tests**

```python
def test_default_fishing_roi_uses_upper_middle_of_window():
    window = WindowInfo(title="Minecraft", left=100, top=100, width=1600, height=900)
    roi = default_fishing_roi(window)
    assert roi == (500, 250, 1300, 700)
```

```python
def test_clamp_roi_to_window_bounds():
    window = WindowInfo(title="Minecraft", left=0, top=0, width=1000, height=700)
    roi = clamp_roi_to_window((900, 650, 1200, 900), window)
    assert roi == (900, 650, 1000, 700)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_roi.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Define a stable ROI inside the Minecraft window:

- Ignore window chrome and the lower hotbar area.
- Default ROI should cover the water area where the bobber is likely to appear.
- Add a dedicated method to capture the full ROI, not a `30x30` patch.

Update the GUI preview to show:

- Left: raw ROI image
- Right: thresholded or annotated ROI image

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_roi.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add autoangler/cursor_camera.py autoangler/roi.py autoangler/gui_tk.py tests/test_roi.py
git commit -m "feat: anchor capture to minecraft window roi"
```

### Task 3: Implement bobber candidate detection after cast

**Files:**
- Create: `autoangler/bobber_detector.py`
- Modify: `autoangler/gui_tk.py`
- Test: `tests/test_bobber_detector.py`
- Fixture: `tests/fixtures/bobber/`

**Step 1: Write the failing tests**

Add fixture images that represent:

- Water with no bobber
- Water with visible bobber
- Water with distracting UI or shoreline pixels

```python
def test_find_bobber_returns_candidate_center():
    detector = BobberDetector()
    frame = load_fixture("water_with_bobber.png")
    result = detector.find_bobber(frame)
    assert result is not None
    assert result.center == (expected_x, expected_y)
```

```python
def test_find_bobber_rejects_large_dark_regions():
    detector = BobberDetector()
    frame = load_fixture("water_with_ui_dark_region.png")
    result = detector.find_bobber(frame)
    assert result is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_bobber_detector.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Implement `BobberDetector.find_bobber(frame)` with this pipeline:

1. Convert ROI to grayscale.
2. Apply adaptive threshold or low fixed threshold tuned to dark bobber pixels.
3. Find connected components or contours.
4. Reject blobs that are:
   - too large
   - too small
   - too close to ROI edges
   - too rectangular or too line-like
5. Score remaining blobs by:
   - compactness
   - darkness
   - distance from ROI center
   - consistency with prior bobber location if available

Return a `BobberCandidate` dataclass with center, bbox, area, score.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_bobber_detector.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add autoangler/bobber_detector.py autoangler/gui_tk.py tests/test_bobber_detector.py tests/fixtures/bobber
git commit -m "feat: detect bobber candidate from fishing roi"
```

### Task 4: Add bobber tracking and bite detection

**Files:**
- Create: `autoangler/bite_detector.py`
- Modify: `autoangler/gui_tk.py`
- Test: `tests/test_bite_detector.py`

**Step 1: Write the failing tests**

```python
def test_bite_detector_fires_when_bobber_drops_or_disappears():
    detector = BiteDetector()
    frames = [
        sample_track(y=100, visible=True),
        sample_track(y=101, visible=True),
        sample_track(y=120, visible=False),
    ]
    events = [detector.update(frame) for frame in frames]
    assert events[-1].bite is True
```

```python
def test_bite_detector_ignores_small_jitter():
    detector = BiteDetector()
    frames = [
        sample_track(y=100, visible=True),
        sample_track(y=102, visible=True),
        sample_track(y=101, visible=True),
    ]
    events = [detector.update(frame) for frame in frames]
    assert not any(event.bite for event in events)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_bite_detector.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Implement a small state machine:

- `IDLE`
- `CASTING`
- `SEARCHING_FOR_BOBBER`
- `TRACKING_BOBBER`
- `BITE_DETECTED`

During `TRACKING_BOBBER`, detect a bite only when one of these holds:

- bobber disappears for `N` consecutive frames
- bobber center drops by more than `motion_threshold`
- local patch darkness changes by more than `darkness_threshold`

Require at least two consecutive confirming frames to avoid single-frame noise.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_bite_detector.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add autoangler/bite_detector.py autoangler/gui_tk.py tests/test_bite_detector.py
git commit -m "feat: track bobber and detect bites"
```

### Task 5: Add calibration and debug capture workflow in the GUI

**Files:**
- Modify: `autoangler/gui_tk.py`
- Modify: `autoangler/image_viewer_tk.py`
- Create: `autoangler/debug_capture.py`
- Test: `tests/test_debug_capture.py`

**Step 1: Write the failing tests**

```python
def test_debug_capture_path_contains_timestamp_and_label():
    path = build_debug_capture_path("bobber-search")
    assert "bobber-search" in str(path)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_debug_capture.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

GUI changes:

- Add `Locate Minecraft` button.
- Add `Calibrate Bobber` button.
- Add a status line that reports:
  - chosen window title
  - ROI size
  - bobber candidate score
  - bite detector state
- Draw overlays in the right preview:
  - ROI border
  - bobber bbox
  - candidate center
  - tracking trail

Debug capture:

- When `AUTOANGLER_CAPTURE_DEBUG_DIR` is set, save:
  - raw ROI frames
  - annotated ROI frames
  - calibration snapshots
  - false bite frames

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_debug_capture.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add autoangler/gui_tk.py autoangler/image_viewer_tk.py autoangler/debug_capture.py tests/test_debug_capture.py
git commit -m "feat: add calibration and debug capture workflow"
```

### Task 6: Remove cursor-first gating from fishing loop

**Files:**
- Modify: `autoangler/gui_tk.py`
- Modify: `README.md`
- Test: `tests/test_capabilities_integration.py`

**Step 1: Write the failing test**

```python
def test_start_transitions_to_bobber_search_without_cursor():
    app = build_app_for_test()
    app.start()
    assert app.state == FishingState.SEARCHING_FOR_BOBBER
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_capabilities_integration.py -v`
Expected: FAIL or missing state.

**Step 3: Write minimal implementation**

Change the control flow:

- `Start Fishing` should:
  - locate Minecraft window
  - cast
  - enter bobber search state
- Remove any requirement that a cursor match must exist before capture starts.
- Keep center fallback only as a debug tool, not as live detection logic.

Update README to explain:

- operator workflow
- permissions required
- debug env vars
- limitation: screen-based fishing still depends on stable in-game visuals

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_capabilities_integration.py -v`
Expected: PASS for non-OS-mocked logic and skip OS-bound checks as appropriate.

**Step 5: Commit**

```bash
git add autoangler/gui_tk.py README.md tests/test_capabilities_integration.py
git commit -m "refactor: make fishing loop bobber-first"
```

### Task 7: Capture real-world fixtures from CurseForge and Lunar Client sessions

**Files:**
- Create: `tests/fixtures/bobber/curseforge/`
- Create: `tests/fixtures/bobber/lunar/`
- Modify: `tests/test_bobber_detector.py`
- Modify: `tests/test_bite_detector.py`

**Step 1: Collect fixtures**

Capture at least these sets from each client:

- windowed daytime water
- nighttime water
- rain
- shoreline/background clutter
- successful bite sequence across 5 to 10 frames

**Step 2: Add regression tests**

```python
def test_detector_handles_real_curseforge_fixture():
    detector = BobberDetector()
    frame = load_fixture("curseforge/daytime_visible_bobber.png")
    assert detector.find_bobber(frame) is not None
```

```python
def test_bite_detector_handles_real_lunar_fixture_sequence():
    detector = BiteDetector()
    frames = load_sequence("lunar/bite_sequence")
    assert any(event.bite for event in map(detector.update, frames))
```

**Step 3: Run tests**

Run: `uv run pytest tests/test_bobber_detector.py tests/test_bite_detector.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add tests/fixtures/bobber tests/test_bobber_detector.py tests/test_bite_detector.py
git commit -m "test: add real-world bobber fixtures"
```

### Task 8: Define the next-stage Java client path without implementing it

**Files:**
- Create: `docs/plans/2026-03-07-java-client-mod-followup.md`

**Step 1: Write follow-up design**

Document a second-stage path for Java Edition:

- preferred loader: Fabric client mod
- events/signals:
  - fishing hook entity state
  - bobber velocity/position
  - splash particles or sound
  - inventory state
- local companion process interface:
  - localhost HTTP or WebSocket
  - read-only telemetry to GUI first
  - no remote server component

Do not implement this in the current plan. Use it only if the screen-based redesign still proves fragile.

**Step 2: Commit**

```bash
git add docs/plans/2026-03-07-java-client-mod-followup.md
git commit -m "docs: outline java client mod follow-up"
```

## Acceptance Criteria

The implementation is complete only when all of the following are true:

- The preview consistently shows a crop inside the Minecraft window, not arbitrary desktop pixels.
- Starting fishing does not depend on cursor-template success.
- The app does not enter a timed cast/reel loop on unrelated dark UI elements.
- Bobber detection is test-backed with both synthetic and real fixture images.
- Bite detection uses temporal state, not a single-frame black-pixel count.
- The GUI shows enough state to debug failures without reading raw logs.
- The operator can use the same workflow on both CurseForge and Lunar Client windowed sessions.

## Test Matrix

- Unit tests:
  - window selection
  - ROI math
  - contour filtering
  - bite state transitions
- Fixture tests:
  - visible bobber
  - missing bobber
  - false positives from UI text or dark shoreline
  - rain and nighttime
- Integration tests:
  - screenshot capability
  - Tk window capability
  - debug snapshot writing

## Assumptions

- Minecraft runs in a window or bordered-fullscreen configuration that exposes a detectable window rectangle to the OS.
- The local GUI remains useful and should stay in the product.
- The user wants to defer the Java mod rewrite until the screen-based approach has a fair, instrumented attempt.
- Public-server policy and anti-cheat concerns are out of scope for this implementation plan.

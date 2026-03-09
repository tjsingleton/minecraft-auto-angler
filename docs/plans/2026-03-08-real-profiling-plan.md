# Real Profiling Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Add real profiling so AutoAngler can identify its live hot path precisely, log it per session, and guide the next round of performance work with evidence instead of guesswork.

**Architecture:** Keep the existing lightweight status/profiling line, but replace the current coarse `tick/cap/rec` timing with stage-level timings collected inside the Tk loop. Store those timings in a small in-memory ring buffer for the GUI and append them to a dedicated per-session profiling CSV so sessions can be analyzed offline. Add a tiny offline summary tool that reads a session profile CSV and reports where time is actually going.

**Tech Stack:** Python 3.12, `time.monotonic`, `csv`, `dataclasses`, `numpy`, `pytest`, `ruff`.

## Current Bottleneck

The current profiling already points to the main bottleneck:

- Session `20260308-224052` logged `avg tick = 405.4ms`
- The same session logged `avg capture = 386.0ms`
- Recording averaged `19.1ms`
- Effective FPS averaged `2.1`

So the primary bottleneck is the capture path, not the watcher logic:

- `autoangler/gui_tk.py` calls `_update_image()` once per tick
- `_update_image()` calls `_capture_window_image()`
- `_capture_window_image()` calls `CursorCamera.capture_bbox()`
- `CursorCamera.capture_bbox()` calls `PIL.ImageGrab.grab()` on the full Minecraft window

That means the current hot path is dominated by:

1. full-window `ImageGrab.grab()`
2. grayscale conversion / frame preparation
3. downstream full-frame copies for overlays and recording

The plan below is for measuring those stages directly.

### Task 1: Add profiling path builders and profile log location

**Files:**
- Modify: `/Users/tjsingleton/Projects/minecraft-auto-angler/autoangler/logging_utils.py`
- Test: `/Users/tjsingleton/Projects/minecraft-auto-angler/tests/test_logging_and_ui.py`

**Step 1: Write the failing test**

Add a test that expects a profile CSV path builder next to the session log:

```python
def test_build_session_profile_path_uses_session_directory(tmp_path: Path) -> None:
    log_path = tmp_path / "sessions" / "20260308-010000" / "20260308-010000.log"
    path = build_session_profile_path(log_path)
    assert path == tmp_path / "sessions" / "20260308-010000" / "20260308-010000-profile.csv"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_logging_and_ui.py::test_build_session_profile_path_uses_session_directory`

Expected: FAIL because `build_session_profile_path` does not exist yet.

**Step 3: Write minimal implementation**

Add:

```python
def build_session_profile_path(log_path: Path) -> Path:
    return log_path.with_name(f"{log_path.stem}-profile.csv")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest -q tests/test_logging_and_ui.py::test_build_session_profile_path_uses_session_directory`

Expected: PASS

**Step 5: Commit**

```bash
git add autoangler/logging_utils.py tests/test_logging_and_ui.py
git commit -m "feat: add session profile path builder"
```

### Task 2: Add a structured per-tick profiling model

**Files:**
- Create: `/Users/tjsingleton/Projects/minecraft-auto-angler/autoangler/profiling.py`
- Test: `/Users/tjsingleton/Projects/minecraft-auto-angler/tests/test_profiling.py`

**Step 1: Write the failing test**

Add a small test around a `TickProfile` / `RollingProfiler` model:

```python
def test_rolling_profiler_computes_stage_averages() -> None:
    profiler = RollingProfiler(capacity=3)
    profiler.add(TickProfile(total_ms=100, capture_ms=70, detect_ms=10, preview_ms=15, record_ms=5))
    profiler.add(TickProfile(total_ms=80, capture_ms=50, detect_ms=15, preview_ms=10, record_ms=5))
    summary = profiler.summary()
    assert summary.avg_total_ms == 90
    assert summary.avg_capture_ms == 60
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_profiling.py::test_rolling_profiler_computes_stage_averages`

Expected: FAIL because the module does not exist.

**Step 3: Write minimal implementation**

Create:

```python
@dataclass(frozen=True)
class TickProfile:
    total_ms: float
    capture_ms: float
    detect_ms: float
    preview_ms: float
    record_ms: float

class RollingProfiler:
    ...
```

Include only the fields the GUI will actually show.

**Step 4: Run test to verify it passes**

Run: `uv run pytest -q tests/test_profiling.py`

Expected: PASS

**Step 5: Commit**

```bash
git add autoangler/profiling.py tests/test_profiling.py
git commit -m "feat: add rolling tick profiler"
```

### Task 3: Instrument the Tk loop by stage

**Files:**
- Modify: `/Users/tjsingleton/Projects/minecraft-auto-angler/autoangler/gui_tk.py`
- Test: `/Users/tjsingleton/Projects/minecraft-auto-angler/tests/test_logging_and_ui.py`

**Step 1: Write the failing test**

Add a test that verifies the debug text includes the new stage timings:

```python
def test_debug_details_text_includes_stage_timings() -> None:
    app = AutoFishTkApp()
    app._last_detect_duration_ms = 12.0
    app._last_preview_duration_ms = 8.5
    text = app._debug_details_text()
    assert "detect:" in text
    assert "preview:" in text
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_logging_and_ui.py::test_debug_details_text_includes_stage_timings`

Expected: FAIL because those fields are not present.

**Step 3: Write minimal implementation**

Split `_tick()` timing into these stages:

- `capture_ms` — `_capture_window_image()`
- `detect_ms` — ROI crop + `find_line()` + `_line_watcher.observe()`
- `preview_ms` — `_build_tracking_preview()` + `_build_debug_composite()` + `self._viewer.update(...)`
- `record_ms` — `_maybe_record_frame()` + trace append

Keep existing `total_ms` and `fps`.

**Step 4: Run test to verify it passes**

Run: `uv run pytest -q tests/test_logging_and_ui.py::test_debug_details_text_includes_stage_timings`

Expected: PASS

**Step 5: Commit**

```bash
git add autoangler/gui_tk.py tests/test_logging_and_ui.py
git commit -m "feat: add stage-level tick profiling"
```

### Task 4: Write a per-session profile CSV

**Files:**
- Modify: `/Users/tjsingleton/Projects/minecraft-auto-angler/autoangler/gui_tk.py`
- Modify: `/Users/tjsingleton/Projects/minecraft-auto-angler/autoangler/logging_utils.py`
- Test: `/Users/tjsingleton/Projects/minecraft-auto-angler/tests/test_recording.py`

**Step 1: Write the failing test**

Add a test that appends one profile row:

```python
def test_append_profile_row_writes_stage_timings(tmp_path: Path, monkeypatch) -> None:
    app = AutoFishTkApp()
    monkeypatch.setenv("AUTOANGLER_SESSION_LOG", str(tmp_path / "sessions" / "s" / "s.log"))
    path = app._append_profile_row(
        now=1.0,
        total_ms=100.0,
        capture_ms=70.0,
        detect_ms=10.0,
        preview_ms=15.0,
        record_ms=5.0,
    )
    assert path.read_text().splitlines()[1].endswith(",100.0,70.0,10.0,15.0,5.0")
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_recording.py::test_append_profile_row_writes_stage_timings`

Expected: FAIL because the helper does not exist.

**Step 3: Write minimal implementation**

Append a profile CSV row with:

- `time_s`
- `is_fishing`
- `is_line_out`
- `total_ms`
- `capture_ms`
- `detect_ms`
- `preview_ms`
- `record_ms`
- `line_pixels`
- `trigger_pixels`

Only write rows while preview capture is active.

**Step 4: Run test to verify it passes**

Run: `uv run pytest -q tests/test_recording.py::test_append_profile_row_writes_stage_timings`

Expected: PASS

**Step 5: Commit**

```bash
git add autoangler/gui_tk.py autoangler/logging_utils.py tests/test_recording.py
git commit -m "feat: write per-session profile csv"
```

### Task 5: Add a session profile summary CLI

**Files:**
- Create: `/Users/tjsingleton/Projects/minecraft-auto-angler/autoangler/profile_session.py`
- Test: `/Users/tjsingleton/Projects/minecraft-auto-angler/tests/test_profile_session.py`
- Modify: `/Users/tjsingleton/Projects/minecraft-auto-angler/README.md`

**Step 1: Write the failing test**

Add a test for a simple summary:

```python
def test_summarize_profile_reports_capture_as_top_stage(tmp_path: Path) -> None:
    profile_csv = tmp_path / "profile.csv"
    profile_csv.write_text(
        "time_s,is_fishing,is_line_out,total_ms,capture_ms,detect_ms,preview_ms,record_ms,line_pixels,trigger_pixels\\n"
        "1,1,1,400,350,20,20,10,10,5\\n"
    )
    summary = summarize_profile(profile_csv)
    assert summary["top_stage"] == "capture"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_profile_session.py::test_summarize_profile_reports_capture_as_top_stage`

Expected: FAIL because the module does not exist.

**Step 3: Write minimal implementation**

Support:

```bash
uv run python -m autoangler.profile_session /path/to/session-profile.csv
```

Print:

- avg FPS
- avg total ms
- avg capture/detect/preview/record ms
- percent of total spent in each stage
- top stage by average time

**Step 4: Run test to verify it passes**

Run: `uv run pytest -q tests/test_profile_session.py`

Expected: PASS

**Step 5: Commit**

```bash
git add autoangler/profile_session.py tests/test_profile_session.py README.md
git commit -m "feat: add session profile summary cli"
```

### Task 6: Add one-command flame graph capture

**Files:**
- Modify: `/Users/tjsingleton/Projects/minecraft-auto-angler/pyproject.toml`
- Create: `/Users/tjsingleton/Projects/minecraft-auto-angler/scripts/profile_flamegraph.sh`
- Modify: `/Users/tjsingleton/Projects/minecraft-auto-angler/README.md`

**Step 1: Write the failing test**

Add a small test that expects a profiling helper script:

```python
def test_profile_flamegraph_script_exists() -> None:
    assert Path("scripts/profile_flamegraph.sh").exists()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_profile_session.py::test_profile_flamegraph_script_exists`

Expected: FAIL because the helper does not exist yet.

**Step 3: Write minimal implementation**

Use a sampling profiler, not `cProfile`. Recommended command:

```bash
py-spy record \
  --output "$SESSION_DIR/$SESSION-flame.svg" \
  --format flamegraph \
  -- python -m autoangler
```

The wrapper script should:

- create a fresh session directory
- launch AutoAngler under `py-spy`
- save `...-flame.svg` beside the other session artifacts

Add `py-spy` as a dev dependency only if you want it managed by `uv`; otherwise document it as an external prerequisite.

**Step 4: Run test to verify it passes**

Run: `uv run pytest -q tests/test_profile_session.py::test_profile_flamegraph_script_exists`

Expected: PASS

**Step 5: Commit**

```bash
git add pyproject.toml scripts/profile_flamegraph.sh README.md tests/test_profile_session.py
git commit -m "feat: add flame graph profiling helper"
```

### Task 7: Tighten the live UI to show the real bottleneck

**Files:**
- Modify: `/Users/tjsingleton/Projects/minecraft-auto-angler/autoangler/gui_tk.py`
- Test: `/Users/tjsingleton/Projects/minecraft-auto-angler/tests/test_logging_and_ui.py`

**Step 1: Write the failing test**

Add a test that expects a compact “top stage” display:

```python
def test_debug_details_text_reports_top_stage() -> None:
    app = AutoFishTkApp()
    app._last_capture_duration_ms = 70.0
    app._last_detect_duration_ms = 10.0
    app._last_preview_duration_ms = 5.0
    app._last_record_duration_ms = 4.0
    assert "top:capture" in app._debug_details_text()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_logging_and_ui.py::test_debug_details_text_reports_top_stage`

Expected: FAIL

**Step 3: Write minimal implementation**

Add one compact line in the debug panel and periodic profile log:

- `top:capture 70.0ms (78%)`

This matters more than adding more raw counters.

**Step 4: Run test to verify it passes**

Run: `uv run pytest -q tests/test_logging_and_ui.py::test_debug_details_text_reports_top_stage`

Expected: PASS

**Step 5: Commit**

```bash
git add autoangler/gui_tk.py tests/test_logging_and_ui.py
git commit -m "feat: surface top profiling stage in ui"
```

## End-to-End Verification

Run:

```bash
uv run pytest -q
uv run ruff check .
AUTOANGLER_LOG_LEVEL=INFO uv run python -m autoangler
```

Expected live behavior:

- The debug panel shows `fps`, `total`, `capture`, `detect`, `preview`, `record`, and `top stage`
- Each session folder contains:
  - `<session>.log`
  - `<session>-trace.csv`
  - `<session>-profile.csv`
  - optional `<session>-flame.svg`
  - any captures/videos for that session
- `uv run python -m autoangler.profile_session <session-profile.csv>` reports the dominant stage

## Acceptance Criteria

- Profiling answers “where is the time going?” at stage granularity, not just `cap/rec`
- Session artifacts stay grouped under one directory
- The next optimization decision can be made from profile evidence alone
- The system can confirm or refute whether `ImageGrab.grab()` is still the dominant cost on real sessions

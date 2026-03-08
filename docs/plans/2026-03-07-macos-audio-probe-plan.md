# macOS Audio Probe Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a macOS-only script that captures Minecraft app audio and reports likely fishing splash events.

**Architecture:** Keep the capture boundary in a small Swift helper that uses ScreenCaptureKit to target Minecraft application audio. Keep detection, process management, and CLI behavior in Python so the existing repo can test the logic without requiring live macOS capture during unit tests.

**Tech Stack:** Python 3.10, pytest, Swift 6, ScreenCaptureKit, AVFoundation, JSON lines over stdout

### Task 1: Audio detector primitives

**Files:**
- Create: `autoangler/audio_probe.py`
- Create: `tests/test_audio_probe.py`

**Step 1: Write the failing test**

Add tests for:
- parsing a JSONL stats line from the Swift helper
- triggering a bite candidate only after an onset spike above a rolling baseline
- suppressing duplicate triggers during a cooldown window

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audio_probe.py -v`
Expected: FAIL with import errors because `autoangler.audio_probe` does not exist yet.

**Step 3: Write minimal implementation**

Add:
- a dataclass for helper audio stats
- a parser from one JSON line into that dataclass
- a small detector that tracks baseline RMS/peak and emits a splash candidate on a strong onset

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_audio_probe.py -v`
Expected: PASS

### Task 2: Helper process wiring

**Files:**
- Modify: `autoangler/audio_probe.py`
- Create: `autoangler/macos_minecraft_audio_capture.swift`
- Modify: `tests/test_audio_probe.py`

**Step 1: Write the failing test**

Add tests for:
- building the Swift helper command
- parsing helper stdout into detector input
- surfacing malformed helper lines without crashing the probe loop

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audio_probe.py -v`
Expected: FAIL because helper process support is missing.

**Step 3: Write minimal implementation**

Add:
- a Python runner that launches `swift <helper>.swift`
- a Swift helper that finds the Minecraft app by bundle/title heuristics, enables `capturesAudio`, and emits JSON lines with RMS/peak/timestamp values

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_audio_probe.py -v`
Expected: PASS

### Task 3: CLI and docs

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md`

**Step 1: Write the failing test**

If needed, add a small CLI test for argument parsing or dry-run command generation.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audio_probe.py -v`

**Step 3: Write minimal implementation**

Expose a command entry such as `uv run python -m autoangler.audio_probe` and document the macOS permissions/limitations.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_audio_probe.py -v`
Expected: PASS

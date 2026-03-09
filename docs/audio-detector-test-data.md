# Audio Detector Test Data Plan

## Goal

Build a small, repeatable dataset for the audio splash detector so we can measure true positives, false positives, and near misses against real captured helper output.

## Layout

Store future samples under `tests/fixtures/audio_detector/` with three label buckets:

- `positive/`: real bite splashes that should trigger
- `negative/`: ambient or unrelated audio that should not trigger
- `near_miss/`: splash-like sounds such as casting, reeling, item pickup, rain spikes, or other effects that should not trigger

## Manifest Schema

Track every sample in `tests/fixtures/audio_detector/manifest.json` with:

- `path`: relative path to the captured helper-output file or paired artifact
- `label`: one of `positive`, `negative`, or `near_miss`
- `expected_trigger_s`: expected trigger timestamp in seconds, or `null` for clips that should not trigger
- `notes`: short human label describing the scene, server/plugin context, and any known confounders

## Collection Guidance

- Capture at least 20 `positive` samples from confirmed bites.
- Capture at least 20 `negative` samples with ordinary ambient gameplay.
- Capture at least 10 `near_miss` samples that sound splash-like but should stay below the trigger threshold.
- When possible, pair each audio sample with the matching session trace/profile so audio hints can be compared to vision-triggered events.

from __future__ import annotations

import json
from pathlib import Path


def test_audio_detector_test_data_plan_exists() -> None:
    assert Path("docs/audio-detector-test-data.md").exists()


def test_audio_detector_fixture_manifest_scaffold_exists() -> None:
    manifest_path = Path("tests/fixtures/audio_detector/manifest.json")
    assert manifest_path.exists()

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert payload["labels"] == ["positive", "negative", "near_miss"]
    assert payload["schema"]["required"] == ["path", "label", "expected_trigger_s", "notes"]

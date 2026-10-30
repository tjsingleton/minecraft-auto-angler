"""Keep default tests independent of the operator's saved sessions and settings."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_app_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    test_home = tmp_path / "home"
    test_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: test_home))
    monkeypatch.delenv("AUTOANGLER_SESSION_LOG", raising=False)

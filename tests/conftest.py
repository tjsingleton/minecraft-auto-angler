"""Keep default tests independent of the operator's saved sessions and settings."""

from pathlib import Path

import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call":
        item.call_report = report


@pytest.fixture(autouse=True)
def isolated_app_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    test_home = tmp_path / "home"
    test_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: test_home))
    monkeypatch.delenv("AUTOANGLER_SESSION_LOG", raising=False)


@pytest.fixture
def replay(tmp_path, monkeypatch, request):
    from tests.replay_support import Replay

    driver = Replay(monkeypatch, tmp_path / "replay", config=getattr(request, "param", None))
    try:
        yield driver
    finally:
        try:
            driver.close()
        finally:
            driver.save_evidence()
            report = getattr(request.node, "call_report", None)
            if report is not None and report.failed:
                (driver.directory / "assertion-failure.txt").write_text(report.longreprtext)

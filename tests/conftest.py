import dataclasses
import datetime
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spotdivoom import stats  # noqa: E402
from spotdivoom.config import settings  # noqa: E402
from spotdivoom.weather import HourForecast, WeatherInfo  # noqa: E402


@pytest.fixture(autouse=True)
def restore_settings():
    """Settings is a process-wide singleton; put it back after each test."""
    saved = {f.name: getattr(settings, f.name) for f in dataclasses.fields(settings)}
    yield settings
    for name, value in saved.items():
        setattr(settings, name, value)


@pytest.fixture(autouse=True)
def isolated_play_log(tmp_path, monkeypatch):
    """Never write to the real listening_log.jsonl."""
    monkeypatch.setattr(stats, "LOG_FILE", tmp_path / "listening_log.jsonl")
    stats._last_logged.update(track_id=None, time=0.0)
    return tmp_path / "listening_log.jsonl"


@pytest.fixture
def weather():
    now = datetime.datetime(2026, 11, 15, 10, 0)
    return WeatherInfo(
        temperature=66,
        weather_code=2,
        is_day=True,
        unit="°F",
        city="Test",
        hourly=[HourForecast(now + datetime.timedelta(hours=i), 60 + i, 2, True) for i in range(13)],
        sunrise=now.replace(hour=6, minute=42),
        sunset=now.replace(hour=17, minute=1),
    )

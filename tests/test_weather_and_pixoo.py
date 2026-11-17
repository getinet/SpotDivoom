from spotdivoom import pixoo as pixoo_module
from spotdivoom import weather as weather_module
from spotdivoom.pixoo import PixooClient
from spotdivoom.weather import WeatherService


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_unit_change_refetches_immediately(monkeypatch):
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        celsius = "celsius" in url
        return FakeResponse({
            "current": {"temperature_2m": 19 if celsius else 66, "weather_code": 0, "is_day": 1},
            "hourly": {"time": ["2026-11-15T11:00"], "temperature_2m": [20], "weather_code": [1], "is_day": [1]},
            "daily": {"sunrise": ["2026-11-15T06:42"], "sunset": ["2026-11-15T17:01"]},
        })

    monkeypatch.setattr(weather_module.requests, "get", fake_get)
    ws = WeatherService(lat=1.0, lon=2.0, unit="F")
    assert ws.get_weather().temperature == 66
    assert ws.get_weather().temperature == 66 and len(calls) == 1, "cached within the TTL"

    w = ws.get_weather(unit="C")
    assert w.temperature == 19 and w.unit == "°C"
    assert len(calls) == 2, "changing the unit must not wait for the cache to expire"
    assert w.hourly[0].temperature == 20 and w.sunrise.hour == 6


def test_status_is_cached_between_dashboard_polls(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append(json["Command"])
        return FakeResponse({"error_code": 0, "Brightness": 42})

    monkeypatch.setattr(pixoo_module.requests, "post", fake_post)
    client = PixooClient(ip="10.0.0.2")
    for _ in range(10):
        assert client.get_status() == {"connected": True, "brightness": 42}
    assert calls == ["Channel/GetAllConf"], "ten dashboard polls, one device request"


def test_send_image_marks_device_online(monkeypatch):
    monkeypatch.setattr(pixoo_module.time, "sleep", lambda s: None)
    monkeypatch.setattr(pixoo_module.requests, "post", lambda url, json, timeout: FakeResponse({"error_code": 0}))
    from PIL import Image
    client = PixooClient(ip="10.0.0.2")
    assert client.send_image(Image.new("RGB", (64, 64)))
    assert client._status["connected"] is True

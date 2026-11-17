import pytest

from spotdivoom import server


class StubPixoo:
    ip = "10.0.0.2"

    def get_status(self, max_age=30):
        return {"connected": True, "brightness": 55}


@pytest.fixture
def client(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("# my settings\nSPOTIPY_CLIENT_ID=abc\nHUD_POSITION=bottom\n")
    monkeypatch.setattr(server, "ENV_FILE", env)
    monkeypatch.setattr(server, "current_app_instance", None)
    monkeypatch.setattr(server, "_pixoo", lambda: StubPixoo())
    monkeypatch.setattr(server, "_weather", lambda: None)
    monkeypatch.setattr(server, "_spotify", lambda: None)
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        c.env_file = env
        yield c


def test_settings_round_trip_to_env(client, restore_settings):
    res = client.post("/api/settings", json={
        "hud_position": "top",
        "night_mode": "clock",
        "night_start": "22:30",
        "idle_screens": "cover,forecast",
        "show_title": True,
    })
    assert res.status_code == 200 and res.get_json()["saved_to_env"]
    assert restore_settings.hud_position == "top"
    text = client.env_file.read_text()
    assert "HUD_POSITION=top" in text
    assert "NIGHT_MODE=clock" in text
    assert "NIGHT_START=22:30" in text
    assert "IDLE_SCREENS=cover,forecast" in text
    assert "SHOW_TITLE=true" in text
    assert text.startswith("# my settings\nSPOTIPY_CLIENT_ID=abc\n"), "other lines stay as they were"


def test_invalid_settings_change_nothing(client, restore_settings):
    before = restore_settings.hud_position
    res = client.post("/api/settings", json={"hud_position": "top", "night_start": "25:99"})
    assert res.status_code == 400
    assert "night_start" in res.get_json()["errors"]
    assert restore_settings.hud_position == before, "a bad field must not half-apply the rest"


def test_status_uses_cached_device_state(client):
    data = client.get("/api/status").get_json()
    assert data["pixoo"] == {"connected": True, "ip": "10.0.0.2", "brightness": 55}
    assert data["playback"] is None
    assert data["daemon"] is False
    assert "hud_position" in data["settings"]


def test_playback_controls_need_the_daemon(client):
    res = client.post("/api/playback/next")
    assert res.status_code == 400
    assert client.post("/api/playback/explode").status_code == 404

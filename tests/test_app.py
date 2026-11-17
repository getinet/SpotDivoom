import datetime

from PIL import Image

from spotdivoom import app as app_module
from spotdivoom import stats
from spotdivoom.app import SpotDivoomApp, is_night_time
from spotdivoom.spotify import PlaybackUnavailable, TrackInfo


def test_night_window_crossing_midnight():
    t = datetime.time
    assert is_night_time(t(23, 30), "23:00", "07:00")
    assert is_night_time(t(6, 59), "23:00", "07:00")
    assert not is_night_time(t(7, 0), "23:00", "07:00")
    assert not is_night_time(t(12, 0), "23:00", "07:00")


def test_night_window_same_day_and_bad_input():
    t = datetime.time
    assert is_night_time(t(13, 0), "12:00", "14:00")
    assert not is_night_time(t(15, 0), "12:00", "14:00")
    assert not is_night_time(t(13, 0), "nonsense", "14:00")
    assert not is_night_time(t(13, 0), "12:00", "12:00")


class FakePixoo:
    def __init__(self):
        self.sent = []
        self.ip = "10.0.0.2"

    def send_image(self, img):
        self.sent.append(img)
        return True

    def send_scrolling_text(self, *a, **k):
        return True

    def clear_text(self):
        return True

    def get_brightness(self):
        return 80

    def set_brightness(self, level):
        return True

    def set_screen_on(self, on):
        return True


class FakeSpotify:
    def __init__(self):
        self.responses = []

    def get_current_track(self):
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def fetch_image(self, url):
        return Image.new("RGB", (300, 300), (200, 30, 30))

    def is_liked(self, track_id):
        return False

    def get_random_liked_track(self, limit=500):
        from spotdivoom.spotify import LikedTrack
        return LikedTrack("Liked", "Someone", "Album", "http://liked")

    def is_authorized(self):
        return True


def _track(playing=True):
    return TrackInfo("t1", "Song", "Artist", "Album", "http://img", playing, 1000, 200000)


def _app(monkeypatch, settings):
    settings.night_mode = "off"
    settings.on_pause = "idle"
    monkeypatch.setattr(app_module, "record_play", stats.record_play)
    a = SpotDivoomApp()
    a.pixoo = FakePixoo()
    a.spotify = FakeSpotify()
    a.spotify_authorized = True
    a.weather_service = None
    return a


def test_spotify_outage_keeps_playing_screen(monkeypatch, restore_settings, isolated_play_log):
    a = _app(monkeypatch, restore_settings)
    a.spotify.responses = [_track(), PlaybackUnavailable("timeout"), _track()]

    a.poll_once()
    assert a.last_track_id == "t1" and a.last_is_playing
    sent_after_start = len(a.pixoo.sent)

    delay = a.poll_once()  # outage
    assert a.last_track_id == "t1" and a.last_is_playing, "an outage must not look like 'stopped'"
    assert delay > restore_settings.poll_interval, "polling should back off while Spotify fails"
    assert len(a.pixoo.sent) == sent_after_start, "no idle screen during the outage"

    a.poll_once()  # back
    assert a.spotify_errors == 0
    lines = isolated_play_log.read_text().splitlines()
    assert len(lines) == 1, "the same play must be logged once"


def test_stopped_playback_switches_to_idle(monkeypatch, restore_settings):
    a = _app(monkeypatch, restore_settings)
    a.spotify.responses = [_track(), None]
    a.poll_once()
    a.poll_once()
    assert a.last_track_id is None
    assert a.current_idle_cover is not None


def test_snapshot_reports_playback_without_api_calls(monkeypatch, restore_settings):
    a = _app(monkeypatch, restore_settings)
    a.spotify.responses = [_track()]
    a.poll_once()
    snap = a.snapshot()
    assert snap["playback"]["title"] == "Song"
    assert snap["playback"]["liked"] is False
    assert snap["idle_active"] is False
    assert a.spotify.responses == []  # snapshot itself made no Spotify call


def test_record_play_skips_quick_repeats(isolated_play_log):
    stats.record_play(_track())
    stats.record_play(_track())
    assert len(isolated_play_log.read_text().splitlines()) == 1

"""
Web server for SpotDivoom dashboard and remote control.
Provides REST API and serves the modern web interface.

Routes read state the daemon already has (SpotDivoomApp.snapshot, the Pixoo's cached status)
instead of calling Spotify or the device per request, so open dashboards add no API traffic.
"""

import datetime
import io
import json
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from flask import Flask, Response, jsonify, render_template, request, send_file
from PIL import Image

from . import events
from .config import ENV_FILE, settings
from .display import (
    create_blank_image,
    create_logo_idle_image,
    render_idle_cover_with_hud,
)
from .pixoo import PixooClient
from .spotify import SpotifyWatcher
from .stats import get_stats
from .weather import WeatherService

web_dir = Path(__file__).resolve().parent / "web"
app = Flask(
    __name__,
    template_folder=str(web_dir / "templates"),
    static_folder=str(web_dir / "static"),
)

# Reference to the running app instance if launched together
current_app_instance = None
last_rendered_frame: Optional[Image.Image] = None
frame_version = 0

# Used only in --web-only mode, when there is no daemon to borrow clients from
_fallback_lock = threading.Lock()
_fallback: dict = {}


def set_current_frame(img: Image.Image):
    global last_rendered_frame, frame_version
    last_rendered_frame = img.copy()
    frame_version += 1
    events.publish()


def _fallback_client(key: str, factory: Callable):
    with _fallback_lock:
        if key not in _fallback:
            _fallback[key] = factory()
        return _fallback[key]


def _pixoo() -> PixooClient:
    if current_app_instance and current_app_instance.pixoo:
        return current_app_instance.pixoo
    return _fallback_client("pixoo", lambda: PixooClient(settings.pixoo_ip))


def _weather():
    if current_app_instance and current_app_instance.weather_service:
        return current_app_instance.get_weather()
    ws = _fallback_client("weather", lambda: WeatherService(
        city=settings.weather_city, lat=settings.weather_lat, lon=settings.weather_lon, unit=settings.weather_unit,
    ))
    return ws.get_weather(unit=settings.weather_unit)


def _spotify() -> Optional[SpotifyWatcher]:
    if current_app_instance and current_app_instance.spotify:
        return current_app_instance.spotify
    if not settings.has_spotify_credentials():
        return None
    return _fallback_client("spotify", lambda: SpotifyWatcher(
        client_id=settings.spotify_client_id,
        client_secret=settings.spotify_client_secret,
        redirect_uri=settings.spotify_redirect_uri,
    ))


# ---------- Settings: one table drives validation, the in-memory update and .env ----------

def _choice(*options: str) -> Callable:
    def parse(value):
        value = str(value).strip().lower()
        if value not in options:
            raise ValueError(f"must be one of {', '.join(options)}")
        return value
    return parse


def _number(cast, low, high) -> Callable:
    def parse(value):
        n = cast(value)
        if not low <= n <= high:
            raise ValueError(f"must be between {low} and {high}")
        return n
    return parse


def _flag(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def _hhmm(value) -> str:
    value = str(value).strip()
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError("must be HH:MM")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _idle_screens(value) -> str:
    items = value if isinstance(value, list) else str(value).split(",")
    screens = [s.strip().lower() for s in items if s.strip().lower() in ("cover", "forecast")]
    if not screens:
        raise ValueError("pick at least one of cover, forecast")
    return ",".join(dict.fromkeys(screens))


SETTINGS_FIELDS: dict[str, tuple[str, Callable]] = {
    "on_pause": ("ON_PAUSE", _choice("idle", "keep", "dim", "clear")),
    "idle_cycle_interval": ("IDLE_CYCLE_INTERVAL", _number(float, 10, 3600)),
    "use_24h_time": ("USE_24H_TIME", _flag),
    "always_show_hud": ("ALWAYS_SHOW_HUD", _flag),
    "hud_position": ("HUD_POSITION", _choice("bottom", "top")),
    "hud_accent": ("HUD_ACCENT", _flag),
    "show_progress": ("SHOW_PROGRESS", _flag),
    "show_title": ("SHOW_TITLE", _flag),
    "idle_screens": ("IDLE_SCREENS", _idle_screens),
    "idle_transition": ("IDLE_TRANSITION", _choice("none", "fade")),
    "weather_unit": ("WEATHER_UNIT", lambda v: _choice("f", "c")(v).upper()),
    "enhance_contrast": ("ENHANCE_CONTRAST", _number(float, 0.5, 2.0)),
    "enhance_color": ("ENHANCE_COLOR", _number(float, 0.5, 2.0)),
    "night_mode": ("NIGHT_MODE", _choice("off", "dim", "clock", "screen_off")),
    "night_start": ("NIGHT_START", _hhmm),
    "night_end": ("NIGHT_END", _hhmm),
    "night_brightness": ("NIGHT_BRIGHTNESS", _number(int, 1, 100)),
}


def _env_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def write_env(env_file: Path, updates: dict[str, str]):
    """
    Rewrites the given keys in .env in place, appending any that aren't there yet.
    """
    lines = env_file.read_text().splitlines()
    new_lines, seen = [], set()
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in updates:
                new_lines.append(f"{k}={updates[k]}")
                seen.add(k)
                continue
        new_lines.append(line)
    new_lines += [f"{k}={v}" for k, v in updates.items() if k not in seen]
    env_file.write_text("\n".join(new_lines) + "\n")


def settings_dict() -> dict:
    data = {name: getattr(settings, name) for name in SETTINGS_FIELDS}
    data.update(idle_mode=settings.idle_mode, poll_interval=settings.poll_interval)
    return data


# ---------- Status ----------

def build_status() -> dict:
    app_instance = current_app_instance
    if app_instance:
        snap = app_instance.snapshot()
    else:
        sp = _spotify()
        snap = {
            "playback": None,
            "idle_active": True,
            "current_cover_title": "SpotDivoom",
            "spotify": {"authorized": bool(sp and sp.is_authorized()), "error": None},
            "night": {"active": False, "mode": None},
        }

    weather = _weather()
    pixoo = _pixoo()
    pixoo_status = pixoo.get_status()

    return {
        "playback": snap["playback"],
        "idle": {
            "active": snap["idle_active"],
            "current_cover_title": snap["current_cover_title"],
            "time": datetime.datetime.now().strftime("%H:%M" if settings.use_24h_time else "%-I:%M %p"),
            "weather": {
                "temperature": weather.temperature,
                "unit": weather.unit,
                "weather_code": weather.weather_code,
                "is_day": weather.is_day,
                "city": weather.city,
            } if weather else None,
        },
        "pixoo": {
            "connected": pixoo_status["connected"],
            "ip": pixoo.ip or settings.pixoo_ip,
            "brightness": pixoo_status["brightness"],
        },
        "spotify": snap["spotify"],
        "night": snap["night"],
        "daemon": app_instance is not None,
        "frame_version": frame_version,
        "settings": settings_dict(),
        "server_time_ms": int(time.time() * 1000),
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    return jsonify(build_status())


@app.route("/api/events")
def api_events():
    """
    Server-sent events: pushes the status whenever the daemon reports a change
    (and every 20 seconds regardless, which also keeps proxies from closing the stream).
    """
    def stream():
        seen = -1
        while True:
            seen = events.wait_for_change(seen, timeout=20)
            yield f"data: {json.dumps(build_status())}\n\n"

    return Response(stream(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@app.route("/api/stats")
def api_stats():
    """
    Returns listening statistics for the "Your Listening Story" section.
    """
    sp = _spotify()
    if not (sp and sp.is_authorized()):
        return jsonify({"error": "Log in to Spotify to see your listening story."}), 503
    try:
        stats = get_stats(sp.sp, force_refresh=request.args.get("refresh") == "1")
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": f"Could not load Spotify stats: {e}"}), 502


@app.route("/api/frame")
def api_frame():
    """
    Returns the current 64x64 pixel frame as a PNG.
    """
    global last_rendered_frame
    if last_rendered_frame is None:
        last_rendered_frame = create_logo_idle_image()

    buf = io.BytesIO()
    last_rendered_frame.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


# ---------- Spotify login (works anywhere, including Docker on another machine) ----------

@app.route("/api/auth/status")
def api_auth_status():
    sp = _spotify()
    if sp is None:
        return jsonify({"configured": False, "authorized": False})
    authorized = sp.is_authorized()
    return jsonify({
        "configured": True,
        "authorized": authorized,
        "authorize_url": None if authorized else sp.authorize_url(),
        "redirect_uri": settings.spotify_redirect_uri,
    })


@app.route("/api/auth/complete", methods=["POST"])
def api_auth_complete():
    """
    Finishes login with the URL Spotify redirected the browser to. That page usually fails to
    load (nothing listens on the redirect address), but its address bar holds the code we need.
    """
    sp = _spotify()
    url = (request.get_json() or {}).get("url", "")
    if sp is None or not url:
        return jsonify({"success": False, "error": "Paste the full address from your browser."}), 400
    try:
        ok = sp.complete_login(url)
    except Exception as e:
        return jsonify({"success": False, "error": f"Spotify rejected the login: {e}"}), 400
    if not ok:
        return jsonify({"success": False, "error": "That address doesn't contain a login code."}), 400
    if current_app_instance:
        current_app_instance.on_spotify_login()
    return jsonify({"success": True})


# ---------- Controls ----------

@app.route("/api/playback/<action>", methods=["POST"])
def api_playback(action):
    if action not in ("toggle", "next", "previous", "like", "unlike"):
        return jsonify({"success": False, "error": "Unknown action"}), 404
    if not current_app_instance:
        return jsonify({"success": False, "error": "Playback controls need the full app (not --web-only)."}), 400
    try:
        ok = current_app_instance.control(action)
    except Exception as e:
        # Spotify returns 403/404 here when there's no active device or the account isn't Premium
        return jsonify({"success": False, "error": f"Spotify said no: {e}"}), 502
    return jsonify({"success": ok})


@app.route("/api/control/brightness", methods=["POST"])
def api_brightness():
    data = request.get_json() or {}
    level = data.get("brightness", 100)
    ok = _pixoo().set_brightness(level)
    events.publish()
    return jsonify({"success": ok, "brightness": level})


@app.route("/api/control/cycle", methods=["POST"])
def api_cycle_cover():
    if current_app_instance:
        current_app_instance.update_idle_display(force_new_cover=True)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "App instance not running"}), 400


@app.route("/api/control/test-pixoo", methods=["POST"])
def api_test_pixoo():
    img = create_logo_idle_image()
    ok = _pixoo().send_image(img)
    if ok:
        set_current_frame(img)
    return jsonify({"success": ok})


@app.route("/api/control/test-idle", methods=["POST"])
def api_test_idle():
    if current_app_instance:
        current_app_instance.update_idle_display(force_new_cover=True)
        return jsonify({"success": True})

    frame = render_idle_cover_with_hud(create_logo_idle_image(), weather=_weather(), position=settings.hud_position)
    ok = _pixoo().send_image(frame)
    if ok:
        set_current_frame(frame)
    return jsonify({"success": ok})


@app.route("/api/control/clear", methods=["POST"])
def api_clear():
    ok = _pixoo().clear()
    if ok:
        set_current_frame(create_blank_image())
    return jsonify({"success": ok})


@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    data = request.get_json() or {}

    # Validate everything first so a bad field doesn't leave settings half-applied
    parsed, errors = {}, {}
    for name, (_, parse) in SETTINGS_FIELDS.items():
        if name in data:
            try:
                parsed[name] = parse(data[name])
            except (TypeError, ValueError) as e:
                errors[name] = str(e)
    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    for name, value in parsed.items():
        setattr(settings, name, value)

    # Persist changes to .env if file exists
    saved = False
    if ENV_FILE.exists():
        try:
            write_env(ENV_FILE, {SETTINGS_FIELDS[n][0]: _env_value(getattr(settings, n)) for n in SETTINGS_FIELDS})
            saved = True
        except OSError:
            pass

    # Redraw right away so changes show without waiting for the next minute
    if current_app_instance:
        try:
            current_app_instance.on_settings_changed()
        except Exception:
            pass

    return jsonify({"success": True, "saved_to_env": saved})


def run_web_server(host="0.0.0.0", port=5050):
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)

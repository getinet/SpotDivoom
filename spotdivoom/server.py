"""
Web server for SpotDivoom dashboard and remote control.
Provides REST API and serves the modern web interface.
"""

import datetime
import io
import os
from pathlib import Path
from typing import Optional
from flask import Flask, jsonify, render_template, request, send_file
from PIL import Image

from .config import ENV_FILE, settings
from .display import (
    create_blank_image,
    create_spotify_idle_image,
    process_image_for_pixoo,
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


def set_current_frame(img: Image.Image):
    global last_rendered_frame
    last_rendered_frame = img.copy()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    global current_app_instance
    playback_data = None
    idle_data = {
        "active": True,
        "current_cover_title": "Spotify",
        "time": "",
        "weather": None,
    }

    # Fetch live playback if spotify watcher available
    if current_app_instance and current_app_instance.spotify:
        track = current_app_instance.spotify.get_current_track()
        if track:
            playback_data = {
                "is_playing": track.is_playing,
                "title": track.title,
                "artist": track.artist,
                "album": track.album,
                "image_url": track.image_url,
                "progress_ms": track.progress_ms,
                "duration_ms": track.duration_ms,
            }
            if track.is_playing:
                idle_data["active"] = False

        idle_data["current_cover_title"] = current_app_instance.current_idle_title

    # Weather & Time
    ws = (
        current_app_instance.weather_service
        if current_app_instance and current_app_instance.weather_service
        else WeatherService(unit=settings.weather_unit)
    )
    weather = ws.get_weather()
    if weather:
        idle_data["weather"] = {
            "temperature": weather.temperature,
            "unit": weather.unit,
            "weather_code": weather.weather_code,
            "is_day": weather.is_day,
            "city": weather.city,
        }

    now = datetime.datetime.now()
    idle_data["time"] = now.strftime("%H:%M" if settings.use_24h_time else "%-I:%M %p")

    pixoo_client = (
        current_app_instance.pixoo
        if current_app_instance and current_app_instance.pixoo
        else PixooClient(settings.pixoo_ip)
    )
    pixoo_connected = pixoo_client.ping()

    return jsonify({
        "playback": playback_data,
        "idle": idle_data,
        "pixoo": {
            "connected": pixoo_connected,
            "ip": pixoo_client.ip or settings.pixoo_ip,
            "brightness": pixoo_client.get_brightness() if pixoo_connected else 100,
        },
        "settings": {
            "on_pause": settings.on_pause,
            "idle_mode": settings.idle_mode,
            "idle_cycle_interval": settings.idle_cycle_interval,
            "use_24h_time": settings.use_24h_time,
            "always_show_hud": settings.always_show_hud,
            "hud_position": settings.hud_position,
            "weather_unit": settings.weather_unit,
            "enhance_contrast": settings.enhance_contrast,
            "enhance_color": settings.enhance_color,
            "poll_interval": settings.poll_interval,
        },
    })


@app.route("/api/stats")
def api_stats():
    """
    Returns listening statistics for the "Your Listening Story" section.
    """
    if not (current_app_instance and current_app_instance.spotify):
        return jsonify({"error": "Spotify is not connected yet."}), 503
    try:
        stats = get_stats(current_app_instance.spotify.sp, force_refresh=request.args.get("refresh") == "1")
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
        last_rendered_frame = create_spotify_idle_image()

    buf = io.BytesIO()
    last_rendered_frame.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/api/control/brightness", methods=["POST"])
def api_brightness():
    data = request.get_json() or {}
    level = data.get("brightness", 100)
    pixoo_client = (
        current_app_instance.pixoo
        if current_app_instance and current_app_instance.pixoo
        else PixooClient(settings.pixoo_ip)
    )
    ok = pixoo_client.set_brightness(level)
    return jsonify({"success": ok, "brightness": level})


@app.route("/api/control/cycle", methods=["POST"])
def api_cycle_cover():
    global current_app_instance
    if current_app_instance:
        current_app_instance.update_idle_display(force_new_cover=True)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "App instance not running"}), 400


@app.route("/api/control/test-pixoo", methods=["POST"])
def api_test_pixoo():
    pixoo_client = (
        current_app_instance.pixoo
        if current_app_instance and current_app_instance.pixoo
        else PixooClient(settings.pixoo_ip)
    )
    img = create_spotify_idle_image()
    ok = pixoo_client.send_image(img)
    if ok:
        set_current_frame(img)
    return jsonify({"success": ok})


@app.route("/api/control/test-idle", methods=["POST"])
def api_test_idle():
    global current_app_instance
    if current_app_instance:
        current_app_instance.update_idle_display(force_new_cover=True)
        return jsonify({"success": True})

    ws = WeatherService(unit=settings.weather_unit)
    w = ws.get_weather()
    frame = render_idle_cover_with_hud(create_spotify_idle_image(), weather=w, position=settings.hud_position)
    client = PixooClient(settings.pixoo_ip)
    ok = client.send_image(frame)
    if ok:
        set_current_frame(frame)
    return jsonify({"success": ok})


@app.route("/api/control/clear", methods=["POST"])
def api_clear():
    pixoo_client = (
        current_app_instance.pixoo
        if current_app_instance and current_app_instance.pixoo
        else PixooClient(settings.pixoo_ip)
    )
    ok = pixoo_client.clear()
    if ok:
        set_current_frame(create_blank_image())
    return jsonify({"success": ok})


@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    data = request.get_json() or {}
    env_file = ENV_FILE

    # Update in-memory settings
    if "on_pause" in data:
        settings.on_pause = str(data["on_pause"]).lower()
    if "idle_cycle_interval" in data:
        settings.idle_cycle_interval = float(data["idle_cycle_interval"])
    if "use_24h_time" in data:
        settings.use_24h_time = bool(data["use_24h_time"])
    if "always_show_hud" in data:
        settings.always_show_hud = bool(data["always_show_hud"])
    if "hud_position" in data:
        settings.hud_position = "top" if str(data["hud_position"]).lower() == "top" else "bottom"
    if "weather_unit" in data:
        settings.weather_unit = str(data["weather_unit"]).upper()
    if "enhance_contrast" in data:
        settings.enhance_contrast = float(data["enhance_contrast"])
    if "enhance_color" in data:
        settings.enhance_color = float(data["enhance_color"])

    # Persist changes to .env if file exists
    if env_file.exists():
        try:
            lines = env_file.read_text().splitlines()
            updates = {
                "ON_PAUSE": settings.on_pause,
                "IDLE_CYCLE_INTERVAL": str(settings.idle_cycle_interval),
                "USE_24H_TIME": "true" if settings.use_24h_time else "false",
                "ALWAYS_SHOW_HUD": "true" if settings.always_show_hud else "false",
                "HUD_POSITION": settings.hud_position,
                "WEATHER_UNIT": settings.weather_unit,
                "ENHANCE_CONTRAST": str(settings.enhance_contrast),
                "ENHANCE_COLOR": str(settings.enhance_color),
            }
            new_lines = []
            seen_keys = set()
            for line in lines:
                if "=" in line and not line.strip().startswith("#"):
                    k, _ = line.split("=", 1)
                    k = k.strip()
                    if k in updates:
                        new_lines.append(f"{k}={updates[k]}")
                        seen_keys.add(k)
                        continue
                new_lines.append(line)
            for k, v in updates.items():
                if k not in seen_keys:
                    new_lines.append(f"{k}={v}")
            env_file.write_text("\n".join(new_lines) + "\n")
        except Exception:
            pass

    # Redraw the now-playing frame right away so bar/clock changes show without waiting a minute
    app_instance = current_app_instance
    if app_instance:
        # Idle screen: force a redraw on the daemon's next poll tick
        app_instance.last_idle_minute = -1
    if app_instance and app_instance.last_is_playing and app_instance.current_raw_cover is not None:
        try:
            app_instance.send_track_frame()
        except Exception:
            pass

    return jsonify({"success": True})


def run_web_server(host="0.0.0.0", port=5050):
    app.run(host=host, port=port, debug=False, use_reloader=False)

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

SpotDivoom streams the album art of the currently playing Spotify track to a Divoom Pixoo 64 (64x64 LED panel) over the LAN, and shows an idle screen (liked-song covers or a forecast, with a clock + weather bar) when nothing plays. It also serves a Flask web dashboard (port 5050) with an LED simulator, playback controls, settings, Spotify login, and a listening-stats section.

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt

python main.py                 # sync daemon + web dashboard (http://localhost:5050)
python main.py --web-only      # dashboard only (no daemon; see "Shared state" below)
python main.py --no-web        # daemon only
python main.py --test-spotify  # check auth, print current track
python main.py --test-pixoo    # push a test graphic to the device
python main.py --test-idle     # render + push the idle HUD frame once
python main.py --discover      # list Divoom devices via LAN discovery
python main.py --clear

python -m pytest                                  # all tests (no network, no device)
python -m pytest tests/test_display.py -k progress  # one test

docker compose up -d --build   # container; persistent files live in ./data
.venv/bin/python design/logo/build.py   # rebuild the local logo demo page
```

There is no linter or build step. Frontend is plain HTML/CSS/JS served by Flask — no bundler. Tests stub the Pixoo, Spotify and HTTP calls; `tests/conftest.py` restores the global `settings` and redirects the play log after each test.

## Architecture

The git root is the repo folder; the Python package is `spotdivoom/`, entry point `main.py` (argparse dispatch to `cmd_*` functions).

**Two components in one process.** Default `main.py` runs the Flask app (`spotdivoom/server.py`) in a daemon thread and the polling loop `SpotDivoomApp.run()` (`spotdivoom/app.py`) on the main thread. Each loop pass is `poll_once()`: night mode check → Spotify poll → `_apply_playback()` state machine over playing / paused (`ON_PAUSE`: idle|keep|dim|clear) / stopped. It pushes a frame only when the track changes, the minute ticks, or (with `SHOW_PROGRESS`) every 15 s for the progress line. The loop sleeps on a `threading.Event`, so dashboard actions call `app.wake()` for an immediate poll.

**Spotify errors vs. "nothing playing".** `SpotifyWatcher.get_current_track()` returns `None` only when nothing plays and raises `PlaybackUnavailable` on errors. The loop keeps the current screen and backs off on errors; don't collapse the two cases or outages flash the idle screen and re-log plays.

**Shared state.** `initialize()` sets `server.current_app_instance = self` first thing (before Spotify login, which the dashboard can complete). Routes read `app.snapshot()` and `PixooClient.get_status()` (cached ~30 s) rather than calling Spotify or the device per request; keep it that way, since the Pixoo 64 freezes under request floods. In `--web-only` mode (no app instance) routes use lazily-created fallback clients (`_pixoo()`, `_weather()`, `_spotify()`). All device commands go through `PixooClient._command` under one `RLock`; app state mutated from web threads is guarded by `SpotDivoomApp.lock`.

**Frames and live updates.** Every frame pushed to the device goes through `SpotDivoomApp._push()`, which calls `server.set_current_frame()` → bumps `frame_version` and `events.publish()`. `/api/events` is an SSE stream that sends `build_status()` whenever `events` is published (and every 20 s); `app.js` refetches `/api/frame` only when `frame_version` changes and falls back to polling `/api/status` if the stream goes quiet. Device-side scrolling text (`SHOW_TITLE`, `Draw/SendHttpText`) is not in the simulator frame.

**Settings.** `spotdivoom/config.py` builds a module-level `settings` dataclass from env at import time. `server.SETTINGS_FIELDS` maps each user-editable field to its env key and a validator; `POST /api/settings` validates all fields first, then mutates the singleton, rewrites keys in `.env` (only if the file exists), and calls `app.on_settings_changed()` to redraw. Adding a setting: field in `config.py`, entry in `SETTINGS_FIELDS`, form control in `index.html` + the `boolSelects`/`valueFields` maps in `app.js`, `.env.example`, README table. Note: code default for `ON_PAUSE` is `keep`, while `.env.example`/README use `idle`.

**Spotify login.** `SpotifyOAuth` opens a browser only when stdin is a TTY. Otherwise the dashboard's login panel uses `/api/auth/status` (authorize URL) and `/api/auth/complete`, where the user pastes the redirect URL from their address bar (the redirect target never needs to load), so it works from Docker on another host. `SPOTIFY_SCOPES` includes playback/library-modify for the dashboard controls; changing scopes invalidates cached tokens (spotipy rejects tokens missing a scope), and the dashboard then prompts for login.

**Data directory.** `DATA_DIR` (env var, defaults to repo root; `/app/data` in Docker) holds `.env`, `.cache-spotify`, and `listening_log.jsonl` (append-only play log; `stats.record_play` skips the same track within 10 minutes).

**Rendering pipeline** (`display.py`, `weather.py`). All frames are 64x64 RGB PIL images. `_draw_hud` draws the time/weather bar (top or bottom, `HUD_POSITION`) with optional album-color accent (`accent_from_cover`) and progress line; it's shared by the cover, forecast (`render_forecast_screen`) screens. Small labels use the built-in 3x5 pixel font (`draw_tiny_text`); large text uses bold TrueType tried by filename (Arial Bold → Liberation → DejaVu), which is why the Dockerfile installs those fonts. Weather is Open-Meteo (current + 13 hourly + sunrise/sunset) with IP geolocation, cached 10 min; passing a new `unit` refetches immediately. The SpotDivoom logo (Lichen Grid) lives in `web/static/img/` (`logo-64.png` for the device via `create_logo_idle_image`, `favicon.svg`) and inline in the `index.html` header with `currentColor` pixels so it follows each look's text color.

**Pixoo protocol** (`pixoo.py`). HTTP POST JSON to `http://<ip>/post`: `Draw/ResetHttpGifId` then `Draw/SendHttpGif` with base64 raw RGB bytes (multi-frame animations loop on the device, so cross-fades are sent as single frames). Also `Draw/SendHttpText`, `Channel/OnOffScreen`, `Channel/SetBrightness`, `Channel/GetAllConf`. Device IP comes from `PIXOO_IP` or Divoom's cloud LAN-discovery endpoint.

**Night mode** (`SpotDivoomApp.update_night_mode`). `dim` lowers brightness and restores the saved level after; `clock` and `screen_off` take over the display (`night_blocks_display()`), during which the loop still polls Spotify and logs plays but sends no track/idle frames.

**Listening stats** (`stats.py`, `/api/stats`, `web/static/js/stats.js`). Merges Spotify top artists/tracks, recently played, saved tracks, and the local play log into one dict, cached in-process for 10 minutes. `stats.js` reloads on the `spotdivoom:login` event.

**Dashboard looks/themes.** `web/static/css/themes.css` defines looks keyed by `<html data-theme="...">` (default `faded-film`), using tokens from `style.css`. `theme.js` handles the switcher (persisted in `localStorage` key `spotdivoom-look`) and dispatches a `spotdivoom:theme` event; `stats.js` re-renders charts on that event, reading colors from computed CSS rather than hardcoding them. New looks need an `<option>` in the `lookSelect` in `index.html` plus a `[data-theme=...]` block in `themes.css`.

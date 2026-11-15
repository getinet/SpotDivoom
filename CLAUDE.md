# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

SpotDivoom streams the album art of the currently playing Spotify track to a Divoom Pixoo 64 (64x64 LED panel) over the LAN, and shows an idle screen (liked-song covers + clock + weather HUD) when nothing plays. It also serves a Flask web dashboard (port 5050) with an LED simulator, controls, settings, and a listening-stats section.

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

python main.py                 # sync daemon + web dashboard (http://localhost:5050)
python main.py --web-only      # dashboard only (no daemon; see "Shared state" below)
python main.py --no-web        # daemon only
python main.py --test-spotify  # check auth, print current track
python main.py --test-pixoo    # push a test graphic to the device
python main.py --test-idle     # render + push the idle HUD frame once
python main.py --discover      # list Divoom devices via LAN discovery
python main.py --clear

docker compose up -d --build   # container; persistent files live in ./data
```

There is no test suite, linter, or build step. Verify changes with the `--test-*` commands and by loading the dashboard. Frontend is plain HTML/CSS/JS served by Flask — no bundler.

## Architecture

The git root is the repo folder; the Python package is `spotdivoom/`, entry point `main.py` (argparse dispatch to `cmd_*` functions).

**Two components in one process.** Default `main.py` runs the Flask app (`spotdivoom/server.py`) in a daemon thread and the polling loop `SpotDivoomApp.run()` (`spotdivoom/app.py`) on the main thread. The loop polls Spotify every `POLL_INTERVAL` and is a state machine over playing / paused (`ON_PAUSE`: idle|keep|dim|clear) / stopped. It only pushes a frame to the Pixoo when the track changes or the clock minute ticks (HUD refresh).

**Shared state.** After `initialize()`, the app sets `server.current_app_instance = self`. Flask routes reach the live `pixoo`, `spotify`, `weather_service`, and idle/playback fields through that global, and fall back to constructing fresh clients when it is `None` (e.g. `--web-only`). The dashboard's simulator reads `server.last_rendered_frame`, set via `set_current_frame()` — any code path that pushes to the device should also update it so the web mirror stays in sync.

**Settings.** `spotdivoom/config.py` builds a module-level `settings` dataclass from env at import time. `POST /api/settings` mutates that singleton in memory (the daemon sees changes on its next tick) and rewrites keys in `.env` only if the file exists. Adding a user-editable setting means touching `config.py`, `api_save_settings` (both the in-memory update and the `.env` `updates` dict), the form in `web/templates/index.html`/`app.js`, `.env.example`, and the README table. Note: code default for `ON_PAUSE` is `keep`, while `.env.example`/README use `idle`.

**Data directory.** `DATA_DIR` (env var, defaults to repo root; `/app/data` in Docker) holds `.env`, `.cache-spotify` (spotipy OAuth token), and `listening_log.jsonl` (append-only play log written by `stats.record_play` on each new track). Spotify OAuth needs a browser, so in Docker the token is created on a desktop first and copied into `data/`. Changing `SPOTIFY_SCOPES` in `spotify.py` requires deleting `.cache-spotify` and re-authorizing.

**Rendering pipeline** (`display.py`, `weather.py`). All frames are 64x64 RGB PIL images. `process_image_for_pixoo` does Lanczos downscale + contrast/color enhancement; `render_idle_cover_with_hud` composites the time/weather bar (used for both idle and, with `ALWAYS_SHOW_HUD`, now-playing). Weather icons are hand-drawn pixel art in `weather.py`; weather is Open-Meteo with IP geolocation (no API key). Bold fonts are tried by filename (Arial Bold → Liberation → DejaVu), which is why the Dockerfile installs Liberation/DejaVu fonts.

**Pixoo protocol** (`pixoo.py`). HTTP POST JSON to `http://<ip>/post`: `Draw/ResetHttpGifId` then `Draw/SendHttpGif` with base64 raw RGB bytes. Device IP comes from `PIXOO_IP` or Divoom's cloud LAN-discovery endpoint.

**Listening stats** (`stats.py`, `/api/stats`, `web/static/js/stats.js`). Merges Spotify top artists/tracks, recently played, saved tracks, and the local play log into one dict, cached in-process for 10 minutes.

**Dashboard looks/themes.** `web/static/css/themes.css` defines looks keyed by `<html data-theme="...">` (default `faded-film`), using tokens from `style.css`. `theme.js` handles the switcher (persisted in `localStorage` key `spotdivoom-look`) and dispatches a `spotdivoom:theme` event; `stats.js` re-renders charts on that event, reading colors from computed CSS rather than hardcoding them. New looks need an `<option>` in the `lookSelect` in `index.html` plus a `[data-theme=...]` block in `themes.css`.

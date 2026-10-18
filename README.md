# SpotDivoom 64 🎵 🖼️ ⏱️ 🌐

A compact, high-performance Python application and modern web dashboard that streams the album cover art of your currently playing Spotify track directly to your **Divoom Pixoo 64** LED display over Wi-Fi.

When nothing is playing, it automatically shifts into an **Ambient Idle Mode**—cycling through the album art of tracks you like (from your Spotify Liked Songs), overlaid with live **local time** and **current weather**.

---

## ✨ Features

- **🌐 Live Web Dashboard & Simulator**:
  - **Authentic LED Matrix Simulator**: Real-time virtual canvas that mirrors your Pixoo 64 display in your browser with realistic LED diode simulation or smooth mode.
  - **Now Playing Hub**: Album cover, track details, animated equalizer bars, and live progress bar.
  - **Hardware Controls**: Live brightness slider with presets (25%, 50%, 75%, 100%), screen clear, and test buttons.
  - **Ambient Hub**: Weather station stats, current cycling cover, and a manual "Next Cover" button.
  - **Settings Manager**: Change pause behaviors, time format (12h/24h), weather units (°F/°C), and LED color boost presets directly from the web UI.
- **🎵 Now Playing Display**: Full 64x64 Lanczos downsampled album art of whatever is currently playing on Spotify.
- **⏱️ Ambient Idle Mode**:
  - Cycles through covers from your **Spotify Liked Songs** library.
  - Clean semi-transparent frosted HUD at the bottom showing **Local Time** (`HH:MM`).
  - **Live Weather & Temperature** (e.g. `66°F` / `19°C` with custom pixel art weather icons for sun, moon, clouds, rain, snow, thunderstorms).
  - Uses the free Open-Meteo API with automatic IP geolocation—**no weather API key required**.
- **🔍 Auto-Discovery**: Automatically discovers your Pixoo 64 on your local network using Divoom's LAN discovery protocol.
- **⚡ Zero Redundant Traffic**: Only sends image payloads to the display when the track changes or the clock minute ticks.
- **💾 In-Memory Caching**: Caches downloaded album covers to minimize bandwidth and eliminate re-downloads.

---

## 🚀 Quickstart Guide

### 1. Requirements

- Python 3.9+
- A Divoom Pixoo 64 connected to the same Wi-Fi network as this computer
- A Spotify account

### 2. Environment Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure Spotify Credentials

Spotify credentials can be created at the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard):
1. Create App with Redirect URI: `http://127.0.0.1:8888/callback`
2. Add Client ID & Secret to [.env](file:///Users/mekuria/Documents/GitHub/SpotDivoom/.env):

```env
SPOTIPY_CLIENT_ID=your_client_id_here
SPOTIPY_CLIENT_SECRET=your_client_secret_here
SPOTIPY_REDIRECT_URI=http://127.0.0.1:8888/callback
```

### 4. Run the Application & Web Dashboard

Start the application (starts both the sync daemon and the web dashboard):

```bash
./.venv/bin/python main.py
```

- Open your browser to **[http://localhost:5050](http://localhost:5050)** to access the live dashboard!
- On the very first run, your default browser will open to authorize Spotify.
- Click **Agree**, and token credentials are automatically saved in `.cache-spotify`.

---

## 🛠️ CLI Options

| Command | Description |
|---|---|
| `python main.py` | Run the sync daemon and web dashboard (port 5050) |
| `python main.py --web-only` | Run only the web dashboard interface |
| `python main.py --no-web` | Run in CLI-only mode without starting the web server |
| `python main.py --port 8080` | Change the web dashboard port |
| `python main.py --test-idle` | Push the idle screen (cover + clock + weather) immediately |
| `python main.py --test-pixoo` | Push a test pattern to verify Pixoo 64 connection |
| `python main.py --discover` | Scan the local network and list all Divoom displays |
| `python main.py --test-spotify` | Check Spotify auth and print the currently playing track |
| `python main.py --clear` | Clear the Pixoo 64 display |

---

## 🌐 Web Dashboard Preview & Controls

When you open `http://localhost:5050`, you have access to:

1. **LED Matrix Simulator**:
   - Toggle between **LED Matrix** (individual diode simulation with glare) and **Smooth** view.
   - Live mirror of what is on your physical Pixoo 64 screen.
2. **Now Playing Card**:
   - Displays real-time song title, artist, album, animated audio visualizer bars, and seek position.
3. **Ambient Card**:
   - Shows active Liked Songs cover being displayed, with a button to immediately trigger the next cover.
4. **Hardware Controls**:
   - Dynamic brightness slider that updates the physical Pixoo 64 in real-time.
   - Screen Clear and Test Graphic buttons.
5. **Preferences Form**:
   - Configure pause behaviors, cycle timers, 12h/24h clocks, and save directly to `.env`.

---

## 🐳 Running in Docker (e.g. Dockge on Proxmox)

The repo includes a `Dockerfile` and `compose.yaml`. Everything the container needs to keep
(`.env`, your Spotify login in `.cache-spotify`, and `listening_log.jsonl`) lives in a `data/` folder next to `compose.yaml`.

**1. Get the code onto the Docker host** (Dockge keeps stacks in `/opt/stacks` by default):

```bash
cd /opt/stacks
git clone https://github.com/getinet/SpotDivoom.git spotdivoom
mkdir -p spotdivoom/data
```

**2. Copy your settings and Spotify login** from a machine where SpotDivoom already runs.
Spotify sign-in needs a browser, so authorize once on your computer (`python main.py`), then copy the files:

```bash
scp .env .cache-spotify root@<docker-host>:/opt/stacks/spotdivoom/data/
```

Set `PIXOO_IP` in `data/.env` so the container doesn't depend on auto-discovery.

**3. Deploy:** in Dockge, use **Scan Stacks Folder**, open `spotdivoom`, set your `TZ` in the compose file, and click **Deploy**.
The dashboard is at `http://<docker-host>:5050`.

### Updating

```bash
cd /opt/stacks/spotdivoom
git pull
```

Then click **Deploy** in Dockge (or run `docker compose up -d`). `pull_policy: build` makes it rebuild from the new code.
Your `data/` folder is untouched, so settings, login and play history carry over.

## ⚙️ Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `SPOTIPY_CLIENT_ID` | `""` | Spotify developer Client ID |
| `SPOTIPY_CLIENT_SECRET` | `""` | Spotify developer Client Secret |
| `SPOTIPY_REDIRECT_URI` | `http://127.0.0.1:8888/callback` | OAuth redirect URI |
| `PIXOO_IP` | Auto-detect | IP address of your Pixoo 64 |
| `POLL_INTERVAL` | `3.0` | Seconds between Spotify playback status checks |
| `ON_PAUSE` | `idle` | Action on pause: `idle`, `keep`, `dim`, or `clear` |
| `IDLE_MODE` | `liked_tracks` | `liked_tracks` (cycle liked songs) or `spotify_logo` |
| `IDLE_CYCLE_INTERVAL` | `30.0` | Seconds between cycling album covers in idle mode |
| `USE_24H_TIME` | `false` | `false` for 12-hour clock, `true` for 24-hour |
| `ALWAYS_SHOW_HUD` | `true` | Keep the time & weather bar over album art while playing |
| `WEATHER_UNIT` | `F` | Temperature unit (`F` or `C`) |
| `WEATHER_CITY` | Auto-detect | Optional manual city name override |
| `ENHANCE_CONTRAST` | `1.0` | Contrast multiplier (`1.15` for punchier art) |
| `ENHANCE_COLOR` | `1.0` | Saturation multiplier (`1.2` for vibrant colors) |

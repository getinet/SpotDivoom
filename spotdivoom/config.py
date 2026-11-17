"""
Configuration loader for SpotDivoom.
Loads values from environment variables and .env file.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Where .env, the Spotify login cache and the play log live.
# Defaults to the project root; the Docker image points it at a mounted volume.
DATA_DIR = Path(os.getenv("DATA_DIR") or Path(__file__).resolve().parent.parent)
ENV_FILE = DATA_DIR / ".env"

# Find .env in the data directory or current working directory
if ENV_FILE.exists():
    load_dotenv(dotenv_path=ENV_FILE)
else:
    load_dotenv()


def _bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("true", "1", "yes")


@dataclass
class Settings:
    # Spotify settings
    spotify_client_id: str = os.getenv("SPOTIPY_CLIENT_ID", "")
    spotify_client_secret: str = os.getenv("SPOTIPY_CLIENT_SECRET", "")
    spotify_redirect_uri: str = os.getenv("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
    
    # Pixoo settings
    pixoo_ip: str = os.getenv("PIXOO_IP", "").strip()
    
    # App behavior
    poll_interval: float = float(os.getenv("POLL_INTERVAL", "3.0"))
    on_pause: str = os.getenv("ON_PAUSE", "keep").lower()  # 'keep', 'dim', or 'clear'
    dim_factor: float = float(os.getenv("DIM_FACTOR", "0.35"))
    
    # Image enhancement for LED pixels
    enhance_contrast: float = float(os.getenv("ENHANCE_CONTRAST", "1.0"))
    enhance_color: float = float(os.getenv("ENHANCE_COLOR", "1.0"))

    # Idle display settings
    # 'liked_tracks' (cycles covers of liked tracks with time & weather) or 'spotify_logo' (the SpotDivoom logo)
    idle_mode: str = os.getenv("IDLE_MODE", "liked_tracks").lower()
    idle_cycle_interval: float = float(os.getenv("IDLE_CYCLE_INTERVAL", "30.0"))
    use_24h_time: bool = os.getenv("USE_24H_TIME", "false").lower() in ("true", "1", "yes")
    # Keep the time & weather bar on screen while a song is playing too, not just when idle
    always_show_hud: bool = os.getenv("ALWAYS_SHOW_HUD", "true").lower() in ("true", "1", "yes")
    # Where the time & weather bar sits on the screen: 'bottom' or 'top'
    hud_position: str = "top" if os.getenv("HUD_POSITION", "bottom").strip().lower() == "top" else "bottom"
    # Tint the temperature and bar edge with a color picked from the album art
    hud_accent: bool = _bool("HUD_ACCENT", "true")
    # Thin song-progress line along the bar while a track plays
    show_progress: bool = _bool("SHOW_PROGRESS", "true")
    # Scroll the song title across the screen using the Pixoo's own text engine
    show_title: bool = _bool("SHOW_TITLE", "false")

    # Idle screens to rotate through: 'cover' and/or 'forecast' (comma separated)
    idle_screens: str = os.getenv("IDLE_SCREENS", "cover").strip().lower() or "cover"
    # Short cross-fade when the idle cover changes ('fade' or 'none')
    idle_transition: str = os.getenv("IDLE_TRANSITION", "none").strip().lower()
    # How many of your most recent Liked Songs the idle screen picks from
    liked_tracks_limit: int = int(os.getenv("LIKED_TRACKS_LIMIT", "500"))

    # Night mode: 'off', 'dim' (lower brightness), 'clock' (dim clock on black) or 'screen_off'
    night_mode: str = os.getenv("NIGHT_MODE", "off").strip().lower()
    night_start: str = os.getenv("NIGHT_START", "23:00").strip()
    night_end: str = os.getenv("NIGHT_END", "07:00").strip()
    night_brightness: int = int(os.getenv("NIGHT_BRIGHTNESS", "10"))

    # Weather settings
    weather_unit: str = os.getenv("WEATHER_UNIT", "F").upper()  # 'F' or 'C'
    weather_city: str = os.getenv("WEATHER_CITY", "")
    weather_lat: Optional[float] = float(os.getenv("WEATHER_LAT")) if os.getenv("WEATHER_LAT") else None
    weather_lon: Optional[float] = float(os.getenv("WEATHER_LON")) if os.getenv("WEATHER_LON") else None

    def has_spotify_credentials(self) -> bool:
        return bool(self.spotify_client_id and self.spotify_client_secret)


settings = Settings()

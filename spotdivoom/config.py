"""
Configuration loader for SpotDivoom.
Loads values from environment variables and .env file.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Find .env in project root or current working directory
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()


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
    # 'liked_tracks' (cycles covers of liked tracks with time & weather) or 'spotify_logo'
    idle_mode: str = os.getenv("IDLE_MODE", "liked_tracks").lower()
    idle_cycle_interval: float = float(os.getenv("IDLE_CYCLE_INTERVAL", "30.0"))
    use_24h_time: bool = os.getenv("USE_24H_TIME", "false").lower() in ("true", "1", "yes")

    # Weather settings
    weather_unit: str = os.getenv("WEATHER_UNIT", "F").upper()  # 'F' or 'C'
    weather_city: str = os.getenv("WEATHER_CITY", "")
    weather_lat: Optional[float] = float(os.getenv("WEATHER_LAT")) if os.getenv("WEATHER_LAT") else None
    weather_lon: Optional[float] = float(os.getenv("WEATHER_LON")) if os.getenv("WEATHER_LON") else None

    def has_spotify_credentials(self) -> bool:
        return bool(self.spotify_client_id and self.spotify_client_secret)


settings = Settings()

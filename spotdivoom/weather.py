"""
Weather service and pixel icon rendering using free Open-Meteo API.
Requires no API keys. Auto-detects location via IP or uses config values.
"""

import time
from dataclasses import dataclass
from typing import Optional
import requests
from PIL import ImageDraw


@dataclass
class WeatherInfo:
    temperature: int
    weather_code: int
    is_day: bool
    unit: str  # "°F" or "°C"
    city: str


class WeatherService:
    def __init__(
        self,
        city: str = "",
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        unit: str = "F",  # "F" or "C"
        cache_ttl_seconds: int = 600,
    ):
        self.city = city
        self.lat = lat
        self.lon = lon
        self.unit = unit.upper()
        self.cache_ttl = cache_ttl_seconds
        self._last_fetch_time: float = 0
        self._cached_weather: Optional[WeatherInfo] = None

    def _detect_location(self) -> bool:
        """
        Auto-detects approximate coordinates and city name via IP.
        """
        try:
            resp = requests.get("http://ip-api.com/json/", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                self.lat = data.get("lat")
                self.lon = data.get("lon")
                if not self.city:
                    self.city = data.get("city", "")
                return bool(self.lat and self.lon)
        except Exception:
            pass
        return False

    def get_weather(self) -> Optional[WeatherInfo]:
        """
        Fetches current weather from Open-Meteo, using cached data if fresh.
        """
        now = time.time()
        if self._cached_weather and (now - self._last_fetch_time) < self.cache_ttl:
            return self._cached_weather

        # Resolve coordinates if not set
        if self.lat is None or self.lon is None:
            if not self._detect_location():
                return self._cached_weather

        try:
            temp_unit_param = "fahrenheit" if self.unit == "F" else "celsius"
            url = (
                f"https://api.open-meteo.com/v1/forecast"
                f"?latitude={self.lat}&longitude={self.lon}"
                f"&current=temperature_2m,weather_code,is_day"
                f"&temperature_unit={temp_unit_param}"
            )
            resp = requests.get(url, timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                current = data.get("current", {})
                temp = round(current.get("temperature_2m", 0))
                code = int(current.get("weather_code", 0))
                is_day = bool(current.get("is_day", 1))

                self._cached_weather = WeatherInfo(
                    temperature=temp,
                    weather_code=code,
                    is_day=is_day,
                    unit=f"°{self.unit}",
                    city=self.city,
                )
                self._last_fetch_time = now
                return self._cached_weather
        except Exception:
            pass

        return self._cached_weather


def draw_pixel_weather_icon(draw: ImageDraw.ImageDraw, x: int, y: int, code: int, is_day: bool = True):
    """
    Renders a crisp 7x7 pixel art weather icon at top-left coordinate (x, y).
    """
    # Clear / Sunny / Starlit
    if code == 0:
        if is_day:
            # Sun: 4x4 gold core with orange rays
            draw.rectangle([x + 1, y + 1, x + 5, y + 5], fill=(255, 215, 0, 255))
            draw.point([(x + 3, y), (x + 3, y + 6), (x, y + 3), (x + 6, y + 3)], fill=(255, 175, 0, 255))
        else:
            # Crescent Moon
            draw.rectangle([x + 1, y + 1, x + 5, y + 5], fill=(225, 230, 245, 255))
            draw.rectangle([x + 3, y + 1, x + 5, y + 5], fill=(15, 15, 20, 200))

    # Mainly clear / Partly cloudy
    elif code in (1, 2):
        if is_day:
            # Sun peeking behind cloud
            draw.point([(x, y + 1), (x + 1, y), (x + 2, y)], fill=(255, 200, 0, 255))
        draw.rectangle([x + 1, y + 3, x + 6, y + 5], fill=(235, 235, 240, 255))
        draw.rectangle([x + 2, y + 2, x + 5, y + 3], fill=(235, 235, 240, 255))

    # Overcast / Fog
    elif code in (3, 45, 48):
        draw.rectangle([x + 1, y + 2, x + 6, y + 5], fill=(180, 185, 195, 255))
        draw.rectangle([x + 2, y + 1, x + 5, y + 2], fill=(215, 220, 230, 255))

    # Rain / Drizzle / Showers
    elif code in (51, 53, 55, 61, 63, 65, 66, 67, 80, 81, 82):
        draw.rectangle([x + 1, y + 1, x + 6, y + 3], fill=(185, 190, 200, 255))
        draw.point([(x + 2, y + 5), (x + 4, y + 6), (x + 5, y + 5)], fill=(75, 190, 255, 255))

    # Snow
    elif code in (71, 73, 75, 77, 85, 86):
        draw.rectangle([x + 1, y + 1, x + 6, y + 3], fill=(185, 190, 200, 255))
        draw.point([(x + 2, y + 5), (x + 4, y + 5), (x + 3, y + 6)], fill=(255, 255, 255, 255))

    # Thunderstorm
    elif code in (95, 96, 99):
        draw.rectangle([x + 1, y + 1, x + 6, y + 3], fill=(150, 155, 165, 255))
        draw.point([(x + 3, y + 4), (x + 4, y + 5), (x + 3, y + 6)], fill=(255, 230, 40, 255))

    # Fallback generic
    else:
        draw.rectangle([x + 1, y + 1, x + 5, y + 5], fill=(255, 210, 0, 255))

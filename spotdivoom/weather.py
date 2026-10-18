"""
Weather service and pixel icon rendering using free Open-Meteo API.
Requires no API keys. Auto-detects location via IP or uses config values.
"""

import time
from dataclasses import dataclass
from typing import Optional
import requests
from PIL import Image, ImageDraw


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


ICON_SIZE = 11


def _draw_cloud(draw: ImageDraw.ImageDraw, x: int, y: int, fill: tuple):
    """
    Draws an 11x5 pixel cloud with its top-left at (x, y).
    """
    draw.rectangle([x + 3, y, x + 6, y], fill=fill)
    draw.rectangle([x + 2, y + 1, x + 8, y + 1], fill=fill)
    draw.rectangle([x + 1, y + 2, x + 9, y + 2], fill=fill)
    draw.rectangle([x, y + 3, x + 10, y + 4], fill=fill)


def draw_pixel_weather_icon(draw: ImageDraw.ImageDraw, x: int, y: int, code: int, is_day: bool = True):
    """
    Renders a crisp 11x11 pixel art weather icon at top-left coordinate (x, y).
    """
    sun_core, sun_ray = (255, 215, 0, 255), (255, 165, 0, 255)
    moon = (225, 230, 245, 255)
    cloud_light, cloud_grey, cloud_dark = (235, 235, 240, 255), (185, 190, 200, 255), (140, 145, 155, 255)

    def draw_sun(sx: int, sy: int):
        draw.ellipse([sx + 3, sy + 3, sx + 7, sy + 7], fill=sun_core)
        draw.rectangle([sx + 5, sy, sx + 5, sy + 1], fill=sun_ray)
        draw.rectangle([sx + 5, sy + 9, sx + 5, sy + 10], fill=sun_ray)
        draw.rectangle([sx, sy + 5, sx + 1, sy + 5], fill=sun_ray)
        draw.rectangle([sx + 9, sy + 5, sx + 10, sy + 5], fill=sun_ray)
        draw.point([(sx + 1, sy + 1), (sx + 9, sy + 1), (sx + 1, sy + 9), (sx + 9, sy + 9)], fill=sun_ray)

    # Clear / Sunny / Starlit
    if code == 0:
        if is_day:
            draw_sun(x, y)
        else:
            # Crescent Moon: a disc with an offset disc cut out, so only the crescent is painted
            mask = Image.new("1", (ICON_SIZE, ICON_SIZE), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse([1, 1, 9, 9], fill=1)
            mask_draw.ellipse([4, 0, 10, 6], fill=0)
            draw.bitmap((x, y), mask, fill=moon)

    # Mainly clear / Partly cloudy
    elif code in (1, 2):
        if is_day:
            draw.ellipse([x + 5, y, x + 10, y + 5], fill=sun_core)
        else:
            draw.ellipse([x + 5, y, x + 10, y + 5], fill=moon)
        _draw_cloud(draw, x, y + 5, cloud_light)

    # Overcast
    elif code == 3:
        _draw_cloud(draw, x, y + 3, cloud_grey)
        draw.rectangle([x + 3, y + 3, x + 6, y + 3], fill=cloud_light)

    # Fog
    elif code in (45, 48):
        for row, inset in ((2, 0), (5, 1), (8, 0)):
            draw.rectangle([x + 1 + inset, y + row, x + 9 + inset, y + row], fill=cloud_grey)

    # Rain / Drizzle / Showers
    elif code in (51, 53, 55, 61, 63, 65, 66, 67, 80, 81, 82):
        _draw_cloud(draw, x, y + 1, cloud_grey)
        for dx, dy in ((2, 7), (5, 8), (8, 7)):
            draw.rectangle([x + dx, y + dy, x + dx, y + dy + 1], fill=(75, 190, 255, 255))

    # Snow
    elif code in (71, 73, 75, 77, 85, 86):
        _draw_cloud(draw, x, y + 1, cloud_grey)
        draw.point([(x + 2, y + 7), (x + 8, y + 7), (x + 5, y + 8), (x + 3, y + 10), (x + 7, y + 10)],
                   fill=(255, 255, 255, 255))

    # Thunderstorm
    elif code in (95, 96, 99):
        _draw_cloud(draw, x, y + 1, cloud_dark)
        draw.line([(x + 6, y + 6), (x + 4, y + 8), (x + 6, y + 8), (x + 4, y + 10)], fill=(255, 230, 40, 255))

    # Fallback generic
    else:
        draw_sun(x, y)

"""
Display and image processing utilities for Divoom Pixoo 64.
"""

import datetime
from typing import Optional
from PIL import Image, ImageDraw, ImageEnhance, ImageFont
from .weather import WeatherInfo, draw_pixel_weather_icon


def process_image_for_pixoo(
    img: Image.Image,
    target_size: tuple[int, int] = (64, 64),
    contrast: float = 1.0,
    color: float = 1.0,
    brightness: float = 1.0,
) -> Image.Image:
    """
    Crops, resizes, and optionally enhances an image for the 64x64 LED matrix.
    """
    # Ensure RGB
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Center crop to square if needed
    width, height = img.size
    if width != height:
        min_dim = min(width, height)
        left = (width - min_dim) // 2
        top = (height - min_dim) // 2
        img = img.crop((left, top, left + min_dim, top + min_dim))

    # High quality downscale
    if img.size != target_size:
        img = img.resize(target_size, Image.Resampling.LANCZOS)

    # Optional color & contrast adjustments
    if color != 1.0:
        img = ImageEnhance.Color(img).enhance(color)
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)
    if brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(brightness)

    return img


def create_spotify_idle_image() -> Image.Image:
    """
    Generates a crisp 64x64 pixel art Spotify icon on a dark background.
    """
    img = Image.new("RGB", (64, 64), color=(18, 18, 18))
    draw = ImageDraw.Draw(img)

    # Spotify Green circle (centered)
    center_x, center_y, radius = 32, 32, 22
    draw.ellipse(
        [center_x - radius, center_y - radius, center_x + radius, center_y + radius],
        fill=(30, 215, 96),  # Spotify green (#1ED760)
    )

    # Three characteristic Spotify curved sound wave bars
    # Top arc
    draw.arc([17, 18, 47, 48], start=205, end=335, fill=(18, 18, 18), width=3)
    # Middle arc
    draw.arc([21, 25, 43, 47], start=205, end=335, fill=(18, 18, 18), width=3)
    # Bottom arc
    draw.arc([25, 31, 39, 45], start=205, end=335, fill=(18, 18, 18), width=2)

    return img


def create_blank_image(size: tuple[int, int] = (64, 64)) -> Image.Image:
    """
    Returns an all-black image.
    """
    return Image.new("RGB", size, color=(0, 0, 0))


def render_idle_cover_with_hud(
    cover_img: Image.Image,
    weather: Optional[WeatherInfo] = None,
    use_24h: bool = False,
    contrast: float = 1.0,
    color: float = 1.0,
) -> Image.Image:
    """
    Overlays a sleek, semi-transparent HUD at the bottom of the album cover
    displaying the local time (left) and current weather/temperature (right).
    """
    # 1. Base album art processing (slightly dim background for maximum HUD legibility)
    base = process_image_for_pixoo(
        cover_img,
        contrast=contrast,
        color=color,
        brightness=0.88,
    ).convert("RGBA")

    # 2. Overlay layer
    overlay = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Gradient dark bar from y=45 to y=63
    for y in range(45, 64):
        alpha = int(225 * ((y - 44) / 19.0))
        draw.line([(0, y), (63, y)], fill=(6, 8, 12, alpha))

    # Subtle translucent highlight line
    draw.line([(0, 45), (63, 45)], fill=(255, 255, 255, 28))

    font = ImageFont.load_default()

    # Time display
    now = datetime.datetime.now()
    if use_24h:
        time_str = now.strftime("%H:%M")
    else:
        time_str = now.strftime("%I:%M").lstrip("0")
        if not time_str:
            time_str = "12:00"

    draw.text((3, 50), time_str, fill=(255, 255, 255, 255), font=font)

    # Weather display
    if weather is not None:
        temp_str = f"{weather.temperature}°"
        tb = draw.textbbox((0, 0), temp_str, font=font)
        tw = tb[2] - tb[0]
        tx = 64 - tw - 2
        draw.text((tx, 50), temp_str, fill=(255, 225, 115, 255), font=font)
        draw_pixel_weather_icon(draw, tx - 9, 51, weather.weather_code, weather.is_day)

    return Image.alpha_composite(base, overlay).convert("RGB")


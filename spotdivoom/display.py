"""
Display and image processing utilities for Divoom Pixoo 64.
"""

import datetime
from typing import Optional
from PIL import Image, ImageDraw, ImageEnhance, ImageFont
from .weather import ICON_SIZE, WeatherInfo, draw_pixel_weather_icon


def load_bold_font(size: int) -> ImageFont.ImageFont:
    """
    Returns a bold sans-serif font, trying macOS, Windows and Linux names in turn.
    """
    for name in ("Arial Bold.ttf", "arialbd.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


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
    brightness: float = 0.88,
    position: str = "bottom",
) -> Image.Image:
    """
    Overlays a sleek, semi-transparent HUD at the bottom (or top) of the album cover
    displaying the local time (left) and current weather/temperature (right).
    """
    at_top = position == "top"
    # 1. Base album art processing (slightly dim background for maximum HUD legibility)
    base = process_image_for_pixoo(
        cover_img,
        contrast=contrast,
        color=color,
        brightness=brightness,
    ).convert("RGBA")

    # 2. Overlay layer
    overlay = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # 19-row gradient bar, darkest at the screen edge: y=45..63 (bottom) or y=0..18 (top)
    for i in range(19):
        alpha = int(225 * ((i + 1) / 19.0))
        y = 18 - i if at_top else 45 + i
        draw.line([(0, y), (63, y)], fill=(6, 8, 12, alpha))

    # Subtle translucent highlight line on the edge facing the artwork
    edge_y = 18 if at_top else 45
    draw.line([(0, edge_y), (63, edge_y)], fill=(255, 255, 255, 28))

    # 18-row text area inside the bar
    area_top = 0 if at_top else 46

    # Crisp, non-antialiased pixels read far better on the LED matrix
    draw.fontmode = "1"

    # Time display
    now = datetime.datetime.now()
    if use_24h:
        time_str = now.strftime("%H:%M")
    else:
        time_str = now.strftime("%I:%M").lstrip("0")
        if not time_str:
            time_str = "12:00"
    temp_str = f"{weather.temperature}°" if weather is not None else ""

    # Largest bold size where time + icon + temperature still fit on one row
    size = 13
    while True:
        font = load_bold_font(size)
        time_box = draw.textbbox((0, 0), time_str, font=font)
        temp_box = draw.textbbox((0, 0), temp_str, font=font) if temp_str else (0, 0, 0, 0)
        needed = (time_box[2] - time_box[0]) + (temp_box[2] - temp_box[0]) + (ICON_SIZE + 4 if temp_str else 0) + 4
        if needed <= 64 or size <= 8:
            break
        size -= 1

    # Vertically center text in the bar, with a dark outline for contrast
    text_top = area_top + (18 - (time_box[3] - time_box[1])) // 2
    outline = (0, 0, 0, 255)
    draw.text((2 - time_box[0], text_top - time_box[1]), time_str, fill=(255, 255, 255, 255),
              font=font, stroke_width=1, stroke_fill=outline)

    # Weather display
    if weather is not None:
        tx = 64 - (temp_box[2] - temp_box[0]) - 2
        draw.text((tx - temp_box[0], text_top - time_box[1]), temp_str, fill=(255, 215, 90, 255),
                  font=font, stroke_width=1, stroke_fill=outline)
        draw_pixel_weather_icon(draw, tx - ICON_SIZE - 2, area_top + (18 - ICON_SIZE) // 2,
                                weather.weather_code, weather.is_day)

    return Image.alpha_composite(base, overlay).convert("RGB")


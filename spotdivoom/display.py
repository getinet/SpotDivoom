"""
Display and image processing utilities for Divoom Pixoo 64.
"""

import colorsys
import datetime
from pathlib import Path
from typing import Optional
from PIL import Image, ImageDraw, ImageEnhance, ImageFont
from .weather import ICON_SIZE, WeatherInfo, draw_pixel_weather_icon

Color = tuple[int, int, int]

DEFAULT_ACCENT: Color = (255, 215, 90)
BAR_COLOR = (6, 8, 12)
SCREEN_BG: Color = (8, 10, 14)


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


# ---------- Tiny 3x5 pixel font for small labels (crisper than any TrueType at this size) ----------

_GLYPHS = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "-": ("000", "000", "111", "000", "000"),
    ":": ("0", "1", "0", "1", "0"),
    "°": ("11", "11", "00", "00", "00"),
    "A": ("010", "101", "111", "101", "101"),
    "P": ("110", "101", "110", "100", "100"),
    "M": ("101", "111", "111", "101", "101"),
    "^": ("010", "111", "000", "000", "000"),
    "v": ("000", "000", "000", "111", "010"),
    " ": ("00", "00", "00", "00", "00"),
}


def tiny_text_width(text: str) -> int:
    widths = [len(_GLYPHS.get(ch, _GLYPHS[" "])[0]) for ch in text]
    return sum(widths) + max(0, len(widths) - 1)


def draw_tiny_text(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, fill) -> int:
    """
    Draws text in the 3x5 pixel font with its top-left at (x, y); returns the width drawn.
    """
    cx = x
    for ch in text:
        glyph = _GLYPHS.get(ch, _GLYPHS[" "])
        for row, bits in enumerate(glyph):
            for col, bit in enumerate(bits):
                if bit == "1":
                    draw.point((cx + col, y + row), fill=fill)
        cx += len(glyph[0]) + 1
    return cx - x - 1


# ---------- Image helpers ----------

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


def accent_from_cover(img: Image.Image) -> Color:
    """
    Picks a vivid color from the album art for the HUD, brightened so it reads on LEDs.
    Falls back to warm yellow for grey or very dark covers.
    """
    small = img.convert("RGB").resize((32, 32))
    quantized = small.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette() or []
    best, best_score = None, 0.0
    for count, idx in quantized.getcolors() or []:
        r, g, b = palette[idx * 3: idx * 3 + 3]
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if v < 0.2 or s < 0.3:
            continue
        score = count * (s ** 1.5) * v
        if score > best_score:
            best, best_score = (h, s), score
    if best is None:
        return DEFAULT_ACCENT
    h, s = best
    r, g, b = colorsys.hsv_to_rgb(h, max(s, 0.55), 1.0)
    return (int(r * 255), int(g * 255), int(b * 255))


def crossfade_frames(a: Image.Image, b: Image.Image, steps: int = 3) -> list[Image.Image]:
    """
    Intermediate frames from a to b (excluding both ends).
    """
    a, b = a.convert("RGB"), b.convert("RGB")
    return [Image.blend(a, b, i / (steps + 1)) for i in range(1, steps + 1)]


LOGO_64_PATH = Path(__file__).resolve().parent / "web" / "static" / "img" / "logo-64.png"


def create_logo_idle_image() -> Image.Image:
    """
    The SpotDivoom mark (Lichen Grid) drawn for the 64x64 panel; shown before any cover is available.
    """
    try:
        return Image.open(LOGO_64_PATH).convert("RGB")
    except OSError:
        return Image.new("RGB", (64, 64), SCREEN_BG)


def create_blank_image(size: tuple[int, int] = (64, 64)) -> Image.Image:
    """
    Returns an all-black image.
    """
    return Image.new("RGB", size, color=(0, 0, 0))


def _time_string(use_24h: bool, now: Optional[datetime.datetime] = None) -> str:
    now = now or datetime.datetime.now()
    if use_24h:
        return now.strftime("%H:%M")
    return now.strftime("%I:%M").lstrip("0") or "12:00"


# ---------- The time & weather bar ----------

def _draw_hud(
    draw: ImageDraw.ImageDraw,
    weather: Optional[WeatherInfo],
    use_24h: bool,
    position: str,
    accent: Optional[Color],
    progress: Optional[float],
):
    at_top = position == "top"
    accent = accent or DEFAULT_ACCENT

    # 19-row gradient bar, darkest at the screen edge: y=45..63 (bottom) or y=0..18 (top)
    for i in range(19):
        alpha = int(225 * ((i + 1) / 19.0))
        y = 18 - i if at_top else 45 + i
        draw.line([(0, y), (63, y)], fill=BAR_COLOR + (alpha,))

    # Translucent edge line facing the artwork; doubles as the song-progress line
    edge_y = 18 if at_top else 45
    draw.line([(0, edge_y), (63, edge_y)], fill=(255, 255, 255, 28))
    if progress is not None:
        filled = int(round(64 * max(0.0, min(1.0, progress))))
        if filled > 0:
            draw.line([(0, edge_y), (filled - 1, edge_y)], fill=accent + (235,))

    # 18-row text area inside the bar
    area_top = 0 if at_top else 46

    # Crisp, non-antialiased pixels read far better on the LED matrix
    draw.fontmode = "1"

    time_str = _time_string(use_24h)
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

    if weather is not None:
        tx = 64 - (temp_box[2] - temp_box[0]) - 2
        draw.text((tx - temp_box[0], text_top - time_box[1]), temp_str, fill=accent + (255,),
                  font=font, stroke_width=1, stroke_fill=outline)
        draw_pixel_weather_icon(draw, tx - ICON_SIZE - 2, area_top + (18 - ICON_SIZE) // 2,
                                weather.weather_code, weather.is_day)


def render_idle_cover_with_hud(
    cover_img: Image.Image,
    weather: Optional[WeatherInfo] = None,
    use_24h: bool = False,
    contrast: float = 1.0,
    color: float = 1.0,
    brightness: float = 0.88,
    position: str = "bottom",
    accent: Optional[Color] = None,
    progress: Optional[float] = None,
    text_band_y: Optional[int] = None,
) -> Image.Image:
    """
    Overlays a sleek, semi-transparent HUD at the bottom (or top) of the album cover
    displaying the local time (left) and current weather/temperature (right).

    accent: color for the temperature and progress line (default warm yellow)
    progress: 0..1 song progress drawn along the bar's inner edge, or None
    text_band_y: darken a 10-row strip from this y so scrolling device text stays readable
    """
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
    if text_band_y is not None:
        add_text_band(draw, text_band_y)
    _draw_hud(draw, weather, use_24h, position, accent, progress)

    return Image.alpha_composite(base, overlay).convert("RGB")


def add_text_band(draw: ImageDraw.ImageDraw, y: int):
    top, bottom = max(0, y - 1), min(63, y + 9)
    draw.rectangle([0, top, 63, bottom], fill=BAR_COLOR + (150,))


def render_cover_with_text_band(img: Image.Image, text_band_y: int) -> Image.Image:
    """
    Darkens the strip under the scrolling title on a frame that has no HUD.
    """
    base = img.convert("RGBA")
    overlay = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    add_text_band(ImageDraw.Draw(overlay), text_band_y)
    return Image.alpha_composite(base, overlay).convert("RGB")


# ---------- Other screens ----------

def _hour_label(hour: datetime.datetime, use_24h: bool) -> str:
    if use_24h:
        return f"{hour.hour:02d}"
    h = hour.hour % 12 or 12
    return f"{h}{'A' if hour.hour < 12 else 'P'}"


def render_forecast_screen(
    weather: Optional[WeatherInfo],
    use_24h: bool = False,
    position: str = "bottom",
) -> Image.Image:
    """
    Idle screen with the time & weather bar plus the next hours and today's sunrise/sunset.
    The bar stays where the user put it; the forecast fills the rest.
    """
    base = Image.new("RGBA", (64, 64), SCREEN_BG + (255,))
    overlay = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    _draw_hud(draw, weather, use_24h, position, None, None)

    # Forecast block occupies the 45 rows the bar doesn't
    top = 21 if position == "top" else 1
    label_color = (150, 160, 175, 255)
    temp_color = DEFAULT_ACCENT + (255,)

    hours = (weather.hourly if weather else [])[3::3][:4]
    for i, h in enumerate(hours):
        x0 = i * 16
        label = _hour_label(h.hour, use_24h)
        draw_tiny_text(draw, x0 + (16 - tiny_text_width(label)) // 2, top, label, label_color)
        draw_pixel_weather_icon(draw, x0 + (16 - ICON_SIZE) // 2, top + 8, h.weather_code, h.is_day)
        temp = f"{h.temperature}°"
        draw_tiny_text(draw, x0 + (16 - tiny_text_width(temp)) // 2, top + 22, temp, temp_color)

    if weather and weather.sunrise and weather.sunset:
        y = top + 33
        rise = "^" + _time_string(use_24h, weather.sunrise)
        sets = "v" + _time_string(use_24h, weather.sunset)
        draw_tiny_text(draw, 2, y, rise, (255, 200, 90, 255))
        draw_tiny_text(draw, 62 - tiny_text_width(sets), y, sets, (255, 130, 70, 255))
    elif not hours:
        msg = "--°"
        draw_tiny_text(draw, (64 - tiny_text_width(msg)) // 2, top + 18, msg, label_color)

    return Image.alpha_composite(base, overlay).convert("RGB")


def render_night_clock(use_24h: bool = False, weather: Optional[WeatherInfo] = None) -> Image.Image:
    """
    Night mode screen: a dim, warm clock on black that won't light up the room.
    """
    img = Image.new("RGB", (64, 64), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.fontmode = "1"
    time_str = _time_string(use_24h)
    size = 18
    while True:
        font = load_bold_font(size)
        box = draw.textbbox((0, 0), time_str, font=font)
        if box[2] - box[0] <= 60 or size <= 10:
            break
        size -= 1
    w, h = box[2] - box[0], box[3] - box[1]
    draw.text(((64 - w) // 2 - box[0], 24 - h // 2 - box[1]), time_str, fill=(120, 60, 25), font=font)
    if weather is not None:
        temp = f"{weather.temperature}°"
        draw_tiny_text(draw, (64 - tiny_text_width(temp)) // 2, 42, temp, (70, 40, 20))
    return img

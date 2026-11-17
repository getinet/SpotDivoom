from PIL import Image

from spotdivoom import display


def _row_brightness(img: Image.Image, y: int) -> float:
    return sum(sum(img.getpixel((x, y))) for x in range(64)) / 64


def _white_cover() -> Image.Image:
    return Image.new("RGB", (300, 300), (240, 240, 240))


def test_bar_sits_at_bottom_by_default(weather):
    frame = display.render_idle_cover_with_hud(_white_cover(), weather)
    assert frame.size == (64, 64)
    # The bar darkens the bottom edge, not the top
    assert _row_brightness(frame, 63) < _row_brightness(frame, 0) / 2


def test_bar_moves_to_top(weather):
    frame = display.render_idle_cover_with_hud(_white_cover(), weather, position="top")
    assert _row_brightness(frame, 0) < _row_brightness(frame, 63) / 2


def test_progress_line_uses_accent_up_to_progress(weather):
    accent = (255, 0, 0)
    frame = display.render_idle_cover_with_hud(_white_cover(), weather, accent=accent, progress=0.5)
    left, right = frame.getpixel((10, 45)), frame.getpixel((54, 45))
    assert left[0] > 200 and left[1] < 80          # red: inside the played half
    assert not (right[0] > 200 and right[1] < 80)  # not red: still to play


def test_no_progress_line_when_disabled(weather):
    accent = (255, 0, 0)
    frame = display.render_idle_cover_with_hud(_white_cover(), weather, accent=accent, progress=None)
    px = frame.getpixel((10, 45))
    assert not (px[0] > 200 and px[1] < 80)


def test_accent_picks_vivid_color_and_falls_back_on_grey():
    blue = Image.new("RGB", (100, 100), (20, 40, 200))
    r, g, b = display.accent_from_cover(blue)
    assert b == 255 and r < 150
    assert display.accent_from_cover(Image.new("RGB", (100, 100), (128, 128, 128))) == display.DEFAULT_ACCENT


def test_tiny_text_width_matches_drawing():
    img = Image.new("RGB", (64, 8))
    from PIL import ImageDraw
    drawn = display.draw_tiny_text(ImageDraw.Draw(img), 0, 0, "12:34", (255, 255, 255))
    assert drawn == display.tiny_text_width("12:34") == 3 + 1 + 3 + 1 + 1 + 1 + 3 + 1 + 3


def test_forecast_and_night_screens_render(weather):
    for position in ("bottom", "top"):
        assert display.render_forecast_screen(weather, position=position).size == (64, 64)
    assert display.render_forecast_screen(None).size == (64, 64)
    night = display.render_night_clock(False, weather)
    # Dim: nothing on the night clock is brighter than a warm glow
    assert max(max(px) for px in night.getdata()) <= 120


def test_crossfade_frames_are_between_endpoints():
    a, b = Image.new("RGB", (64, 64), (0, 0, 0)), Image.new("RGB", (64, 64), (200, 200, 200))
    steps = display.crossfade_frames(a, b, steps=3)
    values = [f.getpixel((0, 0))[0] for f in steps]
    assert values == sorted(values) and 0 < values[0] and values[-1] < 200


def test_logo_image_is_panel_sized():
    assert display.create_logo_idle_image().size == (64, 64)

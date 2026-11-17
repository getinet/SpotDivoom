"""
Builds design/logo/index.html: the Lichen Grid logo in the dashboard header, at small sizes,
and on the Pixoo (rendered with the app's own code).

Run from the repo root:  .venv/bin/python design/logo/build.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from spotdivoom.display import create_logo_idle_image, render_idle_cover_with_hud  # noqa: E402
from spotdivoom.weather import WeatherInfo  # noqa: E402

HERE = Path(__file__).resolve().parent


def main():
    # The header mark lives inline in the dashboard template; reuse it so the demo can't drift
    template = (ROOT / "spotdivoom/web/templates/index.html").read_text()
    match = re.search(r'<div class="brand-icon">\s*<svg[^>]*>(.*?)</svg>', template, re.S)
    if not match:
        sys.exit("Could not find the logo SVG in index.html")
    symbol = f'<symbol id="mark" viewBox="0 0 64 64">{match.group(1).strip()}</symbol>'

    page = (HERE / "index.template.html").read_text().replace("{{SYMBOL}}", symbol)
    (HERE / "index.html").write_text(page)

    weather = WeatherInfo(66, 2, True, "°F", "Demo")
    logo = create_logo_idle_image()
    logo.save(HERE / "led-logo.png")
    render_idle_cover_with_hud(logo, weather, position="bottom").save(HERE / "led-hud-bottom.png")
    render_idle_cover_with_hud(logo, weather, position="top").save(HERE / "led-hud-top.png")
    print(f"Wrote {HERE / 'index.html'}")


if __name__ == "__main__":
    main()

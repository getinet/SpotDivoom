#!/usr/bin/env python3
"""
SpotDivoom - Spotify Album Art on Divoom Pixoo 64.

Usage:
    python main.py                  # Run the Spotify watcher daemon
    python main.py --discover       # Discover Pixoo devices on your local network
    python main.py --test-pixoo     # Send a test graphic to verify Pixoo communication
    python main.py --test-spotify   # Check Spotify connection and current playback
    python main.py --clear          # Clear the Pixoo 64 screen
"""

import argparse
import sys

from spotdivoom.app import SpotDivoomApp, print_banner
from spotdivoom.config import settings
from spotdivoom.display import create_blank_image, create_logo_idle_image
from spotdivoom.pixoo import PixooClient
from spotdivoom.spotify import PlaybackUnavailable, SpotifyWatcher


def cmd_discover():
    print_banner()
    print("[*] Scanning local network for Divoom devices...")
    devices = PixooClient.discover_devices()
    if not devices:
        print("[!] No Divoom devices found via LAN discovery.")
        print("    Ensure your Pixoo 64 is turned on and connected to the same Wi-Fi.")
        return

    print(f"[✓] Found {len(devices)} device(s):")
    for i, dev in enumerate(devices, 1):
        name = dev.get("DeviceName", "Unknown")
        ip = dev.get("DevicePrivateIP", "Unknown IP")
        mac = dev.get("DeviceMac", "Unknown MAC")
        dev_id = dev.get("DeviceId", "")
        print(f"  {i}. {name} | IP: {ip} | MAC: {mac} | ID: {dev_id}")
    print("\nTip: You can add 'PIXOO_IP=<IP>' to your .env file or leave it blank to auto-detect.")


def cmd_test_pixoo():
    print_banner()
    print("[*] Testing communication with Pixoo 64...")
    client = PixooClient(ip=settings.pixoo_ip)
    if not client.ensure_connected():
        print("[!] Could not connect to Pixoo 64.")
        sys.exit(1)

    print(f"[✓] Successfully connected to Pixoo 64 at {client.ip}")
    print("[*] Sending test graphic...")
    test_img = create_logo_idle_image()
    if client.send_image(test_img):
        print("[✓] Test image successfully sent to your Pixoo 64 display!")
    else:
        print("[!] Failed to send image to device.")
        sys.exit(1)


def cmd_test_spotify():
    print_banner()
    if not settings.has_spotify_credentials():
        print("[!] Spotify credentials not set. Fill in SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET in .env.")
        sys.exit(1)

    print("[*] Connecting to Spotify...")
    watcher = SpotifyWatcher(
        client_id=settings.spotify_client_id,
        client_secret=settings.spotify_client_secret,
        redirect_uri=settings.spotify_redirect_uri,
    )
    if not watcher.is_authorized() and not watcher.authorize_interactively():
        print("[!] Not logged in to Spotify. Run 'python main.py' and log in from the dashboard.")
        sys.exit(1)
    try:
        track = watcher.get_current_track()
    except PlaybackUnavailable as e:
        print(f"[!] Spotify request failed: {e}")
        sys.exit(1)
    if track is None:
        print("[✓] Connected to Spotify, but nothing is currently playing.")
    else:
        status = "Playing" if track.is_playing else "Paused"
        print(f"[✓] Current Track ({status}):")
        print(f"    Title:  {track.title}")
        print(f"    Artist: {track.artist}")
        print(f"    Album:  {track.album}")
        print(f"    Cover:  {track.image_url}")


def cmd_clear():
    print("[*] Clearing Pixoo 64 display...")
    client = PixooClient(ip=settings.pixoo_ip)
    if client.ensure_connected() and client.clear():
        print("[✓] Display cleared.")
    else:
        print("[!] Failed to clear display.")


def cmd_test_idle():
    from spotdivoom.display import render_idle_cover_with_hud, create_logo_idle_image
    from spotdivoom.weather import WeatherService
    import datetime

    print_banner()
    print("[*] Testing Idle Clock & Weather HUD...")

    # 1. Weather
    ws = WeatherService(
        city=settings.weather_city,
        lat=settings.weather_lat,
        lon=settings.weather_lon,
        unit=settings.weather_unit,
    )
    weather = ws.get_weather()
    if weather:
        print(f"[✓] Weather: {weather.temperature}{weather.unit} in {weather.city} (code {weather.weather_code})")
    else:
        print("[!] Weather unavailable (network or location issue).")

    # 2. Cover image (liked track or Spotify idle)
    cover_img = None
    cover_title = "SpotDivoom logo"
    if settings.has_spotify_credentials():
        try:
            watcher = SpotifyWatcher(
                client_id=settings.spotify_client_id,
                client_secret=settings.spotify_client_secret,
                redirect_uri=settings.spotify_redirect_uri,
            )
            if watcher.is_authorized():
                liked = watcher.get_random_liked_track()
                if liked:
                    img = watcher.fetch_image(liked.image_url)
                    if img:
                        cover_img = img
                        cover_title = f"{liked.title} by {liked.artist}"
            else:
                print("[*] Spotify login pending (run 'python main.py' to authorize). Using preview background.")
        except Exception:
            pass

    if cover_img is None:
        cover_img = create_logo_idle_image()

    print(f"[✓] Using background cover: {cover_title}")

    # 3. Render HUD
    frame = render_idle_cover_with_hud(
        cover_img,
        weather=weather,
        use_24h=settings.use_24h_time,
        contrast=settings.enhance_contrast,
        color=settings.enhance_color,
        position=settings.hud_position,
    )

    # 4. Send to Pixoo
    client = PixooClient(ip=settings.pixoo_ip)
    if not client.ensure_connected():
        print("[!] Could not connect to Pixoo 64.")
        sys.exit(1)

    if client.send_image(frame):
        time_str = datetime.datetime.now().strftime("%H:%M" if settings.use_24h_time else "%-I:%M %p")
        print(f"[✓] Idle display pushed to Pixoo 64 at {client.ip} (Time: {time_str})!")
    else:
        print("[!] Failed to send image to Pixoo.")


def cmd_web_only(host="0.0.0.0", port=5050):
    from spotdivoom.server import app
    print_banner()
    print(f"[🌐] Starting SpotDivoom Web Dashboard on http://localhost:{port}")
    print("    Press Ctrl+C to stop.")
    app.run(host=host, port=port, debug=False)


def main():
    parser = argparse.ArgumentParser(
        description="SpotDivoom - Display Spotify Album Art on Divoom Pixoo 64"
    )
    parser.add_argument("--discover", action="store_true", help="Discover Pixoo devices on the LAN")
    parser.add_argument("--test-pixoo", action="store_true", help="Send test graphic to Pixoo 64")
    parser.add_argument("--test-spotify", action="store_true", help="Test Spotify playback API")
    parser.add_argument("--test-idle", action="store_true", help="Test idle display (liked track cover + time + weather)")
    parser.add_argument("--clear", action="store_true", help="Clear the Pixoo 64 display")
    parser.add_argument("--web-only", action="store_true", help="Run only the web dashboard")
    parser.add_argument("--no-web", action="store_true", help="Disable the web dashboard")
    parser.add_argument("--port", type=int, default=5050, help="Web dashboard port (default: 5050)")

    args = parser.parse_args()

    if args.discover:
        cmd_discover()
    elif args.test_pixoo:
        cmd_test_pixoo()
    elif args.test_spotify:
        cmd_test_spotify()
    elif args.test_idle:
        cmd_test_idle()
    elif args.clear:
        cmd_clear()
    elif args.web_only:
        cmd_web_only(port=args.port)
    else:
        # Start web dashboard in background thread unless --no-web specified
        if not args.no_web:
            import threading
            import logging
            from spotdivoom.server import app

            # Mute default werkzeug access logs to keep terminal pristine
            logging.getLogger("werkzeug").setLevel(logging.ERROR)

            web_thread = threading.Thread(
                target=lambda: app.run(host="0.0.0.0", port=args.port, debug=False, use_reloader=False),
                daemon=True,
            )
            web_thread.start()
            print(f"\033[96m[🌐] Web Dashboard running at \033[1mhttp://localhost:{args.port}\033[0m")

        app_instance = SpotDivoomApp()
        app_instance.run()


if __name__ == "__main__":
    main()

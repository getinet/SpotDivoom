"""
Main application loop and controller for SpotDivoom.
"""

import datetime
import signal
import sys
import time
from typing import Optional
from PIL import Image

from .config import settings
from .display import (
    create_blank_image,
    create_spotify_idle_image,
    process_image_for_pixoo,
    render_idle_cover_with_hud,
)
from .pixoo import PixooClient
from .spotify import SpotifyWatcher, TrackInfo
from .stats import record_play
from .weather import WeatherService

# ANSI styling helpers
GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
DIM = "\033[90m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_banner():
    print(f"""
{GREEN}{BOLD}╔══════════════════════════════════════════════════════╗
║                    SpotDivoom 64                     ║
║         Spotify Album Art on Divoom Pixoo 64         ║
╚══════════════════════════════════════════════════════╝{RESET}
""")


def print_spotify_setup_guide():
    print(f"""{YELLOW}{BOLD}[!] Spotify Developer credentials not configured.{RESET}

To link SpotDivoom with your Spotify account:
1. Open {CYAN}https://developer.spotify.com/dashboard{RESET} and log in.
2. Click {BOLD}'Create App'{RESET}:
   • App name: {BOLD}SpotDivoom{RESET}
   • Redirect URI: {BOLD}http://127.0.0.1:8888/callback{RESET}
   • APIs used: check {BOLD}Web API{RESET}
3. Go to Settings on your new app and copy:
   • {BOLD}Client ID{RESET}
   • {BOLD}Client Secret{RESET}
4. Paste them into your {BOLD}.env{RESET} file:
   {GREEN}SPOTIPY_CLIENT_ID=your_client_id_here
   SPOTIPY_CLIENT_SECRET=your_client_secret_here{RESET}
""")


class SpotDivoomApp:
    def __init__(self):
        self.running = True
        self.pixoo: Optional[PixooClient] = None
        self.spotify: Optional[SpotifyWatcher] = None
        self.weather_service: Optional[WeatherService] = None
        
        # Playback tracking
        self.last_track_id: Optional[str] = None
        self.last_is_playing: Optional[bool] = None
        self.current_processed_img: Optional[Image.Image] = None
        self.current_raw_cover: Optional[Image.Image] = None
        self.last_hud_minute: int = -1

        # Idle screen tracking (cycling liked tracks + time + weather)
        self.current_idle_cover: Optional[Image.Image] = None
        self.current_idle_title: str = "Liked Tracks"
        self.last_idle_cycle_time: float = 0
        self.last_idle_minute: int = -1

    def setup_signals(self):
        signal.signal(signal.SIGINT, self._handle_exit)
        signal.signal(signal.SIGTERM, self._handle_exit)

    def _handle_exit(self, signum, frame):
        print(f"\n{YELLOW}Stopping SpotDivoom... Goodbye!{RESET}")
        self.running = False
        sys.exit(0)

    def initialize(self) -> bool:
        print_banner()

        # 1. Check Spotify Credentials
        if not settings.has_spotify_credentials():
            print_spotify_setup_guide()
            return False

        # 2. Connect to Pixoo 64
        print(f"[*] Connecting to Pixoo 64...")
        self.pixoo = PixooClient(ip=settings.pixoo_ip)

        if not self.pixoo.ensure_connected():
            print(f"{YELLOW}[!] Could not locate or connect to Pixoo 64.{RESET}")
            print(f"    Check that your device is powered on and on the same Wi-Fi.")
            print(f"    You can also manually set PIXOO_IP in your .env file.")
            return False

        print(f"{GREEN}[✓] Connected to Pixoo 64 at {BOLD}{self.pixoo.ip}{RESET}")

        # 3. Authenticate with Spotify
        print(f"[*] Authenticating with Spotify...")
        try:
            self.spotify = SpotifyWatcher(
                client_id=settings.spotify_client_id,
                client_secret=settings.spotify_client_secret,
                redirect_uri=settings.spotify_redirect_uri,
            )
            print(f"{GREEN}[✓] Spotify authentication ready.{RESET}")
        except Exception as e:
            print(f"{YELLOW}[!] Failed to initialize Spotify: {e}{RESET}")
            return False

        # 4. Initialize Weather Service
        print(f"[*] Initializing Weather Service...")
        self.weather_service = WeatherService(
            city=settings.weather_city,
            lat=settings.weather_lat,
            lon=settings.weather_lon,
            unit=settings.weather_unit,
        )
        weather = self.weather_service.get_weather()
        if weather:
            print(f"{GREEN}[✓] Weather ready: {weather.temperature}{weather.unit} in {weather.city}{RESET}")
        else:
            print(f"{DIM}[*] Weather service active (location auto-detect pending){RESET}")

        # 5. Preload Liked Songs for Idle Mode
        if settings.idle_mode == "liked_tracks":
            print(f"[*] Preloading your liked tracks from Spotify...")
            try:
                liked = self.spotify.get_liked_tracks(limit=50)
                print(f"{GREEN}[✓] Loaded {len(liked)} track covers for idle display.{RESET}")
            except Exception as e:
                print(f"{YELLOW}[!] Note: Could not preload liked songs ({e}). Using top tracks/fallback.{RESET}")

        # 6. Show Initial Idle Screen
        print(f"[*] Sending startup idle screen to Pixoo 64...")
        self.update_idle_display(force_new_cover=True)

        try:
            from . import server
            server.current_app_instance = self
        except Exception:
            pass

        print(f"\n{CYAN}[♫] Watching for playback (polling every {settings.poll_interval}s)... Press Ctrl+C to quit.{RESET}\n")
        return True

    def update_idle_display(self, force_new_cover: bool = False):
        """
        Renders and sends the idle screen: cover of a liked track with
        the current time and weather HUD at the bottom.
        """
        now = time.time()
        now_dt = datetime.datetime.now()
        now_minute = now_dt.minute
        needs_update = force_new_cover

        # Check if it's time to cycle to another liked track
        if (
            force_new_cover
            or self.current_idle_cover is None
            or (now - self.last_idle_cycle_time) >= settings.idle_cycle_interval
        ):
            if settings.idle_mode == "liked_tracks" and self.spotify:
                liked = self.spotify.get_random_liked_track()
                if liked:
                    cover = self.spotify.fetch_image(liked.image_url)
                    if cover:
                        self.current_idle_cover = cover
                        self.current_idle_title = f"{liked.title} by {liked.artist}"

            if self.current_idle_cover is None:
                self.current_idle_cover = create_spotify_idle_image()
                self.current_idle_title = "Spotify"

            self.last_idle_cycle_time = now
            needs_update = True

        # Check if the minute ticked (clock changed)
        elif now_minute != self.last_idle_minute:
            needs_update = True

        if needs_update and self.current_idle_cover and self.pixoo:
            weather = self.weather_service.get_weather() if self.weather_service else None
            hud_frame = render_idle_cover_with_hud(
                self.current_idle_cover,
                weather=weather,
                use_24h=settings.use_24h_time,
                contrast=settings.enhance_contrast,
                color=settings.enhance_color,
            )
            success = self.pixoo.send_image(hud_frame)
            if success:
                try:
                    from . import server
                    server.set_current_frame(hud_frame)
                except Exception:
                    pass
                self.last_idle_minute = now_minute
                time_fmt = "%H:%M" if settings.use_24h_time else "%-I:%M %p"
                time_str = now_dt.strftime(time_fmt)
                w_str = f" | {weather.temperature}{weather.unit} ({weather.city})" if weather else ""
                print(f"{DIM}[• Idle Display]{RESET} {CYAN}{time_str}{RESET}{w_str} {DIM}| Cover: {self.current_idle_title}{RESET}")

    def render_track_frame(self, brightness: float = 1.0) -> Image.Image:
        """
        Renders the current track's cover, with the time & weather bar when ALWAYS_SHOW_HUD is on.
        """
        if settings.always_show_hud:
            weather = self.weather_service.get_weather() if self.weather_service else None
            return render_idle_cover_with_hud(
                self.current_raw_cover,
                weather=weather,
                use_24h=settings.use_24h_time,
                contrast=settings.enhance_contrast,
                color=settings.enhance_color,
                brightness=brightness,
            )
        return process_image_for_pixoo(
            self.current_raw_cover,
            contrast=settings.enhance_contrast,
            color=settings.enhance_color,
            brightness=brightness,
        )

    def send_track_frame(self, brightness: float = 1.0) -> bool:
        frame = self.render_track_frame(brightness)
        if not self.pixoo.send_image(frame):
            return False
        self.last_hud_minute = datetime.datetime.now().minute
        try:
            from . import server
            server.set_current_frame(frame)
        except Exception:
            pass
        return True

    def refresh_track_hud(self, brightness: float = 1.0):
        """
        Re-sends the track frame when the minute ticks so the clock over the album art stays current.
        """
        if (
            settings.always_show_hud
            and self.current_raw_cover is not None
            and datetime.datetime.now().minute != self.last_hud_minute
        ):
            self.send_track_frame(brightness)

    def update_playback_display(self, img: Image.Image, track: TrackInfo):
        self.current_processed_img = img
        success = self.pixoo.send_image(img)
        if success:
            self.last_hud_minute = datetime.datetime.now().minute
            try:
                from . import server
                server.set_current_frame(img)
            except Exception:
                pass
            state_icon = "▶" if track.is_playing else "⏸"
            print(
                f"{GREEN}[{state_icon} Now Playing]{RESET} {BOLD}{track.title}{RESET} "
                f"{DIM}by{RESET} {track.artist} {DIM}({track.album}){RESET}"
            )
        else:
            print(f"{YELLOW}[!] Failed to send image to Pixoo at {self.pixoo.ip}{RESET}")

    def run(self):
        self.setup_signals()
        if not self.initialize():
            return

        while self.running:
            try:
                track = self.spotify.get_current_track()

                # State 1: Active track detected
                if track is not None and track.is_playing:
                    # New track started
                    if track.track_id != self.last_track_id:
                        self.last_track_id = track.track_id
                        self.last_is_playing = track.is_playing
                        self.current_idle_cover = None  # Reset idle cover for future
                        record_play(track)

                        raw_img = self.spotify.fetch_image(track.image_url)
                        if raw_img:
                            self.current_raw_cover = raw_img
                            self.update_playback_display(self.render_track_frame(), track)

                    # Same track resumed from pause
                    elif not self.last_is_playing:
                        self.last_is_playing = True
                        print(f"{GREEN}[▶ Resumed]{RESET} {track.title}")
                        if self.current_raw_cover is not None:
                            self.send_track_frame()

                    # Same track still playing: keep the clock current
                    else:
                        self.refresh_track_hud()

                # State 2: Track is paused
                elif track is not None and not track.is_playing:
                    if self.last_is_playing is True:
                        self.last_is_playing = False
                        print(f"{YELLOW}[⏸ Paused]{RESET} {track.title}")

                        if settings.on_pause == "dim" and self.current_raw_cover is not None:
                            self.send_track_frame(brightness=settings.dim_factor)
                        elif settings.on_pause == "clear":
                            self.pixoo.clear()
                        elif settings.on_pause == "idle":
                            self.update_idle_display(force_new_cover=True)
                        # 'keep' leaves the current image as-is

                    # Keep updating time/weather while paused
                    if settings.on_pause == "idle":
                        self.update_idle_display()
                    elif settings.on_pause in ("keep", "dim"):
                        self.refresh_track_hud(
                            brightness=settings.dim_factor if settings.on_pause == "dim" else 1.0
                        )

                # State 3: Nothing playing / Spotify closed (Idle)
                else:
                    if self.last_track_id is not None:
                        self.last_track_id = None
                        self.last_is_playing = None
                        print(f"{DIM}[• Idle] Playback stopped. Starting clock & liked tracks display...{RESET}")
                        self.update_idle_display(force_new_cover=True)
                    else:
                        self.update_idle_display()

            except Exception as e:
                # Catch unexpected loop errors so daemon keeps running
                print(f"{YELLOW}[!] Polling warning: {e}{RESET}")

            time.sleep(settings.poll_interval)

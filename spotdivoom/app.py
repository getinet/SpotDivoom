"""
Main application loop and controller for SpotDivoom.
"""

import datetime
import signal
import sys
import threading
import time
from typing import Optional
from PIL import Image

from . import events
from .config import settings
from .display import (
    accent_from_cover,
    create_logo_idle_image,
    crossfade_frames,
    process_image_for_pixoo,
    render_cover_with_text_band,
    render_forecast_screen,
    render_idle_cover_with_hud,
    render_night_clock,
)
from .pixoo import PixooClient
from .spotify import PlaybackUnavailable, SpotifyWatcher, TrackInfo
from .stats import record_play
from .weather import WeatherService

# ANSI styling helpers
GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
DIM = "\033[90m"
BOLD = "\033[1m"
RESET = "\033[0m"

# While a song plays, redraw for the progress line at most this often (each redraw is 2+ device requests)
PROGRESS_REFRESH_SECONDS = 15
# Longest wait between Spotify polls while it keeps failing
MAX_BACKOFF_SECONDS = 60


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


def _parse_hhmm(value: str) -> Optional[datetime.time]:
    try:
        h, m = value.strip().split(":")
        return datetime.time(int(h), int(m))
    except (ValueError, AttributeError):
        return None


def is_night_time(now: datetime.time, start: str, end: str) -> bool:
    """
    True if `now` falls in [start, end), handling windows that cross midnight.
    """
    s, e = _parse_hhmm(start), _parse_hhmm(end)
    if s is None or e is None or s == e:
        return False
    if s < e:
        return s <= now < e
    return now >= s or now < e


def _hex(color: tuple) -> str:
    return "#{:02X}{:02X}{:02X}".format(*color[:3])


class SpotDivoomApp:
    def __init__(self):
        self.running = True
        self.pixoo: Optional[PixooClient] = None
        self.spotify: Optional[SpotifyWatcher] = None
        self.weather_service: Optional[WeatherService] = None
        self.spotify_authorized = False

        # Shared with web-request threads (cycle cover, settings redraw, playback controls)
        self.lock = threading.RLock()
        self._wake = threading.Event()

        # Playback tracking
        self.current_track: Optional[TrackInfo] = None
        self.track_polled_at: float = 0
        self.track_liked: Optional[bool] = None
        self.last_track_id: Optional[str] = None
        self.last_is_playing: Optional[bool] = None
        self.current_raw_cover: Optional[Image.Image] = None
        self.track_accent: Optional[tuple] = None
        self.last_hud_minute: int = -1
        self.last_track_push: float = 0
        self.title_showing = False
        self.spotify_errors = 0
        self.spotify_error: Optional[str] = None

        # Idle screen tracking (cycling liked tracks + time + weather)
        self.current_idle_cover: Optional[Image.Image] = None
        self.idle_accent: Optional[tuple] = None
        self.current_idle_title: str = "Liked Tracks"
        self.last_idle_cycle_time: float = 0
        self.last_idle_minute: int = -1
        self.idle_screen_index: int = 0
        self.last_sent_frame: Optional[Image.Image] = None

        # Night mode
        self.night_active = False
        self.night_kind: Optional[str] = None
        self.saved_brightness: Optional[int] = None
        self.last_night_minute: int = -1

    def setup_signals(self):
        signal.signal(signal.SIGINT, self._handle_exit)
        signal.signal(signal.SIGTERM, self._handle_exit)

    def _handle_exit(self, signum, frame):
        print(f"\n{YELLOW}Stopping SpotDivoom... Goodbye!{RESET}")
        self.running = False
        sys.exit(0)

    # ---------- Startup ----------

    def initialize(self) -> bool:
        print_banner()

        # 1. Check Spotify Credentials
        if not settings.has_spotify_credentials():
            print_spotify_setup_guide()
            return False

        # Let the dashboard reach this instance right away (it also handles Spotify login)
        from . import server
        server.current_app_instance = self

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
        except Exception as e:
            print(f"{YELLOW}[!] Failed to initialize Spotify: {e}{RESET}")
            return False

        self.spotify_authorized = self.spotify.is_authorized()
        if not self.spotify_authorized and sys.stdin.isatty():
            self.spotify_authorized = self.spotify.authorize_interactively()
        if self.spotify_authorized:
            print(f"{GREEN}[✓] Spotify authentication ready.{RESET}")
        else:
            print(f"{YELLOW}[!] Not logged in to Spotify yet. Open the dashboard and click 'Log in to Spotify'.{RESET}")

        # 4. Initialize Weather Service
        print(f"[*] Initializing Weather Service...")
        self.weather_service = WeatherService(
            city=settings.weather_city,
            lat=settings.weather_lat,
            lon=settings.weather_lon,
            unit=settings.weather_unit,
        )
        weather = self.get_weather()
        if weather:
            print(f"{GREEN}[✓] Weather ready: {weather.temperature}{weather.unit} in {weather.city}{RESET}")
        else:
            print(f"{DIM}[*] Weather service active (location auto-detect pending){RESET}")

        # 5. Preload Liked Songs for Idle Mode
        if self.spotify_authorized and settings.idle_mode == "liked_tracks":
            self._preload_liked()

        # 6. Show Initial Idle Screen
        print(f"[*] Sending startup idle screen to Pixoo 64...")
        self.update_idle_display(force_new_cover=True)

        print(f"\n{CYAN}[♫] Watching for playback (polling every {settings.poll_interval}s)... Press Ctrl+C to quit.{RESET}\n")
        return True

    def _preload_liked(self):
        print(f"[*] Preloading your liked tracks from Spotify...")
        try:
            liked = self.spotify.get_liked_tracks(limit=settings.liked_tracks_limit)
            print(f"{GREEN}[✓] Loaded {len(liked)} album covers for idle display.{RESET}")
        except Exception as e:
            print(f"{YELLOW}[!] Note: Could not preload liked songs ({e}). Using top tracks/fallback.{RESET}")

    def get_weather(self):
        if not self.weather_service:
            return None
        return self.weather_service.get_weather(unit=settings.weather_unit)

    # ---------- Sending frames ----------

    def _push(self, frame: Image.Image) -> bool:
        if not self.pixoo.send_image(frame):
            return False
        self.last_sent_frame = frame
        from . import server
        server.set_current_frame(frame)
        return True

    def _title_y(self) -> int:
        # Scroll the title on whichever edge the time & weather bar isn't using
        if settings.always_show_hud and settings.hud_position == "bottom":
            return 2
        return 54

    def _idle_screens(self) -> list[str]:
        screens = [s.strip() for s in settings.idle_screens.split(",") if s.strip() in ("cover", "forecast")]
        return screens or ["cover"]

    def update_idle_display(self, force_new_cover: bool = False):
        """
        Renders and sends the idle screen: a liked-track cover or the forecast,
        with the time and weather bar. Covers rotate every IDLE_CYCLE_INTERVAL.
        """
        with self.lock:
            now = time.time()
            now_dt = datetime.datetime.now()
            now_minute = now_dt.minute
            needs_update = force_new_cover
            cycled = False

            # Time to rotate: next screen, and a fresh cover when that screen is a cover
            if (
                force_new_cover
                or self.current_idle_cover is None
                or (now - self.last_idle_cycle_time) >= settings.idle_cycle_interval
            ):
                screens = self._idle_screens()
                if self.current_idle_cover is not None:
                    self.idle_screen_index = (self.idle_screen_index + 1) % len(screens)
                if screens[self.idle_screen_index % len(screens)] == "cover" or self.current_idle_cover is None:
                    self._load_next_idle_cover()
                self.last_idle_cycle_time = now
                needs_update = True
                cycled = True

            # Check if the minute ticked (clock changed)
            elif now_minute != self.last_idle_minute:
                needs_update = True

            if not (needs_update and self.current_idle_cover and self.pixoo):
                return

            weather = self.get_weather()
            screen = self._idle_screens()[self.idle_screen_index % len(self._idle_screens())]
            if screen == "forecast":
                frame = render_forecast_screen(weather, use_24h=settings.use_24h_time, position=settings.hud_position)
                label = "Forecast"
            else:
                frame = render_idle_cover_with_hud(
                    self.current_idle_cover,
                    weather=weather,
                    use_24h=settings.use_24h_time,
                    contrast=settings.enhance_contrast,
                    color=settings.enhance_color,
                    position=settings.hud_position,
                    accent=self.idle_accent if settings.hud_accent else None,
                )
                label = self.current_idle_title

            if self.title_showing:
                self.pixoo.clear_text()
                self.title_showing = False

            if cycled and settings.idle_transition == "fade" and self.last_sent_frame is not None:
                for step in crossfade_frames(self.last_sent_frame, frame):
                    self.pixoo.send_image(step)
                    time.sleep(0.05)

            if self._push(frame):
                self.last_idle_minute = now_minute
                time_fmt = "%H:%M" if settings.use_24h_time else "%-I:%M %p"
                w_str = f" | {weather.temperature}{weather.unit} ({weather.city})" if weather else ""
                print(f"{DIM}[• Idle Display]{RESET} {CYAN}{now_dt.strftime(time_fmt)}{RESET}{w_str} {DIM}| {label}{RESET}")

    def _load_next_idle_cover(self):
        if settings.idle_mode == "liked_tracks" and self.spotify and self.spotify_authorized:
            liked = self.spotify.get_random_liked_track(limit=settings.liked_tracks_limit)
            if liked:
                cover = self.spotify.fetch_image(liked.image_url)
                if cover:
                    self.current_idle_cover = cover
                    self.current_idle_title = f"{liked.title} by {liked.artist}"
                    self.idle_accent = accent_from_cover(cover)
                    return
        if self.current_idle_cover is None:
            self.current_idle_cover = create_logo_idle_image()
            self.current_idle_title = "SpotDivoom"
            self.idle_accent = None

    def _progress(self) -> Optional[float]:
        t = self.current_track
        if not settings.show_progress or not t or not t.duration_ms:
            return None
        elapsed = t.progress_ms
        if t.is_playing:
            elapsed += (time.time() - self.track_polled_at) * 1000
        return min(1.0, elapsed / t.duration_ms)

    def render_track_frame(self, brightness: float = 1.0) -> Image.Image:
        """
        Renders the current track's cover, with the time & weather bar when ALWAYS_SHOW_HUD is on.
        """
        band = self._title_y() if settings.show_title else None
        if settings.always_show_hud:
            return render_idle_cover_with_hud(
                self.current_raw_cover,
                weather=self.get_weather(),
                use_24h=settings.use_24h_time,
                contrast=settings.enhance_contrast,
                color=settings.enhance_color,
                brightness=brightness,
                position=settings.hud_position,
                accent=self.track_accent if settings.hud_accent else None,
                progress=self._progress(),
                text_band_y=band,
            )
        frame = process_image_for_pixoo(
            self.current_raw_cover,
            contrast=settings.enhance_contrast,
            color=settings.enhance_color,
            brightness=brightness,
        )
        return render_cover_with_text_band(frame, band) if band is not None else frame

    def send_track_frame(self, brightness: float = 1.0) -> bool:
        with self.lock:
            if self.current_raw_cover is None or self.night_blocks_display():
                return False
            if not self._push(self.render_track_frame(brightness)):
                return False
            self.last_hud_minute = datetime.datetime.now().minute
            self.last_track_push = time.time()
            self._send_title()
            return True

    def _send_title(self):
        t = self.current_track
        if settings.show_title and t and (self.last_is_playing or settings.on_pause in ("keep", "dim")):
            color = self.track_accent if settings.hud_accent and self.track_accent else (255, 255, 255)
            self.title_showing = self.pixoo.send_scrolling_text(
                f"{t.title} - {t.artist}", y=self._title_y(), color=_hex(color)
            )
        elif self.title_showing:
            self.pixoo.clear_text()
            self.title_showing = False

    def refresh_track_hud(self, brightness: float = 1.0):
        """
        Re-sends the track frame when the minute ticks (clock) or, with the progress line on,
        every PROGRESS_REFRESH_SECONDS.
        """
        if self.current_raw_cover is None or not settings.always_show_hud:
            return
        minute_changed = datetime.datetime.now().minute != self.last_hud_minute
        progress_due = (
            settings.show_progress
            and self.last_is_playing
            and time.time() - self.last_track_push >= PROGRESS_REFRESH_SECONDS
        )
        if minute_changed or progress_due:
            self.send_track_frame(brightness)

    def start_new_track(self, track: TrackInfo):
        raw_img = self.spotify.fetch_image(track.image_url)
        if raw_img is None:
            # Don't leave the previous song's cover up; the next poll retries the download
            self.current_raw_cover = None
            return
        self.current_raw_cover = raw_img
        self.track_accent = accent_from_cover(raw_img)
        self.track_liked = self.spotify.is_liked(track.track_id)
        if self.send_track_frame():
            print(
                f"{GREEN}[▶ Now Playing]{RESET} {BOLD}{track.title}{RESET} "
                f"{DIM}by{RESET} {track.artist} {DIM}({track.album}){RESET}"
            )
        elif not self.night_blocks_display():
            print(f"{YELLOW}[!] Failed to push cover art to Pixoo.{RESET}")

    def redraw(self):
        """
        Redraws whatever should be on screen now (after settings change or night mode ends).
        """
        with self.lock:
            if self.night_blocks_display():
                self.last_night_minute = -1
                return
            if self.last_is_playing and self.current_raw_cover is not None:
                self.send_track_frame()
            elif self.last_is_playing is False and settings.on_pause in ("keep", "dim") and self.current_raw_cover is not None:
                self.send_track_frame(settings.dim_factor if settings.on_pause == "dim" else 1.0)
            else:
                self.last_idle_minute = -1
                self.update_idle_display()

    def on_settings_changed(self):
        self.redraw()
        events.publish()

    # ---------- Night mode ----------

    def night_blocks_display(self) -> bool:
        return self.night_active and self.night_kind in ("clock", "screen_off")

    def update_night_mode(self):
        """
        Enters or leaves night mode based on the schedule, then keeps the night clock current.
        """
        mode = settings.night_mode if settings.night_mode in ("dim", "clock", "screen_off") else "off"
        should_be_on = mode != "off" and is_night_time(
            datetime.datetime.now().time(), settings.night_start, settings.night_end
        )

        # Leave night mode (schedule ended, or the mode was changed/turned off)
        if self.night_active and (not should_be_on or mode != self.night_kind):
            kind = self.night_kind
            self.night_active, self.night_kind = False, None
            if kind == "dim" and self.saved_brightness is not None:
                self.pixoo.set_brightness(self.saved_brightness)
            elif kind == "screen_off":
                self.pixoo.set_screen_on(True)
            self.saved_brightness = None
            print(f"{CYAN}[☀ Night mode off]{RESET}")
            self.redraw()
            events.publish()

        if should_be_on and not self.night_active:
            self.night_active, self.night_kind = True, mode
            if self.title_showing:
                self.pixoo.clear_text()
                self.title_showing = False
            if mode == "dim":
                self.saved_brightness = self.pixoo.get_brightness()
                self.pixoo.set_brightness(settings.night_brightness)
            elif mode == "screen_off":
                self.pixoo.set_screen_on(False)
            self.last_night_minute = -1
            print(f"{CYAN}[☾ Night mode on: {mode}]{RESET}")
            events.publish()

        if self.night_active and self.night_kind == "clock":
            minute = datetime.datetime.now().minute
            if minute != self.last_night_minute:
                if self._push(render_night_clock(settings.use_24h_time, self.get_weather())):
                    self.last_night_minute = minute

    # ---------- Dashboard ----------

    def snapshot(self) -> dict:
        """
        Everything the dashboard shows, from state the loop already has (no extra API calls).
        """
        t = self.current_track
        playback = None
        if t:
            progress = t.progress_ms
            if t.is_playing:
                progress = min(t.duration_ms or progress, progress + int((time.time() - self.track_polled_at) * 1000))
            playback = {
                "track_id": t.track_id,
                "is_playing": t.is_playing,
                "title": t.title,
                "artist": t.artist,
                "album": t.album,
                "image_url": t.image_url,
                "progress_ms": progress,
                "duration_ms": t.duration_ms,
                "liked": self.track_liked,
            }
        idle_cover = self._idle_screens()[self.idle_screen_index % len(self._idle_screens())] != "forecast"
        return {
            "playback": playback,
            "idle_active": not (t and t.is_playing),
            "current_cover_title": self.current_idle_title if idle_cover else "Forecast",
            "spotify": {
                "authorized": self.spotify_authorized,
                "error": self.spotify_error,
            },
            "night": {"active": self.night_active, "mode": self.night_kind},
        }

    def control(self, action: str) -> bool:
        """
        Playback controls from the dashboard; wakes the loop so the Pixoo follows right away.
        """
        if not (self.spotify and self.spotify_authorized):
            return False
        t = self.current_track
        if action == "toggle":
            self.spotify.toggle_playback(bool(t and t.is_playing))
        elif action == "next":
            self.spotify.next_track()
        elif action == "previous":
            self.spotify.previous_track()
        elif action in ("like", "unlike") and t:
            self.spotify.set_liked(t.track_id, action == "like")
            self.track_liked = action == "like"
            events.publish()
        else:
            return False
        self.wake()
        return True

    def wake(self):
        self._wake.set()

    def on_spotify_login(self):
        """
        Called by the dashboard after a successful login.
        """
        self.spotify_authorized = True
        self.spotify_error = None
        if settings.idle_mode == "liked_tracks":
            self._preload_liked()
        self.wake()
        events.publish()

    # ---------- Main loop ----------

    def poll_once(self) -> float:
        """
        One pass of the loop. Returns how long to wait before the next one.
        """
        self.update_night_mode()

        if not self.spotify_authorized:
            self.spotify_authorized = self.spotify.is_authorized()
            if not self.spotify_authorized:
                if not self.night_blocks_display():
                    self.update_idle_display()
                return settings.poll_interval
            self.on_spotify_login()

        try:
            track = self.spotify.get_current_track()
        except PlaybackUnavailable as e:
            # Keep showing what we have; don't mistake an outage for "playback stopped"
            self.spotify_errors += 1
            if self.spotify_errors == 1:
                print(f"{YELLOW}[!] Spotify unavailable ({e}); keeping the current screen.{RESET}")
            self.spotify_error = "Spotify isn't responding; retrying."
            if not self.night_blocks_display():
                if self.last_is_playing:
                    self.refresh_track_hud()
                elif self.last_is_playing is None:
                    self.update_idle_display()
            events.publish()
            return min(MAX_BACKOFF_SECONDS, settings.poll_interval * (2 ** min(self.spotify_errors, 5)))

        if self.spotify_errors:
            print(f"{GREEN}[✓] Spotify is back.{RESET}")
        self.spotify_errors = 0
        self.spotify_error = None
        self.current_track = track
        self.track_polled_at = time.time()

        if self.night_blocks_display():
            # Screen is reserved for night mode; still log plays and track state for the dashboard
            if track and track.is_playing and track.track_id != self.last_track_id:
                record_play(track)
            self.last_track_id = track.track_id if track else None
            self.last_is_playing = track.is_playing if track else None
            self.current_raw_cover = None
            events.publish()
            return settings.poll_interval

        with self.lock:
            self._apply_playback(track)
        events.publish()
        return settings.poll_interval

    def _apply_playback(self, track: Optional[TrackInfo]):
        # State 1: Active track detected
        if track is not None and track.is_playing:
            if track.track_id != self.last_track_id or self.current_raw_cover is None:
                self.last_track_id = track.track_id
                self.last_is_playing = True
                self.current_idle_cover = None  # Reset idle cover for future
                record_play(track)
                self.start_new_track(track)

            # Same track resumed from pause
            elif not self.last_is_playing:
                self.last_is_playing = True
                print(f"{GREEN}[▶ Resumed]{RESET} {track.title}")
                self.send_track_frame()

            # Same track still playing: keep the clock and progress current
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
                    if self.title_showing:
                        self.pixoo.clear_text()
                        self.title_showing = False
                    self._push(Image.new("RGB", (64, 64)))
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

    def run(self):
        self.setup_signals()
        if not self.initialize():
            return

        while self.running:
            try:
                delay = self.poll_once()
            except Exception as e:
                # Catch unexpected loop errors so daemon keeps running
                print(f"{YELLOW}[!] Polling warning: {e}{RESET}")
                delay = settings.poll_interval
            # Sleep, but wake early when the dashboard asks (playback controls, login)
            self._wake.wait(delay)
            self._wake.clear()

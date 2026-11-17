"""
Spotify client for polling currently playing tracks and fetching album art.
"""

import io
import random
import sys
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from PIL import Image

from .config import DATA_DIR

SPOTIFY_SCOPES = (
    "user-read-currently-playing user-read-playback-state user-library-read user-top-read "
    "user-read-recently-played user-modify-playback-state user-library-modify"
)

# Covers are kept at this size; plenty for a 64x64 panel and far lighter than the originals
IMAGE_CACHE_SIZE = 120
IMAGE_CACHE_DIM = 300


class PlaybackUnavailable(Exception):
    """Spotify could not be reached or returned an error (as opposed to 'nothing is playing')."""


@dataclass
class TrackInfo:
    track_id: str
    title: str
    artist: str
    album: str
    image_url: str
    is_playing: bool
    progress_ms: int = 0
    duration_ms: int = 0


@dataclass
class LikedTrack:
    title: str
    artist: str
    album: str
    image_url: str


def _medium_image(images: list) -> str:
    # images[1] is usually 300x300, which downsamples best; fall back to the first
    if not images:
        return ""
    if len(images) > 1 and "url" in images[1]:
        return images[1]["url"]
    return images[0].get("url", "")


class SpotifyWatcher:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str = "http://127.0.0.1:8888/callback",
        cache_path: str = str(DATA_DIR / ".cache-spotify"),
    ):
        self.auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=SPOTIFY_SCOPES,
            cache_path=cache_path,
            # Only pop a browser when someone is at a terminal; otherwise log in from the dashboard
            open_browser=sys.stdin.isatty(),
        )
        self.sp = spotipy.Spotify(auth_manager=self.auth_manager, requests_timeout=10)
        self._image_cache: "OrderedDict[str, Image.Image]" = OrderedDict()
        self._liked_tracks_cache: list[LikedTrack] = []
        self._liked_tracks_last_fetch: float = 0
        self._shuffle_bag: list[LikedTrack] = []

    # ---------- Login ----------

    def is_authorized(self) -> bool:
        """
        True when a token with all required scopes is cached (refreshing it if expired).
        """
        try:
            token = self.auth_manager.validate_token(self.auth_manager.cache_handler.get_cached_token())
            return token is not None
        except Exception:
            return False

    def authorize_interactively(self) -> bool:
        """
        Runs spotipy's terminal/browser login. Only call when a person is at the terminal.
        """
        try:
            self.auth_manager.get_access_token(as_dict=False)
            return self.is_authorized()
        except Exception:
            return False

    def authorize_url(self) -> str:
        return self.auth_manager.get_authorize_url()

    def complete_login(self, redirected_url: str) -> bool:
        """
        Finishes login from the URL Spotify redirected to (pasted from the browser's address bar).
        """
        code = self.auth_manager.parse_response_code(redirected_url.strip())
        if not code or code == redirected_url.strip():
            return False
        self.auth_manager.get_access_token(code, as_dict=False, check_cache=False)
        return self.is_authorized()

    # ---------- Playback ----------

    def get_current_track(self) -> Optional[TrackInfo]:
        """
        Polls Spotify for the current track or podcast episode.
        Returns None when nothing is playing; raises PlaybackUnavailable on errors.
        """
        try:
            playback = self.sp.current_playback(additional_types="track,episode")
        except Exception as e:
            raise PlaybackUnavailable(str(e)) from e

        if not playback or not playback.get("item"):
            return None

        item = playback["item"]
        track_id = item.get("id") or item.get("uri") or item.get("name")

        # Handle music tracks vs podcast episodes
        if "artists" in item:
            artist = ", ".join([a["name"] for a in item.get("artists", [])])
            album = item.get("album", {}).get("name", "")
            images = item.get("album", {}).get("images", [])
        else:
            artist = item.get("show", {}).get("name", "Podcast")
            album = item.get("show", {}).get("publisher", "")
            images = item.get("images", [])

        return TrackInfo(
            track_id=track_id,
            title=item.get("name", "Unknown Title"),
            artist=artist,
            album=album,
            image_url=_medium_image(images),
            is_playing=playback.get("is_playing", False),
            progress_ms=playback.get("progress_ms") or 0,
            duration_ms=item.get("duration_ms") or 0,
        )

    def toggle_playback(self, is_playing: bool):
        if is_playing:
            self.sp.pause_playback()
        else:
            self.sp.start_playback()

    def next_track(self):
        self.sp.next_track()

    def previous_track(self):
        self.sp.previous_track()

    def is_liked(self, track_id: str) -> Optional[bool]:
        if not track_id or ":" in track_id:
            return None
        try:
            return bool(self.sp.current_user_saved_tracks_contains([track_id])[0])
        except Exception:
            return None

    def set_liked(self, track_id: str, liked: bool):
        if liked:
            self.sp.current_user_saved_tracks_add([track_id])
        else:
            self.sp.current_user_saved_tracks_delete([track_id])
        self._liked_tracks_last_fetch = 0  # pick up the change next time idle covers load

    # ---------- Images ----------

    def fetch_image(self, url: str) -> Optional[Image.Image]:
        """
        Downloads album art, keeping a bounded cache of recently used covers.
        """
        if not url:
            return None
        if url in self._image_cache:
            self._image_cache.move_to_end(url)
            return self._image_cache[url].copy()

        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                img.thumbnail((IMAGE_CACHE_DIM, IMAGE_CACHE_DIM), Image.Resampling.LANCZOS)
                self._image_cache[url] = img
                while len(self._image_cache) > IMAGE_CACHE_SIZE:
                    self._image_cache.popitem(last=False)
                return img.copy()
        except Exception:
            pass
        return None

    # ---------- Idle covers ----------

    def _tracks_from_items(self, items: list, seen_urls: set) -> list[LikedTrack]:
        tracks = []
        for track in items:
            if not track:
                continue
            album = track.get("album", {})
            img_url = _medium_image(album.get("images", []))
            if not img_url or img_url in seen_urls:
                continue
            seen_urls.add(img_url)
            tracks.append(
                LikedTrack(
                    title=track.get("name", "Unknown"),
                    artist=", ".join([a["name"] for a in track.get("artists", [])]),
                    album=album.get("name", ""),
                    image_url=img_url,
                )
            )
        return tracks

    def get_liked_tracks(self, limit: int = 500, force_refresh: bool = False) -> list[LikedTrack]:
        """
        Retrieves up to `limit` Liked Songs (one per album cover), falling back to top tracks.
        Cached for an hour.
        """
        now = time.time()
        if not force_refresh and self._liked_tracks_cache and (now - self._liked_tracks_last_fetch) < 3600:
            return self._liked_tracks_cache

        tracks: list[LikedTrack] = []
        seen_urls: set = set()

        # 1. Liked Songs, 50 per page
        try:
            offset = 0
            while offset < limit:
                page = self.sp.current_user_saved_tracks(limit=min(50, limit - offset), offset=offset) or {}
                items = page.get("items", [])
                tracks += self._tracks_from_items([i.get("track") for i in items], seen_urls)
                if not page.get("next") or not items:
                    break
                offset += len(items)
        except Exception:
            pass

        # 2. Fallback to Top Tracks if no saved tracks found
        if not tracks:
            try:
                results = self.sp.current_user_top_tracks(limit=50) or {}
                tracks = self._tracks_from_items(results.get("items", []), seen_urls)
            except Exception:
                pass

        if tracks:
            self._liked_tracks_cache = tracks
            self._liked_tracks_last_fetch = now
            self._shuffle_bag = []

        return self._liked_tracks_cache

    def get_random_liked_track(self, limit: int = 500) -> Optional[LikedTrack]:
        """
        Returns the next cover from a shuffled bag, so every cover shows once before any repeats.
        """
        tracks = self.get_liked_tracks(limit=limit)
        if not tracks:
            return None
        if not self._shuffle_bag:
            self._shuffle_bag = list(tracks)
            random.shuffle(self._shuffle_bag)
        return self._shuffle_bag.pop()

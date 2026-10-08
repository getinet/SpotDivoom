"""
Spotify client for polling currently playing tracks and fetching album art.
"""

import io
from dataclasses import dataclass
from typing import Optional
import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from PIL import Image

import random
import time

SPOTIFY_SCOPES = "user-read-currently-playing user-read-playback-state user-library-read user-top-read"


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


class SpotifyWatcher:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str = "http://127.0.0.1:8888/callback",
        cache_path: str = ".cache-spotify",
    ):
        self.auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=SPOTIFY_SCOPES,
            cache_path=cache_path,
            open_browser=True,
        )
        self.sp = spotipy.Spotify(auth_manager=self.auth_manager)
        self._image_cache: dict[str, Image.Image] = {}
        self._liked_tracks_cache: list[LikedTrack] = []
        self._liked_tracks_last_fetch: float = 0

    def get_current_track(self) -> Optional[TrackInfo]:
        """
        Polls Spotify API for currently playing track or podcast episode.
        """
        try:
            playback = self.sp.current_playback()
            if not playback or not playback.get("item"):
                return None

            item = playback["item"]
            is_playing = playback.get("is_playing", False)
            track_id = item.get("id") or item.get("uri") or item.get("name")
            title = item.get("name", "Unknown Title")

            # Handle music tracks vs podcast episodes
            if "artists" in item:
                artist = ", ".join([a["name"] for a in item.get("artists", [])])
                album = item.get("album", {}).get("name", "")
                images = item.get("album", {}).get("images", [])
            else:
                # Podcast episode
                artist = item.get("show", {}).get("name", "Podcast")
                album = item.get("show", {}).get("publisher", "")
                images = item.get("images", [])

            # Pick image: medium 300x300 downsamples best, fallback to 640 or 64
            image_url = ""
            if images:
                # If 3 or more images, images[1] is usually 300x300
                if len(images) > 1 and "url" in images[1]:
                    image_url = images[1]["url"]
                else:
                    image_url = images[0]["url"]

            return TrackInfo(
                track_id=track_id,
                title=title,
                artist=artist,
                album=album,
                image_url=image_url,
                is_playing=is_playing,
                progress_ms=playback.get("progress_ms", 0),
                duration_ms=item.get("duration_ms", 0),
            )
        except Exception:
            return None

    def fetch_image(self, url: str) -> Optional[Image.Image]:
        """
        Downloads and caches album art from URL.
        """
        if not url:
            return None
        if url in self._image_cache:
            return self._image_cache[url].copy()

        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                img = Image.open(io.BytesIO(resp.content))
                self._image_cache[url] = img.copy()
                return img
        except Exception:
            pass
        return None

    def get_liked_tracks(self, limit: int = 50, force_refresh: bool = False) -> list[LikedTrack]:
        """
        Retrieves user's saved tracks (or top tracks as fallback), caching results for 1 hour.
        """
        now = time.time()
        if not force_refresh and self._liked_tracks_cache and (now - self._liked_tracks_last_fetch) < 3600:
            return self._liked_tracks_cache

        tracks: list[LikedTrack] = []
        seen_urls = set()

        # 1. Try Saved Tracks (Liked Songs)
        try:
            results = self.sp.current_user_saved_tracks(limit=limit)
            items = results.get("items", []) if results else []
            for item in items:
                track = item.get("track")
                if not track:
                    continue
                album = track.get("album", {})
                images = album.get("images", [])
                if not images:
                    continue

                # Use medium image if available, else first
                img_url = images[1]["url"] if len(images) > 1 else images[0]["url"]
                if img_url in seen_urls:
                    continue
                seen_urls.add(img_url)

                artists = ", ".join([a["name"] for a in track.get("artists", [])])
                tracks.append(
                    LikedTrack(
                        title=track.get("name", "Unknown"),
                        artist=artists,
                        album=album.get("name", ""),
                        image_url=img_url,
                    )
                )
        except Exception:
            pass

        # 2. Fallback to Top Tracks if no saved tracks found
        if not tracks:
            try:
                results = self.sp.current_user_top_tracks(limit=limit)
                items = results.get("items", []) if results else []
                for track in items:
                    album = track.get("album", {})
                    images = album.get("images", [])
                    if not images:
                        continue
                    img_url = images[1]["url"] if len(images) > 1 else images[0]["url"]
                    if img_url in seen_urls:
                        continue
                    seen_urls.add(img_url)
                    artists = ", ".join([a["name"] for a in track.get("artists", [])])
                    tracks.append(
                        LikedTrack(
                            title=track.get("name", "Unknown"),
                            artist=artists,
                            album=album.get("name", ""),
                            image_url=img_url,
                        )
                    )
            except Exception:
                pass

        if tracks:
            self._liked_tracks_cache = tracks
            self._liked_tracks_last_fetch = now

        return self._liked_tracks_cache

    def get_random_liked_track(self) -> Optional[LikedTrack]:
        """
        Returns a random track from user's liked or top tracks.
        """
        tracks = self.get_liked_tracks()
        if not tracks:
            return None
        return random.choice(tracks)

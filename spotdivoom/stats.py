"""
Listening statistics for the web dashboard's "Your Listening Story" section.

Combines Spotify's top artists/tracks and recently played history with a local
play log that SpotDivoom records while it watches playback, so listening-time
patterns keep improving the longer the app runs.
"""

import datetime
import json
import statistics
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Optional

from .config import DATA_DIR

LOG_FILE = DATA_DIR / "listening_log.jsonl"
TERMS = ("short_term", "medium_term", "long_term")
STATS_CACHE_TTL = 600

_log_lock = threading.Lock()
_stats_cache: Optional[dict] = None
_stats_cache_time: float = 0

# Don't log the same track again within this window (e.g. after a brief Spotify outage)
REPLAY_WINDOW_SECONDS = 600
_last_logged: dict = {"track_id": None, "time": 0.0}


def record_play(track) -> None:
    """
    Appends a track start to the local play log (one JSON object per line).
    """
    now = time.time()
    if track.track_id == _last_logged["track_id"] and now - _last_logged["time"] < REPLAY_WINDOW_SECONDS:
        return
    _last_logged.update(track_id=track.track_id, time=now)

    entry = {
        "track_id": track.track_id,
        "title": track.title,
        "artist": track.artist,
        "album": track.album,
        "duration_ms": track.duration_ms,
        "played_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    try:
        with _log_lock, LOG_FILE.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _read_log() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    entries = []
    with _log_lock:
        for line in LOG_FILE.read_text().splitlines():
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
    return entries


def _parse_time(value: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()


def _image(images: list, prefer_index: int = 1) -> str:
    if not images:
        return ""
    return images[min(prefer_index, len(images) - 1)].get("url", "")


def _release_year(track: dict) -> Optional[int]:
    date = (track.get("album") or {}).get("release_date") or ""
    try:
        return int(date[:4])
    except ValueError:
        return None


def _gather_plays(recent_items: list, log_entries: list) -> list[dict]:
    """
    Merges Spotify's recently-played list with the local log, skipping log entries
    that Spotify already reported (same track within 15 minutes).
    """
    plays = []
    for item in recent_items:
        track = item.get("track") or {}
        plays.append({
            "track_id": track.get("id"),
            "title": track.get("name", ""),
            "artist": ", ".join(a["name"] for a in track.get("artists", [])),
            "image": _image((track.get("album") or {}).get("images", []), 2),
            "duration_ms": track.get("duration_ms", 0),
            "played_at": _parse_time(item["played_at"]),
        })

    for entry in log_entries:
        played_at = _parse_time(entry["played_at"])
        duplicate = any(
            p["track_id"] == entry.get("track_id")
            and abs((p["played_at"] - played_at).total_seconds()) < 900
            for p in plays
        )
        if not duplicate:
            plays.append({
                "track_id": entry.get("track_id"),
                "title": entry.get("title", ""),
                "artist": entry.get("artist", ""),
                "image": "",
                "duration_ms": entry.get("duration_ms", 0),
                "played_at": played_at,
            })

    plays.sort(key=lambda p: p["played_at"], reverse=True)
    return plays


def _time_personality(peak_hour: int) -> tuple[str, str]:
    if 5 <= peak_hour < 10:
        return "Early Bird", "You press play with your morning coffee."
    if 10 <= peak_hour < 17:
        return "Daytime Groover", "Music is your work-day soundtrack."
    if 17 <= peak_hour < 22:
        return "Evening Unwinder", "Your listening peaks once the day winds down."
    return "Night Owl", "Your music comes alive after dark."


def _taste_personality(fresh_share: Optional[int], median_year: Optional[int], loyalty: float) -> tuple[str, str]:
    if fresh_share is not None and fresh_share >= 50:
        flavor = "New-Release Hunter"
    elif median_year is not None and median_year < 2010:
        flavor = "Time Traveler"
    else:
        flavor = "Explorer"

    if loyalty >= 0.5:
        prefix, line = "Loyal", "you keep coming back to the artists you love"
    elif loyalty <= 0.2:
        prefix, line = "Restless", "your rotation is always changing"
    else:
        prefix, line = "Curious", "you mix old favorites with new finds"

    if flavor == "New-Release Hunter":
        detail = "You're always on the freshest drops, and"
    elif flavor == "Time Traveler":
        detail = "Your favorites come from decades past, and"
    else:
        detail = "You roam across eras, and"
    return f"{prefix} {flavor}", f"{detail} {line}."


def _fetch_saved_tracks(sp, max_items: int = 2000) -> tuple[list, Optional[int]]:
    """
    Pages through Liked Songs (newest first), up to max_items.
    """
    items, total = [], None
    try:
        offset = 0
        while offset < max_items:
            page = sp.current_user_saved_tracks(limit=50, offset=offset) or {}
            total = page.get("total", total)
            batch = page.get("items", [])
            items.extend(batch)
            if not page.get("next") or not batch:
                break
            offset += 50
    except Exception:
        pass
    return items, total


def build_stats(sp) -> dict:
    """
    Fetches the user's Spotify data and turns it into dashboard-ready stats.
    """
    user = sp.current_user() or {}

    top_artists = {}
    top_tracks = {}
    for term in TERMS:
        top_artists[term] = (sp.current_user_top_artists(limit=50, time_range=term) or {}).get("items", [])
        top_tracks[term] = (sp.current_user_top_tracks(limit=50, time_range=term) or {}).get("items", [])

    recent_error = None
    try:
        recent_items = (sp.current_user_recently_played(limit=50) or {}).get("items", [])
    except Exception as e:
        recent_items = []
        recent_error = str(e)

    saved_items, library_size = _fetch_saved_tracks(sp)

    log_entries = _read_log()
    plays = _gather_plays(recent_items, log_entries)

    # --- Top lists ---
    def artist_card(a):
        return {
            "name": a.get("name", ""),
            "image": _image(a.get("images", [])),
            "url": (a.get("external_urls") or {}).get("spotify", ""),
        }

    def track_card(t):
        return {
            "name": t.get("name", ""),
            "artist": ", ".join(a["name"] for a in t.get("artists", [])),
            "image": _image((t.get("album") or {}).get("images", [])),
            "url": (t.get("external_urls") or {}).get("spotify", ""),
        }

    # --- Decades & track traits (medium + long term top tracks, deduped) ---
    seen = set()
    trait_tracks = []
    for t in top_tracks["medium_term"] + top_tracks["long_term"]:
        if t.get("id") and t["id"] not in seen:
            seen.add(t["id"])
            trait_tracks.append(t)

    years = [y for y in (_release_year(t) for t in trait_tracks) if y]
    decade_counts = Counter(f"{(y // 10) * 10}s" for y in years)
    decades = [{"decade": d, "count": c} for d, c in sorted(decade_counts.items())]

    this_year = datetime.date.today().year
    fresh_share = round(100 * sum(1 for y in years if y >= this_year - 1) / len(years)) if years else None
    median_year = round(statistics.median(years)) if years else None
    album_types = Counter((t.get("album") or {}).get("album_type", "album") for t in trait_tracks)
    singles_share = round(100 * album_types.get("single", 0) / len(trait_tracks)) if trait_tracks else None
    unique_artists = len({a["id"] for t in top_tracks["medium_term"] for a in t.get("artists", [])[:1]})
    variety = round(100 * unique_artists / len(top_tracks["medium_term"])) if top_tracks["medium_term"] else None
    explicit_share = (
        round(100 * sum(1 for t in trait_tracks if t.get("explicit")) / len(trait_tracks))
        if trait_tracks else None
    )
    durations = [t["duration_ms"] for t in trait_tracks if t.get("duration_ms")]
    avg_length = round(statistics.mean(durations) / 1000) if durations else None

    # --- Taste evolution ---
    short_names = [a["name"] for a in top_artists["short_term"]]
    long_names = {a["name"] for a in top_artists["long_term"]}
    medium_names = {a["name"] for a in top_artists["medium_term"]}
    new_obsessions = [artist_card(a) for a in top_artists["short_term"] if a["name"] not in long_names][:5]
    ride_or_die = [
        artist_card(a) for a in top_artists["long_term"]
        if a["name"] in medium_names and a["name"] in short_names
    ][:5]
    loyalty = (
        len(set(short_names[:20]) & long_names) / min(20, len(short_names))
        if short_names else 0.0
    )

    # --- Library growth (songs liked per month, last 24 months) ---
    added = [_parse_time(i["added_at"]) for i in saved_items if i.get("added_at")]
    month_counts = Counter(d.strftime("%Y-%m") for d in added)
    months = []
    cursor = datetime.date.today().replace(day=1)
    for _ in range(24):
        months.append({"month": cursor.strftime("%Y-%m"), "count": month_counts.get(cursor.strftime("%Y-%m"), 0)})
        cursor = (cursor - datetime.timedelta(days=1)).replace(day=1)
    months.reverse()
    first_like = min(added).date().isoformat() if added else None
    biggest_month = max(month_counts.items(), key=lambda kv: kv[1]) if month_counts else None

    # --- When you listen ---
    # Uses plays when available, otherwise the times you liked songs
    clock_source = "plays" if plays else "likes"
    moments = [p["played_at"] for p in plays] if plays else added
    hours = [0] * 24
    week = [[0] * 24 for _ in range(7)]  # Monday-first rows
    for moment in moments:
        hours[moment.hour] += 1
        week[moment.weekday()][moment.hour] += 1
    peak_hour = max(range(24), key=lambda h: hours[h]) if moments else None
    weekday_totals = [sum(row) for row in week]
    peak_day = (
        ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][
            max(range(7), key=lambda d: weekday_totals[d])
        ] if moments else None
    )

    span_days = None
    if len(plays) >= 2:
        span_days = max(1, round((plays[0]["played_at"] - plays[-1]["played_at"]).total_seconds() / 86400))
    minutes_sampled = round(sum(p["duration_ms"] or 0 for p in plays) / 60000)

    play_counts = Counter(p["artist"] for p in plays if p["artist"])
    on_repeat_counts = Counter((p["title"], p["artist"]) for p in plays if p["title"])
    on_repeat = [
        {"name": title, "artist": artist, "plays": n}
        for (title, artist), n in on_repeat_counts.most_common(5) if n > 1
    ]

    # --- Personality ---
    taste_label, taste_line = _taste_personality(fresh_share, median_year, loyalty)
    time_label, time_line = _time_personality(peak_hour) if peak_hour is not None else (None, None)

    return {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "profile": {
            "name": user.get("display_name") or user.get("id", "You"),
            "image": _image(user.get("images", []), 0),
        },
        "personality": {
            "taste_label": taste_label,
            "taste_line": taste_line,
            "time_label": time_label,
            "time_line": time_line,
        },
        "headline": {
            "library_size": library_size,
            "median_year": median_year,
            "fresh_share": fresh_share,
            "singles_share": singles_share,
            "variety": variety,
            "explicit_share": explicit_share,
            "avg_length_s": avg_length,
            "loyalty": round(loyalty * 100),
        },
        "top_artists": {term: [artist_card(a) for a in top_artists[term][:10]] for term in TERMS},
        "top_tracks": {term: [track_card(t) for t in top_tracks[term][:10]] for term in TERMS},
        "decades": decades,
        "library": {
            "months": months,
            "first_like": first_like,
            "biggest_month": {"month": biggest_month[0], "count": biggest_month[1]} if biggest_month else None,
            "sampled": len(added),
        },
        "evolution": {"new_obsessions": new_obsessions, "ride_or_die": ride_or_die},
        "listening": {
            "clock_source": clock_source,
            "hours": hours,
            "week": week,
            "peak_hour": peak_hour,
            "peak_day": peak_day,
            "plays_sampled": len(plays),
            "logged_plays": len(log_entries),
            "span_days": span_days,
            "minutes_sampled": minutes_sampled,
            "top_recent_artist": play_counts.most_common(1)[0][0] if play_counts else None,
            "on_repeat": on_repeat,
            "recent": [
                {
                    "name": p["title"],
                    "artist": p["artist"],
                    "image": p["image"],
                    "played_at": p["played_at"].isoformat(timespec="minutes"),
                }
                for p in plays[:8]
            ],
            "recent_error": recent_error,
        },
    }


def get_stats(sp, force_refresh: bool = False) -> dict:
    """
    Returns cached stats, rebuilding them at most every 10 minutes.
    """
    global _stats_cache, _stats_cache_time
    now = time.time()
    if force_refresh or _stats_cache is None or now - _stats_cache_time > STATS_CACHE_TTL:
        _stats_cache = build_stats(sp)
        _stats_cache_time = now
    return _stats_cache

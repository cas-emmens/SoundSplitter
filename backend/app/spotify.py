"""Spotify Web API: OAuth + current-track polling + search/playback (via spotipy)."""
from __future__ import annotations

from typing import Optional

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from . import config

_oauth: Optional[SpotifyOAuth] = None
_REQUIRED_SCOPES = set(config.SPOTIFY_SCOPES.split())


class PlaybackError(RuntimeError):
    """Raised when a playback command fails for a user-actionable reason."""


def _auth() -> SpotifyOAuth:
    global _oauth
    if _oauth is None:
        _oauth = SpotifyOAuth(
            client_id=config.SPOTIPY_CLIENT_ID,
            client_secret=config.SPOTIPY_CLIENT_SECRET,
            redirect_uri=config.SPOTIPY_REDIRECT_URI,
            scope=config.SPOTIFY_SCOPES,
            cache_path=str(config.SPOTIFY_CACHE),
            open_browser=False,
        )
    return _oauth


def configured() -> bool:
    return bool(config.SPOTIPY_CLIENT_ID and config.SPOTIPY_CLIENT_SECRET)


def is_authenticated() -> bool:
    """Authenticated AND the cached token covers all currently-required scopes.

    Returning False when scopes are missing makes the UI prompt a reconnect after
    we add new scopes (e.g. playback control), instead of silently 403-ing.
    """
    if not configured():
        return False
    tok = _auth().cache_handler.get_cached_token()
    if not tok:
        return False
    have = set((tok.get("scope") or "").split())
    return _REQUIRED_SCOPES.issubset(have)


def login_url() -> str:
    return _auth().get_authorize_url()


def complete_login(code: str) -> None:
    _auth().get_access_token(code, as_dict=False, check_cache=False)


def _client() -> Optional[spotipy.Spotify]:
    if not is_authenticated():
        return None
    return spotipy.Spotify(auth_manager=_auth())


def now_playing() -> Optional[dict]:
    """Normalized current-playback state, or None if nothing/unauthenticated.

    Returns: {track_id, title, artist, album, art_url, duration_ms, progress_ms,
              is_playing, is_ad}
    """
    sp = _client()
    if sp is None:
        return None
    try:
        cur = sp.current_playback(additional_types="track,episode")
    except Exception:
        return None
    if not cur:
        return None

    item = cur.get("item")
    currently = cur.get("currently_playing_type")
    if currently == "ad" or item is None:
        return {"is_ad": True, "is_playing": cur.get("is_playing", False),
                "track_id": None, "progress_ms": cur.get("progress_ms", 0)}

    images = (item.get("album") or {}).get("images") or []
    return {
        "is_ad": False,
        "track_id": item.get("id"),
        "title": item.get("name", "Unknown"),
        "artist": ", ".join(a["name"] for a in item.get("artists", [])) or "Unknown",
        "album": (item.get("album") or {}).get("name"),
        "art_url": images[0]["url"] if images else None,
        "duration_ms": item.get("duration_ms", 0),
        "progress_ms": cur.get("progress_ms", 0),
        "is_playing": cur.get("is_playing", False),
    }


def _track_summary(item: dict) -> dict:
    images = (item.get("album") or {}).get("images") or []
    return {
        "track_id": item.get("id"),
        "uri": item.get("uri"),
        "title": item.get("name", "Unknown"),
        "artist": ", ".join(a["name"] for a in item.get("artists", [])) or "Unknown",
        "album": (item.get("album") or {}).get("name"),
        "art_url": images[-1]["url"] if images else None,  # smallest thumbnail
        "duration_ms": item.get("duration_ms", 0),
    }


def search(query: str, limit: int = 10) -> list[dict]:
    sp = _client()
    if sp is None or not query.strip():
        return []
    # Spotify's search endpoint currently rejects limits above 10.
    res = sp.search(q=query, type="track", limit=min(limit, 10))
    items = (res.get("tracks") or {}).get("items") or []
    return [_track_summary(it) for it in items]


def product() -> Optional[str]:
    """'premium' / 'free' / None — playback control needs 'premium'."""
    sp = _client()
    if sp is None:
        return None
    try:
        return sp.me().get("product")
    except Exception:
        return None


def devices() -> list[dict]:
    sp = _client()
    if sp is None:
        return []
    try:
        return sp.devices().get("devices", [])
    except Exception:
        return []


def _resolve_device(device_id: Optional[str]) -> Optional[str]:
    """Pick a device to play on: the caller's choice, else the active one, else the
    only device available (so a single idle device still works)."""
    if device_id:
        return device_id
    devs = devices()
    active = next((d for d in devs if d.get("is_active")), None)
    if active:
        return active["id"]
    return devs[0]["id"] if len(devs) == 1 else None


def play_track(track_id: str, device_id: Optional[str] = None) -> None:
    """Start the given track from the beginning on the active (or given) device."""
    sp = _client()
    if sp is None:
        raise PlaybackError("Connect Spotify first.")
    uri = track_id if track_id.startswith("spotify:") else f"spotify:track:{track_id}"
    dev = _resolve_device(device_id)
    try:
        # Make sure the track can't loop forever (which would re-record it).
        try:
            sp.repeat("off", device_id=dev)
        except Exception:
            pass
        # Explicit device id also transfers playback to (and wakes) an idle device.
        sp.start_playback(device_id=dev, uris=[uri])
    except spotipy.SpotifyException as exc:
        if exc.http_status == 403:
            raise PlaybackError(
                "Spotify Premium is required to control playback from the app."
            ) from exc
        if exc.http_status == 404:
            raise PlaybackError(
                "No active Spotify device. Open Spotify (with output set to CABLE "
                "Input), press play once, then try again."
            ) from exc
        raise PlaybackError(f"Spotify playback error: {exc.msg or exc}") from exc


def pause() -> None:
    sp = _client()
    if sp is None:
        return
    try:
        sp.pause_playback()
    except Exception:
        pass  # already paused / no active device — nothing to do

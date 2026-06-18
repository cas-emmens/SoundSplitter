"""Central configuration and paths."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# backend/ directory (this file is backend/app/config.py)
BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

# --- Storage ---
DATA_DIR = BACKEND_DIR / "data"
LIBRARY_DIR = DATA_DIR / "library"      # data/library/{track_id}/{stem}.flac
DB_PATH = DATA_DIR / "library.db"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

# --- Audio / model ---
SAMPLE_RATE = 44100
MODEL_NAME = "htdemucs_6s"
MODEL_STEMS = ["drums", "bass", "other", "vocals", "guitar", "piano"]
# Stems muted by the one-tap "Practice mode" preset.
PRACTICE_MUTE = ["vocals", "guitar"]

# --- Capture ---
# Substring matched against input device names to find the VB-CABLE capture endpoint.
CAPTURE_DEVICE_MATCH = os.getenv("CAPTURE_DEVICE_MATCH", "CABLE Output")
CAPTURE_BLOCK = 2048                     # frames per audio callback block
POLL_INTERVAL = 1.0                      # seconds between Spotify now-playing polls
# Only begin capturing a track if first seen within this many ms of its start,
# so we don't store partial songs we joined late.
START_THRESHOLD_MS = 10_000
RING_SECONDS = 12 * 60                   # rolling capture buffer length
# A finished capture is only kept if its length matches Spotify's reported track
# duration within this tolerance (seconds). Seeking/skipping mid-song breaks the
# capture window, so a mismatch means the recording is junk and is discarded.
CAPTURE_LENGTH_TOLERANCE_S = float(os.getenv("CAPTURE_LENGTH_TOLERANCE_S", "2.0"))

# --- Spotify ---
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID", "")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET", "")
SPOTIPY_REDIRECT_URI = os.getenv(
    "SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8000/api/spotify/callback"
)
SPOTIFY_SCOPES = ("user-read-currently-playing user-read-playback-state "
                  "user-modify-playback-state user-read-private")
SPOTIFY_CACHE = DATA_DIR / ".spotify_token_cache"

# --- Server ---
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:4200")

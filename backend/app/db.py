"""SQLite library: songs and their stems (model-produced + user-imported)."""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from typing import Iterator, Optional

from . import config

# Song.status lifecycle: capturing -> queued -> separating -> done | error
SCHEMA = """
CREATE TABLE IF NOT EXISTS songs (
    track_id      TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    artist        TEXT NOT NULL,
    album         TEXT,
    art_url       TEXT,
    duration_ms   INTEGER,
    original_path TEXT,
    status        TEXT NOT NULL DEFAULT 'queued',
    error         TEXT,
    created_at    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS stems (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id   TEXT NOT NULL REFERENCES songs(track_id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,            -- 'model' | 'user'
    name       TEXT NOT NULL,
    path       TEXT NOT NULL,
    gain       REAL NOT NULL DEFAULT 1.0,
    offset_ms  INTEGER NOT NULL DEFAULT 0,
    trim_start_ms INTEGER NOT NULL DEFAULT 0,   -- ms removed from the front
    trim_end_ms   INTEGER NOT NULL DEFAULT 0,   -- ms removed from the end
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stems_track ON stems(track_id);
"""


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        # Add columns introduced after the first release to existing databases.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(stems)")}
        for col in ("trim_start_ms", "trim_end_ms"):
            if col not in cols:
                conn.execute(
                    f"ALTER TABLE stems ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")


# --- songs ---

def song_exists(track_id: str) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM songs WHERE track_id=?", (track_id,)).fetchone()
        return row is not None


def upsert_song(track_id: str, title: str, artist: str, album: str,
                art_url: str, duration_ms: int, status: str = "queued") -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO songs (track_id, title, artist, album, art_url, duration_ms, status, created_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(track_id) DO UPDATE SET
                 title=excluded.title, artist=excluded.artist, album=excluded.album,
                 art_url=excluded.art_url, duration_ms=excluded.duration_ms""",
            (track_id, title, artist, album, art_url, duration_ms, status, time.time()),
        )


def set_song_status(track_id: str, status: str, error: Optional[str] = None) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE songs SET status=?, error=? WHERE track_id=?",
                     (status, error, track_id))


def set_original_path(track_id: str, path: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE songs SET original_path=? WHERE track_id=?", (path, track_id))


def delete_song(track_id: str) -> None:
    """Remove a song and its stems (FK cascade). Used to discard bad captures."""
    with get_conn() as conn:
        conn.execute("DELETE FROM songs WHERE track_id=?", (track_id,))


def get_song(track_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM songs WHERE track_id=?", (track_id,)).fetchone()
        return dict(row) if row else None


def list_songs() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM songs ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


# --- stems ---

def add_stem(track_id: str, kind: str, name: str, path: str,
             gain: float = 1.0, offset_ms: int = 0) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO stems (track_id, kind, name, path, gain, offset_ms, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (track_id, kind, name, path, gain, offset_ms, time.time()),
        )
        return int(cur.lastrowid)


def get_stems(track_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM stems WHERE track_id=? ORDER BY kind, id", (track_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_stem(stem_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM stems WHERE id=?", (stem_id,)).fetchone()
        return dict(row) if row else None


def update_stem(stem_id: int, **fields) -> None:
    allowed = {"name", "gain", "offset_ms", "trim_start_ms", "trim_end_ms"}
    sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not sets:
        return
    cols = ", ".join(f"{k}=?" for k in sets)
    with get_conn() as conn:
        conn.execute(f"UPDATE stems SET {cols} WHERE id=?", (*sets.values(), stem_id))


def delete_stem(stem_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM stems WHERE id=?", (stem_id,))


def clear_model_stems(track_id: str) -> None:
    """Remove model stems before (re)writing them; user stems are preserved."""
    with get_conn() as conn:
        conn.execute("DELETE FROM stems WHERE track_id=? AND kind='model'", (track_id,))

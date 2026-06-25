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
CREATE TABLE IF NOT EXISTS tabs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id   TEXT NOT NULL REFERENCES songs(track_id) ON DELETE CASCADE,
    stem_id    INTEGER REFERENCES stems(id) ON DELETE SET NULL,  -- audio stem this tab follows
    name       TEXT NOT NULL,
    source_url TEXT,                       -- the tab webpage it was generated from
    alphatex   TEXT,                       -- the transcription (filled when status='done')
    status     TEXT NOT NULL DEFAULT 'pending',  -- pending | done | error
    error      TEXT,
    timing     TEXT,                        -- JSON warp (notated<->audio anchors), filled by tabsync
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tabs_track ON tabs(track_id);
CREATE TABLE IF NOT EXISTS progressions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    root_pc    INTEGER NOT NULL DEFAULT 0,    -- default key pitch-class (0=C .. 11=B)
    quality    TEXT NOT NULL DEFAULT 'major', -- 'major' | 'minor' key flavour
    chords     TEXT NOT NULL,                 -- JSON array of roman numerals
    tempo      INTEGER NOT NULL DEFAULT 100,  -- default BPM
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS wiki_articles (
    slug           TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    category       TEXT NOT NULL,
    category_order INTEGER NOT NULL DEFAULT 0,
    sort           INTEGER NOT NULL DEFAULT 0,
    widget         TEXT,                       -- interactive explorer to embed (or NULL)
    widget_arg     TEXT,                       -- preset for that explorer (e.g. 'dorian')
    body           TEXT NOT NULL,              -- Markdown
    updated_at     REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
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
        tab_cols = {r["name"] for r in conn.execute("PRAGMA table_info(tabs)")}
        if "timing" not in tab_cols:
            conn.execute("ALTER TABLE tabs ADD COLUMN timing TEXT")


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


# --- tabs (manually added, generated from a webpage URL via the image-tabs library) ---

def create_tab(track_id: str, name: str, stem_id: int | None, source_url: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO tabs (track_id, stem_id, name, source_url, status, created_at)
               VALUES (?, ?, ?, ?, 'pending', ?)""",
            (track_id, stem_id, name, source_url, time.time()),
        )
        return int(cur.lastrowid)


def set_tab_result(tab_id: int, *, alphatex: Optional[str] = None,
                   status: str = "done", error: Optional[str] = None) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE tabs SET alphatex=?, status=?, error=? WHERE id=?",
                     (alphatex, status, error, tab_id))


def set_tab_timing(tab_id: int, timing_json: str) -> None:
    """Store the tabsync warp (JSON) for a tab; computed in the background after generation."""
    with get_conn() as conn:
        conn.execute("UPDATE tabs SET timing=? WHERE id=?", (timing_json, tab_id))


def update_tab_alphatex(tab_id: int, alphatex: str) -> None:
    """Persist a user-edited tab transcription (from the editor); keeps status 'done'."""
    with get_conn() as conn:
        conn.execute("UPDATE tabs SET alphatex=?, status='done', error=NULL WHERE id=?",
                     (alphatex, tab_id))


def get_tab(tab_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tabs WHERE id=?", (tab_id,)).fetchone()
        return dict(row) if row else None


def get_tabs(track_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tabs WHERE track_id=? ORDER BY created_at", (track_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def delete_tab(tab_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM tabs WHERE id=?", (tab_id,))


# --- practice: user-saved chord progressions (global, not tied to a song) ---

def create_progression(name: str, root_pc: int, quality: str, chords_json: str, tempo: int) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO progressions (name, root_pc, quality, chords, tempo, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, root_pc, quality, chords_json, tempo, time.time()),
        )
        return int(cur.lastrowid)


def get_progressions() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM progressions ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]


def get_progression(prog_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM progressions WHERE id=?", (prog_id,)).fetchone()
        return dict(row) if row else None


def update_progression(prog_id: int, *, name: Optional[str] = None, root_pc: Optional[int] = None,
                       quality: Optional[str] = None, chords_json: Optional[str] = None,
                       tempo: Optional[int] = None) -> None:
    sets, vals = [], []
    for col, val in (("name", name), ("root_pc", root_pc), ("quality", quality),
                     ("chords", chords_json), ("tempo", tempo)):
        if val is not None:
            sets.append(f"{col}=?")
            vals.append(val)
    if not sets:
        return
    vals.append(prog_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE progressions SET {', '.join(sets)} WHERE id=?", vals)


def delete_progression(prog_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM progressions WHERE id=?", (prog_id,))


# --- music-theory wiki (reference content, seeded from the bundled wiki_content module) ---

def seed_wiki(version: int, articles: list[dict]) -> bool:
    """Upsert the bundled wiki content into the DB, but only when it's newer than what's stored.

    Guarded by an integer content version in app_meta so first launch seeds it and a later app
    update (which bumps WIKI_VERSION) re-seeds it, while an unchanged version is a cheap no-op.
    Returns True if it (re)seeded. Wiki rows are reference data, not user data, so this overwrites.
    """
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM app_meta WHERE key='wiki_version'").fetchone()
        stored = int(row["value"]) if row and row["value"] is not None else -1
        if stored >= version:
            return False
        now = time.time()
        slugs = [a["slug"] for a in articles]
        for a in articles:
            conn.execute(
                """INSERT OR REPLACE INTO wiki_articles
                   (slug, title, category, category_order, sort, widget, widget_arg, body, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (a["slug"], a["title"], a["category"], a.get("category_order", 0), a.get("order", 0),
                 a.get("widget"), a.get("widget_arg"), a["body"], now),
            )
        # Drop any articles removed since the last seed.
        if slugs:
            placeholders = ",".join("?" * len(slugs))
            conn.execute(f"DELETE FROM wiki_articles WHERE slug NOT IN ({placeholders})", slugs)
        conn.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES ('wiki_version', ?)",
                     (str(version),))
        return True


def get_wiki_index() -> list[dict]:
    """All articles without bodies, ordered for the sidebar."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT slug, title, category, category_order, sort, widget, widget_arg
               FROM wiki_articles ORDER BY category_order, sort, title"""
        ).fetchall()
        return [dict(r) for r in rows]


def get_wiki_article(slug: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM wiki_articles WHERE slug=?", (slug,)).fetchone()
        return dict(row) if row else None

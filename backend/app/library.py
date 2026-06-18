"""Library queries and user-stem import."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from . import config, db, encoder


def list_songs() -> list[dict]:
    songs = db.list_songs()
    for s in songs:
        s["stem_count"] = len(db.get_stems(s["track_id"]))
    return songs


def delete_song(track_id: str) -> bool:
    """Remove a song, its stems (DB cascade), and all its files. False if unknown."""
    if db.get_song(track_id) is None:
        return False
    db.delete_song(track_id)
    shutil.rmtree(config.LIBRARY_DIR / track_id, ignore_errors=True)
    return True


def song_detail(track_id: str) -> dict | None:
    song = db.get_song(track_id)
    if song is None:
        return None
    song["stems"] = db.get_stems(track_id)
    return song


def import_user_stem(track_id: str, src_path: str | Path, name: str,
                     offset_ms: int = 0) -> dict:
    """Transcode an uploaded recording to FLAC and attach it as a user stem."""
    if db.get_song(track_id) is None:
        raise ValueError("unknown track")
    data, _sr = encoder.load_audio(src_path, target_sr=config.SAMPLE_RATE, stereo=True)
    out_dir = config.LIBRARY_DIR / track_id
    filename = f"user_{int(time.time() * 1000)}.flac"
    dest = out_dir / filename
    encoder.write_flac(dest, data, config.SAMPLE_RATE)
    stem_id = db.add_stem(track_id, "user", name, str(dest), offset_ms=offset_ms)
    return db.get_stem(stem_id)


def stem_file_path(track_id: str, stem_name: str) -> Path | None:
    for stem in db.get_stems(track_id):
        if stem["name"] == stem_name:
            return Path(stem["path"])
    return None

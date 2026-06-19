"""Library queries and user-stem import."""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

import numpy as np

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


def stem_peaks(track_id: str, stem_name: str, buckets: int = 1200) -> dict | None:
    """Downsampled waveform envelope for drawing. Cached next to the audio file."""
    path = stem_file_path(track_id, stem_name)
    if path is None or not path.exists():
        return None
    cache = path.with_suffix(".peaks.json")
    if cache.exists() and cache.stat().st_mtime >= path.stat().st_mtime:
        try:
            return json.loads(cache.read_text())
        except Exception:
            pass  # fall through and recompute

    data, sr = encoder.load_audio(path, target_sr=None, stereo=False)
    mono = data.mean(axis=1) if data.ndim == 2 else data
    n = int(mono.shape[0])
    if n == 0:
        result = {"peaks": [], "duration": 0.0}
    else:
        b = min(buckets, n)
        edges = np.linspace(0, n, b + 1, dtype=int)
        peaks = [float(np.abs(mono[edges[i]:edges[i + 1]]).max())
                 if edges[i + 1] > edges[i] else 0.0 for i in range(b)]
        result = {"peaks": peaks, "duration": n / sr}
    try:
        cache.write_text(json.dumps(result))
    except Exception:
        pass
    return result


def _safe(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip() or "stem"


def export_for_daw(track_id: str) -> str | None:
    """Render every stem trimmed + aligned to a common start, same length, as 24-bit
    WAVs in data/exports/<song>/. Import them all at 0:00 in any DAW and they line up.
    Mix gains are intentionally NOT baked in — mix in the DAW."""
    song = db.get_song(track_id)
    if song is None:
        return None
    sr = config.SAMPLE_RATE

    rendered: list[dict] = []
    for st in db.get_stems(track_id):
        p = Path(st["path"])
        if not p.exists():
            continue
        data, _ = encoder.load_audio(p, target_sr=sr, stereo=True)
        a = max(0, min(int(round(st.get("trim_start_ms", 0) / 1000 * sr)), len(data)))
        end = max(a, len(data) - max(0, int(round(st.get("trim_end_ms", 0) / 1000 * sr))))
        rendered.append({"name": st["name"], "data": data[a:end],
                         "offset_ms": st.get("offset_ms", 0)})
    if not rendered:
        return None

    min_off = min(r["offset_ms"] for r in rendered)
    total = 0
    for r in rendered:
        r["front"] = int(round((r["offset_ms"] - min_off) / 1000 * sr))
        total = max(total, r["front"] + len(r["data"]))

    folder = f"{_safe(song['artist'])} - {_safe(song['title'])}"
    out_dir = config.DATA_DIR / "exports" / f"{track_id}_{folder}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, r in enumerate(rendered, start=1):
        buf = np.zeros((total, 2), dtype=np.float32)
        buf[r["front"]:r["front"] + len(r["data"])] = r["data"]
        encoder.write_wav(out_dir / f"{i:02d} - {_safe(r['name'])}.wav", buf, sr)

    (out_dir / "README.txt").write_text(
        "Stems exported from Sound Splitter.\n"
        f"Song: {song['artist']} - {song['title']}\n\n"
        "Import all WAVs and place each at the very start (0:00 / bar 1). They are\n"
        "trimmed, aligned to each other, and padded to the same length, so they will\n"
        "stay in sync. Mix levels are left at unity — set them in your DAW.\n")
    return str(out_dir)

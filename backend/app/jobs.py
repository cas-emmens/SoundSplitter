"""Background separation queue: one GPU job at a time."""
from __future__ import annotations

import queue
import threading
import traceback
from pathlib import Path

from . import config, db, encoder, separator

_q: "queue.Queue[str]" = queue.Queue()
_current: str | None = None
_worker: threading.Thread | None = None
_lock = threading.Lock()


def enqueue(track_id: str) -> None:
    db.set_song_status(track_id, "queued")
    _q.put(track_id)


def status() -> dict:
    return {"current": _current, "queued": list(_q.queue)}


def _process(track_id: str) -> None:
    song = db.get_song(track_id)
    if not song or not song.get("original_path"):
        db.set_song_status(track_id, "error", "missing original audio")
        return
    db.set_song_status(track_id, "separating")
    out_dir = config.LIBRARY_DIR / track_id

    stems = separator.separate(song["original_path"])
    db.clear_model_stems(track_id)
    for name, data in stems.items():
        path = out_dir / f"{name}.flac"
        encoder.write_flac(path, data, config.SAMPLE_RATE)
        db.add_stem(track_id, "model", name, str(path))

    db.set_song_status(track_id, "done")


def _run() -> None:
    global _current
    while True:
        track_id = _q.get()
        _current = track_id
        try:
            _process(track_id)
        except Exception as exc:  # noqa: BLE001 - record and continue
            traceback.print_exc()
            db.set_song_status(track_id, "error", str(exc))
        finally:
            _current = None
            _q.task_done()


def start_worker() -> None:
    global _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, name="separation-worker", daemon=True)
            _worker.start()
    # Re-enqueue any songs left mid-flight from a previous run.
    for song in db.list_songs():
        if song["status"] in ("queued", "separating"):
            enqueue(song["track_id"])

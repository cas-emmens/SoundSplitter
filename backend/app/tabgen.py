"""Generate a tab from a webpage URL via the image-tabs library, in a background thread.

This is intentionally separate from the GPU separation queue (jobs.py): tab generation is a
headless-browser capture + OCR (CPU/network bound), so it must not block separation. Each run
writes its result back to the tabs table (status: pending -> done | error).
"""
from __future__ import annotations

import os
import threading
import traceback

from . import db

# Serialize timing syncs per stem: importing several parts at once fires concurrent syncs that
# would otherwise race on the shared master alignment and leave inconsistent warps.
_stem_sync_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()

# Importing a whole song's guitar tabs at once starts several captures; each one is a headless
# Chromium + OCR pass, so a couple in flight is plenty — more just thrashes CPU/RAM.
_generation_gate = threading.Semaphore(2)


def _stem_lock(stem_id: int) -> threading.Lock:
    with _locks_guard:
        return _stem_sync_locks.setdefault(stem_id, threading.Lock())


def _ensure_tesseract() -> None:
    """Point image-tabs at a Tesseract binary if the environment hasn't already.

    Override with the TESSERACT_CMD env var; otherwise fall back to the per-user install used in
    development. A bundled installer should set TESSERACT_CMD to the shipped binary.
    """
    if os.environ.get("TESSERACT_CMD"):
        return
    candidate = os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe")
    if os.path.exists(candidate):
        os.environ["TESSERACT_CMD"] = candidate


def _run(tab_id: int, url: str, title: str, tuning: list[int] | None = None) -> None:
    try:
        _ensure_tesseract()
        # Heavy imports (OpenCV/Playwright) are deferred to the worker thread.
        from image_tabs import tabs_from_url

        with _generation_gate:
            alphatex = tabs_from_url(url, title=title, tuning=tuple(tuning) if tuning else None)
        if not alphatex.strip():
            db.set_tab_result(tab_id, status="error", error="no tab content recognized")
        else:
            db.set_tab_result(tab_id, alphatex=alphatex, status="done")
            # Align to the recording (cursor warp) — but when a whole song's tabs are being
            # generated together, only the LAST finisher syncs: the sync covers every done
            # sibling on the stem anyway, and earlier partial syncs would be redone n times.
            if not _has_pending_siblings(tab_id):
                sync_timing(tab_id)
    except Exception as exc:  # noqa: BLE001 - record on the tab row and keep the server alive
        traceback.print_exc()
        db.set_tab_result(tab_id, status="error", error=str(exc))


def _has_pending_siblings(tab_id: int) -> bool:
    tab = db.get_tab(tab_id)
    if not tab or not tab.get("stem_id"):
        return False
    return any(
        t.get("stem_id") == tab["stem_id"] and t.get("status") == "pending" and t["id"] != tab_id
        for t in db.get_tabs(tab["track_id"])
    )


def sync_timing(tab_id: int) -> None:
    """Align the stem's parts to the recording and store each one's warp (best-effort).

    A guitar stem often carries several parts panned differently (acoustic left, 12-string right).
    We align every done tab on the stem and **competitively** assign each its pan side, so each
    part aligns against the azimuth-isolated audio it actually lives in (a follower part can't
    steal the louder part's side). basic-pitch is cached per stem/side; runs under a per-stem lock
    so concurrent imports don't race. Timing is optional — failures are logged and swallowed.
    """
    try:
        import json

        tab = db.get_tab(tab_id)
        if not tab or not tab.get("stem_id"):
            return
        stem = db.get_stem(tab["stem_id"])
        if not stem:
            return
        from .tabsync import compute_timings_competitive

        with _stem_lock(tab["stem_id"]):
            siblings = [
                t for t in db.get_tabs(tab["track_id"])
                if t.get("stem_id") == tab["stem_id"]
                and t.get("status") == "done" and t.get("alphatex")
            ]
            if not siblings:
                return
            timings = compute_timings_competitive(stem["path"], [t["alphatex"] for t in siblings])
            for t, timing in zip(siblings, timings):
                db.set_tab_timing(t["id"], json.dumps(timing))
    except Exception:  # noqa: BLE001
        traceback.print_exc()


def start(tab_id: int, url: str, title: str, tuning: list[int] | None = None) -> None:
    """Kick off generation for an already-created (pending) tab row.

    ``tuning`` (MIDI pitches, high string first — from the track's site metadata) is passed
    through to the converter so the alphaTex carries the real string pitches.
    """
    threading.Thread(
        target=_run, args=(tab_id, url, title, tuning), name=f"tabgen-{tab_id}", daemon=True
    ).start()


def start_sync(tab_id: int) -> None:
    """Background-recompute a tab's timing (e.g. re-sync an existing tab)."""
    threading.Thread(
        target=sync_timing, args=(tab_id,), name=f"tabsync-{tab_id}", daemon=True
    ).start()

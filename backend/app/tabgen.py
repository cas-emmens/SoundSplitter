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


def _run(tab_id: int, url: str, title: str) -> None:
    try:
        _ensure_tesseract()
        # Heavy imports (OpenCV/Playwright) are deferred to the worker thread.
        from image_tabs import tabs_from_url

        alphatex = tabs_from_url(url, title=title)
        if not alphatex.strip():
            db.set_tab_result(tab_id, status="error", error="no tab content recognized")
        else:
            db.set_tab_result(tab_id, alphatex=alphatex, status="done")
            sync_timing(tab_id)  # align to the recording (cursor warp) once the tab exists
    except Exception as exc:  # noqa: BLE001 - record on the tab row and keep the server alive
        traceback.print_exc()
        db.set_tab_result(tab_id, status="error", error=str(exc))


def sync_timing(tab_id: int) -> None:
    """Align a done tab to its coupled guitar stem and store the warp (best-effort).

    Runs basic-pitch on the stem (cached per stem) + DTW alignment. Timing is optional, so any
    failure is logged and swallowed — the tab still works, the cursor just falls back to the
    notated tempo until a warp exists.
    """
    try:
        import json

        tab = db.get_tab(tab_id)
        if not tab or not tab.get("stem_id") or not tab.get("alphatex"):
            return
        stem = db.get_stem(tab["stem_id"])
        if not stem:
            return
        from .tabsync import compute_timing

        timing = compute_timing(stem["path"], tab["alphatex"])
        db.set_tab_timing(tab_id, json.dumps(timing))
    except Exception:  # noqa: BLE001
        traceback.print_exc()


def start(tab_id: int, url: str, title: str) -> None:
    """Kick off generation for an already-created (pending) tab row."""
    threading.Thread(
        target=_run, args=(tab_id, url, title), name=f"tabgen-{tab_id}", daemon=True
    ).start()


def start_sync(tab_id: int) -> None:
    """Background-recompute a tab's timing (e.g. re-sync an existing tab)."""
    threading.Thread(
        target=sync_timing, args=(tab_id,), name=f"tabsync-{tab_id}", daemon=True
    ).start()

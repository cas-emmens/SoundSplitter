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
    except Exception as exc:  # noqa: BLE001 - record on the tab row and keep the server alive
        traceback.print_exc()
        db.set_tab_result(tab_id, status="error", error=str(exc))


def start(tab_id: int, url: str, title: str) -> None:
    """Kick off generation for an already-created (pending) tab row."""
    threading.Thread(
        target=_run, args=(tab_id, url, title), name=f"tabgen-{tab_id}", daemon=True
    ).start()

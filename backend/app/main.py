"""FastAPI app: Spotify auth, capture control, library, stems, files."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse

from . import capture, config, db, jobs, library, separator, spotify

app = FastAPI(title="sound-splitter")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.FRONTEND_ORIGIN],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    # A 'capturing' row means a recording was interrupted by a restart; its audio
    # lived only in the in-memory ring, so it can't be recovered — drop it.
    for song in db.list_songs():
        if song["status"] == "capturing":
            library.delete_song(song["track_id"])
    jobs.start_worker()


# --- health / info ---
@app.get("/api/health")
def health() -> dict:
    return {"ok": True, **separator.device_info(),
            "spotify_configured": spotify.configured(),
            "spotify_authenticated": spotify.is_authenticated()}


# --- Spotify OAuth ---
@app.get("/api/spotify/login")
def spotify_login():
    if not spotify.configured():
        raise HTTPException(400, "Spotify client credentials not configured (.env)")
    return RedirectResponse(spotify.login_url())


@app.get("/api/spotify/callback")
def spotify_callback(code: str | None = None, error: str | None = None):
    if error or not code:
        raise HTTPException(400, f"Spotify auth failed: {error or 'no code'}")
    spotify.complete_login(code)
    return RedirectResponse(f"{config.FRONTEND_ORIGIN}/capture?spotify=ok")


@app.get("/api/now-playing")
def now_playing() -> dict:
    state = spotify.now_playing()
    return state or {"is_playing": False, "track_id": None}


# --- Spotify search + playback control ---
@app.get("/api/spotify/search")
def spotify_search(q: str = "") -> dict:
    return {"results": spotify.search(q)}


@app.get("/api/spotify/devices")
def spotify_devices() -> dict:
    return {"devices": spotify.devices(), "product": spotify.product()}


@app.post("/api/spotify/record")
def spotify_record(payload: dict) -> dict:
    track_id = (payload or {}).get("track_id")
    if not track_id:
        raise HTTPException(400, "track_id required")
    if db.song_exists(track_id):
        raise HTTPException(409, "This song is already in your library.")
    if capture.service.status()["capturing_track"] or capture.service.status()["requested_track"]:
        raise HTTPException(409, "A recording is already in progress.")

    # Make sure the capture stream is open before we start playback.
    st = capture.service.start()
    if st.get("error"):
        raise HTTPException(400, st["error"])

    capture.service.request_track(track_id, payload.get("meta"))
    try:
        spotify.play_track(track_id, payload.get("device_id"))
    except spotify.PlaybackError as exc:
        capture.service.cancel_request()
        raise HTTPException(400, str(exc)) from exc
    return capture.service.status()


@app.post("/api/spotify/pause")
def spotify_pause() -> dict:
    # Clear the in-progress capture first so the poller doesn't finalize it as a
    # failed recording, then stop Spotify.
    st = capture.service.cancel_request()
    spotify.pause()
    return st


# --- capture control ---
@app.get("/api/capture/status")
def capture_status() -> dict:
    return capture.service.status()


@app.get("/api/capture/devices")
def capture_devices() -> dict:
    return {"devices": capture.CaptureService.list_input_devices(),
            "match": config.CAPTURE_DEVICE_MATCH}


@app.post("/api/capture/start")
def capture_start() -> dict:
    return capture.service.start()


@app.post("/api/capture/stop")
def capture_stop() -> dict:
    return capture.service.stop()


@app.delete("/api/capture/failed/{fid}")
def capture_dismiss_failed(fid: int) -> dict:
    return capture.service.dismiss_failed(fid)


# --- library ---
@app.get("/api/library")
def get_library() -> dict:
    return {"songs": library.list_songs()}


@app.get("/api/songs/{track_id}")
def get_song(track_id: str) -> dict:
    detail = library.song_detail(track_id)
    if detail is None:
        raise HTTPException(404, "song not found")
    detail["practice_mute"] = config.PRACTICE_MUTE
    return detail


@app.delete("/api/songs/{track_id}")
def delete_song(track_id: str) -> dict:
    if not library.delete_song(track_id):
        raise HTTPException(404, "song not found")
    return {"ok": True}


@app.post("/api/songs/{track_id}/export")
def export_song(track_id: str) -> dict:
    """Render trimmed + aligned stems to a folder and open it (local desktop app)."""
    path = library.export_for_daw(track_id)
    if path is None:
        raise HTTPException(404, "nothing to export")
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]  # opens Explorer
    except Exception:
        pass
    return {"path": path}


@app.get("/api/jobs")
def get_jobs() -> dict:
    return jobs.status()


# --- stems ---
@app.post("/api/songs/{track_id}/stems")
async def import_stem(track_id: str, file: UploadFile = File(...),
                      name: str = Form("My take"), offset_ms: int = Form(0)) -> dict:
    if db.get_song(track_id) is None:
        raise HTTPException(404, "song not found")
    suffix = Path(file.filename or "take").suffix or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        stem = library.import_user_stem(track_id, tmp_path, name, offset_ms)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return stem


@app.patch("/api/stems/{stem_id}")
def patch_stem(stem_id: int, payload: dict) -> dict:
    if db.get_stem(stem_id) is None:
        raise HTTPException(404, "stem not found")
    db.update_stem(stem_id, name=payload.get("name"),
                   gain=payload.get("gain"), offset_ms=payload.get("offset_ms"),
                   trim_start_ms=payload.get("trim_start_ms"),
                   trim_end_ms=payload.get("trim_end_ms"))
    return db.get_stem(stem_id)


@app.delete("/api/stems/{stem_id}")
def remove_stem(stem_id: int) -> dict:
    stem = db.get_stem(stem_id)
    if stem is None:
        raise HTTPException(404, "stem not found")
    if stem["kind"] == "model":
        raise HTTPException(400, "cannot delete a model stem")
    Path(stem["path"]).unlink(missing_ok=True)
    db.delete_stem(stem_id)
    return {"ok": True}


# --- file serving ---
@app.get("/api/files/{track_id}/{stem_name}")
def get_stem_file(track_id: str, stem_name: str):
    name = stem_name[:-5] if stem_name.endswith(".flac") else stem_name
    path = library.stem_file_path(track_id, name)
    if path is None or not path.exists():
        raise HTTPException(404, "stem file not found")
    return FileResponse(path, media_type="audio/flac")


@app.get("/api/files/{track_id}/{stem_name}/peaks")
def get_stem_peaks(track_id: str, stem_name: str) -> dict:
    name = stem_name[:-5] if stem_name.endswith(".flac") else stem_name
    data = library.stem_peaks(track_id, name)
    if data is None:
        raise HTTPException(404, "stem file not found")
    return data


# --- built frontend (SPA) ---
# Registered last so it never shadows the /api routes above. Serves the compiled
# Angular app from FRONTEND_DIST, falling back to index.html for client-side
# routes (e.g. /capture, /library, /player). This lets the Tauri desktop window
# (and any browser) load the whole app from this single origin.
@app.get("/{full_path:path}")
def serve_frontend(full_path: str):
    root = config.FRONTEND_DIST
    index = root / "index.html"
    if not index.exists():
        raise HTTPException(404, "frontend not built (run: npm run build)")
    candidate = (root / full_path).resolve()
    if full_path and candidate.is_file() and root.resolve() in candidate.parents:
        return FileResponse(candidate)
    return FileResponse(index)

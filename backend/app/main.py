"""FastAPI app: Spotify auth, capture control, library, stems, files."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse

from . import (capture, config, db, jobs, library, separator, spotify, tabgen, wiki_content)

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
    # Seed/refresh the music-theory wiki from the bundled content (no-op when already current).
    db.seed_wiki(wiki_content.WIKI_VERSION, wiki_content.ARTICLES)
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


# --- tabs (added manually, generated from a webpage URL via the image-tabs library) ---
def _tab_dict(row: dict) -> dict:
    import json

    raw = row.get("timing") if isinstance(row, dict) else row["timing"]
    return {
        "id": row["id"], "track_id": row["track_id"], "stem_id": row["stem_id"],
        "name": row["name"], "source_url": row["source_url"],
        "status": row["status"], "error": row["error"],
        "alphatex": row["alphatex"], "created_at": row["created_at"],
        "timing": json.loads(raw) if raw else None,  # tabsync warp (anchors); null until computed
    }


@app.post("/api/songs/{track_id}/tabs")
def create_tab(track_id: str, payload: dict) -> dict:
    """Create a tab for a song from a webpage URL, transcribed in the background.

    Body: ``{name, url, stem_id?}``. The tab is coupled to an audio stem so the tabs screen
    knows which track it follows. Generation (headless capture + OCR) runs asynchronously; poll
    GET /api/tabs/{id} until status is 'done' or 'error'.
    """
    if db.get_song(track_id) is None:
        raise HTTPException(404, "song not found")
    name = (payload.get("name") or "").strip()
    url = (payload.get("url") or "").strip()
    if not name or not url:
        raise HTTPException(400, "name and url are required")
    tab_id = db.create_tab(track_id, name, payload.get("stem_id"), url)
    tabgen.start(tab_id, url, name)
    return _tab_dict(db.get_tab(tab_id))


@app.post("/api/songs/{track_id}/tabs/from-song")
def create_tabs_from_song(track_id: str, payload: dict) -> dict:
    """Discover every guitar tab of the song at ``url`` and generate them all.

    Body: ``{url, stem_id?}``. One Songsterr URL is enough: the song's track list is read
    from the page and each non-empty guitar part becomes its own tab (named after the
    part, converted with its real tuning), all coupled to the same stem. Generation runs
    in the background; the stem's timing sync fires once, after the last part finishes.
    """
    if db.get_song(track_id) is None:
        raise HTTPException(404, "song not found")
    url = (payload.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "url is required")
    from image_tabs import guitar_tracks

    try:
        tracks = guitar_tracks(url)
    except Exception as exc:  # noqa: BLE001 - bad URL / site change / offline
        raise HTTPException(422, f"could not read the song's track list: {exc}") from exc
    if not tracks:
        raise HTTPException(422, "no guitar tabs found at that URL")

    tabs = []
    for track in tracks:
        name = _track_display_name(track)
        tab_id = db.create_tab(track_id, name, payload.get("stem_id"), track.url)
        tabgen.start(tab_id, track.url, name, tuning=list(track.tuning) if track.tuning else None)
        tabs.append(_tab_dict(db.get_tab(tab_id)))
    return {"tabs": tabs}


def _track_display_name(track) -> str:
    """A short tab name from the site's performer|gear|role line: the role, else instrument."""
    role = track.name.rsplit("|", 1)[-1].strip() if track.name else ""
    return role or track.instrument or f"Track {track.index}"


@app.get("/api/songs/{track_id}/tabs")
def list_tabs(track_id: str) -> dict:
    return {"tabs": [_tab_dict(t) for t in db.get_tabs(track_id)]}


@app.get("/api/tabs/{tab_id}")
def get_tab(tab_id: int) -> dict:
    tab = db.get_tab(tab_id)
    if tab is None:
        raise HTTPException(404, "tab not found")
    return _tab_dict(tab)


@app.patch("/api/tabs/{tab_id}")
def update_tab(tab_id: int, payload: dict) -> dict:
    """Save an edited tab transcription from the editor, then re-sync its timing in the background."""
    if db.get_tab(tab_id) is None:
        raise HTTPException(404, "tab not found")
    alphatex = payload.get("alphatex")
    if not isinstance(alphatex, str) or not alphatex.strip():
        raise HTTPException(400, "alphatex is required")
    db.update_tab_alphatex(tab_id, alphatex)
    tabgen.start_sync(tab_id)  # the warp depends on the notes, so recompute it
    return _tab_dict(db.get_tab(tab_id))


@app.post("/api/tabs/{tab_id}/sync")
def sync_tab(tab_id: int) -> dict:
    """Recompute a tab's timing warp in the background (basic-pitch + DTW against its stem)."""
    tab = db.get_tab(tab_id)
    if tab is None:
        raise HTTPException(404, "tab not found")
    tabgen.start_sync(tab_id)
    return {"ok": True}


@app.delete("/api/tabs/{tab_id}")
def delete_tab(tab_id: int) -> dict:
    db.delete_tab(tab_id)
    return {"ok": True}


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


# --- practice: user-saved chord progressions (global) ---
def _progression_dict(row: dict) -> dict:
    import json

    return {
        "id": row["id"], "name": row["name"], "root_pc": row["root_pc"],
        "quality": row["quality"], "chords": json.loads(row["chords"]),
        "tempo": row["tempo"], "created_at": row["created_at"],
    }


def _validate_progression(payload: dict) -> tuple[str, int, str, str, int]:
    """Pull + validate the progression fields from a request body. Returns the DB-ready tuple."""
    import json

    name = (payload.get("name") or "").strip()
    chords = payload.get("chords")
    if not name:
        raise HTTPException(400, "name is required")
    if not isinstance(chords, list) or not chords or not all(isinstance(c, str) for c in chords):
        raise HTTPException(400, "chords must be a non-empty array of roman numerals")
    quality = payload.get("quality", "major")
    if quality not in ("major", "minor"):
        raise HTTPException(400, "quality must be 'major' or 'minor'")
    root_pc = int(payload.get("root_pc", 0)) % 12
    tempo = max(20, min(400, int(payload.get("tempo", 100))))
    return name, root_pc, quality, json.dumps(chords), tempo


@app.get("/api/progressions")
def list_progressions() -> dict:
    return {"progressions": [_progression_dict(p) for p in db.get_progressions()]}


@app.post("/api/progressions")
def create_progression(payload: dict) -> dict:
    name, root_pc, quality, chords_json, tempo = _validate_progression(payload)
    pid = db.create_progression(name, root_pc, quality, chords_json, tempo)
    return _progression_dict(db.get_progression(pid))


@app.get("/api/progressions/{prog_id}")
def get_progression(prog_id: int) -> dict:
    prog = db.get_progression(prog_id)
    if prog is None:
        raise HTTPException(404, "progression not found")
    return _progression_dict(prog)


@app.patch("/api/progressions/{prog_id}")
def update_progression(prog_id: int, payload: dict) -> dict:
    if db.get_progression(prog_id) is None:
        raise HTTPException(404, "progression not found")
    name, root_pc, quality, chords_json, tempo = _validate_progression(payload)
    db.update_progression(prog_id, name=name, root_pc=root_pc, quality=quality,
                          chords_json=chords_json, tempo=tempo)
    return _progression_dict(db.get_progression(prog_id))


@app.delete("/api/progressions/{prog_id}")
def delete_progression(prog_id: int) -> dict:
    db.delete_progression(prog_id)
    return {"ok": True}


# --- music-theory wiki (seeded reference content) ---
@app.get("/api/wiki")
def wiki_index() -> dict:
    """Articles grouped by category, in display order, without bodies."""
    categories: list[dict] = []
    by_name: dict[str, dict] = {}
    for a in db.get_wiki_index():
        cat = by_name.get(a["category"])
        if cat is None:
            cat = {"name": a["category"], "articles": []}
            by_name[a["category"]] = cat
            categories.append(cat)
        cat["articles"].append({
            "slug": a["slug"], "title": a["title"],
            "widget": a["widget"], "widget_arg": a["widget_arg"],
        })
    return {"categories": categories}


@app.get("/api/wiki/{slug}")
def wiki_article(slug: str) -> dict:
    a = db.get_wiki_article(slug)
    if a is None:
        raise HTTPException(404, "article not found")
    return {
        "slug": a["slug"], "title": a["title"], "category": a["category"],
        "widget": a["widget"], "widget_arg": a["widget_arg"], "body": a["body"],
    }


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
    # index.html must never be cached, or the webview keeps loading an old build
    # (it points at hashed chunks); the hashed assets themselves stay cacheable.
    no_cache = {"Cache-Control": "no-cache, no-store, must-revalidate"}
    candidate = (root / full_path).resolve()
    if full_path and candidate.is_file() and root.resolve() in candidate.parents:
        if candidate.name == "index.html":
            return FileResponse(candidate, headers=no_cache)
        return FileResponse(candidate)
    return FileResponse(index, headers=no_cache)

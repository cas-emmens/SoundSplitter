"""Continuously capture the VB-CABLE output and slice it into songs using Spotify.

Strategy: always buffer incoming audio with wall-clock timestamps in a ring. When
Spotify reports a track change, the just-finished track's true start time is known
(detected_time - progress at detection), so we slice [start, start+duration] out of
the ring. This captures full songs even the part that played before we detected them.
"""
from __future__ import annotations

import shutil
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np
import soundfile as sf

from . import config, db, jobs, spotify

_CHANNELS = 2


class CaptureService:
    def __init__(self) -> None:
        self._stream = None
        self._ring: deque[tuple[float, np.ndarray]] = deque()
        self._ring_lock = threading.Lock()
        self._armed = False
        self._poller: threading.Thread | None = None
        self._stop = threading.Event()
        self._device_index: int | None = None
        self._device_name: str | None = None
        self._last_error: str | None = None
        # Track currently being captured.
        self._cur_id: str | None = None
        self._cur_meta: dict | None = None
        self._cur_start_wall: float | None = None
        # Recent captures rejected by validation (surfaced to the UI as prompts).
        self._failed: list[dict] = []
        self._failed_seq = 0
        # Targeted recording: only this track is captured (set by the record flow).
        self._requested: str | None = None
        self._requested_meta: dict | None = None

    # --- device discovery ---
    @staticmethod
    def list_input_devices() -> list[dict]:
        import sounddevice as sd
        devices = []
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                devices.append({"index": i, "name": d["name"],
                                "channels": d["max_input_channels"]})
        return devices

    def _find_device(self) -> int | None:
        for d in self.list_input_devices():
            if config.CAPTURE_DEVICE_MATCH.lower() in d["name"].lower():
                self._device_name = d["name"]
                return d["index"]
        return None

    # --- audio callback ---
    def _callback(self, indata, frames, time_info, status):  # noqa: ANN001
        now = time.time()
        block = np.array(indata, dtype=np.float32, copy=True)
        with self._ring_lock:
            self._ring.append((now, block))
            # Drop blocks older than the ring window.
            cutoff = now - config.RING_SECONDS
            while self._ring and self._ring[0][0] < cutoff:
                self._ring.popleft()

    # --- lifecycle ---
    def start(self) -> dict:
        if self._armed:
            return self.status()
        import sounddevice as sd

        self._device_index = self._find_device()
        if self._device_index is None:
            self._last_error = (
                f"Capture device matching '{config.CAPTURE_DEVICE_MATCH}' not found. "
                "Install VB-CABLE and set it as Spotify's output device."
            )
            return self.status()

        self._last_error = None
        self._stop.clear()
        self._stream = sd.InputStream(
            device=self._device_index, channels=_CHANNELS,
            samplerate=config.SAMPLE_RATE, blocksize=config.CAPTURE_BLOCK,
            dtype="float32", callback=self._callback,
        )
        self._stream.start()
        self._armed = True
        self._poller = threading.Thread(target=self._poll_loop, name="spotify-poller",
                                        daemon=True)
        self._poller.start()
        return self.status()

    def stop(self) -> dict:
        self._stop.set()
        self._armed = False
        if self._cur_id is not None:
            self._finalize()
        self._requested = self._requested_meta = None
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        return self.status()

    def status(self) -> dict:
        return {
            "armed": self._armed,
            "device": self._device_name,
            "capturing_track": self._cur_id,
            "requested_track": self._requested,
            "requested_meta": self._requested_meta,
            "spotify_authenticated": spotify.is_authenticated(),
            "spotify_configured": spotify.configured(),
            "error": self._last_error,
            "failed_captures": list(self._failed),
        }

    # --- targeted recording ---
    def request_track(self, track_id: str, meta: dict | None = None) -> dict:
        """Mark a track as the one to record next; the poller captures only it."""
        self._requested = track_id
        self._requested_meta = meta or {}
        return self.status()

    def cancel_request(self) -> dict:
        """Abort the targeted recording: drop any in-progress capture without
        leaving an orphan row or a 'discarded' prompt (this is a deliberate stop)."""
        self._requested = self._requested_meta = None
        if self._cur_id is not None:
            db.delete_song(self._cur_id)
            shutil.rmtree(config.LIBRARY_DIR / self._cur_id, ignore_errors=True)
            self._cur_id = self._cur_meta = self._cur_start_wall = None
        return self.status()

    def dismiss_failed(self, fid: int | None) -> dict:
        """Drop one rejected-capture prompt (or all when fid is None)."""
        if fid is None:
            self._failed.clear()
        else:
            self._failed = [f for f in self._failed if f["id"] != fid]
        return self.status()

    # --- polling loop ---
    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
            self._stop.wait(config.POLL_INTERVAL)

    def _tick(self) -> None:
        np_state = spotify.now_playing()

        # Nothing playing / paused / ad -> close any open capture.
        if not np_state or np_state.get("is_ad") or not np_state.get("is_playing"):
            if self._cur_id is not None:
                self._finalize()
            return

        tid = np_state.get("track_id")
        progress = np_state.get("progress_ms", 0)

        if self._cur_id is None:
            self._maybe_begin(np_state, tid, progress)
        elif tid != self._cur_id:
            # Previous track ended; capture it, then maybe begin the new one.
            self._finalize()
            self._maybe_begin(np_state, tid, progress)
        elif self._capture_complete():
            # Same track still 'playing' past its full length (e.g. repeat-one is
            # on): the song has played through once, so finalize instead of letting
            # it loop and re-record itself.
            self._finalize()

    def _capture_complete(self) -> bool:
        if self._cur_start_wall is None or self._cur_meta is None:
            return False
        duration_s = (self._cur_meta.get("duration_ms") or 0) / 1000.0
        if duration_s <= 0:
            return False
        return time.time() >= self._cur_start_wall + duration_s + 1.0

    def _maybe_begin(self, meta: dict, tid: str, progress: int) -> None:
        # Only record the track the user explicitly asked for (we start it at 0),
        # so auto-advanced or background tracks are never captured.
        if not tid or tid != self._requested or db.song_exists(tid):
            return
        self._cur_id = tid
        self._cur_meta = meta
        self._cur_start_wall = time.time() - progress / 1000.0
        db.upsert_song(tid, meta["title"], meta["artist"], meta.get("album") or "",
                       meta.get("art_url") or "", meta.get("duration_ms") or 0,
                       status="capturing")

    def _finalize(self) -> None:
        tid, meta, start_wall = self._cur_id, self._cur_meta, self._cur_start_wall
        self._cur_id = self._cur_meta = self._cur_start_wall = None
        if not tid or meta is None or start_wall is None:
            return
        try:
            self._finalize_capture(tid, meta, start_wall)
        finally:
            # The requested track is done (good or bad): stop playback so the
            # auto-advanced next song can't blast, and clear the request.
            if tid == self._requested:
                self._requested = self._requested_meta = None
                spotify.pause()

    def _finalize_capture(self, tid: str, meta: dict, start_wall: float) -> None:
        duration_s = (meta.get("duration_ms") or 0) / 1000.0
        end_wall = start_wall + duration_s + 1.0  # small tail guard
        audio = self._slice_ring(start_wall, end_wall)
        captured_s = 0.0 if audio is None else len(audio) / config.SAMPLE_RATE

        # Validate against Spotify's reported duration. A clean capture spans the
        # whole song; seeking/skipping mid-track truncates the window, so a length
        # mismatch means the recording is junk -> discard it and prompt a re-record.
        tol = config.CAPTURE_LENGTH_TOLERANCE_S
        if duration_s <= 0:
            return self._reject(tid, meta, captured_s, duration_s,
                                "no track duration from Spotify")
        if audio is None or captured_s < duration_s - tol:
            return self._reject(tid, meta, captured_s, duration_s,
                                "recording too short — the song was skipped or seeked")
        if captured_s > duration_s + 1.0 + tol:
            return self._reject(tid, meta, captured_s, duration_s,
                                "recording too long — the song was skipped or seeked")

        target = int(duration_s * config.SAMPLE_RATE)
        audio = audio[:target]

        out_dir = config.LIBRARY_DIR / tid
        out_dir.mkdir(parents=True, exist_ok=True)
        original = out_dir / "original.flac"
        sf.write(str(original), np.clip(audio, -1.0, 1.0), config.SAMPLE_RATE, format="FLAC")
        db.set_original_path(tid, str(original))
        jobs.enqueue(tid)

    def _reject(self, tid: str, meta: dict, captured_s: float, duration_s: float,
                reason: str) -> None:
        """Discard a bad capture: delete its row + files so it can be re-recorded,
        and queue a prompt for the UI."""
        db.delete_song(tid)
        shutil.rmtree(config.LIBRARY_DIR / tid, ignore_errors=True)
        self._failed_seq += 1
        self._failed.append({
            "id": self._failed_seq,
            "track_id": tid,
            "title": meta.get("title") or tid,
            "artist": meta.get("artist") or "",
            "captured_s": round(captured_s, 1),
            "expected_s": round(duration_s, 1),
            "reason": reason,
            "at": time.time(),
        })
        # Keep the prompt list bounded.
        self._failed = self._failed[-10:]

    def _slice_ring(self, start_wall: float, end_wall: float) -> np.ndarray | None:
        with self._ring_lock:
            blocks = [b for (ts, b) in self._ring if start_wall <= ts <= end_wall]
        if not blocks:
            return None
        return np.concatenate(blocks, axis=0)


service = CaptureService()

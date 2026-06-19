"""POC: stem -> note events -> beat-quantized ASCII tab, monophonic (librosa pyin).

Throwaway proof-of-concept (per the "standalone script first" pattern) to judge whether
automatic transcription produces *usable* tabs before wiring any UI. Downstream of pitch
detection it shares poc_tab.py (beat-grid quantization, fretboard, bar rendering) with the
basic-pitch POC.

MONOPHONIC only: pyin tracks one f0 per frame, so it is honest only for single-note material
(bass, lead, vocal melody). Best on the split-out guitar_lead stem (see poc_split_guitar.py).

Usage (3.13 backend venv):
    .venv\\Scripts\\python poc_transcribe.py <track_id> <stem> [--instrument guitar|bass]
                                             [--bpm N] [--subdiv 4] [--seconds 40]
"""
from __future__ import annotations

import argparse

import librosa
import numpy as np

import poc_tab
from app import config

MIN_NOTE_S = 0.08
PITCH_FMIN, PITCH_FMAX = "C1", "C7"


def track_notes(y: np.ndarray, sr: int) -> list[tuple[float, float, int, float]]:
    """pyin f0 -> (start_s, end_s, midi, amp=1.0) note events."""
    hop = 256
    f0, voiced, _ = librosa.pyin(
        y, sr=sr, hop_length=hop,
        fmin=librosa.note_to_hz(PITCH_FMIN), fmax=librosa.note_to_hz(PITCH_FMAX))
    times = librosa.times_like(f0, sr=sr, hop_length=hop)
    midi = np.full(f0.shape, np.nan)
    ok = voiced & ~np.isnan(f0)
    midi[ok] = np.round(librosa.hz_to_midi(f0[ok]))

    notes: list[tuple[float, float, int, float]] = []
    i, n = 0, len(midi)
    while i < n:
        if np.isnan(midi[i]):
            i += 1
            continue
        j = i + 1
        while j < n and midi[j] == midi[i]:
            j += 1
        start, end = times[i], times[min(j, n - 1)]
        if end - start >= MIN_NOTE_S:
            notes.append((float(start), float(end), int(midi[i]), 1.0))
        i = j
    return notes


def grid_source(track_id: str, sr: int) -> np.ndarray:
    """Beat-track on the drums stem when present (percussive = reliable beats)."""
    drums = config.LIBRARY_DIR / track_id / "drums.flac"
    path = drums if drums.exists() else None
    if path is None:
        return np.array([])
    y, _ = librosa.load(str(path), sr=sr, mono=True)
    return y


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("track_id")
    ap.add_argument("stem")
    ap.add_argument("--instrument", choices=list(poc_tab.TUNINGS), default="guitar")
    ap.add_argument("--bpm", type=float, default=None, help="tempo prior (fixes octave errors)")
    ap.add_argument("--subdiv", type=int, default=4, help="grid slots per beat (4 = 16ths)")
    ap.add_argument("--seconds", type=float, default=40.0)
    args = ap.parse_args()

    path = config.LIBRARY_DIR / args.track_id / f"{args.stem}.flac"
    if not path.exists():
        raise SystemExit(f"no such stem: {path}")

    print(f"Loading {path.name} ...")
    y, sr = librosa.load(str(path), sr=22050, mono=True)
    print(f"  {len(y)/sr:.1f}s @ {sr} Hz | tracking pitch (pyin) ...")
    notes = track_notes(y, sr)
    if not notes:
        raise SystemExit("no notes detected (silent or unpitched stem?)")

    drums_y = grid_source(args.track_id, sr)
    grid, tempo, slots_per_bar = poc_tab.beat_grid(
        drums_y if len(drums_y) else y, sr, subdiv=args.subdiv, start_bpm=args.bpm)
    max_slots = int(np.searchsorted(grid, args.seconds, side="right"))
    events = poc_tab.build_events(notes, grid, args.instrument, max_slots,
                                  dedup_octaves=False, amp_floor=0.0)
    pitches = [m for _s, _e, m, _a in notes]
    print(f"  {len(notes)} notes | grid tempo ~{tempo:.0f} bpm | "
          f"range {poc_tab.midi_name(min(pitches))}..{poc_tab.midi_name(max(pitches))}")
    print(f"  {poc_tab.value_histogram(events)}\n")

    print(f"--- tab ({args.instrument}, durations: onset=fret, ==sustain, --=silence, "
          f"first {args.seconds:.0f}s) ---\n")
    print(poc_tab.render_events(events, args.instrument, slots_per_bar, max_slots))


if __name__ == "__main__":
    main()

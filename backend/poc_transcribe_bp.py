"""POC #2: polyphonic transcription with Spotify's basic-pitch -> beat-quantized ASCII tab.

Runs in the throwaway Python 3.11 venv (.venv311-poc) because basic-pitch pins
tensorflow<2.16, which has no 3.13 wheel. Unlike the pyin POC it detects multiple
simultaneous notes, so it can transcribe chords. Shares poc_tab.py (beat grid, octave
dedup / confidence cap, fretboard, bar rendering).

Usage (3.11 venv):
    .venv311-poc\\Scripts\\python poc_transcribe_bp.py <track_id> <stem> [--instrument guitar|bass]
        [--seconds 40] [--minlen 130] [--onset 0.6] [--frame 0.4] [--bpm N] [--ampfloor 0.15]
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")  # quiet TF banner

import librosa  # noqa: E402

import poc_tab  # noqa: E402

LIBRARY_DIR = Path(__file__).resolve().parent / "data" / "library"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("track_id")
    ap.add_argument("stem")
    ap.add_argument("--instrument", choices=list(poc_tab.TUNINGS), default="guitar")
    ap.add_argument("--seconds", type=float, default=40.0)
    ap.add_argument("--minlen", type=float, default=127.7, help="min note length (ms)")
    ap.add_argument("--onset", type=float, default=0.5)
    ap.add_argument("--frame", type=float, default=0.3)
    ap.add_argument("--bpm", type=float, default=None, help="tempo prior (fixes octave errors)")
    ap.add_argument("--subdiv", type=int, default=4)
    ap.add_argument("--ampfloor", type=float, default=0.15,
                    help="drop notes below this fraction of the loudest in a slot")
    args = ap.parse_args()

    path = LIBRARY_DIR / args.track_id / f"{args.stem}.flac"
    if not path.exists():
        raise SystemExit(f"no such stem: {path}")

    fmin, fmax = (75.0, 1350.0) if args.instrument == "guitar" else (38.0, 420.0)

    print(f"Loading basic-pitch model + inference on {path.name} ...")
    from basic_pitch.inference import predict
    from basic_pitch import ICASSP_2022_MODEL_PATH

    _m, _midi, note_events = predict(
        str(path), ICASSP_2022_MODEL_PATH,
        onset_threshold=args.onset, frame_threshold=args.frame,
        minimum_note_length=args.minlen, minimum_frequency=fmin, maximum_frequency=fmax)
    # note_events: (start, end, pitch, amplitude, bends)
    notes = [(float(s), float(e), int(p), float(a)) for s, e, p, a, *_ in note_events]
    print(f"  {len(notes)} raw notes")

    import numpy as np
    drums = LIBRARY_DIR / args.track_id / "drums.flac"
    grid_y, sr = librosa.load(str(drums if drums.exists() else path), sr=22050, mono=True)
    grid, tempo, slots_per_bar = poc_tab.beat_grid(
        grid_y, sr, subdiv=args.subdiv, start_bpm=args.bpm)
    max_slots = int(np.searchsorted(grid, args.seconds, side="right"))
    events = poc_tab.build_events(notes, grid, args.instrument, max_slots,
                                  dedup_octaves=True, amp_floor=args.ampfloor)
    print(f"  grid tempo ~{tempo:.0f} bpm | dedup octaves + amp floor {args.ampfloor}")
    print(f"  {poc_tab.value_histogram(events)}\n")

    print(f"--- tab ({args.instrument}, basic-pitch, durations: onset=fret, ==sustain, "
          f"--=silence, first {args.seconds:.0f}s) ---\n")
    print(poc_tab.render_events(events, args.instrument, slots_per_bar, max_slots))


if __name__ == "__main__":
    main()

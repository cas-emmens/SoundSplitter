"""POC #5: two-layer rhythm-guitar transcription = stable chord + picking articulation.

Targets the gap found vs Songsterr on "It Runs Through Me": the hand holds one chord shape
while a thumb/fingers fingerpicking groove plays (user's 4-4-1-3 pattern). So:
  1. CHORD LAYER (slow): recognize ONE chord per bar (aggregate chroma over the bar) so the
     shape stays stable instead of flipping every beat.
  2. ARTICULATION LAYER (fast): detect onsets, and per onset classify bass-strike (thumb) vs
     treble-strike (fingers) vs both, from low- vs high-band energy. Render the held shape split
     into thumb (low strings) / fingers (top 3) accordingly.

    .venv\\Scripts\\python poc_artic.py <track_id> [--stem guitar] [--bpm N] [--bars 6]
                                        [--split-hz 200] [--bass-th 0.55] [--treb-th 0.30]
"""
from __future__ import annotations

import argparse

import librosa
import numpy as np

from app import chords as C
from app import config

SR, HOP = 22050, 512


def _low_pc(y, fmax_note):
    """pyin restricted to the low register -> per-frame pitch class (-1 unvoiced)."""
    f0, voiced, _ = librosa.pyin(y, sr=SR, hop_length=HOP,
                                 fmin=librosa.note_to_hz("C1"),
                                 fmax=librosa.note_to_hz(fmax_note))
    pc = np.full(f0.shape, -1, dtype=int)
    ok = voiced & ~np.isnan(f0)
    pc[ok] = (np.round(librosa.hz_to_midi(f0[ok])).astype(int)) % 12
    return pc


def root_pc_per_frame(track_id, y_guitar):
    """Per-frame root pitch class from the separated BASS stem (the only reliable root
    signal; guitar-low pyin tracks harmonics on chords, not the true bass note). Returns
    -1 where the bass isn't playing (e.g. the intro) -> no root pin there."""
    bass_file = config.LIBRARY_DIR / track_id / "bass.flac"
    if not bass_file.exists():
        return None
    return _low_pc(librosa.load(str(bass_file), sr=SR, mono=True)[0], "C4")


def _window_bass_pc(bass_pc, lo, hi):
    if bass_pc is None:
        return -1
    seg = bass_pc[lo:min(hi, len(bass_pc))]
    seg = seg[seg >= 0]
    return int(np.bincount(seg).argmax()) if len(seg) else -1


def chord_per_window(chroma, beats, key, win_beats=2, bass_pc=None):
    """Recognize one chord per window of `win_beats` beats (default 2 = half bar). The
    bass stem's pitch class pins the root (big bonus to chords rooted there)."""
    templates, labels = C._templates()
    diatonic = C._diatonic_roots(*key)
    out: dict[int, tuple[int, str]] = {}
    for wi, b0 in enumerate(range(0, len(beats) - 1, win_beats)):
        b1 = min(b0 + win_beats, len(beats) - 1)
        seg = chroma[:, beats[b0]:beats[b1]]
        if seg.shape[1] == 0:
            continue
        v = seg.mean(axis=1)
        v /= (np.linalg.norm(v) + 1e-9)
        emit = templates @ v
        broot = _window_bass_pc(bass_pc, beats[b0], beats[b1])
        for ci, (root, _q) in enumerate(labels):
            if root in diatonic:
                emit[ci] += 0.08
            if root == broot:                 # bass-pinned root: strong bonus
                emit[ci] += 0.35
        out[wi] = labels[int(np.argmax(emit))]
    return out


def band_onsets(S_mag, freqs, lo_hz, hi_hz, split_hz):
    """Detect onsets separately in a low band (thumb/bass) and a high band (fingers/treble)
    via per-band spectral flux. Returns (set(bass_frames), set(treble_frames))."""
    low = S_mag[freqs < split_hz, :]
    high = S_mag[(freqs >= split_hz) & (freqs < hi_hz), :]
    env_low = np.maximum(0.0, np.diff(low, axis=1)).sum(axis=0)
    env_high = np.maximum(0.0, np.diff(high, axis=1)).sum(axis=0)
    bass_f = librosa.onset.onset_detect(onset_envelope=env_low, sr=SR, hop_length=HOP)
    treb_f = librosa.onset.onset_detect(onset_envelope=env_high, sr=SR, hop_length=HOP)
    return set(bass_f + 1), set(treb_f + 1)     # +1: diff shifts frame index by one


def split_voicing(voicing):
    """(bass strings, treble strings) as [(string_idx, fret)] — thumb vs fingers."""
    sounded = [(i, f) for i, f in enumerate(voicing) if f is not None]
    treble = sounded[-3:]
    bass = sounded[:-3] if len(sounded) > 3 else sounded[:1]
    return bass, treble


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("track_id")
    ap.add_argument("--stem", default="guitar")
    ap.add_argument("--bpm", type=float, default=None)
    ap.add_argument("--bars", type=int, default=6)
    ap.add_argument("--split-hz", type=float, default=200.0)
    ap.add_argument("--win-beats", type=int, default=2, help="chord window (2 = half bar)")
    args = ap.parse_args()

    src = config.LIBRARY_DIR / args.track_id / f"{args.stem}.flac"
    y, _ = librosa.load(str(src), sr=SR, mono=True)
    y_h = librosa.effects.harmonic(y, margin=3.0)
    chroma = librosa.feature.chroma_cqt(y=y_h, sr=SR, hop_length=HOP)

    drums = config.LIBRARY_DIR / args.track_id / "drums.flac"
    grid_y = librosa.load(str(drums), sr=SR, mono=True)[0] if drums.exists() else y
    tempo, beats = librosa.beat.beat_track(y=grid_y, sr=SR, hop_length=HOP,
                                           start_bpm=args.bpm or 120.0, units="frames")
    tempo = float(np.atleast_1d(tempo)[0])
    beat_times = librosa.frames_to_time(beats, sr=SR, hop_length=HOP)
    key = C.detect_key(chroma.mean(axis=1))
    root_pc = root_pc_per_frame(args.track_id, y_h)
    win_chords = chord_per_window(chroma, beats, key, args.win_beats, root_pc)

    # two-band onset detection from the raw stem (thumb/bass vs fingers/treble)
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=HOP))
    freqs = librosa.fft_frequencies(sr=SR, n_fft=2048)
    bass_f, treb_f = band_onsets(S, freqs, 60.0, 2000.0, args.split_hz)

    # 16th-note grid from beats
    subdiv = 4
    grid = []
    for i in range(len(beat_times) - 1):
        grid.extend(np.linspace(beat_times[i], beat_times[i + 1], subdiv, endpoint=False))
    grid = np.array(grid)
    slots_per_bar = subdiv * 4
    n_slots = min(len(grid), args.bars * slots_per_bar)

    def chord_at_slot(slot):
        beat_idx = slot // subdiv
        return win_chords.get(beat_idx // args.win_beats)

    def frames_to_slots(frames):
        out = set()
        for f in frames:
            t = librosa.frames_to_time(f, sr=SR, hop_length=HOP)
            s = int(np.argmin(np.abs(grid - t)))
            if s < n_slots:
                out.add(s)
        return out

    bass_slots, treble_slots = frames_to_slots(bass_f), frames_to_slots(treb_f)

    cell = [["" for _ in range(n_slots)] for _ in range(6)]
    counts = {"bass": 0, "treble": 0, "both": 0}
    for slot in sorted(bass_slots | treble_slots):
        ch = chord_at_slot(slot)
        if ch is None:
            continue
        bass, treble = split_voicing(C.voicing(*ch))
        in_b, in_t = slot in bass_slots, slot in treble_slots
        kind = "both" if in_b and in_t else ("bass" if in_b else "treble")
        counts[kind] += 1
        strings = {"bass": bass, "treble": treble, "both": bass + treble}[kind]
        for idx, fret in strings:
            cell[idx][slot] = str(fret)

    print(f"tempo ~{tempo:.0f} bpm | key {C.PC_NAMES[key[0]]} {key[1]} | "
          f"chord window {args.win_beats} beats")
    print(f"articulation mix: {counts}\n")

    n_win = (args.bars * 4 + args.win_beats - 1) // args.win_beats
    print(f"=== chords (per {args.win_beats}-beat window) ===")
    print("  " + "  ".join(f"w{w+1}:{C.chord_name(*win_chords[w])}"
                           for w in range(n_win) if w in win_chords))

    # standard tab orientation: high e on top, low E on bottom (cell idx 0 = low E)
    labels6 = ["E", "A", "D", "G", "B", "e"]
    print("\n=== tab (onset = strike; thumb=low strings, fingers=top 3) ===")
    for s in reversed(range(6)):
        row = [labels6[s], "|"]
        for col in range(n_slots):
            if col % slots_per_bar == 0 and col != 0:
                row.append("|")
            tok = cell[s][col]
            row.append(tok.rjust(2, "-") if tok else "--")
        row.append("|")
        print("".join(row))


if __name__ == "__main__":
    main()

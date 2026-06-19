"""POC #4: rhythm-guitar transcription via CHORD RECOGNITION (not note detection).

Multi-angle approach (see memory: idea-tab-transcription): instead of detecting every note
(noisy/incomplete), classify each beat into a chord from a vocabulary, then fill in the full
playable voicing from a local chord-shape dictionary. Works on the FULL guitar stem - no
lead/rhythm split needed. Judge the progression by ear/eye before wiring into the app.

    .venv\\Scripts\\python poc_chords.py <track_id> [--stem guitar] [--bpm N] [--bars 16]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import librosa
import numpy as np

LIBRARY_DIR = Path(__file__).resolve().parent / "data" / "library"
PC_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# pitch-class intervals per chord quality
QUALITIES = {
    "":     [0, 4, 7],         # major
    "m":    [0, 3, 7],
    "7":    [0, 4, 7, 10],
    "m7":   [0, 3, 7, 10],
    "maj7": [0, 4, 7, 11],
}

# Open-position voicings (low E -> high e); None = muted string.
OPEN_SHAPES: dict[str, list[int | None]] = {
    "C":   [None, 3, 2, 0, 1, 0],
    "C7":  [None, 3, 2, 3, 1, 0],
    "Cmaj7": [None, 3, 2, 0, 0, 0],
    "D":   [None, None, 0, 2, 3, 2],
    "Dm":  [None, None, 0, 2, 3, 1],
    "D7":  [None, None, 0, 2, 1, 2],
    "Dm7": [None, None, 0, 2, 1, 1],
    "E":   [0, 2, 2, 1, 0, 0],
    "Em":  [0, 2, 2, 0, 0, 0],
    "E7":  [0, 2, 0, 1, 0, 0],
    "Em7": [0, 2, 0, 0, 0, 0],
    "G":   [3, 2, 0, 0, 0, 3],
    "G7":  [3, 2, 0, 0, 0, 1],
    "A":   [None, 0, 2, 2, 2, 0],
    "Am":  [None, 0, 2, 2, 1, 0],
    "A7":  [None, 0, 2, 0, 2, 0],
    "Am7": [None, 0, 2, 0, 1, 0],
    "Amaj7": [None, 0, 2, 1, 2, 0],
}
# movable barre shapes (offsets from the root fret), root on string 6 (E-shape) or 5 (A-shape)
E_SHAPE = {"": [0, 2, 2, 1, 0, 0], "m": [0, 2, 2, 0, 0, 0], "7": [0, 2, 0, 1, 0, 0],
           "m7": [0, 2, 0, 0, 0, 0], "maj7": [0, 2, 1, 1, 0, 0]}
A_SHAPE = {"": [None, 0, 2, 2, 2, 0], "m": [None, 0, 2, 2, 1, 0], "7": [None, 0, 2, 0, 2, 0],
           "m7": [None, 0, 2, 0, 1, 0], "maj7": [None, 0, 2, 1, 1, 0]}
OPEN_E_PC, OPEN_A_PC = 4, 9  # low E string = E(4 -> pc4? E=4), A string pc=9


def chord_name(root: int, qual: str) -> str:
    return PC_NAMES[root] + qual


def voicing(root: int, qual: str) -> list[int | None]:
    """Pick a playable shape: prefer a known open shape, else the lower of the two barres."""
    name = chord_name(root, qual)
    if name in OPEN_SHAPES:
        return OPEN_SHAPES[name]
    e_fret = (root - OPEN_E_PC) % 12          # root on low-E string
    a_fret = (root - OPEN_A_PC) % 12          # root on A string
    e_voicing = [None if f is None else f + e_fret for f in E_SHAPE[qual]]
    a_voicing = [None if f is None else f + a_fret for f in A_SHAPE[qual]]
    # prefer the shape sitting lower on the neck
    e_max = max(f for f in e_voicing if f is not None)
    a_max = max(f for f in a_voicing if f is not None)
    return e_voicing if e_max <= a_max else a_voicing


def build_templates() -> tuple[np.ndarray, list[tuple[int, str]]]:
    templates, labels = [], []
    for root in range(12):
        for qual, ivs in QUALITIES.items():
            vec = np.zeros(12)
            for iv in ivs:
                vec[(root + iv) % 12] = 1.0
            vec /= np.linalg.norm(vec)
            templates.append(vec)
            labels.append((root, qual))
    return np.array(templates), labels


def viterbi(emit: np.ndarray, self_bonus: float = 0.15) -> list[int]:
    """Cheap Viterbi: reward staying on the same chord to suppress jitter."""
    T, S = emit.shape
    score = emit.copy()
    back = np.zeros((T, S), dtype=int)
    for t in range(1, T):
        for s in range(S):
            stay = score[t - 1, s] + self_bonus
            prev = score[t - 1]
            best_prev = int(np.argmax(prev))
            if stay >= prev[best_prev]:
                back[t, s], add = s, stay
            else:
                back[t, s], add = best_prev, prev[best_prev]
            score[t, s] += add
    path = [int(np.argmax(score[-1]))]
    for t in range(T - 1, 0, -1):
        path.append(back[t, path[-1]])
    return path[::-1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("track_id")
    ap.add_argument("--stem", default="guitar")
    ap.add_argument("--bpm", type=float, default=None)
    ap.add_argument("--bars", type=int, default=16)
    args = ap.parse_args()

    src = LIBRARY_DIR / args.track_id / f"{args.stem}.flac"
    if not src.exists():
        raise SystemExit(f"no such stem: {src}")

    sr, hop = 22050, 512
    y, _ = librosa.load(str(src), sr=sr, mono=True)
    y_h = librosa.effects.harmonic(y, margin=3.0)          # de-emphasize transients
    chroma = librosa.feature.chroma_cqt(y=y_h, sr=sr, hop_length=hop)

    drums = LIBRARY_DIR / args.track_id / "drums.flac"
    grid_y = librosa.load(str(drums), sr=sr, mono=True)[0] if drums.exists() else y
    tempo, beats = librosa.beat.beat_track(y=grid_y, sr=sr, hop_length=hop,
                                           start_bpm=args.bpm or 120.0, units="frames")
    tempo = float(np.atleast_1d(tempo)[0])
    beat_chroma = librosa.util.sync(chroma, beats, aggregate=np.median, axis=1)
    beat_chroma /= (np.linalg.norm(beat_chroma, axis=0, keepdims=True) + 1e-9)

    templates, labels = build_templates()
    emit = templates @ beat_chroma                          # [n_chords, n_beats]
    energy = np.linalg.norm(librosa.util.sync(chroma, beats, aggregate=np.mean, axis=1), axis=0)
    path = viterbi(emit.T)
    chords = [labels[i] for i in path]

    print(f"tempo ~{tempo:.0f} bpm | {len(beats)} beats | guitar stem (no split)\n")

    # bar-aligned progression (assume 4/4) + collapse repeats within a bar
    print("=== chord progression (4 beats/bar) ===")
    for bar in range((min(len(chords), args.bars * 4) + 3) // 4):
        cells = []
        for b in range(bar * 4, min(bar * 4 + 4, len(chords))):
            root, qual = chords[b]
            cells.append("N" if energy[b] < 0.02 else chord_name(root, qual))
        # show repeats as '.'
        shown = [cells[0]] + [("." if cells[i] == cells[i - 1] else cells[i])
                              for i in range(1, len(cells))]
        print(f"|{bar + 1:>3} | " + " ".join(f"{c:<6}" for c in shown) + "|")

    # tab of the distinct chord shapes used (a legend)
    print("\n=== shapes used (low E -> high e) ===")
    seen = []
    for root, qual in chords[:args.bars * 4]:
        if (root, qual) not in seen:
            seen.append((root, qual))
    labels6 = ["e", "B", "G", "D", "A", "E"]
    for root, qual in seen[:12]:
        v = voicing(root, qual)
        cells = ["x" if f is None else str(f) for f in v][::-1]  # high e first
        line = "  ".join(f"{labels6[i]}:{cells[i]:>2}" for i in range(6))
        print(f"{chord_name(root, qual):<6} {line}")


if __name__ == "__main__":
    main()

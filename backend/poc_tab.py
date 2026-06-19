"""Shared POC tab helpers: beat-grid quantization, octave dedup / confidence cap,
fretboard mapping, and bar-aware ASCII rendering.

Imported by both transcription POCs (poc_transcribe.py on the 3.13 venv, and
poc_transcribe_bp.py on the 3.11 venv) — so it must stay pure numpy + librosa, with no
app/spotify imports. A "note" is a tuple (start_s, midi, amp); amp is 1.0 when the
detector gives no confidence (pyin).
"""
from __future__ import annotations

import librosa
import numpy as np

TUNINGS = {
    "guitar": [40, 45, 50, 55, 59, 64],   # E A D G B e
    "bass":   [28, 33, 38, 43],           # E A D G
}
STRING_LABELS = {
    "guitar": ["E", "A", "D", "G", "B", "e"],
    "bass":   ["E", "A", "D", "G"],
}
MAX_FRET = 19

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def midi_name(m: int) -> str:
    return f"{NOTE_NAMES[m % 12]}{m // 12 - 1}"


def fit_range(m: int, tuning: list[int]) -> int:
    lo, hi = min(tuning), max(tuning) + MAX_FRET
    while m < lo:
        m += 12
    while m > hi:
        m -= 12
    return m


# --- #1: beat-grid quantization ---

def beat_grid(y: np.ndarray, sr: int, subdiv: int = 4, beats_per_bar: int = 4,
              start_bpm: float | None = None) -> tuple[np.ndarray, float, int]:
    """Return (grid_times, tempo, slots_per_bar). The grid subdivides each beat into
    `subdiv` slots (subdiv=4 -> 16th notes in 4/4)."""
    tempo, beats = librosa.beat.beat_track(
        y=y, sr=sr, start_bpm=start_bpm or 120.0, units="time")
    tempo = float(np.atleast_1d(tempo)[0])
    if len(beats) < 2:
        period = 60.0 / (tempo or 120.0)
        beats = np.arange(0.0, len(y) / sr, period)

    grid: list[float] = []
    for i in range(len(beats) - 1):
        grid.extend(np.linspace(beats[i], beats[i + 1], subdiv, endpoint=False))
    period = float(np.median(np.diff(beats)))
    step = period / subdiv
    for j in range(subdiv):                       # subdivisions of the final beat
        grid.append(beats[-1] + j * step)
    return np.array(sorted(grid)), tempo, subdiv * beats_per_bar


def place_chord(pitches: list[int], tuning: list[int],
                prev_fret: float | None) -> list[tuple[int, int]]:
    """Assign each pitch to a distinct string (brute force over small chords),
    minimizing fret span + distance from the previous column's fret centroid."""
    pitches = sorted(set(fit_range(p, tuning) for p in pitches))
    best: tuple[float, list[tuple[int, int]]] | None = None

    def options(p: int) -> list[tuple[int, int]]:
        return [(s, p - o) for s, o in enumerate(tuning) if 0 <= p - o <= MAX_FRET]

    def search(idx: int, used: set[int], chosen: list[tuple[int, int]]) -> None:
        nonlocal best
        if idx == len(pitches):
            frets = [f for _, f in chosen]
            if not frets:
                return
            span = max(frets) - min(frets)
            move = 0.0 if prev_fret is None else abs(sum(frets) / len(frets) - prev_fret)
            score = span + 0.3 * move + 0.05 * sum(frets)
            if best is None or score < best[0]:
                best = (score, list(chosen))
            return
        opts = options(pitches[idx])
        if not opts:                              # unplayable note: skip it
            search(idx + 1, used, chosen)
            return
        for s, fret in opts:
            if s in used:
                continue
            chosen.append((s, fret))
            search(idx + 1, used | {s}, chosen)
            chosen.pop()

    search(0, set(), [])
    return best[1] if best else []


# --- #2: octave dedup + confidence cap ---

def _clean_chord(pairs: list[tuple[int, float]], n_strings: int,
                 dedup_octaves: bool, amp_floor: float) -> list[int]:
    """pairs are (midi, amp) folded into one grid slot -> cleaned pitch list."""
    if not pairs:
        return []
    top_amp = max(a for _m, a in pairs)
    kept = [(m, a) for m, a in pairs if a >= amp_floor * top_amp]
    pitches = {m for m, _a in kept}
    if dedup_octaves:
        # basic-pitch tends to add an octave-up ghost; drop p when p-12 is present.
        pitches = {p for p in pitches if (p - 12) not in pitches}
    amp_of: dict[int, float] = {}
    for m, a in kept:
        amp_of[m] = max(amp_of.get(m, 0.0), a)
    ordered = sorted(pitches, key=lambda p: amp_of.get(p, 0.0), reverse=True)
    return sorted(ordered[:n_strings])            # cap to playable string count


# --- duration quantization: notes -> notation-ready event list ---

# slot counts (in 16ths, subdiv=4) -> note-value label
_VALUE_NAMES = {1: "16", 2: "8", 3: "8.", 4: "4", 6: "4.", 8: "2", 12: "2.", 16: "1"}


def value_name(slots: int) -> str:
    """Nearest representable note value for a slot count (POC: approximate odd ones)."""
    if slots in _VALUE_NAMES:
        return _VALUE_NAMES[slots]
    best = min(_VALUE_NAMES, key=lambda k: abs(k - slots))
    return _VALUE_NAMES[best] + ("~" if best != slots else "")  # ~ = tie/approx


def build_events(notes: list[tuple[float, float, int, float]], grid: np.ndarray,
                 instrument: str, max_slots: int, dedup_octaves: bool,
                 amp_floor: float) -> list[dict]:
    """Single-voice notation events. Each is a dict:
      {kind:'note', slot, dur, frets:[(string,fret)], midis:[..]}  or
      {kind:'rest', slot, dur}
    `dur` is in grid slots (16ths). Rests fill the gap when a column stops sounding
    before the next onset."""
    tuning = TUNINGS[instrument]
    n_strings = len(tuning)

    def nearest(t: float) -> int:
        return int(np.argmin(np.abs(grid - t)))

    # fold notes into onset slots, tracking each note's quantized end slot
    by_slot: dict[int, list[tuple[int, int, float]]] = {}  # slot -> (end_slot, midi, amp)
    for start, end, midi, amp in notes:
        s = nearest(start)
        e = max(nearest(end), s + 1)
        by_slot.setdefault(s, []).append((e, int(midi), amp))

    onsets = sorted(s for s in by_slot if s < max_slots)
    events: list[dict] = []
    prev_fret: float | None = None
    for i, s in enumerate(onsets):
        nxt = onsets[i + 1] if i + 1 < len(onsets) else max_slots
        col = by_slot[s]
        pitches = _clean_chord([(m, a) for _e, m, a in col], n_strings,
                               dedup_octaves, amp_floor)
        placed = place_chord(pitches, tuning, prev_fret) if pitches else []
        if not placed:
            continue
        prev_fret = sum(f for _st, f in placed) / len(placed)
        gap = nxt - s
        end_slot = max(e for e, _m, _a in col)
        sounded = max(1, min(end_slot - s, gap))
        events.append({"kind": "note", "slot": s, "dur": sounded,
                       "frets": placed, "midis": pitches})
        if gap - sounded > 0:
            events.append({"kind": "rest", "slot": s + sounded, "dur": gap - sounded})
    return events


def value_histogram(events: list[dict]) -> str:
    from collections import Counter
    notes = Counter(value_name(e["dur"]) for e in events if e["kind"] == "note")
    rests = sum(1 for e in events if e["kind"] == "rest")
    order = ["1", "2.", "2", "4.", "4", "8.", "8", "16"]
    parts = [f"{v}:{notes[v]}" for v in order if notes.get(v)]
    extra = [f"{k}:{c}" for k, c in notes.items() if k not in order]
    return f"note values [{' '.join(parts + extra)}]  rests:{rests}"


def render_events(events: list[dict], instrument: str, slots_per_bar: int,
                  max_slots: int, bars_per_line: int = 3) -> str:
    """ASCII tab from events. Onset = fret; sustained slots = '=' on ringing strings;
    silence = '-'. So note durations and rests are both visible."""
    labels = STRING_LABELS[instrument]
    n_strings = len(TUNINGS[instrument])
    # cell[string][slot]: fret token, "=" sustain, or "" empty
    cell = [["" for _ in range(max_slots)] for _ in range(n_strings)]
    for e in events:
        if e["kind"] != "note":
            continue
        s = e["slot"]
        for st, fret in e["frets"]:
            if s < max_slots:
                cell[st][s] = str(fret)
            for k in range(1, e["dur"]):
                if s + k < max_slots:
                    cell[st][s + k] = "="

    out: list[str] = []
    cols_per_line = slots_per_bar * bars_per_line
    for line_start in range(0, max_slots, cols_per_line):
        line_slots = range(line_start, min(line_start + cols_per_line, max_slots))
        for st in reversed(range(n_strings)):
            row = [labels[st], "|"]
            for col in line_slots:
                if col % slots_per_bar == 0 and col != line_start:
                    row.append("|")
                tok = cell[st][col]
                row.append(tok.rjust(2, "-") if tok and tok != "=" else
                           ("==" if tok == "=" else "--"))
            row.append("|")
            out.append("".join(row))
        out.append("")
    return "\n".join(out)

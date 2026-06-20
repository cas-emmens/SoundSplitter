"""Align a tab to its recording using the separated guitar stem.

The tab is notated at a fixed tempo, but the performance accelerates / rubatos, so the notated
timeline drifts from the audio (out of sync by the 10th bar). This module aligns the tab's note
sequence to note events detected in the guitar stem (via basic-pitch, which is polyphonic and
handles let-ring overlap that monophonic pitch trackers can't), producing:

* a **warp** — a real audio time for every beat — so the cursor can follow the recording, and
* a **cross-check** — audio note-groups that matched no tab beat (candidate *missing* notes the
  OCR dropped, e.g. faint thumb-bass notes) and tab beats with no audio support.

The alignment is a DTW over pitch sequences (not absolute time): basic-pitch note identities vs
the tab's expected pitches (string+fret+tuning -> MIDI). Confidently-matched beats anchor a
piecewise-linear notated->audio warp; everything else interpolates between anchors.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

# Standard guitar tuning: alphaTab string number -> MIDI of the open string (1 = high E).
STANDARD_TUNING = {1: 64, 2: 59, 3: 55, 4: 50, 5: 45, 6: 40}


@dataclass
class Beat:
    index: int            # position among ALL beats (incl. rests), matching alphaTab's order
    bar: int              # 0-based bar number
    pitches: list[int]    # expected MIDI pitches; empty for a rest
    notated_time: float   # seconds from the start at the notated tempo
    is_rest: bool = False


@dataclass
class NoteGroup:
    time: float           # onset time in the audio (seconds)
    pitches: set[int]     # MIDI pitches attacked together


@dataclass
class AlignResult:
    beat_times: list[float]                 # audio time per beat (index-aligned to parse_beats)
    confidence: list[float]                 # 0..1 per beat (1 = exact pitch match anchored it)
    anchors: list[tuple[float, float]]      # (notated_time, audio_time) confident matches
    missing: list[NoteGroup] = field(default_factory=list)  # audio attacks with no tab beat


# --------------------------------------------------------------------------- tab parsing

def _tuning_from_header(alphatex: str) -> dict[int, int]:
    """Read a `\\tuning E4 B3 ...` header if present, else standard tuning."""
    m = re.search(r"\\tuning\s+([A-G][#b]?\d(?:\s+[A-G][#b]?\d)*)", alphatex)
    if not m:
        return STANDARD_TUNING
    names = m.group(1).split()
    step = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    out = {}
    for i, tok in enumerate(names, start=1):  # listed high string -> low, i.e. string 1..6
        mm = re.match(r"([A-G])([#b]?)(\d)", tok)
        if not mm:
            return STANDARD_TUNING
        semis = step[mm.group(1)] + (1 if mm.group(2) == "#" else -1 if mm.group(2) == "b" else 0)
        out[i] = (int(mm.group(3)) + 1) * 12 + semis
    return out


def parse_beats(alphatex: str) -> list[Beat]:
    """Parse alphaTex into an ordered beat list with notated times (incl. rests).

    Handles `\\tempo`, `\\ts`, `:N` durations, chords `(f.s f.s)`, single notes `f.s`, rests `r`,
    and tolerates note-effect suffixes like `{h}` / ties `-.s`. Bar number increments at `|`.
    """
    tuning = _tuning_from_header(alphatex)
    lines = alphatex.splitlines()
    start = next((i + 1 for i, l in enumerate(lines) if l.strip() == "."), 0)
    bpm_m = re.search(r"\\tempo\s+(\d+)", alphatex)
    bpm = int(bpm_m.group(1)) if bpm_m else 120
    sec_per_whole = (60.0 / bpm) * 4.0

    toks = " ".join(lines[start:]).replace("|", " | ").split()

    def midi(tok: str) -> int | None:
        m = re.match(r"^[x\-]?\.?(\d+)\.(\d+)", tok) or re.match(r"^(\d+)\.(\d+)", tok)
        if not m:
            return None
        fret, string = int(m.group(1)), int(m.group(2))
        return tuning[string] + fret if string in tuning else None

    beats: list[Beat] = []
    skip, i, dur, t, bar, idx = 0, 0, 4, 0.0, 0, 0
    while i < len(toks):
        tok = toks[i]; i += 1
        if skip:
            skip -= 1; continue
        if tok == "|":
            bar += 1; continue
        if tok.startswith("\\"):
            skip = 2 if tok == "\\ts" else 1 if tok in ("\\tempo", "\\tuning") else 0
            continue
        if tok.startswith(":"):
            try:
                dur = int(tok[1:])
            except ValueError:
                pass
            continue
        secs = sec_per_whole / dur
        if tok == "r":
            beats.append(Beat(idx, bar, [], t, is_rest=True)); idx += 1; t += secs; continue
        pitches: list[int] = []
        if tok.startswith("("):
            inner = tok[1:]; done = inner.endswith(")")
            if (mm := midi(inner.rstrip(")"))) is not None:
                pitches.append(mm)
            while not done and i < len(toks):
                u = toks[i]; i += 1; done = u.endswith(")")
                if (mm := midi(u.rstrip(")"))) is not None:
                    pitches.append(mm)
        elif (mm := midi(tok)) is not None:
            pitches.append(mm)
        else:
            continue  # unknown token, not a beat
        beats.append(Beat(idx, bar, pitches, t, is_rest=not pitches)); idx += 1; t += secs
    return beats


# --------------------------------------------------------------------------- audio note events

def extract_note_events(stem_path: str, *, duration: float | None = None,
                        cache: bool = True) -> list[tuple[float, float, int, float]]:
    """basic-pitch note events `(start_s, end_s, midi, amplitude)`, cached next to the stem.

    basic-pitch is polyphonic and slow, so the full-song result is cached as `<stem>.notes.json`.
    `duration` (for dev) limits analysis to the first N seconds and bypasses the cache.
    """
    cache_path = stem_path + ".notes.json"
    if cache and duration is None and os.path.exists(cache_path):
        with open(cache_path) as f:
            return [tuple(r) for r in json.load(f)]

    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    import librosa, soundfile as sf, tempfile
    from basic_pitch.inference import predict
    from basic_pitch import ICASSP_2022_MODEL_PATH

    path = stem_path
    if duration is not None:
        y, sr = librosa.load(stem_path, sr=22050, duration=duration)
        path = os.path.join(tempfile.gettempdir(), "tabsync_clip.wav")
        sf.write(path, y, sr)

    _, _, notes = predict(path, ICASSP_2022_MODEL_PATH)
    events = sorted([(float(s), float(e), int(p), float(a)) for s, e, p, a, *_ in notes])
    if cache and duration is None:
        with open(cache_path, "w") as f:
            json.dump(events, f)
    return events


def group_onsets(events, window: float = 0.07) -> list[NoteGroup]:
    """Cluster note events whose onsets fall within `window` into one attack (chord/beat)."""
    groups: list[NoteGroup] = []
    for s, _e, p, _a in sorted(events):
        if groups and s - groups[-1].time <= window:
            groups[-1].pitches.add(p)
        else:
            groups.append(NoteGroup(s, {p}))
    return groups


# --------------------------------------------------------------------------- alignment

def _cost(audio: set[int], tab: list[int]) -> float:
    """Pitch-set distance: 0 exact overlap, .4 octave, .7 pitch-class, 1 none."""
    if not tab:
        return 0.6  # rest beat: weak match to anything (handled outside DTW normally)
    if any(a == t for a in audio for t in tab):
        return 0.0
    if any((a - t) % 12 == 0 for a in audio for t in tab):
        return 0.4
    if any(a % 12 == t % 12 for a in audio for t in tab):
        return 0.7
    return 1.0


def align(beats: list[Beat], groups: list[NoteGroup]) -> AlignResult:
    """DTW-align tab note-beats to audio note-groups; build a notated->audio warp.

    Rests are excluded from the DTW (they carry no pitch) but get an interpolated audio time so
    the returned `beat_times` is index-aligned with `beats`.
    """
    note_beats = [b for b in beats if not b.is_rest]
    A, B = groups, note_beats
    if not A or not B:
        return AlignResult([b.notated_time for b in beats], [0.0] * len(beats), [])

    # DTW cost matrix + backtrack (sequences are small enough for the full DP).
    import numpy as np
    n, m = len(A), len(B)
    D = np.full((n + 1, m + 1), 1e9)
    D[0, 0] = 0.0
    for i in range(1, n + 1):
        ai = A[i - 1].pitches
        for j in range(1, m + 1):
            D[i, j] = _cost(ai, B[j - 1].pitches) + min(D[i - 1, j - 1], D[i - 1, j], D[i, j - 1])

    i, j = n, m
    pairs: list[tuple[int, int]] = []
    while i > 0 and j > 0:
        pairs.append((i - 1, j - 1))
        diag, up, left = D[i - 1, j - 1], D[i - 1, j], D[i, j - 1]
        if diag <= up and diag <= left:
            i, j = i - 1, j - 1
        elif up <= left:
            i -= 1
        else:
            j -= 1
    pairs.reverse()

    # Confident matches (cost 0) anchor the warp: tab beat's notated_time -> audio onset time.
    anchors: list[tuple[float, float]] = []
    conf_by_beat: dict[int, float] = {}
    matched_audio: set[int] = set()
    for ai, bj in pairs:
        c = _cost(A[ai].pitches, B[bj].pitches)
        if c == 0.0:
            anchors.append((B[bj].notated_time, A[ai].time))
            matched_audio.add(ai)
        conf_by_beat[B[bj].index] = max(conf_by_beat.get(B[bj].index, 0.0), 1.0 - c)

    # De-duplicate / enforce monotonic anchors (notated and audio both increasing).
    anchors.sort()
    mono: list[tuple[float, float]] = []
    for nt, at in anchors:
        if not mono or (nt > mono[-1][0] and at > mono[-1][1]):
            mono.append((nt, at))
    anchors = mono

    beat_times = [_warp(b.notated_time, anchors) for b in beats]
    confidence = [conf_by_beat.get(b.index, 0.0) for b in beats]

    # Cross-check: audio groups never matched to a beat (cost-0) = candidate missing tab notes.
    missing = [A[ai] for ai in range(len(A)) if ai not in matched_audio]
    return AlignResult(beat_times, confidence, anchors, missing)


def compute_timing(stem_path: str, alphatex: str) -> dict:
    """End-to-end: align a tab's alphaTex to its guitar stem and return a storable warp.

    Returns ``{"version", "anchors": [[notated_s, audio_s], ...], "missing": [...]}``. ``anchors``
    are the confident notated<->audio matches the frontend inverse-warps to drive the cursor;
    ``missing`` is the Phase-2 cross-check (audio attacks with no tab beat).
    """
    beats = parse_beats(alphatex)
    events = extract_note_events(stem_path)  # full song, cached next to the stem
    groups = group_onsets(events)
    res = align(beats, groups)

    # Per-bar audio start time: warp the first beat of each bar. The tabs page renders bars in
    # this same order, so the frontend maps bar index -> real audio time directly and glides the
    # cursor across each bar by real elapsed time (instead of the equal-bar guess that drifted).
    bar_start_notated: dict[int, float] = {}
    for b in beats:
        bar_start_notated.setdefault(b.bar, b.notated_time)
    n_bars = (max(bar_start_notated) + 1) if bar_start_notated else 0
    bar_times = [round(_warp(bar_start_notated.get(i, 0.0), res.anchors), 4) for i in range(n_bars)]

    return {
        "version": 1,
        "anchors": [[round(n, 4), round(a, 4)] for n, a in res.anchors],
        "bar_times": bar_times,
        "missing": [{"t": round(g.time, 4), "pitches": sorted(g.pitches)} for g in res.missing],
    }


def _warp(notated: float, anchors: list[tuple[float, float]]) -> float:
    """Piecewise-linear map notated_time -> audio_time using the anchor points."""
    if not anchors:
        return notated
    if notated <= anchors[0][0]:
        return anchors[0][1]
    if notated >= anchors[-1][0]:
        return anchors[-1][1]
    for k in range(1, len(anchors)):
        n0, a0 = anchors[k - 1]
        n1, a1 = anchors[k]
        if notated <= n1:
            f = (notated - n0) / (n1 - n0) if n1 > n0 else 0.0
            return a0 + f * (a1 - a0)
    return anchors[-1][1]

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
    part: int = 0         # which source tab this beat came from (master alignment); 0 = focus
    canon: float = 0.0    # canonical musical position = bar + fraction-within-bar (drift-robust)


@dataclass
class NoteGroup:
    time: float           # onset time in the audio (seconds)
    pitches: set[int]     # MIDI pitches attacked together
    amp: float = 0.0      # peak basic-pitch amplitude in the group (0..1), for artifact filtering


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

def _isolate_pan(stem_path: str, side: str):
    """Azimuth-unmask one pan side of a stereo stem into a mono signal (+ sample rate).

    Estimates each STFT bin's pan from the L/R magnitude balance and keeps the bins panned to
    ``side`` ('left'/'right'), so a part panned that way is isolated from one panned the other.
    Mono files are returned unchanged.
    """
    import librosa
    import numpy as np

    y, sr = librosa.load(stem_path, sr=22050, mono=False)
    if y.ndim != 2:
        return y, sr
    left, right = y
    ls, rs = librosa.stft(left), librosa.stft(right)
    la, ra = np.abs(ls), np.abs(rs)
    pan = (ra - la) / (ra + la + 1e-9)  # -1 hard-left .. +1 hard-right
    gain = np.clip(-pan, 0, 1) if side == "left" else np.clip(pan, 0, 1)
    return librosa.istft(((ls + rs) / 2) * gain), sr


def extract_note_events(stem_path: str, *, side: str | None = None, duration: float | None = None,
                        cache: bool = True) -> list[tuple[float, float, int, float]]:
    """basic-pitch note events `(start_s, end_s, midi, amplitude)`, cached next to the stem.

    basic-pitch is polyphonic and slow, so each result is cached (`<stem>.notes[.side].json`).
    ``side`` ('left'/'right') runs basic-pitch on the azimuth-isolated channel so a panned part
    aligns against just its own audio. ``duration`` (dev) limits analysis and bypasses the cache.
    """
    suffix = f".notes.{side}.json" if side else ".notes.json"
    cache_path = stem_path + suffix
    if cache and duration is None and os.path.exists(cache_path):
        with open(cache_path) as f:
            return [tuple(r) for r in json.load(f)]

    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    import librosa, soundfile as sf, tempfile
    from basic_pitch.inference import predict
    from basic_pitch import ICASSP_2022_MODEL_PATH

    if side:
        sig, sr = _isolate_pan(stem_path, side)
    else:
        sig, sr = librosa.load(stem_path, sr=22050, duration=duration)
    path = os.path.join(tempfile.gettempdir(), f"tabsync_{side or 'mono'}.wav")
    sf.write(path, sig, sr)

    _, _, notes = predict(path, ICASSP_2022_MODEL_PATH)
    events = sorted([(float(s), float(e), int(p), float(a)) for s, e, p, a, *_ in notes])
    if cache and duration is None:
        with open(cache_path, "w") as f:
            json.dump(events, f)
    return events


def group_onsets(events, window: float = 0.07) -> list[NoteGroup]:
    """Cluster note events whose onsets fall within `window` into one attack (chord/beat)."""
    groups: list[NoteGroup] = []
    for s, _e, p, a in sorted(events):
        if groups and s - groups[-1].time <= window:
            groups[-1].pitches.add(p)
            groups[-1].amp = max(groups[-1].amp, a)
        else:
            groups.append(NoteGroup(s, {p}, a))
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


def _dtw_pairs(seq_a: list[set | list], seq_b: list[list[int]]) -> list[tuple[int, int]]:
    """DTW match audio groups ``seq_a`` to tab beats ``seq_b`` by pitch cost; return path pairs."""
    import numpy as np

    n, m = len(seq_a), len(seq_b)
    D = np.full((n + 1, m + 1), 1e15)
    D[0, 0] = 0.0
    for i in range(1, n + 1):
        ai = seq_a[i - 1]
        prev, cur = D[i - 1], D[i]
        for j in range(1, m + 1):
            cur[j] = _cost(ai, seq_b[j - 1]) + min(prev[j - 1], prev[j], cur[j - 1])
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
    return pairs


def _monotonic(anchors: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Sort and keep only strictly-increasing (notated, audio) anchors."""
    out: list[tuple[float, float]] = []
    for nt, at in sorted(anchors):
        if not out or (nt > out[-1][0] and at > out[-1][1]):
            out.append((nt, at))
    return out


def align(beats: list[Beat], groups: list[NoteGroup]) -> AlignResult:
    """DTW-align tab note-beats to audio note-groups; build a notated->audio warp.

    Rests are excluded from the DTW (they carry no pitch) but get an interpolated audio time so
    the returned ``beat_times`` is index-aligned with ``beats``.
    """
    note_beats = [b for b in beats if not b.is_rest]
    if not groups or not note_beats:
        return AlignResult([b.notated_time for b in beats], [0.0] * len(beats), [])
    pairs = _dtw_pairs([g.pitches for g in groups], [b.pitches for b in note_beats])

    anchors, conf_by_beat, matched_audio = [], {}, set()
    for ai, bj in pairs:
        b = note_beats[bj]
        c = _cost(groups[ai].pitches, b.pitches)
        if c == 0.0:
            anchors.append((b.notated_time, groups[ai].time))
            matched_audio.add(ai)
        conf_by_beat[b.index] = max(conf_by_beat.get(b.index, 0.0), 1.0 - c)
    anchors = _monotonic(anchors)

    beat_times = [_warp(b.notated_time, anchors) for b in beats]
    confidence = [conf_by_beat.get(b.index, 0.0) for b in beats]
    missing = [groups[ai] for ai in range(len(groups)) if ai not in matched_audio]
    return AlignResult(beat_times, confidence, anchors, missing)


def build_master(alphatexts: list[str]) -> list[Beat]:
    """Union of every part's note-beats, each TAGGED with its source part and canonical position.

    A single guitar stem often carries several parts at once (acoustic arpeggio + electric backing
    + solo). Aligning one part alone mis-matches its notes onto another part's onsets. Including
    every part as candidates lets each part claim its own onsets (deconfliction).

    Beats are NOT merged across parts: each keeps its own ``part`` tag and notated time, so the
    focus warp is read from *its* beats only (a blended timeline corrupts the warp). They are
    ordered by **canonical position** = ``bar + fraction-within-bar`` rather than absolute notated
    time: bars are the shared anchor across parts (same song measures), so this interleaves
    musically-simultaneous beats correctly even when the parts' OCR'd durations drift apart.
    """
    master: list[Beat] = []
    for pi, tex in enumerate(alphatexts):
        beats = parse_beats(tex)
        bar_start: dict[int, float] = {}
        for b in beats:
            bar_start.setdefault(b.bar, b.notated_time)
        ordered_bars = sorted(bar_start)
        bar_dur: dict[int, float] = {}
        for k, bar in enumerate(ordered_bars):
            nxt = bar_start[ordered_bars[k + 1]] if k + 1 < len(ordered_bars) else None
            if nxt:
                bar_dur[bar] = nxt - bar_start[bar]
        median_dur = sorted(bar_dur.values())[len(bar_dur) // 2] if bar_dur else 1.0
        for b in beats:
            if b.is_rest:
                continue
            dur = bar_dur.get(b.bar, median_dur) or median_dur
            frac = (b.notated_time - bar_start[b.bar]) / dur if dur else 0.0
            master.append(
                Beat(0, b.bar, list(b.pitches), b.notated_time, part=pi, canon=b.bar + frac)
            )
    master.sort(key=lambda b: b.canon)
    for i, b in enumerate(master):
        b.index = i
    return master


def _dtw_pairs_banded(groups: list[NoteGroup], note_beats: list[Beat],
                     trend: list[tuple[float, float]], band: float) -> list[tuple[int, int]]:
    """DTW like :func:`_dtw_pairs` but penalizing matches whose audio time is more than ``band``
    seconds from the tempo trend's expected time for that beat — so the path can't drift onto an
    onset a bar early/late (the cursor "running ahead")."""
    import numpy as np

    expected = [_warp(b.notated_time, trend) for b in note_beats]
    n, m = len(groups), len(note_beats)
    D = np.full((n + 1, m + 1), 1e15)
    D[0, 0] = 0.0
    for i in range(1, n + 1):
        gi = groups[i - 1]
        prev, cur = D[i - 1], D[i]
        for j in range(1, m + 1):
            pen = 0.0 if abs(gi.time - expected[j - 1]) <= band else 5.0
            cur[j] = _cost(gi.pitches, note_beats[j - 1].pitches) + pen + min(prev[j - 1], prev[j], cur[j - 1])
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
    return pairs


def _anchors_of(pairs, groups, note_beats):
    anchors, matched = [], set()
    for ai, bj in pairs:
        if _cost(groups[ai].pitches, note_beats[bj].pitches) == 0.0:
            anchors.append((note_beats[bj].notated_time, groups[ai].time))
            matched.add(ai)
    return _monotonic(anchors), matched


def _align_variant(stem_path: str, side: str | None, beat_pitches: list[list[int]],
                  note_beats: list[Beat]) -> dict | None:
    """Align the focus beats against one audio variant (mono / left / right isolate).

    Two passes: a pitch-only DTW establishes the tempo trend, then a time-banded DTW re-aligns
    within ~3/4 of a bar of that trend so the path can't run ahead onto a wrong-time onset.
    """
    groups = group_onsets(extract_note_events(stem_path, side=side))
    if not groups:
        return None
    anchors, matched = _anchors_of(_dtw_pairs([g.pitches for g in groups], beat_pitches), groups, note_beats)

    if len(anchors) >= 4:
        span_bars = max(1, note_beats[-1].bar - note_beats[0].bar)
        notated_bar = (note_beats[-1].notated_time - note_beats[0].notated_time) / span_bars
        slope = (anchors[-1][1] - anchors[0][1]) / max(1e-6, anchors[-1][0] - anchors[0][0])
        band = max(1.0, 0.75 * notated_bar * slope)
        banded_pairs = _dtw_pairs_banded(groups, note_beats, anchors, band)
        b_anchors, b_matched = _anchors_of(banded_pairs, groups, note_beats)
        if len(b_anchors) >= 0.5 * len(anchors):  # keep the band only if it didn't gut the matches
            anchors, matched = b_anchors, b_matched

    return {"anchors": anchors, "n": len(matched), "groups": groups, "matched": matched}


def _assign_sides(counts: list[tuple[int, int]]) -> list[str]:
    """Competitively assign each part a pan side from its (left, right) match counts.

    A follower part (e.g. a 12-string doubling the acoustic) matches the *louder* part's side
    too, so raw counts mis-assign it. Instead each side goes to its strongest **ratio** claimant
    (the part leaning that way hardest); other parts that preferred the same side are demoted to
    the other side. So acoustic (leans left hardest) keeps left, the 12-string is pushed right.
    """
    prefs = ["left" if l >= r else "right" for l, r in counts]

    def ratio(i: int, side: str) -> float:
        l, r = counts[i]
        return (l + 1) / (r + 1) if side == "left" else (r + 1) / (l + 1)

    owner: dict[str, int] = {}
    for side in ("left", "right"):
        claimants = [i for i, p in enumerate(prefs) if p == side]
        if claimants:
            owner[side] = max(claimants, key=lambda i: ratio(i, side))
    return [
        p if owner.get(p) == i else ("right" if p == "left" else "left")
        for i, p in enumerate(prefs)
    ]


def compute_timings_competitive(stem_path: str, alphatexts: list[str]) -> list[dict]:
    """Align all parts on a stem, assigning each its own pan side competitively (see
    :func:`_assign_sides`). Returns one timing dict per part (same order), tagged with ``side``."""
    variants = []
    counts: list[tuple[int, int]] = []
    for tex in alphatexts:
        nb = [b for b in parse_beats(tex) if not b.is_rest]
        bp = [b.pitches for b in nb]
        vl = _align_variant(stem_path, "left", bp, nb)
        vr = _align_variant(stem_path, "right", bp, nb)
        variants.append((tex, vl, vr))
        counts.append(((vl or {"n": 0})["n"], (vr or {"n": 0})["n"]))

    sides = _assign_sides(counts)
    out: list[dict] = []
    for (tex, vl, vr), side in zip(variants, sides):
        chosen = vl if side == "left" else vr
        if chosen is None:
            out.append({"version": 1, "anchors": [], "bar_times": [], "missing": [], "side": side})
            continue
        anchors = chosen["anchors"]
        focus_beats = parse_beats(tex)
        bar_start: dict[int, float] = {}
        for b in focus_beats:
            bar_start.setdefault(b.bar, b.notated_time)
        n_bars = (max(bar_start) + 1) if bar_start else 0
        bar_times = [round(_warp(bar_start.get(i, 0.0), anchors), 4) for i in range(n_bars)]
        missing_groups = [g for ai, g in enumerate(chosen["groups"]) if ai not in chosen["matched"]]
        res = AlignResult([], [], anchors, missing_groups)
        out.append({
            "version": 1,
            "anchors": [[round(n, 4), round(a, 4)] for n, a in anchors],
            "bar_times": bar_times,
            "missing": _candidate_missing(focus_beats, res),
            "side": side,
        })
    return out


def compute_timing(stem_path: str, focus_alphatex: str, *_compat) -> dict:
    """Align a tab to its guitar stem, on the pan side the part lives on.

    A guitar stem often carries parts panned differently (acoustic left, 12-string right). We
    align the tab against the mono mix and each azimuth-isolated side (see :func:`_isolate_pan`)
    and use whichever side the part favours — so a panned part aligns against just its own audio,
    free of the other part's onsets (the cross-part onsets were what drifted the cursor mid-song).
    A centre-panned part keeps mono (isolating would throw away too many of its onsets).
    """
    note_beats = [b for b in parse_beats(focus_alphatex) if not b.is_rest]
    if not note_beats:
        return {"version": 1, "anchors": [], "bar_times": [], "missing": []}
    beat_pitches = [b.pitches for b in note_beats]

    mono = _align_variant(stem_path, None, beat_pitches, note_beats)
    left = _align_variant(stem_path, "left", beat_pitches, note_beats)
    right = _align_variant(stem_path, "right", beat_pitches, note_beats)
    side = max((v for v in (left, right) if v), key=lambda v: v["n"], default=None)
    # Use the favoured pan side only if it retains most of the part's onsets (i.e. it really is
    # panned there); otherwise the part is centre-ish and mono is safer.
    chosen = side if (side and mono and side["n"] >= 0.7 * mono["n"]) else (mono or side)
    if chosen is None:
        return {"version": 1, "anchors": [], "bar_times": [], "missing": []}

    anchors = chosen["anchors"]
    focus_beats = parse_beats(focus_alphatex)
    bar_start: dict[int, float] = {}
    for b in focus_beats:
        bar_start.setdefault(b.bar, b.notated_time)
    n_bars = (max(bar_start) + 1) if bar_start else 0
    bar_times = [round(_warp(bar_start.get(i, 0.0), anchors), 4) for i in range(n_bars)]

    missing_groups = [g for ai, g in enumerate(chosen["groups"]) if ai not in chosen["matched"]]
    res = AlignResult([], [], anchors, missing_groups)
    return {
        "version": 1,
        "anchors": [[round(n, 4), round(a, 4)] for n, a in anchors],
        "bar_times": bar_times,
        "missing": _candidate_missing(focus_beats, res),
    }


def _candidate_missing(beats: list[Beat], res: AlignResult, *, min_amp: float = 0.5,
                      active_window: float = 1.0, dedup_window: float = 0.4) -> list[dict]:
    """Filter raw unmatched audio groups down to likely *missing tab notes*.

    The raw cross-check is noisy (basic-pitch artifacts, harmonics, bleed, and audio during
    sections this part rests). We keep a group only if it is (a) loud enough (`min_amp`), (b) in
    an *active* passage — within `active_window`s of a confidently-matched beat, not a long rest —
    and (c) carries a pitch that is *new* to its bar: not at-or-above an octave of a note already
    there (which would be a duplicate or an upper harmonic). Lower-octave notes are kept, since the
    dropped notes are mostly thumb-bass. Ringing re-detections (same pitch-class within
    `dedup_window`s) are collapsed. Each survivor is mapped to the bar it belongs in via the warp.
    """
    import bisect

    if not res.anchors:
        return []
    matched = sorted(a for _, a in res.anchors)

    def gap(t: float) -> float:
        i = bisect.bisect_left(matched, t)
        left = matched[i - 1] if i > 0 else -1e9
        right = matched[i] if i < len(matched) else 1e9
        return min(t - left, right - t)

    bn = sorted((b.notated_time, b.bar) for b in beats)
    bn_t = [x[0] for x in bn]
    bar_notes: dict[int, set[int]] = {}
    for b in beats:
        bar_notes.setdefault(b.bar, set()).update(b.pitches)

    out: list[dict] = []
    last_t, last_pc = -1e9, -1
    for g in sorted(res.missing, key=lambda g: g.time):
        if g.amp < min_amp or gap(g.time) > active_window:
            continue
        bar = bn[max(0, bisect.bisect_right(bn_t, _inv_warp(g.time, res.anchors)) - 1)][1]
        novel = sorted(
            p for p in g.pitches
            if not any((p - q) % 12 == 0 and q <= p for q in bar_notes.get(bar, ()))
        )
        if not novel:
            continue
        if out and g.time - last_t < dedup_window and novel[0] % 12 == last_pc:
            continue
        out.append({"bar": bar, "midi": novel, "t": round(g.time, 3), "amp": round(g.amp, 2)})
        last_t, last_pc = g.time, novel[0] % 12
    return out


def _inv_warp(audio: float, anchors: list[tuple[float, float]]) -> float:
    """Inverse of :func:`_warp`: audio_time -> notated_time."""
    if not anchors:
        return audio
    if audio <= anchors[0][1]:
        return anchors[0][0]
    if audio >= anchors[-1][1]:
        return anchors[-1][0]
    for k in range(1, len(anchors)):
        n0, a0 = anchors[k - 1]
        n1, a1 = anchors[k]
        if audio <= a1:
            f = (audio - a0) / (a1 - a0) if a1 > a0 else 0.0
            return n0 + f * (n1 - n0)
    return anchors[-1][0]


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

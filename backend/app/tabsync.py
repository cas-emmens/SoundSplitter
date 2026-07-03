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
    alts: list[int] = field(default_factory=list)  # alternate sounding pitches (bend targets)


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


def _tokenize(body: str) -> list[str]:
    """Split alphaTex music text into tokens, keeping each ``{…}`` property group whole.

    Property groups can contain spaces and parentheses (``{b (0 4)}``, ``{tu 3}``); naive
    whitespace splitting fed their fragments to the chord parser, which then consumed
    everything — bar separators included — while hunting for a closing ``)``. A note's
    attached groups (``5.3{h}{b (0 4)}``) come out as separate tokens after the note.
    """
    tokens: list[str] = []
    i, n = 0, len(body)
    while i < n:
        c = body[i]
        if c.isspace():
            i += 1
            continue
        if c == "{":
            j = body.find("}", i)
            j = n - 1 if j < 0 else j
            tokens.append(body[i : j + 1])
            i = j + 1
            continue
        j = i
        while j < n and not body[j].isspace() and body[j] != "{":
            j += 1
        tokens.append(body[i:j])
        i = j
    return tokens


# Tuplet factor: N notes in the time of the nearest lower power of two.
_TUPLET_FACTORS = {3: 2 / 3, 5: 4 / 5, 6: 2 / 3, 7: 4 / 7, 9: 8 / 9}


def parse_beats(alphatex: str) -> list[Beat]:
    """Parse alphaTex into an ordered beat list with notated times (incl. rests).

    Handles `\\tempo` (header AND mid-song changes — the notated timeline follows every
    change), `\\ts`, `:N` durations, `{d}` dots and `{tu N}` tuplets (they stretch/shrink
    the beat they follow), chords `(f.s f.s)`, single notes `f.s`, rests `r`. Tied (`-.s`)
    and dead (`x.s`) notes carry no reliable pitch to match, but their beats still occupy
    time — they become silent (rest-like) beats rather than disappearing from the
    timeline, which used to compress everything after them. Bar number increments at `|`.
    """
    tuning = _tuning_from_header(alphatex)
    lines = alphatex.splitlines()
    start = next((i + 1 for i, l in enumerate(lines) if l.strip() == "."), 0)
    bpm_m = re.search(r"\\tempo\s+(\d+)", alphatex)
    bpm = int(bpm_m.group(1)) if bpm_m else 120
    sec_per_whole = (60.0 / bpm) * 4.0

    toks = _tokenize(" ".join(lines[start:]).replace("|", " | "))
    tempo_next = False  # the token after a mid-song \tempo is its BPM value

    def midi(tok: str) -> int | None:
        m = re.match(r"^(\d+)\.(\d+)", tok)
        if not m:
            return None
        fret, string = int(m.group(1)), int(m.group(2))
        return tuning[string] + fret if string in tuning else None

    def is_silent_note(tok: str) -> bool:
        return re.match(r"^[x\-]\.\d+", tok) is not None  # tied (-.s) or dead (x.s)

    beats: list[Beat] = []
    skip, i, dur, t, bar, idx = 0, 0, 4, 0.0, 0, 0
    last_secs = 0.0  # duration of the most recent beat, for {d}/{tu N} adjustments
    while i < len(toks):
        tok = toks[i]; i += 1
        if skip:
            skip -= 1; continue
        if tempo_next:
            tempo_next = False
            if tok.isdigit():  # a mid-song tempo change: the timeline speeds up/slows here
                sec_per_whole = (60.0 / int(tok)) * 4.0
            continue
        if tok == "|":
            bar += 1; continue
        if tok.startswith("\\"):
            if tok == "\\tempo":
                tempo_next = True
                continue
            skip = 2 if tok == "\\ts" else 1 if tok == "\\tuning" else 0
            continue
        if tok.startswith(":"):
            try:
                dur = int(tok[1:])
            except ValueError:
                pass
            continue
        if tok.startswith("{"):
            # Beat property groups adjust the PREVIOUS beat's time; a bend group records
            # the note's sounding TARGET pitch (a 7 bent full sounds as 9 — without this,
            # bend-heavy passages have nothing the audio can match); other note-effect
            # groups ({h}, {v}, …) don't affect matching or timing.
            if tok == "{d}" and last_secs:
                t += last_secs / 2
            elif (m := re.match(r"^\{tu (\d+)\}$", tok)) and last_secs:
                t -= last_secs * (1 - _TUPLET_FACTORS.get(int(m.group(1)), 1.0))
            elif (m := re.match(r"^\{.*b \(([\d ]+)\)", tok)) and beats and beats[-1].pitches:
                peak = max(int(v) for v in m.group(1).split())  # alphaTab quarter steps
                if peak:
                    beats[-1].alts.append(beats[-1].pitches[-1] + (peak + 1) // 2)
            continue
        secs = sec_per_whole / dur
        if tok == "r":
            beats.append(Beat(idx, bar, [], t, is_rest=True))
            idx += 1; t += secs; last_secs = secs
            continue
        pitches: list[int] = []
        is_beat = False
        if tok.startswith("("):
            is_beat = True
            inner = tok[1:]; done = inner.endswith(")")
            if (mm := midi(inner.rstrip(")"))) is not None:
                pitches.append(mm)
            while not done and i < len(toks):
                u = toks[i]; i += 1; done = u.endswith(")")
                if (mm := midi(u.rstrip(")"))) is not None:
                    pitches.append(mm)
        elif (mm := midi(tok)) is not None:
            pitches.append(mm); is_beat = True
        elif is_silent_note(tok):
            is_beat = True  # tied/dead: occupies its time, matches nothing
        if not is_beat:
            continue  # unknown token, not a beat
        beats.append(Beat(idx, bar, pitches, t, is_rest=not pitches))
        idx += 1; t += secs; last_secs = secs
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

def _cost(audio: set[int], tab: list[int], alts: list[int] = ()) -> float:  # type: ignore[assignment]
    """Pitch-set distance: 0 = confident match, grading up to 1 = unrelated.

    A single note matches on its exact pitch. A chord only reaches 0 when the audio
    contains **most of it** (at least two notes and half the chord): one shared pitch is
    no evidence there — neighbouring chords share open strings and ring-out tones, and
    single-pitch "matches" anchored chords onto the wrong strum (the cursor hung on chord
    ends and skipped transitions). A partial chord overlap is a usable path hint (0.3)
    but never an anchor; where chords can't anchor, the warp follows the notated
    timeline, which accurate tabs make right.
    """
    if not tab:
        return 0.6  # rest beat: weak match to anything (handled outside DTW normally)
    pool = set(tab) | set(alts)  # a bent note may sound at its target pitch instead
    shared = sum(1 for t in pool if t in audio)
    if len(tab) == 1:
        if shared:
            return 0.0
    elif shared >= max(2, (len(tab) + 1) // 2):
        return 0.0
    elif shared:
        return 0.3
    if any((a - t) % 12 == 0 for a in audio for t in pool):
        return 0.4
    if any(a % 12 == t % 12 for a in audio for t in pool):
        return 0.7
    return 1.0


def _dtw_pairs(seq_a: list[set | list], seq_b: list[list[int]]) -> list[tuple[int, int]]:
    """Subsequence-DTW match audio groups ``seq_a`` to tab beats ``seq_b`` by pitch cost.

    Audio before the part's first beat and after its last is skipped for FREE (``D[i,0]=0``
    and the end picked as the best row of the last column): a part that rests through half
    the song — a solo track, a slide overdub — aligns to its own section instead of being
    forced to absorb every earlier onset into its first notes.
    """
    import numpy as np

    n, m = len(seq_a), len(seq_b)
    D = np.full((n + 1, m + 1), 1e15)
    D[:, 0] = 0.0  # free leading-audio skip
    for i in range(1, n + 1):
        ai = seq_a[i - 1]
        prev, cur = D[i - 1], D[i]
        for j in range(1, m + 1):
            cur[j] = _cost(ai, seq_b[j - 1]) + min(prev[j - 1], prev[j], cur[j - 1])
    i, j = int(np.argmin(D[:, m])), m  # free trailing-audio skip
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
    D[:, 0] = 0.0  # subsequence DTW: leading/trailing audio is free (see _dtw_pairs)
    for i in range(1, n + 1):
        gi = groups[i - 1]
        prev, cur = D[i - 1], D[i]
        for j in range(1, m + 1):
            pen = 0.0 if abs(gi.time - expected[j - 1]) <= band else 5.0
            nb = note_beats[j - 1]
            cur[j] = _cost(gi.pitches, nb.pitches, nb.alts) + pen + min(prev[j - 1], prev[j], cur[j - 1])
    i, j = int(np.argmin(D[:, m])), m
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


def _anchors_of(pairs, groups, note_beats, trend=None, band=None, ambiguity_window=2.5):
    """Exact pitch matches on locally *distinctive* beats, as (notated, audio) anchors.

    With ``trend``/``band``, only matches whose audio time lies within the band of the
    trend anchor the warp: the banded DTW's out-of-band penalty is soft (a hard wall can
    make the path infeasible), so a starved stretch — a part barely audible in the stem —
    can still take penalized far-away matches, and those must not steer the cursor.
    Beats whose pitch-set repeats within ``ambiguity_window`` (see :func:`distinct_beat_ids`)
    never anchor: their evidence could belong to a different repetition. The window scales
    with the band in use — inside a tight band, twins two seconds apart ARE distinguishable.
    """
    distinct = distinct_beat_ids(note_beats, window=ambiguity_window)
    anchors, matched = [], set()
    for ai, bj in pairs:
        beat = note_beats[bj]
        if _cost(groups[ai].pitches, beat.pitches, beat.alts) != 0.0:
            continue
        matched.add(ai)
        if id(beat) not in distinct:
            continue
        if trend is not None and band is not None:
            expected = _warp(beat.notated_time, trend)
            if abs(groups[ai].time - expected) > band:
                continue
        anchors.append((beat.notated_time, groups[ai].time))
    return _monotonic(anchors), matched


def matchable_beats(beats: list[Beat]) -> list[Beat]:
    """The beats worth matching against audio: notes and the FIRST chord of a strum run.

    A strumming pattern repeats the same chord in quick succession, and its attacks are
    soft and smeared in a recording — basic-pitch onsets there are unreliable, and the
    repeats are mutually indistinguishable to a pitch DTW (identical pitch sets), so they
    produced the hanging-then-jumping anchors. They are excluded from matching entirely:
    the warp interpolates between surrounding anchors **on the notated timeline**, which is
    exact now (it carries the source's tempo automations) — i.e. strummed sections keep tab
    timing. The first strum of each run stays matchable to anchor the section's start.
    """
    out: list[Beat] = []
    prev: Beat | None = None
    for b in beats:
        if b.is_rest:
            continue
        is_repeat = (
            prev is not None
            and len(b.pitches) >= 2
            and set(b.pitches) == set(prev.pitches)
            and (b.notated_time - prev.notated_time) <= 0.5
        )
        if not is_repeat:
            out.append(b)
        prev = b
    return out


def distinct_beat_ids(note_beats: list[Beat], window: float = 2.5) -> set[int]:
    """Beats whose pitch-set does NOT recur in another beat within ``window`` seconds.

    Only these may ANCHOR the warp. In a fast lick the same pitches cycle several times
    inside the alignment band, and the DTW pinned bars onto the *previous* repetition (the
    cursor ran a bar ahead and skipped the next run). Ambiguous beats still participate in
    the DTW — they shape the path — but the warp is built from beats whose audio evidence
    can only belong to them; repeat-heavy stretches interpolate on the notated timeline.
    """
    by_key: dict[tuple[frozenset[int], frozenset[int]], list[Beat]] = {}
    for b in note_beats:
        # The key includes the bend targets: a bent 7 SOUNDS different from a plain 7, so
        # it is distinctive evidence even when plain 7s surround it — the solo's bends are
        # its anchoring backbone, and keying on base pitches alone gated them all away.
        by_key.setdefault((frozenset(b.pitches), frozenset(b.alts)), []).append(b)
    ambiguous: set[int] = set()
    for twins in by_key.values():
        for i in range(1, len(twins)):
            if twins[i].notated_time - twins[i - 1].notated_time <= window:
                ambiguous.add(id(twins[i - 1]))
                ambiguous.add(id(twins[i]))
    return {id(b) for b in note_beats if id(b) not in ambiguous}


def _bar_durations(alphatex: str):
    """Audio-time -> the tab's local bar duration, for drumgrid's expected-bar prior
    (identity time assumption: the tab's LOCAL tempo is accurate even when the song's
    structure shifts sections around)."""
    import bisect

    starts: dict[int, float] = {}
    for b in parse_beats(alphatex):
        starts.setdefault(b.bar, b.notated_time)
    times = sorted(starts.values())
    durs = [t1 - t0 for t0, t1 in zip(times, times[1:])]

    def expected(t: float) -> float | None:
        if not durs:
            return None
        i = min(max(bisect.bisect_right(times, t) - 1, 0), len(durs) - 1)
        return durs[i]

    return expected


def _structure_prior(stem_path: str, alphatexts: list[str]) -> list[tuple[float, float]] | None:
    """Map notated bars onto the drum stem's measured bar grid (None without usable drums).

    The banded pitch DTW can absorb tempo nuance but not whole-bar structure differences
    (un-notated intro vamps, a rap verse, outro inserts): they push the true mapping far
    outside any identity band, and the pitch DTW then latches self-similar groove bars
    onto wrong repetitions inside it. Bars are the right unit for structure: the drum
    grid measures the audio's bars, each gets a pitch profile from the (cached) note
    events, and a bar-level DTW with gap moves maps notated bars onto them — extra audio
    bars and skipped tab bars both allowed. Matched pairs (decent cost only) become the
    fine alignment's prior trend. Validated on IRTM: discovered the un-notated De La
    Soul verse (+28s) and landed the tab's last bar within one bar of the last onset.
    """
    from . import drumgrid

    drums = drumgrid.sibling_drum_stem(stem_path)
    if not drums:
        return None
    # Profile source: the densest part (most bars with struck notes) speaks for the
    # song's shared measure grid.
    densest = max(alphatexts, key=lambda tex: sum(1 for b in parse_beats(tex) if b.pitches))
    grid = drumgrid.compute_grid(drums, expected_bar=_bar_durations(densest))
    if len(grid.boundaries) < 8:
        return None

    events = extract_note_events(stem_path)
    audio_bars: list[tuple[float, set[int]]] = []
    for b0, b1 in zip(grid.boundaries, grid.boundaries[1:]):
        if b1 - b0 > 8:  # gap between drum sections
            continue
        audio_bars.append((b0, {int(p) for (s, e, p, a) in events if b0 <= s < b1 and a >= 0.4}))

    notated: dict[int, set[int]] = {}
    bar_start: dict[int, float] = {}
    for b in parse_beats(densest):
        bar_start.setdefault(b.bar, b.notated_time)
        notated.setdefault(b.bar, set()).update(b.pitches)
    tab_bars = [(bar_start[i], notated.get(i, set())) for i in sorted(bar_start)]
    if len(tab_bars) < 8:
        return None

    # Tab bars that the tab's own timeline places clearly outside the drum coverage
    # (a drum-less acoustic intro / outro) are free to skip in the bar DTW; bars
    # plausibly inside coverage are not, or the self-similar groove head gets discarded.
    margin = 45.0
    cov0, cov1 = audio_bars[0][0], audio_bars[-1][0]
    free_lead = sum(1 for t, _ in tab_bars if t < cov0 - margin)
    free_trail = sum(1 for t, _ in tab_bars if t > cov1 + margin)

    pairs = _bar_dtw(audio_bars, tab_bars, free_lead=free_lead, free_trail=free_trail)
    good = [(tab_bars[tj][0], audio_bars[ai][0]) for ai, tj, cost in pairs if cost <= 0.6]
    if len(good) < 8:
        return None
    # Consistency pruning: a pair's shift (audio - notated) must agree with its local
    # consensus. True structure is long plateaus; short inconsistent runs are boundary
    # force-matches (tab bars just outside drum coverage taking weak matches inside it).
    import statistics

    shifts = [a - n for n, a in good]
    w = 5
    kept = [
        (n, a)
        for k, (n, a) in enumerate(good)
        if abs(shifts[k] - statistics.median(shifts[max(0, k - w):k + w + 1])) <= 2.5
    ]
    # Edge trim: the FIRST/LAST pairs anchor the slope-1 extrapolation across everything
    # outside drum coverage (_pin_identity), so a single boundary force-match there
    # shifts a whole drum-less song half. An edge pair must agree with the consensus of
    # its 10 inward neighbours; a real structure plateau (IRTM's +15s head) does.
    def trim(seq: list[tuple[float, float]]) -> list[tuple[float, float]]:
        while len(seq) > 12:
            edge = seq[0][1] - seq[0][0]
            consensus = statistics.median(a - n for n, a in seq[1:11])
            if abs(edge - consensus) <= 2.0:
                break
            seq = seq[1:]
        return seq

    kept = trim(kept)
    kept = trim(kept[::-1])[::-1]
    if len(kept) < 8:
        return None
    return _monotonic(kept)


_GAP_AUDIO = 0.55   # bar-DTW: skip an audio bar (un-notated vamp / extra pass)
_GAP_TAB = 0.65     # bar-DTW: skip a notated bar (the record skips it)


def _bar_dtw(audio_bars, tab_bars, free_lead: int = 0, free_trail: int = 0) -> list[tuple[int, int, float]]:
    """Bar-level DTW with gap moves; returns matched (audio_idx, tab_idx, cost).

    ``free_lead`` / ``free_trail`` leading/trailing TAB bars are skippable for free: the
    drum grid only covers drum sections, so tab bars the tab's own timeline places
    clearly before/after that coverage (a drum-less acoustic intro, an outro) must not
    be priced — pricing them made mis-matching Stairway's intro into the drum section
    cheaper than skipping it (+124s derail). They must not be free UNCONDITIONALLY
    either: a self-similar groove head then gets discarded and matched into the intro
    vamp (IRTM lost its +15s head). Inner gaps stay paid: extra audio bars (un-notated
    vamps) and skipped tab bars mid-song are real structure.
    """
    import numpy as np

    def cost(a: set[int], t: set[int]) -> float:
        if not t and not a:
            return 0.1
        if not t or not a:
            return 0.6
        return 1.0 - len(a & t) / max(len(t), 1)

    na, nt = len(audio_bars), len(tab_bars)
    D = np.full((na + 1, nt + 1), np.inf)
    D[0, 0] = 0.0
    for j in range(1, nt + 1):
        D[0, j] = 0.0 if j <= free_lead else D[0, j - 1] + _GAP_TAB
    D[1:, 0] = np.arange(1, na + 1) * _GAP_AUDIO
    for i in range(1, na + 1):
        ai = audio_bars[i - 1][1]
        for j in range(1, nt + 1):
            c = cost(ai, tab_bars[j - 1][1])
            D[i, j] = min(D[i - 1, j - 1] + c, D[i - 1, j] + _GAP_AUDIO, D[i, j - 1] + _GAP_TAB)
    end = [D[na, j] + max(0, (nt - j) - free_trail) * _GAP_TAB for j in range(1, nt + 1)]
    pairs: list[tuple[int, int, float]] = []
    i, j = na, int(np.argmin(end)) + 1
    while i > 0 and j > 0:
        c = cost(audio_bars[i - 1][1], tab_bars[j - 1][1])
        if D[i, j] == D[i - 1, j - 1] + c:
            pairs.append((i - 1, j - 1, c))
            i, j = i - 1, j - 1
        elif D[i, j] == D[i - 1, j] + _GAP_AUDIO:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def _estimate_offset(groups: list[NoteGroup], note_beats: list[Beat], limit: float = 45.0) -> float:
    """Global audio-vs-notated offset (a count-in / silent intro before the tab's bar 1).

    A recording that opens with material not in the tab shifts EVERY beat by the same
    amount, and the identity prior spends its band margin on that shift before it can
    absorb real nuance. Vote ``group time - beat notated time`` over exact pitch matches
    of distinctive beats: on a structure-true tab, the whole song votes the same shift,
    so the histogram mode is the count-in and stray coincidental matches are outvoted.
    """
    distinct = distinct_beat_ids(note_beats)
    votes: list[float] = []
    for b in note_beats:
        if id(b) not in distinct or not b.pitches:
            continue
        for g in groups:
            d = g.time - b.notated_time
            if -limit <= d <= limit and _cost(g.pitches, b.pitches, b.alts) == 0.0:
                votes.append(d)
    if len(votes) < 8:
        return 0.0
    bins: dict[int, int] = {}
    for d in votes:
        bins[int(d // 1.0)] = bins.get(int(d // 1.0), 0) + 1
    mode = max(bins, key=lambda k: bins[k])
    near = sorted(d for d in votes if mode - 1.0 <= d <= mode + 2.0)
    return near[len(near) // 2]


def _align_variant(stem_path: str, side: str | None, beat_pitches: list[list[int]],
                  note_beats: list[Beat], prior: list[tuple[float, float]] | None = None) -> dict | None:
    """Align the focus beats against one audio variant (mono / left / right isolate).

    The tab's notated timeline is the prior: it is built from the source's exact tempo
    automations, so it tracks the recording within a few percent — a note notated at 356s
    sounds near 356s, never at 196s. Pass one is therefore a time-banded DTW around the
    **identity** trend — shifted by the estimated global offset, so a recording's count-in
    doesn't eat the band — with a generous band (it corrects nuance, not location — this is
    what anchors parts that rest through most of the song, where a pitch-only bootstrap
    latches onto any similar-sounding earlier section). Pass two re-aligns in a tight band
    around pass one's own anchors.

    With a drum-grid ``prior`` (see :func:`_structure_prior`) pass one bands around THAT
    trend instead, tightly (±1–2 bars of bar-mapping uncertainty): it already carries the
    count-in and whole-bar structure differences the identity band can't reach.
    """
    groups = group_onsets(extract_note_events(stem_path, side=side))
    if not groups:
        return None

    span = max(note_beats[-1].notated_time, groups[-1].time, 1.0)
    if prior:
        trend0 = _pin_identity(prior)
        band = 4.0
    else:
        offset = _estimate_offset(groups, note_beats)
        trend0 = [(0.0, offset), (span, span + offset)]
        band = max(12.0, 0.06 * span)
    anchors, matched = _anchors_of(
        _dtw_pairs_banded(groups, note_beats, trend0, band),
        groups, note_beats, trend=trend0, band=band,
    )

    if len(anchors) >= 4:
        span_bars = max(1, note_beats[-1].bar - note_beats[0].bar)
        notated_bar = (note_beats[-1].notated_time - note_beats[0].notated_time) / span_bars
        slope = (anchors[-1][1] - anchors[0][1]) / max(1e-6, anchors[-1][0] - anchors[0][0])
        tight = max(1.0, 0.75 * notated_bar * slope)
        # Pin the trend to the pass-one prior at both ends: outside its anchors a
        # piecewise-linear warp clamps flat, which would let the head/tail regions drift
        # arbitrarily far from the notated prior inside a formally-satisfied band.
        ends = [(0.0, _warp(0.0, trend0)), (span, _warp(span, trend0))]
        trend = _monotonic([ends[0]] + anchors + [ends[1]])
        banded_pairs = _dtw_pairs_banded(groups, note_beats, trend, tight)
        b_anchors, b_matched = _anchors_of(
            banded_pairs, groups, note_beats, trend=trend, band=tight
        )
        if len(b_anchors) >= 0.5 * len(anchors):  # keep the band only if it didn't gut the matches
            anchors, matched = b_anchors, b_matched

    return {"anchors": anchors, "n": len(matched), "groups": groups, "matched": matched}


def _assign_sides(counts: list[tuple[int, int]]) -> list[str]:
    """Competitively assign each part a pan side from its (left, right) match counts.

    A follower part (e.g. a 12-string doubling the acoustic) matches the *louder* part's side
    too, so raw counts mis-assign it. Each side goes to its strongest **ratio** claimant (the
    part leaning that way hardest). Every other part aligns against the plain **mono** mix:
    with many parts on one stem (a full song can carry seven guitar tracks), demoting losers
    to the *opposite* side — the old rule, built for two parts — pushed most parts onto
    isolated audio they aren't in at all, and their warps came out garbage.
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
    return [p if owner.get(p) == i else "mono" for i, p in enumerate(prefs)]


def _pin_identity(anchors: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Extend a warp trend beyond its anchors at slope 1 (tempo-exact continuation).

    A piecewise-linear warp clamps flat outside its anchors, letting head/tail regions
    drift anywhere inside a formally-satisfied band. The backward pin follows slope 1
    down to audio zero — clamping its audio at zero while pushing notated far negative
    (an earlier bug) created a near-flat segment across the whole head of the song for
    parts whose anchors start late.
    """
    (n0, a0), (n1, a1) = anchors[0], anchors[-1]
    span = 24 * 3600.0
    return _monotonic([(n0 - a0, 0.0), *anchors, (n1 + span, a1 + span)])


# ------------------------------------------------------------------- bend-glide anchoring

def _bend_probes(beats: list[Beat]) -> list[tuple[Beat, int, int, float]]:
    """Bend beats worth probing for a pitch glide: (beat, base_midi, rise_semitones, duration).

    Only single-note bends of at least a whole step with ~150ms of ring time are probed:
    smaller bends live inside vibrato territory, and the fast repeated-lick bends (80ms)
    are both too short to glide-track and mutually ambiguous anyway.
    """
    out: list[tuple[Beat, int, int, float]] = []
    for k, b in enumerate(beats):
        if b.is_rest or len(b.pitches) != 1 or not b.alts:
            continue
        rise = max(b.alts) - b.pitches[0]
        dur = beats[k + 1].notated_time - b.notated_time if k + 1 < len(beats) else 0.3
        if rise >= 2 and dur >= 0.15:
            out.append((b, b.pitches[0], rise, dur))
    return out


_signal_cache: dict[tuple[str, str], tuple] = {}


def _part_signal(stem_path: str, side: str | None):
    """The audio a part aligns against (mono load or azimuth isolate), cached per side."""
    key = (stem_path, side or "mono")
    if key not in _signal_cache:
        import librosa

        if side in ("left", "right"):
            sig, sr = _isolate_pan(stem_path, side)
        else:
            sig, sr = librosa.load(stem_path, sr=22050)
        if len(_signal_cache) > 3:
            _signal_cache.clear()
        _signal_cache[key] = (sig, sr)
    return _signal_cache[key]


def _glide_onsets(cents, hop_t: float, rise_cents: float, dur: float) -> list[float]:
    """Times where a pluck-then-bend glide starts in a pYIN cents track (NaN = unvoiced).

    A glide is a frame near the base pitch (below +40c) from which the pitch climbs to
    near the bend target within ~1.6x the note's duration and stays up briefly. Vibrato
    wobble fails the climb, a re-pluck already at the target pitch fails the near-base
    start, and a run down to a different note breaks the walk.
    """
    import numpy as np

    goal = max(rise_cents - 70.0, 0.55 * rise_cents)
    hold = 0.45 * rise_cents
    max_len = max(4, int(max(dur * 1.6, 0.25) / hop_t))
    onsets: list[float] = []
    n = len(cents)
    for i in range(n):
        c0 = cents[i]
        if np.isnan(c0) or not (-120.0 < c0 < 40.0):
            continue
        gaps = 0
        for j in range(i + 1, min(n, i + 1 + max_len)):
            c = cents[j]
            if np.isnan(c):
                gaps += 1
                if gaps > 3:
                    break
                continue
            if c < -140.0:
                break  # fell to another note: not a bend from this base
            if c >= goal:
                tail = cents[j + 1 : j + 6]
                if all(np.isnan(x) or x >= hold for x in tail):
                    # Onset ~ the pluck. Bound it so a same-pitch note still ringing
                    # just before the bend can't drag the estimate a beat early.
                    onsets.append(max(i * hop_t, j * hop_t - 1.2 * max(dur, 0.15)))
                break
    merged: list[float] = []
    last: float | None = None
    for t in sorted(onsets):  # one glide yields a run of valid start frames: keep its head
        if last is not None and t - last <= 0.3:
            last = t
            continue
        merged.append(t)
        last = t
    return merged


def _glide_anchors(sig, sr, probes, trend, band: float) -> list[tuple[float, float]]:
    """Physically-verified bend anchors ``(notated, audio-glide-start)``.

    For each probe, pYIN tracks f0 in a small window around the beat's expected audio
    time (from ``trend``), band-limited around the bend's frequencies, and the window is
    accepted only if it contains EXACTLY one matching glide — two glides means twin bends
    (a repeated lick) and the evidence could belong to either.
    """
    import librosa
    import numpy as np

    anchors: list[tuple[float, float, int]] = []
    total = len(sig) / sr
    for b, base, rise, dur in probes:
        t_pred = _warp(b.notated_time, trend)
        w0 = max(0.0, t_pred - band)
        w1 = min(total, t_pred + band + max(dur, 0.3) + 0.2)
        if w1 - w0 < 0.5:
            continue
        seg = sig[int(w0 * sr) : int(w1 * sr)]
        base_hz = float(librosa.midi_to_hz(base))
        # fill_na=None keeps pYIN's best f0 estimate on frames its Viterbi hesitates to
        # call voiced — distorted/sustained bends read as barely-voiced and a NaN there
        # cut the glide off mid-climb. The glide-shape test is the discriminator, not
        # the voicing flag. The band is generous for the same reason: too narrow a range
        # degrades the estimates near its edges.
        f0, _vflag, _vprob = librosa.pyin(
            seg, sr=sr, fmin=base_hz * 2 ** (-8 / 12),
            fmax=base_hz * 2 ** ((rise + 6) / 12), frame_length=1024, hop_length=256,
            fill_na=None,
        )
        with np.errstate(invalid="ignore", divide="ignore"):
            cents = 1200.0 * np.log2(f0 / base_hz)
        found = _glide_onsets(cents, 256.0 / sr, rise * 100.0, dur)
        if len(found) == 1:
            anchors.append((b.notated_time, w0 + found[0], base))
    return _prune_glides(anchors)


def _prune_glides(cands: list[tuple[float, float, int]]) -> list[tuple[float, float]]:
    """Reduce raw per-probe glide claims ``(notated, audio, base_midi)`` to trusted anchors.

    Two probes claiming the SAME audio glide happens with same-pitch twin bends where
    only one twin's glide is detectable — each probe's window sees exactly one glide and
    calls it unique, but the ownership is ambiguous, so both claims are dropped. Then a
    leave-one-out consistency check removes wrong-occurrence matches: every glide anchor
    must sit near the trend its siblings agree on (a wrong occurrence is seconds off).
    """
    keep: list[tuple[float, float]] = []
    for k, (nt, at, base) in enumerate(cands):
        contested = any(
            j != k and cands[j][2] == base and abs(cands[j][1] - at) < 0.25
            for j in range(len(cands))
        )
        if not contested:
            keep.append((nt, at))
    anchors = _monotonic(keep)
    while len(anchors) >= 3:
        resid = [
            abs(a - _warp(n, _pin_identity(anchors[:k] + anchors[k + 1 :])))
            for k, (n, a) in enumerate(anchors)
        ]
        worst = max(range(len(anchors)), key=lambda k: resid[k])
        if resid[worst] <= 1.25:
            break
        anchors.pop(worst)
    return anchors


def _merge_trusted(trusted, others) -> list[tuple[float, float]]:
    """Merge anchor lists, keeping every ``trusted`` point: an *other* anchor is inserted
    only where it stays strictly monotone with what's already in (trusted wins conflicts)."""
    import bisect

    out: list[tuple[float, float]] = sorted(trusted)
    for nt, at in sorted(others):
        i = bisect.bisect_left(out, (nt, at))
        if i > 0 and (nt <= out[i - 1][0] or at <= out[i - 1][1]):
            continue
        if i < len(out) and (nt >= out[i][0] or at >= out[i][1]):
            continue
        out.insert(i, (nt, at))
    return out


def _glide_refine(stem_path: str, picked: list[tuple[str, dict | None, str]]) -> None:
    """Re-anchor each part around physically-verified bend glides.

    Pitch-identity anchors can land on the wrong repetition of a phrase — all their
    evidence says is "these notes again". A measured glide (this pitch, bent THIS far,
    over THIS duration, at the only spot in the window it occurs) cannot. Verified glides
    become trusted anchors: existing anchors that contradict the glide-corrected trend
    are evicted — with a tolerance that grows with distance from the nearest glide, so
    dense well-anchored regions far from any bend are untouched — then pitch anchors are
    re-harvested in a tight band around the corrected warp.
    """
    for i, (tex, chosen, side) in enumerate(picked):
        if chosen is None or not chosen["anchors"]:
            continue
        beats = parse_beats(tex)
        probes = _bend_probes(beats)
        if not probes:
            continue
        sig, sr = _part_signal(stem_path, side)
        # The window must cover the trend's plausible ERROR (a wrong-repetition anchor
        # can put it ~3s off), or a probe centred on the corruption finds a twin bend,
        # calls it unique, and confirms the bad trend. Wide windows are safe: glide
        # probes are pitch-selective, and same-pitch twins self-reject via uniqueness.
        glides = _glide_anchors(sig, sr, probes, _pin_identity(chosen["anchors"]), band=4.0)
        if not glides:
            continue
        gtrend = _pin_identity(glides)
        survivors = [
            (nt, at) for nt, at in chosen["anchors"]
            if abs(at - _warp(nt, gtrend))
            <= 0.8 + 0.15 * min(abs(nt - g[0]) for g in glides)
        ]
        merged = _merge_trusted(glides, survivors)
        nb = matchable_beats(beats)
        own = _pin_identity(merged)
        pairs = _dtw_pairs_banded(chosen["groups"], nb, own, 1.5)
        refined, matched = _anchors_of(
            pairs, chosen["groups"], nb, trend=own, band=1.5, ambiguity_window=2.0
        )
        final = _merge_trusted(glides, refined)
        picked[i] = (
            tex,
            {**chosen, "anchors": final, "matched": matched, "n": len(matched)},
            side,
        )


def _cross_refine(picked: list[tuple[str, dict | None, str]]) -> None:
    """Realign weakly-anchored parts around the best-anchored part's warp.

    Every part follows the SAME recording on an IDENTICAL notated grid (same tempo
    automations), so the densest part's warp is a far tighter prior than identity for its
    siblings. This is what rescues a sparse part whose own phrase repeats: the lead solo's
    opening figure recurs 20+ seconds later, and inside a wide identity band the DTW is
    free to pick the wrong repetition — the cursor then camps on the first solo note until
    the recording catches up with the bad anchor. Beyond the reference's coverage the
    trend extrapolates at slope 1 (tempo-exact continuation) instead of clamping flat.
    """
    scored = [(i, p[1]) for i, p in enumerate(picked) if p[1] and len(p[1]["anchors"]) >= 30]
    if not scored:
        return
    ref_i, ref = max(scored, key=lambda s: len(s[1]["anchors"]))
    trend = _pin_identity(ref["anchors"])
    for i, (tex, chosen, side) in enumerate(picked):
        if i == ref_i or chosen is None:
            continue
        nb = matchable_beats(parse_beats(tex))
        if not nb:
            continue
        band = 3.0
        pairs = _dtw_pairs_banded(chosen["groups"], nb, trend, band)
        refined, matched = _anchors_of(pairs, chosen["groups"], nb, trend=trend, band=band)
        if len(refined) < 4:
            continue
        # Second, tighter iteration around the part's OWN safe anchors: within a ±1.5s band
        # twins two seconds apart are distinguishable, so more beats may anchor — this is
        # what densifies a repetitive solo without re-admitting wrong-repetition matches.
        own = _pin_identity(refined)
        pairs2 = _dtw_pairs_banded(chosen["groups"], nb, own, 1.5)
        refined2, matched2 = _anchors_of(
            pairs2, chosen["groups"], nb, trend=own, band=1.5, ambiguity_window=2.0
        )
        if len(refined2) >= len(refined):
            refined, matched = refined2, matched2
        picked[i] = (
            tex,
            {**chosen, "anchors": refined, "matched": matched, "n": len(matched)},
            side,
        )


def compute_timings_competitive(stem_path: str, alphatexts: list[str]) -> list[dict]:
    """Align all parts on a stem, assigning each its own pan side competitively (see
    :func:`_assign_sides`). Returns one timing dict per part (same order), tagged with ``side``."""
    prior = _structure_prior(stem_path, alphatexts)
    variants = []
    counts: list[tuple[int, int]] = []
    for tex in alphatexts:
        nb = matchable_beats(parse_beats(tex))
        bp = [b.pitches for b in nb]
        vl = _align_variant(stem_path, "left", bp, nb, prior)
        vr = _align_variant(stem_path, "right", bp, nb, prior)
        vm = _align_variant(stem_path, None, bp, nb, prior)
        variants.append((tex, {"left": vl, "right": vr, "mono": vm}))
        counts.append(((vl or {"n": 0})["n"], (vr or {"n": 0})["n"]))

    sides = _assign_sides(counts)
    picked: list[tuple[str, dict | None, str]] = []
    for (tex, by_side), side in zip(variants, sides):
        chosen = by_side[side]
        # A side owner whose isolated-audio alignment is much weaker than mono isn't
        # really panned there — mono is the safer bed (mirrors compute_timing's guard).
        mono = by_side["mono"]
        if side != "mono" and mono and (chosen is None or chosen["n"] < 0.7 * mono["n"]):
            chosen, side = mono, "mono"
        picked.append((tex, chosen, side))

    _cross_refine(picked)
    _glide_refine(stem_path, picked)

    out: list[dict] = []
    for tex, chosen, side in picked:
        if chosen is None:
            out.append({"version": 1, "anchors": [], "bar_times": [], "missing": [], "side": side})
            continue
        anchors = chosen["anchors"]
        focus_beats = parse_beats(tex)
        bar_start: dict[int, float] = {}
        for b in focus_beats:
            bar_start.setdefault(b.bar, b.notated_time)
        n_bars = (max(bar_start) + 1) if bar_start else 0
        # Bars outside the anchored region continue at slope 1 (see _pin_identity): a flat
        # clamp gave every closing bar the last anchor's time (count-in read a 0s beat there).
        trend = _pin_identity(anchors) if anchors else []
        bar_times = [round(_warp(bar_start.get(i, 0.0), trend), 4) for i in range(n_bars)]
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
    note_beats = matchable_beats(parse_beats(focus_alphatex))
    if not note_beats:
        return {"version": 1, "anchors": [], "bar_times": [], "missing": []}
    beat_pitches = [b.pitches for b in note_beats]

    prior = _structure_prior(stem_path, [focus_alphatex])
    mono = _align_variant(stem_path, None, beat_pitches, note_beats, prior)
    left = _align_variant(stem_path, "left", beat_pitches, note_beats, prior)
    right = _align_variant(stem_path, "right", beat_pitches, note_beats, prior)
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
    trend = _pin_identity(anchors) if anchors else []
    bar_times = [round(_warp(bar_start.get(i, 0.0), trend), 4) for i in range(n_bars)]

    missing_groups = [g for ai, g in enumerate(chosen["groups"]) if ai not in chosen["matched"]]
    res = AlignResult([], [], anchors, missing_groups)
    return {
        "version": 1,
        "anchors": [[round(n, 4), round(a, 4)] for n, a in anchors],
        "bar_times": bar_times,
        "missing": _candidate_missing(focus_beats, res),
    }


def _candidate_missing(beats: list[Beat], res: AlignResult, *, min_amp: float = 0.6,
                      active_window: float = 0.5, dedup_window: float = 0.4) -> list[dict]:
    """Filter raw unmatched audio groups down to *high-precision* missing-note hints.

    The raw cross-check is noisy (basic-pitch artifacts, harmonics, bleed, alignment drift), so
    surfacing it raw wastes the user's time. We keep a group only if it is (a) loud (``min_amp``),
    (b) close (``active_window``) to a confidently-matched beat — i.e. in a reliably-aligned spot,
    not a drift region (the window is tight but small enough that the song-opening thumb note,
    whose first match is ~0.3s in, still survives), and (c) carries a pitch *new* to its bar (not
    at-or-above an octave of a note already there — a duplicate or upper harmonic; lower-octave
    bass is kept). Ringing repeats and same-bar octave harmonics are then collapsed (keep the
    lowest octave). Favours precision over recall: a few trustworthy flags, not a noisy list.
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

    raw: list[dict] = []
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
        if raw and g.time - last_t < dedup_window and novel[0] % 12 == last_pc:
            continue
        raw.append({"bar": bar, "midi": novel, "t": round(g.time, 3), "amp": round(g.amp, 2)})
        last_t, last_pc = g.time, novel[0] % 12

    # Per-bar octave dedup: drop a flagged pitch if a LOWER octave of the same pitch-class is also
    # flagged in that bar (it's the upper harmonic of the real, lower note).
    by_bar: dict[int, list[int]] = {}
    for c in raw:
        by_bar.setdefault(c["bar"], []).extend(c["midi"])
    out: list[dict] = []
    for c in raw:
        kept = [p for p in c["midi"]
                if not any((p - q) % 12 == 0 and q < p for q in by_bar[c["bar"]])]
        if kept:
            out.append({**c, "midi": kept})
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

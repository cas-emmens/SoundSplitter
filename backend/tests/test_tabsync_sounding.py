"""Sounding-frame matching: per-part pitch-shift detection + unheard-pitch filtering.

The Chain broke the sync two ways (Cas's diagnosis session, 2026-07-08): two of its
three Songsterr parts are notated in double-drop-D a whole step BELOW the recording
(every pitch match failed - measured +2 wins 4950 vs 2790 exact votes on the Dobro),
and Demucs separation loses pitches outright (D2 thumb strikes: zero events in the
guitar stem). Matching now happens in the frame the record sounds in.
"""

from app.tabsync import (
    Beat,
    NoteGroup,
    _absent_pitches,
    _detect_pitch_shift,
    _sounding_beats,
)

# A pitch set with no internal +-2 mapping (P and P+2 are disjoint), so the correct
# shift is decisively separable from coincidences — like real tonal material is
# (measured on The Chain: +2 beat 0 by 1.8-4x), unlike a uniform pitch cycle.
PITCHES = [50, 51, 55, 62, 68]


def _beats(n=40, step=2.0):
    return [
        Beat(index=i, bar=i // 4, pitches=[PITCHES[i % len(PITCHES)]],
             notated_time=i * step)
        for i in range(n)
    ]


def _groups(beats, shift=0):
    return [NoteGroup(time=b.notated_time, pitches={p + shift for p in b.pitches})
            for b in beats]


def test_detect_pitch_shift_finds_transposed_recording():
    beats = _beats()
    assert _detect_pitch_shift(_groups(beats, shift=2), beats) == 2
    assert _detect_pitch_shift(_groups(beats, shift=-1), beats) == -1


def test_detect_pitch_shift_keeps_correct_notation_at_zero():
    beats = _beats()
    assert _detect_pitch_shift(_groups(beats, shift=0), beats) == 0


def test_detect_pitch_shift_needs_decisive_evidence():
    # A handful of beats can't reach the absolute vote floor: stay in notation frame.
    beats = _beats(n=5)
    assert _detect_pitch_shift(_groups(beats, shift=2), beats) == 0


def test_absent_pitches_flags_separation_losses_only():
    beats = [Beat(index=i, bar=0, pitches=[38, 62], notated_time=i * 1.0) for i in range(10)]
    beats += [Beat(index=99, bar=9, pitches=[45], notated_time=99.0)]  # rare tab pitch
    groups = [NoteGroup(time=i * 1.0, pitches={62}) for i in range(10)]
    absent = _absent_pitches(groups, beats)
    assert 38 in absent          # used 10x, never heard -> separation loss
    assert 62 not in absent      # heard throughout
    assert 45 not in absent      # too rare in the tab to judge (< 6 uses)


def test_sounding_beats_shifts_and_drops_unheard():
    # Thumb-strike pattern on the low string: E2+E4 beats and pure-E2 beats (standard
    # tuning tex), recording +2 -> sounding F#2/F#4; the stem only ever heard F#4.
    tex = ".\n:4 " + " ".join(["(0.6 0.1)", "0.6", "(0.6 0.1)", "0.6"] * 4)
    audio = [NoteGroup(time=t * 0.75, pitches={66}) for t in range(16)]
    beats, nb = _sounding_beats(tex, 2, audio)
    assert nb, "the heard pitch must keep its beats matchable"
    assert all(b.pitches == [66] for b in nb)        # F#4 kept, F#2 dropped everywhere
    # Pure thumb-strike beats lost their only pitch -> unmatchable, ride the warp.
    assert len(nb) < len([b for b in beats if not b.is_rest])


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")

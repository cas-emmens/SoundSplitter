"""parse_beats must follow mid-song tempo changes, not just the header tempo."""

from app.tabsync import parse_beats

TEX = "\\tempo 60\n.\n:4 5.3 5.3 | \\tempo 120 :4 5.3 5.3 | 5.3"


def test_mid_song_tempo_change_shifts_notated_times():
    beats = parse_beats(TEX)
    times = [round(b.notated_time, 2) for b in beats]
    # 60 bpm quarters (1.0 s) for bar 1, then 120 bpm quarters (0.5 s) after the change.
    assert times == [0.0, 1.0, 2.0, 2.5, 3.0]
    assert [b.bar for b in beats] == [0, 0, 1, 1, 2]


def test_tempo_change_tokens_are_not_beats():
    beats = parse_beats(TEX)
    assert len(beats) == 5
    assert all(b.pitches == [60] for b in beats)  # 5.3 = G3 open + 5 = MIDI 60 on every beat

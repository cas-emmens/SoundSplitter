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


def test_bend_property_group_does_not_eat_the_bar():
    # {b (0 4)} used to fragment into tokens whose '(0' opened a phantom chord that
    # consumed everything (bar separators included) hunting for ')'.
    tex = ".\n:8 15.2{h}{b (0 4 0)} 13.2 | 14.3 | 12.3"
    beats = parse_beats(tex)
    assert [b.bar for b in beats] == [0, 0, 1, 2]
    assert [b.pitches for b in beats] == [[74], [72], [69], [67]]


def test_tied_and_dead_beats_keep_their_time():
    tex = ".\n:4 5.3 -.3 x.3 5.3"
    beats = parse_beats(tex)
    assert len(beats) == 4
    assert [b.is_rest for b in beats] == [False, True, True, False]
    assert [round(b.notated_time, 2) for b in beats] == [0.0, 0.5, 1.0, 1.5]  # 120bpm quarters


def test_dot_and_tuplet_groups_adjust_the_previous_beat():
    tex = ".\n:4 5.3 {d} 5.3 | :8 5.3{tu 3} 5.3{tu 3} 5.3{tu 3} 5.3"
    beats = parse_beats(tex)
    times = [b.notated_time for b in beats]
    # dotted quarter = 0.75s at 120bpm; triplet eighths = 1/6s each (0.25 * 2/3).
    assert times[0] == 0.0 and abs(times[1] - 0.75) < 1e-9
    third = 0.25 * 2 / 3
    assert abs((times[3] - times[2]) - third) < 1e-9
    assert abs((times[4] - times[3]) - third) < 1e-9


def test_chord_with_tied_members_keeps_real_pitches():
    tex = ".\n:8 (0.5 -.2 -.3) 8.5"
    beats = parse_beats(tex)
    assert len(beats) == 2
    assert beats[0].pitches == [45]  # the struck open A; tied strings match nothing
    assert not beats[0].is_rest


def test_strum_repeats_are_not_matchable():
    from app.tabsync import matchable_beats

    # Four identical quick chords (a strum run) then a different chord: only the run's
    # first strum and the new chord are matchable; single notes always are.
    tex = ".\n:16 (5.1 5.2 7.3) (5.1 5.2 7.3) (5.1 5.2 7.3) (5.1 5.2 7.3) :8 (8.1 8.2) 7.3"
    beats = parse_beats(tex)
    m = matchable_beats(beats)
    assert [b.index for b in m] == [0, 4, 5]

    # Slow repeats (clear attacks) stay matchable: gap above the strum threshold.
    tex2 = ".\n:2 (5.1 5.2 7.3) (5.1 5.2 7.3)"
    assert len(matchable_beats(parse_beats(tex2))) == 2

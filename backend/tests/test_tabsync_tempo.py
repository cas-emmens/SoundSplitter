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

    # Slow repeats stay matchable (they still shape the DTW path)…
    tex2 = ".\n:2 (5.1 5.2 7.3) (5.1 5.2 7.3)"
    assert len(matchable_beats(parse_beats(tex2))) == 2


def test_ambiguous_repeats_may_match_but_never_anchor():
    from app.tabsync import distinct_beat_ids, matchable_beats

    # Identical beats near each other could each explain the other's audio — neither may
    # anchor the warp; far enough apart they are distinguishable again.
    near = matchable_beats(parse_beats(".\n:2 (5.1 5.2 7.3) (5.1 5.2 7.3) :4 7.3"))
    ids = distinct_beat_ids(near)
    assert [id(b) in ids for b in near] == [False, False, True]
    far = matchable_beats(parse_beats("\\tempo 40\n.\n:2 (5.1 5.2 7.3) (5.1 5.2 7.3)"))
    assert len(distinct_beat_ids(far)) == 2  # 3s apart -> both may anchor


def test_glide_onsets_finds_one_full_bend():
    import numpy as np
    from app.tabsync import _glide_onsets

    hop = 0.0116
    # pluck at base (0c) for 20 frames, ramp to +200c over 10, hold 30 — a full bend.
    cents = np.array([0.0] * 20 + list(np.linspace(0, 200, 10)) + [200.0] * 30)
    onsets = _glide_onsets(cents, hop, 200.0, 0.4)
    assert len(onsets) == 1
    assert onsets[0] <= 20 * hop + 1e-9  # anchored at the pluck, not the ramp


def test_glide_onsets_rejects_vibrato_and_target_replucks():
    import numpy as np
    from app.tabsync import _glide_onsets

    hop = 0.0116
    wobble = 30 + 30 * np.sin(np.linspace(0, 20, 80))  # vibrato: never climbs near +130c
    assert _glide_onsets(wobble, hop, 200.0, 0.4) == []
    at_target = np.full(60, 200.0)  # already at the target: no near-base start
    assert _glide_onsets(at_target, hop, 200.0, 0.4) == []


def test_glide_onsets_reports_twin_bends_separately():
    import numpy as np
    from app.tabsync import _glide_onsets

    hop = 0.0116
    one = [0.0] * 12 + list(np.linspace(0, 200, 8)) + [200.0] * 15
    gap = [float("nan")] * 60  # ~0.7s apart
    cents = np.array(one + gap + one)
    assert len(_glide_onsets(cents, hop, 200.0, 0.15)) == 2


def test_merge_trusted_prefers_trusted_on_conflict():
    from app.tabsync import _merge_trusted

    trusted = [(10.0, 10.0), (20.0, 19.0)]
    others = [(9.0, 11.0), (15.0, 14.0), (21.0, 18.5)]
    merged = _merge_trusted(trusted, others)
    # (9, 11) breaks monotonicity against (10, 10); (21, 18.5) against (20, 19).
    assert merged == [(10.0, 10.0), (15.0, 14.0), (20.0, 19.0)]


def test_bend_probes_skip_short_and_small_bends():
    from app.tabsync import parse_beats, _bend_probes

    # full bend with ring time -> probed; 80ms lick bend and half-step bend -> skipped.
    tex = ".\n:2 15.1{b (0 4)} :32 15.1{b (0 4)} :2 15.1{b (0 2)}"
    probes = _bend_probes(parse_beats(tex))
    assert len(probes) == 1
    beat, base, rise, dur = probes[0]
    assert (base, rise) == (79, 2) and dur >= 0.15


def test_prune_glides_drops_contested_and_inconsistent_claims():
    from app.tabsync import _prune_glides

    # Two probes (same base pitch) claiming one audio glide: ownership ambiguous, both go.
    contested = [(10.0, 9.5, 74), (11.0, 9.6, 74), (20.0, 19.5, 79)]
    assert _prune_glides(contested) == [(20.0, 19.5)]

    # A wrong-occurrence match sits seconds off the trend its siblings agree on.
    cands = [(10.0, 9.2, 79), (12.0, 11.3, 74), (15.0, 10.5, 76), (20.0, 19.4, 81)]
    assert _prune_glides(cands) == [(10.0, 9.2), (12.0, 11.3), (20.0, 19.4)]


def test_bend_records_the_sounding_target_pitch():
    from app.tabsync import parse_beats as pb

    # 7 on string 3 bent a full step sounds as MIDI 55+7+2 = 64.
    beats = pb(".\n:8 7.3{h b (0 4 0)} 5.3")
    assert beats[0].pitches == [62]
    assert beats[0].alts == [64]
    assert beats[1].alts == []


def test_estimate_offset_finds_the_count_in_shift():
    from app.tabsync import NoteGroup, _estimate_offset, parse_beats

    # Distinct climbing beats every half second; the "recording" plays them all 7s late
    # (count-in), with a few coincidental early matches that must be outvoted.
    tex = ".\n:4 " + " ".join(f"{fret}.1" for fret in range(1, 13))
    beats = parse_beats(tex)
    groups = [NoteGroup(time=b.notated_time + 7.0, pitches=set(b.pitches)) for b in beats]
    groups += [NoteGroup(time=0.4, pitches={65}), NoteGroup(time=1.1, pitches={68})]
    groups.sort(key=lambda g: g.time)
    assert abs(_estimate_offset(groups, beats) - 7.0) < 0.5


def test_estimate_offset_zero_when_no_shift_or_no_evidence():
    from app.tabsync import NoteGroup, _estimate_offset, parse_beats

    tex = ".\n:4 " + " ".join(f"{fret}.1" for fret in range(1, 13))
    beats = parse_beats(tex)
    aligned = [NoteGroup(time=b.notated_time, pitches=set(b.pitches)) for b in beats]
    assert abs(_estimate_offset(aligned, beats)) < 0.5
    # Fewer than 8 exact matches: not enough evidence, stay on plain identity.
    assert _estimate_offset(aligned[:3], beats) == 0.0


def test_bar_dtw_discovers_structure_gaps():
    from app.tabsync import _bar_dtw

    # Tab bars A B C D E; audio plays A B [2 un-notated vamp bars] C D E.
    A, B, C, D, E = {40}, {45}, {50}, {55}, {60}
    vamp = {47}
    audio = [(float(i), p) for i, p in enumerate([A, B, vamp, vamp, C, D, E])]
    tab = [(float(j), p) for j, p in enumerate([A, B, C, D, E])]
    pairs = _bar_dtw(audio, tab)
    matched = {(ai, tj) for ai, tj, c in pairs if c == 0.0}
    assert {(0, 0), (1, 1), (4, 2), (5, 3), (6, 4)} <= matched


def test_bar_dtw_free_lead_skips_uncovered_intro():
    from app.tabsync import _bar_dtw

    # Tab has a 3-bar intro the (drum-covered) audio never saw; free_lead skips it
    # without pricing, so the map starts cleanly at the covered material.
    intro, X, Y, Z = {30}, {50}, {55}, {60}
    audio = [(0.0, X), (1.0, Y), (2.0, Z)]
    tab = [(float(j), p) for j, p in enumerate([intro, intro, intro, X, Y, Z])]
    pairs = _bar_dtw(audio, tab, free_lead=3)
    exact = {(ai, tj) for ai, tj, c in pairs if c == 0.0}
    assert exact == {(0, 3), (1, 4), (2, 5)}

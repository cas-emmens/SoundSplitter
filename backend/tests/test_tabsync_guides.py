"""Guided re-sync: manual timing-editor anchors steering the automatic alignment."""

from app.tabsync import _fits_between, _merge_guides, apply_manual

TEX = ".\n:4 5.3 5.3 5.3 5.3 | 5.3 5.3 5.3 5.3"


def test_fits_between_rejects_crossing_pairs():
    truth = [(10.0, 12.0), (20.0, 24.0)]
    assert _fits_between((15.0, 18.0), truth)          # inside, monotonic
    assert not _fits_between((15.0, 11.0), truth)      # before the left truth's audio
    assert not _fits_between((15.0, 25.0), truth)      # past the right truth's audio
    assert not _fits_between((5.0, 13.0), truth)       # would cross truth[0] from the left
    assert _fits_between((5.0, 6.0), truth)
    assert _fits_between((25.0, 30.0), truth)


def test_merge_guides_without_grid_prior_returns_guides():
    guides = [(0.0, 5.0), (60.0, 66.0)]
    assert _merge_guides(None, guides) == guides
    assert _merge_guides([(0.0, 0.0), (2.0, 2.0)], None) == [(0.0, 0.0), (2.0, 2.0)]


def test_merge_guides_drops_disagreeing_prior_inside_coverage():
    # Grid prior at identity (2s bars); the user's ear says everything is +6s.
    prior = [(float(n), float(n)) for n in range(0, 40, 2)]
    guides = [(10.0, 16.0), (30.0, 36.0)]
    merged = _merge_guides(prior, guides)
    assert all(g in merged for g in guides)
    # Inside guide coverage the identity pairs disagree by ~6s (> a bar) -> dropped.
    assert not [p for p in merged if 10.0 <= p[0] <= 30.0 and p not in guides]
    # Far outside coverage the grid keeps its say (subject to monotonicity)...
    assert (0.0, 0.0) in merged
    # ...but pairs that would cross a guide are gone: (8,8) fits (8 < 16), kept.
    audio = [a for _, a in merged]
    assert audio == sorted(audio)


def test_merge_guides_evicts_prior_pairs_that_would_cross():
    prior = [(0.0, 30.0), (10.0, 40.0)]     # grid thinks the song starts at +30s
    guides = [(12.0, 14.0)]                 # the ear says bar ~6 is at 14s
    merged = _merge_guides(prior, guides)
    assert guides[0] in merged
    assert merged == sorted(merged) and all(
        b[1] > a[1] for a, b in zip(merged, merged[1:])
    )


def test_apply_manual_wins_over_crossing_engine_anchors():
    # Engine put this whole stretch ~20s late; the hand fix crosses its anchors.
    timing = {
        "version": 1,
        "anchors": [[4.0, 24.0], [8.0, 28.0], [12.0, 32.0]],
        "missing": [],
    }
    fixed = apply_manual(timing, [[8.0, 9.0]], TEX)
    assert [8.0, 9.0] in fixed["anchors"]
    # The engine anchor at the same notated spot AND the earlier one it would cross
    # (4.0 -> 24.0 with audio >= 9.0) are evicted; the later one (12 -> 32) stays.
    assert [4.0, 24.0] not in fixed["anchors"]
    assert [12.0, 32.0] in fixed["anchors"]
    assert fixed["manual"] == [[8.0, 9.0]]
    audio = [a for _, a in fixed["anchors"]]
    assert audio == sorted(audio)


def test_apply_manual_keeps_agreeing_engine_anchors():
    timing = {
        "version": 1,
        "anchors": [[0.0, 0.5], [4.0, 4.6], [8.0, 8.7]],
        "missing": [],
    }
    fixed = apply_manual(timing, [[6.0, 6.65]], TEX)
    assert [[0.0, 0.5], [4.0, 4.6], [6.0, 6.65], [8.0, 8.7]] == fixed["anchors"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")

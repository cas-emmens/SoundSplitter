"""Derive the recording's own measure grid from the drum stem.

The tab's notated timeline is a guess about the recording (tempo marks, structure); the
drums ARE the recording's clock. A drum groove repeats per measure (or per two measures),
so the onset-strength envelope's autocorrelation peaks at the pattern period — tracked in
windows it yields the true local tempo curve, and integrating it yields audio bar
boundaries. Alignment can then map notated bars onto measured audio bars (whole-bar
structure differences become countable) instead of trusting the tab's timeline.

Findings that shaped this (2026-07-03 spikes, Stairway + It Runs Through Me):
- Raw window periods lock to the truth within ~0.1 bpm where the groove is steady, but
  autocorrelation alone cannot decide what a "bar" is: both test grooves also repeat at
  3-beat hemiola sub-periods, and argmax / comb scoring locked whole songs onto them.
  The accepted peak must sit near an EXPECTED bar duration — from the tab's own local
  tempo when available (locally accurate even when song structure differs), else from
  librosa's beat tracker (whose global tempo prior mistracks tempo-ramping songs).
- Gate drum activity on a ~1s moving max of RMS: the silence BETWEEN hits of a steady
  groove makes per-frame gates see it as half-silent.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field

SR = 22050
HOP = 512
_WIN_S = 12.0          # analysis window: a few bars of groove
_STEP_S = 3.0
_MIN_BAR_S, _MAX_BAR_S = 1.2, 6.0   # 40-200 bpm 4/4
_PEAK_TOL = 0.12       # accept a peak within 12% of k x expected bar
_FOLD_TOL = 0.06       # post-hoc trend smoothing tolerance
_EMA = 0.25


@dataclass
class DrumGrid:
    """The measured measure grid of a recording (empty when the song has no usable drums)."""

    boundaries: list[float] = field(default_factory=list)  # bar start times, drum sections only
    sections: list[tuple[float, float]] = field(default_factory=list)  # (t0, t1) drum activity
    periods: list[tuple[float, float]] = field(default_factory=list)   # (time, bar duration)

    def bar_at(self, t: float) -> float | None:
        """Local measured bar duration near time ``t`` (None outside coverage)."""
        if not self.periods:
            return None
        best = min(self.periods, key=lambda tp: abs(tp[0] - t))
        return best[1] if abs(best[0] - t) <= _WIN_S else None


def _activity(y, sr):
    import librosa
    import numpy as np
    from scipy.ndimage import maximum_filter1d

    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=HOP)[0]
    smoothed = maximum_filter1d(rms, size=int(1.0 * sr / HOP))
    return smoothed > 0.05 * np.percentile(rms, 99)


def _beat_expected(beats, beats_per_bar: int) -> Callable[[float], float | None]:
    """Fallback expected-bar prior from the beat tracker's local inter-beat interval."""
    import numpy as np

    def expected(t: float) -> float | None:
        local = beats[(beats >= t - _WIN_S / 2) & (beats <= t + _WIN_S / 2)]
        if len(local) < beats_per_bar + 1:
            return None
        return float(np.median(np.diff(local))) * beats_per_bar

    return expected


def _window_periods(env, active, frame_t, expected) -> list[tuple[float, float]]:
    """Raw (window centre time, bar duration) for windows of sustained drumming.

    The accepted autocorrelation peak is the strongest local max within ±12% of
    k x expected(t) for k in (1, 2) — grooves often span two notated bars — and the
    returned duration is peak/k, i.e. normalized to ONE bar.
    """
    import librosa
    import numpy as np

    win, step = int(_WIN_S / frame_t), int(_STEP_S / frame_t)
    lo, hi = int(_MIN_BAR_S / frame_t), int(2 * _MAX_BAR_S / frame_t)
    rows: list[tuple[float, float]] = []
    for start in range(0, max(0, len(env) - win), step):
        if active[start:start + win].mean() < 0.8:
            continue
        centre = (start + win / 2) * frame_t
        e = expected(centre)
        if not e or not (_MIN_BAR_S <= e <= _MAX_BAR_S):
            continue
        seg = env[start:start + win].astype(float)
        seg -= seg.mean()
        ac = librosa.autocorrelate(seg)
        ac[:max(lo, 1)] = 0
        ac[min(hi, len(ac) - 1):] = 0

        best: tuple[float, int] | None = None  # (ac value, lag) at the chosen k
        best_k = 1
        for k in (1, 2):
            target = k * e / frame_t
            span = int(_PEAK_TOL * target)
            lo_k, hi_k = int(target) - span, int(target) + span + 1
            for lag in range(max(lo_k, 1), min(hi_k, len(ac) - 1)):
                if ac[lag] > 0 and ac[lag] >= ac[lag - 1] and ac[lag] >= ac[lag + 1]:
                    if best is None or ac[lag] > best[0]:
                        best = (ac[lag], lag)
                        best_k = k
        if best is None:
            continue
        lag = best[1]
        if 1 <= lag < len(ac) - 1:  # parabolic peak refinement
            a, b, c = ac[lag - 1], ac[lag], ac[lag + 1]
            if (denom := a - 2 * b + c) != 0:
                lag += 0.5 * (a - c) / denom
        rows.append((centre, lag * frame_t / best_k))
    return rows


def _fold(rows: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Smooth the bar-duration curve: reject windows off the local trend (fills)."""
    import numpy as np

    if not rows:
        return []
    trend = float(np.median([p for _, p in rows]))
    out: list[tuple[float, float]] = []
    for t, p in rows:
        if abs(p - trend) / trend > 3 * _FOLD_TOL:
            continue
        trend = (1 - _EMA) * trend + _EMA * p
        out.append((t, p))
    return out


def _phase(env, frame_t, t0: float, t1: float, period: float) -> float:
    """Downbeat offset in [0, period) for one drum section: the phase where the folded
    onset energy peaks (grooves hit hardest on the one)."""
    import numpy as np

    lo, hi = int(t0 / frame_t), min(int(t1 / frame_t), len(env))
    steps = 64
    scores = np.zeros(steps)
    times = (np.arange(lo, hi) * frame_t) % period
    idx = np.minimum((times / period * steps).astype(int), steps - 1)
    np.add.at(scores, idx, env[lo:hi])
    return (int(np.argmax(scores)) + 0.5) / steps * period


def _prior_signature(expected, duration: float) -> list:
    return [round(expected(t) or 0.0, 3) for t in range(0, int(duration), 15)]


def compute_grid(
    drums_path: str,
    expected_bar: Callable[[float], float | None] | None = None,
    beats_per_bar: int = 4,
) -> DrumGrid:
    """Measure the bar grid of ``drums_path``.

    ``expected_bar`` maps audio time -> expected bar duration (seconds); pass the tab's
    local tempo when aligning (see module docstring). Cached next to the stem, keyed on
    the prior so a different tab re-measures.
    """
    import librosa

    y, sr = librosa.load(drums_path, sr=SR, mono=True)
    duration = len(y) / sr
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP)
    frame_t = HOP / sr

    if expected_bar is None:
        _, beat_frames = librosa.beat.beat_track(onset_envelope=env, sr=sr, hop_length=HOP)
        beats = librosa.frames_to_time(beat_frames, sr=sr, hop_length=HOP)
        expected_bar = _beat_expected(beats, beats_per_bar)

    sig = _prior_signature(expected_bar, duration)
    cache = drums_path + ".drumgrid.json"
    if os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(drums_path):
        data = json.load(open(cache, encoding="utf-8"))
        if data.get("prior_sig") == sig:
            return DrumGrid(
                boundaries=data["boundaries"],
                sections=[tuple(s) for s in data["sections"]],
                periods=[tuple(p) for p in data["periods"]],
            )

    active = _activity(y, sr)
    periods = _fold(_window_periods(env, active, frame_t, expected_bar))

    grid = DrumGrid(periods=periods)
    if periods:
        # Split measured coverage into sections wherever consecutive windows are far apart.
        section: list[tuple[float, float]] = [periods[0]]
        sections: list[list[tuple[float, float]]] = [section]
        for prev, cur in zip(periods, periods[1:]):
            if cur[0] - prev[0] > _WIN_S:
                section = []
                sections.append(section)
            section.append(cur)
        for sec in sections:
            t0 = sec[0][0] - _WIN_S / 2
            t1 = sec[-1][0] + _WIN_S / 2
            grid.sections.append((t0, t1))
            # Integrate bar boundaries through the section at the local bar duration,
            # phase-anchored on the section's strongest folded onset position.
            local = lambda t: min(sec, key=lambda tp: abs(tp[0] - t))[1]  # noqa: E731
            phase = _phase(env, frame_t, t0, t1, local(t0))
            t = t0 + phase
            while t < t1:
                grid.boundaries.append(round(t, 4))
                t += local(t)

    json.dump(
        {"prior_sig": sig, "boundaries": grid.boundaries,
         "sections": grid.sections, "periods": grid.periods},
        open(cache, "w", encoding="utf-8"),
    )
    return grid


def sibling_drum_stem(stem_path: str) -> str | None:
    """The drums stem next to another stem of the same song (separator layout)."""
    cand = os.path.join(os.path.dirname(stem_path), "drums.flac")
    return cand if os.path.exists(cand) and os.path.abspath(cand) != os.path.abspath(stem_path) else None

"""POC #3: split the guitar stem into lead (monophonic melody) + rhythm (the rest),
via pyin f0 tracking + a harmonic soft-mask on the spectrogram (the approach parked in
memory). Writes guitar_lead.flac / guitar_rhythm.flac next to the source stem so the
transcription POCs can target them by name.

Idea: track the dominant f0 (pyin). For each frame, pass the f0 + its harmonics through
to LEAD via a soft Gaussian mask in log-frequency; the residual (1-mask) is RHYTHM.
Monophonic lead vs polyphonic rhythm is exactly the favorable case for "It Runs Through Me".

Runs in the 3.13 backend venv (librosa + soundfile already installed):
    .venv\\Scripts\\python poc_split_guitar.py <track_id> [--stem guitar] [--harmonics 8] [--width 0.4]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

LIBRARY_DIR = Path(__file__).resolve().parent / "data" / "library"
SR = 22050
N_FFT = 2048
HOP = 512


def split(y: np.ndarray, sr: int, n_harm: int, width_semitones: float,
          power: float = 1.0, vprob_gate: float = 0.0, smooth: bool = False
          ) -> tuple[np.ndarray, np.ndarray]:
    S = librosa.stft(y, n_fft=N_FFT, hop_length=HOP)
    mag, phase = np.abs(S), np.angle(S)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=N_FFT)[:, None]  # (bins, 1)

    f0, voiced, vprob = librosa.pyin(
        y, sr=sr, hop_length=HOP,
        fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C7"))
    # align f0 frames to STFT frames (both use center padding -> same count)
    nf = min(f0.shape[0], mag.shape[1])
    f0, voiced, vprob = f0[:nf], voiced[:nf], np.nan_to_num(vprob[:nf])
    mag, phase = mag[:, :nf], phase[:, :nf]

    lead_mask = np.zeros_like(mag)
    voiced_idx = np.where(voiced & ~np.isnan(f0))[0]
    for t in voiced_idx:
        col = np.zeros((freqs.shape[0],))
        for k in range(1, n_harm + 1):
            fh = k * f0[t]
            if fh >= sr / 2:
                break
            dsemi = 12.0 * np.log2((freqs[:, 0] + 1e-9) / fh)
            col = np.maximum(col, np.exp(-0.5 * (dsemi / width_semitones) ** 2))
        lead_mask[:, t] = col

    # Sharpen toward 1 (power<1) so harmonic bins are captured more completely -> less
    # lead energy bleeds into the rhythm residual. Gate out very low-confidence frames
    # entirely (they tend to be rhythm misread as a weak pitch), but don't *scale* by
    # confidence on kept frames (that just weakens lead capture; verified worse).
    if vprob_gate > 0.0:
        lead_mask[:, vprob < vprob_gate] = 0.0
    if power != 1.0:
        lead_mask = np.power(lead_mask, power)
    if smooth:
        # time-smooth the mask to suppress musical-noise flicker between frames
        from scipy.ndimage import median_filter
        lead_mask = median_filter(lead_mask, size=(1, 3))

    lead_S = mag * lead_mask * np.exp(1j * phase)
    rhythm_S = mag * (1.0 - lead_mask) * np.exp(1j * phase)
    lead = librosa.istft(lead_S, hop_length=HOP, length=len(y))
    rhythm = librosa.istft(rhythm_S, hop_length=HOP, length=len(y))
    return lead.astype(np.float32), rhythm.astype(np.float32)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("track_id")
    ap.add_argument("--stem", default="guitar")
    ap.add_argument("--harmonics", type=int, default=8)
    ap.add_argument("--width", type=float, default=0.4, help="harmonic band width (semitones)")
    # Experimental knobs, default to no-ops (the plain soft mask). Sweep these by EAR on
    # the output FLACs — note count is not a reliable bleed metric (see session notes).
    ap.add_argument("--power", type=float, default=1.0, help="mask sharpening (<1 = more inclusive)")
    ap.add_argument("--vprob-gate", type=float, default=0.0, dest="vprob_gate",
                    help="drop frames with pitch confidence below this")
    ap.add_argument("--smooth", action="store_true", help="median-smooth the mask over time")
    args = ap.parse_args()

    src = LIBRARY_DIR / args.track_id / f"{args.stem}.flac"
    if not src.exists():
        raise SystemExit(f"no such stem: {src}")

    print(f"Loading {src.name} ...")
    y, sr = librosa.load(str(src), sr=SR, mono=True)
    print(f"  {len(y)/sr:.1f}s | tracking f0 + masking ({args.harmonics} harmonics, "
          f"{args.width} semitone band) ...")
    lead, rhythm = split(y, sr, args.harmonics, args.width, args.power,
                         args.vprob_gate, args.smooth)

    out_dir = src.parent
    for name, data in (("guitar_lead", lead), ("guitar_rhythm", rhythm)):
        path = out_dir / f"{name}.flac"
        sf.write(str(path), data, sr, format="FLAC")
        rms = float(np.sqrt(np.mean(data ** 2)))
        print(f"  wrote {path.name:18s} rms={rms:.4f}")
    print("\nNow transcribe them, e.g.:")
    print(f"  pyin  lead   : .venv\\Scripts\\python poc_transcribe.py {args.track_id} guitar_lead --instrument guitar")
    print(f"  bp    rhythm : .venv311-poc\\Scripts\\python poc_transcribe_bp.py {args.track_id} guitar_rhythm --instrument guitar")


if __name__ == "__main__":
    main()

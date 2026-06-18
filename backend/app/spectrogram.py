"""STFT spectrogram rendering (the visible 'Fourier' view). Stretch feature."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from . import config, encoder


def render_spectrogram(audio_path: str | Path, png_path: str | Path,
                       n_fft: int = 2048, hop: int = 512) -> None:
    """Render a log-frequency dB spectrogram PNG from an audio file."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    data, sr = encoder.load_audio(audio_path, target_sr=config.SAMPLE_RATE, stereo=False)
    mono = data.mean(axis=1)

    window = np.hanning(n_fft).astype(np.float32)
    n_frames = 1 + max(0, (len(mono) - n_fft) // hop)
    if n_frames < 1:
        return
    stft = np.empty((n_fft // 2 + 1, n_frames), dtype=np.float32)
    for i in range(n_frames):
        frame = mono[i * hop: i * hop + n_fft] * window
        stft[:, i] = np.abs(np.fft.rfft(frame))
    db = 20.0 * np.log10(stft + 1e-6)

    Path(png_path).parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.imshow(db, origin="lower", aspect="auto", cmap="magma",
              extent=[0, len(mono) / sr, 0, sr / 2])
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Frequency (Hz)")
    ax.set_yscale("symlog")
    fig.tight_layout()
    fig.savefig(png_path, dpi=90)
    plt.close(fig)

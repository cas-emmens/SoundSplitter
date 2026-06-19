"""Audio loading and FLAC encoding helpers."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from . import config


def load_audio(path: str | Path, target_sr: int | None = config.SAMPLE_RATE,
               stereo: bool = True) -> tuple[np.ndarray, int]:
    """Load any audio file to float32 [samples, channels].

    Tries soundfile (wav/flac/ogg and, with recent libsndfile, mp3); falls back to
    torchaudio (ffmpeg backend) for anything else. Optionally resamples to target_sr.
    """
    try:
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception:
        import torch  # local import; heavy
        import torchaudio
        wav, sr = torchaudio.load(str(path))           # [channels, samples]
        data = wav.numpy().T.astype(np.float32)        # [samples, channels]

    if stereo:
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        elif data.shape[1] > 2:
            data = data[:, :2]

    if target_sr is not None and sr != target_sr:
        import torch
        import torchaudio
        t = torch.from_numpy(data.T)                   # [channels, samples]
        t = torchaudio.functional.resample(t, sr, target_sr)
        data = t.numpy().T.astype(np.float32)
        sr = target_sr

    return data, sr


def write_flac(path: str | Path, data: np.ndarray, sr: int = config.SAMPLE_RATE) -> None:
    """Write float32 [samples, channels] (or [channels, samples]) to FLAC."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    arr = np.asarray(data, dtype=np.float32)
    # Normalize to [samples, channels]
    if arr.ndim == 1:
        arr = arr[:, None]
    elif arr.ndim == 2 and arr.shape[0] in (1, 2) and arr.shape[0] < arr.shape[1]:
        arr = arr.T
    np.clip(arr, -1.0, 1.0, out=arr)
    sf.write(str(path), arr, sr, format="FLAC")


def write_wav(path: str | Path, data: np.ndarray, sr: int = config.SAMPLE_RATE,
              subtype: str = "PCM_24") -> None:
    """Write float32 [samples, channels] (or [channels, samples]) to WAV.

    24-bit PCM by default — universally importable into any DAW.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr[:, None]
    elif arr.ndim == 2 and arr.shape[0] in (1, 2) and arr.shape[0] < arr.shape[1]:
        arr = arr.T
    np.clip(arr, -1.0, 1.0, out=arr)
    sf.write(str(path), arr, sr, subtype=subtype)

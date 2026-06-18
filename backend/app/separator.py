"""Offline 6-stem separation with Demucs htdemucs_6s (loaded once, on GPU if available)."""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import torch

from . import config, encoder

_model = None
_device = None
_load_lock = threading.Lock()
# Serialize GPU work: one separation at a time.
_gpu_lock = threading.Lock()


def _get_model():
    global _model, _device
    if _model is None:
        with _load_lock:
            if _model is None:
                from demucs.pretrained import get_model
                _device = "cuda" if torch.cuda.is_available() else "cpu"
                m = get_model(config.MODEL_NAME)
                m.to(_device).eval()
                _model = m
    return _model, _device


def device_info() -> dict:
    cuda = torch.cuda.is_available()
    return {
        "device": "cuda" if cuda else "cpu",
        "gpu": torch.cuda.get_device_name(0) if cuda else None,
        "model": config.MODEL_NAME,
        "stems": config.MODEL_STEMS,
    }


def separate(input_path: str | Path) -> dict[str, np.ndarray]:
    """Separate a file into stems. Returns {stem_name: float32 [samples, channels]}."""
    from demucs.apply import apply_model

    model, device = _get_model()
    data, _sr = encoder.load_audio(input_path, target_sr=model.samplerate, stereo=True)
    wav = torch.from_numpy(data.T)  # [channels, samples]

    ref = wav.mean(0)
    wav = (wav - ref.mean()) / (ref.std() + 1e-8)

    with _gpu_lock:
        with torch.no_grad():
            sources = apply_model(model, wav[None], device=device, progress=False)[0]
    sources = sources * ref.std() + ref.mean()  # [n_sources, channels, samples]

    out: dict[str, np.ndarray] = {}
    for name, src in zip(model.sources, sources):
        out[name] = src.cpu().numpy().T.astype(np.float32)  # [samples, channels]
    return out

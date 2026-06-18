"""
GATE smoke test: confirm demucs htdemucs_6s installs, loads on CUDA, and produces
6 stems. Usage:
    python smoke_separate.py [path/to/audio]   # optional real track; else synthesizes
Writes stems to ./smoke_out/.
"""
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import torchaudio


def make_test_clip(path: Path, sr: int = 44100, secs: float = 6.0) -> None:
    """Synthesize a crude multi-instrument stereo mix so the pipeline has something real-ish."""
    t = np.linspace(0, secs, int(sr * secs), endpoint=False)
    bass = 0.30 * np.sin(2 * np.pi * 80 * t)
    chord = 0.20 * (np.sin(2 * np.pi * 220 * t) + np.sin(2 * np.pi * 330 * t))
    lead = 0.15 * np.sin(2 * np.pi * 880 * t)
    hits = (np.sin(2 * np.pi * 2 * t) > 0.9).astype(np.float32)
    drums = 0.10 * np.random.randn(len(t)).astype(np.float32) * hits
    mix = (bass + chord + lead + drums).astype(np.float32)
    stereo = np.stack([mix, mix], axis=1)
    sf.write(str(path), stereo, sr)


def main() -> int:
    out = Path("smoke_out")
    out.mkdir(exist_ok=True)

    print("torch:", torch.__version__)
    cuda = torch.cuda.is_available()
    print("CUDA available:", cuda, "-", torch.cuda.get_device_name(0) if cuda else "CPU only")
    device = "cuda" if cuda else "cpu"

    if len(sys.argv) > 1:
        inp = Path(sys.argv[1])
        print("input:", inp)
    else:
        inp = out / "test_mix.wav"
        print("no input given; synthesizing", inp)
        make_test_clip(inp)

    # Import here so torch/CUDA prints happen even if demucs import fails.
    from demucs.pretrained import get_model
    from demucs.apply import apply_model

    print("loading htdemucs_6s ...")
    model = get_model("htdemucs_6s")
    model.to(device).eval()
    print("sources:", model.sources, "| samplerate:", model.samplerate, "| channels:", model.audio_channels)

    # Read audio via soundfile (no ffmpeg dependency) -> torch [channels, samples].
    data, sr = sf.read(str(inp), dtype="float32", always_2d=True)  # [samples, channels]
    wav = torch.from_numpy(data.T)  # [channels, samples]
    if wav.shape[0] == 1:
        wav = wav.repeat(model.audio_channels, 1)
    if sr != model.samplerate:
        wav = torchaudio.functional.resample(wav, sr, model.samplerate)

    ref = wav.mean(0)
    wav = (wav - ref.mean()) / (ref.std() + 1e-8)

    t0 = time.time()
    with torch.no_grad():
        sources = apply_model(model, wav[None], device=device, progress=True)[0]
    dt = time.time() - t0
    sources = sources * ref.std() + ref.mean()  # [n_sources, channels, samples]
    print(f"separation took {dt:.2f}s on {device}")

    for name, source in zip(model.sources, sources):
        out_data = source.cpu().numpy().T  # [samples, channels]
        sf.write(str(out / f"{name}.flac"), out_data, model.samplerate)
        print(f"  wrote {name}.flac  shape={tuple(source.shape)}")

    print("\nGATE PASSED: 6-stem separation works on", device)
    print("stems:", list(model.sources))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Seed one separated demo song so the player UI is usable before VB-CABLE/Spotify setup."""
import numpy as np

from app import config, db, encoder, jobs

TID = "demo-synthetic-0001"


def synth(secs=20, sr=config.SAMPLE_RATE):
    t = np.linspace(0, secs, int(sr * secs), endpoint=False)
    bass = 0.30 * np.sin(2 * np.pi * (55 * (1 + 0.0)) * t)
    chord = 0.18 * (np.sin(2 * np.pi * 220 * t) + np.sin(2 * np.pi * 277 * t) + np.sin(2 * np.pi * 330 * t))
    lead = 0.14 * np.sin(2 * np.pi * (660 + 40 * np.sin(2 * np.pi * 0.5 * t)) * t)
    hits = (np.sin(2 * np.pi * 2 * t) > 0.92).astype(np.float32)
    drums = 0.12 * np.random.randn(len(t)).astype(np.float32) * hits
    mix = (bass + chord + lead + drums).astype(np.float32)
    return np.stack([mix, mix], axis=1)


def main():
    db.init_db()
    out_dir = config.LIBRARY_DIR / TID
    out_dir.mkdir(parents=True, exist_ok=True)
    original = out_dir / "original.flac"
    encoder.write_flac(original, synth(), config.SAMPLE_RATE)

    db.upsert_song(TID, "Demo (synthetic)", "sound-splitter", "Built-in", "", 20000, "queued")
    db.set_original_path(TID, str(original))
    print("separating demo...")
    jobs._process(TID)
    print("done:", [s["name"] for s in db.get_stems(TID)])


if __name__ == "__main__":
    main()

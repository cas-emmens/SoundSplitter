"""Offline test of separate -> store -> library -> import, no Spotify/VB-CABLE needed."""
import shutil
from pathlib import Path

from app import config, db, jobs, library

TID = "TESTTRACK0001"


def main() -> int:
    db.init_db()
    src = Path("smoke_out/test_mix.wav")
    assert src.exists(), "run smoke_separate.py first to create smoke_out/test_mix.wav"

    out_dir = config.LIBRARY_DIR / TID
    out_dir.mkdir(parents=True, exist_ok=True)
    original = out_dir / "original.flac"
    from app import encoder
    data, _ = encoder.load_audio(src)
    encoder.write_flac(original, data)

    db.upsert_song(TID, "Test Song", "Test Artist", "Test Album", "", 6000, "queued")
    db.set_original_path(TID, str(original))

    print("separating (this calls demucs on GPU)...")
    jobs._process(TID)  # synchronous, no worker thread

    detail = library.song_detail(TID)
    print("status:", detail["status"])
    model_stems = [s["name"] for s in detail["stems"] if s["kind"] == "model"]
    print("model stems:", sorted(model_stems))
    assert detail["status"] == "done"
    assert sorted(model_stems) == sorted(config.MODEL_STEMS)
    for s in detail["stems"]:
        assert Path(s["path"]).exists(), f"missing {s['path']}"

    # Import a user stem (reuse the test mix as a fake "take").
    stem = library.import_user_stem(TID, src, "My guitar take", offset_ms=120)
    print("imported user stem:", stem["name"], "offset_ms=", stem["offset_ms"])
    detail = library.song_detail(TID)
    assert any(s["kind"] == "user" for s in detail["stems"])

    print("library list:", [(s["title"], s["status"], s["stem_count"])
                            for s in library.list_songs()])

    # cleanup
    shutil.rmtree(out_dir, ignore_errors=True)
    with db.get_conn() as conn:
        conn.execute("DELETE FROM songs WHERE track_id=?", (TID,))
        conn.execute("DELETE FROM stems WHERE track_id=?", (TID,))
    print("\nPIPELINE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Releasing the self-contained installer

This builds the **fully bundled** Windows installer (`SoundSplitter-Setup-<version>.exe`) — a
relocatable Python runtime + all wheels + CPU PyTorch + pre-downloaded Demucs weights +
Playwright Chromium + Tesseract + ffmpeg + the prebuilt Angular UI. The target PC needs **no**
Python, Node, winget, or internet.

## Why Inno Setup (not Tauri's NSIS bundler)

The payload is ~2.5 GB. NSIS (and WiX) store install-data offsets in 32-bit fields, so they hard
cap installers at ~2 GB — a 64-bit makensis doesn't help (it's a *format* limit). **Inno Setup**
uses 64-bit LZMA2 and packs the whole payload into a single ~630 MB `.exe` with no size issue.

Because Inno isn't NSIS/MSI, Tauri's updater plugin can't drive it, so the app ships a **custom
auto-updater** in the Rust shell (`src-tauri/src/lib.rs`): on launch it fetches `latest.json`,
compares the version, and if newer downloads this installer, **verifies a minisign signature
against a public key embedded in the binary**, then runs it silently and relaunches.

## One-time: generate the updater signing key

```powershell
cargo tauri signer generate -w $env:USERPROFILE\.tauri\soundsplitter.key
```

This prints a **public key** and writes a password-protected **private key**. Then:

1. Put the **public key** (the base64 `dW50cnVzdGVk…` value, i.e. base64 of the `.pub` file) into
   `UPDATE_PUBKEY_B64` in `src-tauri/src/lib.rs` (commit this — it's public). It's already set to
   the current key; only change it if you rotate keys.
2. Keep the **private key** out of the repo (`.gitignore` excludes `*.key` / `.tauri/`).

## Each release

1. **Bump the version** in **both** `src-tauri/Cargo.toml` and `src-tauri/tauri.conf.json`
   (keep them in sync — the running app compares `latest.json`'s version against its own
   `CARGO_PKG_VERSION`). The update only fires when `latest.json` is **higher**.

2. **Set the signing key env vars and build:**
   ```powershell
   $env:TAURI_SIGNING_PRIVATE_KEY = Get-Content $env:USERPROFILE\.tauri\soundsplitter.key -Raw
   $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = "<the password you chose>"
   .\build-installer.ps1          # add -Fresh to rebuild the Python runtime from scratch
   ```
   This stages the payload, builds the shell, compiles the Inno installer, signs it, and writes:
   - `dist\SoundSplitter-Setup-<version>.exe`  (the installer, ~630 MB)
   - `dist\SoundSplitter-Setup-<version>.exe.sig`  (its minisign signature)
   - `dist\latest.json`  (already filled in with the version, signature, and download URL)

   Without the signing env vars the installer still builds (unsigned) for local testing, but the
   auto-updater will reject unsigned updates.

3. **Publish a GitHub Release** tagged `v<version>` and upload:
   - `SoundSplitter-Setup-<version>.exe`, and
   - `latest.json`.

   The shell's update endpoint is
   `https://github.com/cas-emmens/SoundSplitter/releases/latest/download/latest.json`, so the
   release tagged **latest** must carry `latest.json`. On launch the app checks it, and if a newer
   signed version exists, downloads -> verifies -> installs -> relaunches.

   GitHub Releases allows assets up to 2 GiB; the ~630 MB installer fits with room to spare.

## What still can't be bundled (the friend does these once)

- **VB-CABLE** - kernel audio driver: install as admin + reboot, set Spotify's output to
  *CABLE Input*. Needed for capture.
- **Spotify Developer credentials** - create a free dev app and paste Client ID/Secret into
  `%APPDATA%\SoundSplitter\.env` (the app seeds this file from the example on first run and shows
  the path on the loading screen). Capture is inert until this is filled.

## Notes

- Writable state (library, SQLite DB, Spotify token, `.env`) lives in `%APPDATA%\SoundSplitter\`,
  outside the install dir, so in-place upgrades don't wipe it.
- Separation uses **CPU** torch (portable), so it takes a few minutes per song on the target.
- The installer is per-user (`{localappdata}\Programs\SoundSplitter`, no admin).
- Each update re-downloads the full installer (~630 MB). Fine for occasional releases.
- The signature round-trip is covered by a `cargo test` (`signature_roundtrip`) that runs against
  the freshly signed installer in `dist\`.

# sound-splitter

Capture a song from Spotify, split it into **6 instrument stems** (vocals / drums / bass /
**guitar** / **piano** / other) offline with Demucs, and play them back in a live stem mixer —
mute **vocals + guitar** for a one-tap practice backing track, generate guitar tabs, and import
your own recorded takes as extra stems.

> Personal, offline use only (not for redistribution).

---

## Install

## ⬇️ [Download the latest release](https://github.com/cas-emmens/SoundSplitter/releases/latest)

Grab **`SoundSplitter-Setup-<version>.exe`** from the [latest release](https://github.com/cas-emmens/SoundSplitter/releases/latest)
and run it. It's a **single, fully self-contained Windows installer** — no Python, Node, or
internet required. Per-user install (no admin), and the app **auto-updates** itself from future
releases.

### Install guide (Windows 10/11, 64-bit)

1. **Download & run** `SoundSplitter-Setup-….exe`. Windows SmartScreen may warn — click
   **More info → Run anyway** (the app isn't signed with a paid code-signing cert).
2. **VB-CABLE** — install [VB-CABLE](https://vb-audio.com/Cable/) (admin install + reboot), then
   set Spotify's output device to **CABLE Input**. The app records from **CABLE Output**. Required
   for capturing audio. *(To also hear the music live, use VoiceMeeter — otherwise just play the
   separated stems back in the app.)*
3. **Spotify** — you need **Spotify Premium** (the app starts/stops playback for you) and a free
   **Spotify Developer app**: create one at the [dashboard](https://developer.spotify.com/dashboard),
   add the redirect URI `http://127.0.0.1:8000/api/spotify/callback`, and paste your **Client ID /
   Secret** into the `.env` the app creates on first run. It shows the exact path on the loading
   screen — `%APPDATA%\nl.emmens.soundsplitter\.env`. Restart the app after editing.
4. Open the **Capture** tab → **Connect Spotify**, then search a song and hit **Record**.

> Separation runs on **CPU** in the bundle (portable), so expect a few minutes per song. Your
> library, settings, and credentials live in `%APPDATA%\nl.emmens.soundsplitter\` and survive
> updates. Needs the WebView2 runtime (ships with Windows 11).

---

## What it does

Each person runs their own copy — recording captures *your* Spotify on *your* machine, so there's
nothing to host or share. Separation is **offline**: a song plays through once, is captured, then
separated, so quality is maximal and there's no real-time latency. The only "live" part is the
browser-based playback mixer.

### Using it

1. **Capture** — Connect Spotify, then search a song and Record. Play it through (output =
   *CABLE Input*); the app captures it, auto-names it, separates it, and adds it to the **Library**.
   Don't seek/skip mid-song — a clean capture needs the whole track.
2. **Library** — open a finished song to load the player.
3. **Player** — toggle/solo individual stems, or hit **🎸 Practice mode** to mute vocals + guitar
   for an instant backing track. **Add your own take** imports a recording as an extra stem (nudge
   its offset to line it up).
4. **Tabs** — from the player, **Add tab**, paste a tab webpage URL (e.g. Songsterr); it's captured
   and transcribed, then plays in sync with the stems.

### Notes / limits

- Guitar/piano separation is the messiest (expect some bleed); vocal removal is clean.
- Capture only keeps songs caught near their start; joining a song late is skipped.
- The first separation loads the bundled `htdemucs_6s` model — slightly slower than later runs.

---

## Architecture

```
Spotify ──(VB-CABLE)──► capture ──► Demucs htdemucs_6s ──► FLAC stems ──► library
                          ▲                                                  │
                   Spotify Web API                                  Angular multitrack
                  (titles + boundaries)                             player (mute/solo)
```

- **Backend:** Python 3.13 + FastAPI; Demucs (`htdemucs_6s`) via PyTorch (CUDA when an NVIDIA GPU
  is present, CPU otherwise — the release bundle is CPU); `sounddevice` capture, `spotipy`, SQLite,
  FLAC via `soundfile`.
- **Frontend:** Angular 22, Web Audio API multitrack player. Tab rendering via alphaTab.
- **Desktop shell:** [Tauri](https://tauri.app) (OS webview + small Rust shell). The **backend
  serves the built Angular app** on its own origin (`http://127.0.0.1:8000`) and the window points
  at it, so every `/api` call and the Spotify OAuth redirect stays same-origin. The shell starts
  the backend, waits for the port, navigates the window, and kills the backend on exit.
- **Distribution:** a single [Inno Setup](https://jrsoftware.org/isinfo.php) installer bundles a
  relocatable Python runtime + all deps + pre-downloaded weights + the built UI (~2.5 GB payload →
  ~630 MB installer). Inno is used instead of NSIS/MSI because those cap install data at ~2 GB.
- **Auto-update:** the shell checks a `latest.json` on the GitHub release, **verifies a minisign
  signature** against a pubkey embedded in the binary, then downloads + runs the new installer.

### Build / run from source (development)

Requires **Windows**. `setup.ps1` auto-installs Python 3.13, Node.js, and ffmpeg via `winget`, and
installs **GPU-aware** PyTorch (CUDA if an NVIDIA card is found, else CPU):

```powershell
.\setup.ps1                         # one-time: venv + PyTorch + deps + frontend deps
# then paste your Spotify Client ID/Secret into backend\.env (created from the example)
```

- **`.\run.ps1`** — dev mode: starts the backend (`:8000`) + Angular dev server (`:4200`) in two
  windows and opens the browser.
- **`.\desktop.ps1`** — runs the Tauri desktop app in dev (installs Rust + Tauri CLI if missing;
  provisions via `setup.ps1` on first launch). Needs the MSVC C++ build tools to compile the shell.
- **`.\build-installer.ps1`** — produces the self-contained release installer (Inno Setup; also
  requires `winget install JRSoftware.InnoSetup`). Signing + publishing steps are in
  **[RELEASING.md](RELEASING.md)**.

> If PowerShell blocks the scripts with an execution-policy error, run once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### Handy backend scripts

- `smoke_separate.py [audio]` — sanity-check 6-stem separation (GPU if available, else CPU).
- `seed_demo.py` — add a built-in synthetic demo song to the library.

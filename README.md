# sound-splitter

A personal app that captures songs from Spotify, separates each into **6 instrument
stems** (vocals / drums / bass / **guitar** / **piano** / other) offline with Demucs,
stores them in a library, and replays them with a live stem mixer — mute **vocals +
guitar** for a one-tap practice backing track, and import your own recorded takes as
extra stems.

> Personal, offline use only (not for redistribution).

## How it works

```
Spotify ──(VB-CABLE)──► capture ──► Demucs htdemucs_6s (GPU) ──► FLAC stems ──► library
                          ▲                                                        │
                   Spotify Web API                                        Angular multitrack
                  (titles + boundaries)                                   player (mute/solo)
```

Separation is **offline** (a song plays through once, is captured, then separated), so
quality is maximal and there's no real-time latency. The only "live" part is the
browser playback mixer.

## Stack
- **Backend:** Python 3.13 + FastAPI, Demucs (`htdemucs_6s`) on CUDA, `sounddevice`
  capture, `spotipy`, SQLite, FLAC via `soundfile`.
- **Frontend:** Angular 22, Web Audio API multitrack player.

---

## Set up on a new PC (e.g. for a friend)

Each person runs their own copy — recording captures *your* Spotify on *your* machine,
so there's nothing to host or share. On a fresh **Windows** PC:

`setup.ps1` now **auto-installs Python 3.13, Node.js, and ffmpeg** for you (via `winget`,
built into Windows), so you only have to handle the two things that can't be automated:

1. **VB-CABLE** — https://vb-audio.com/Cable/ → install as admin, **reboot** (it's a
   driver, so this one is manual). Then set Spotify’s output device to **CABLE Input**
   (Windows → Settings → System → Sound → Volume mixer → Spotify). The app records from
   **CABLE Output**.
2. **Spotify Premium** (required — the app starts/stops playback for you) and a free
   **Spotify Developer app**:
   - https://developer.spotify.com/dashboard → *Create app*.
   - Add Redirect URI **exactly**: `http://127.0.0.1:8000/api/spotify/callback`
   - Copy the **Client ID** and **Client Secret** for the next step.

**Then, in the project folder (PowerShell):**
```powershell
.\setup.ps1
```
This installs any missing prerequisites, creates the Python environment, and installs
everything. It **auto-detects your GPU**: with an NVIDIA card, separation takes seconds–a
minute per song; without one it falls back to CPU and takes a few minutes per song (still
works). (If a tool was just installed and isn't found yet, open a **new** terminal and
re-run — Windows only adds it to PATH for new shells.)

Open `backend\.env` and paste your Spotify Client ID/Secret:
```
SPOTIPY_CLIENT_ID=your_id
SPOTIPY_CLIENT_SECRET=your_secret
SPOTIPY_REDIRECT_URI=http://127.0.0.1:8000/api/spotify/callback
```

**Start it (any time after):**
```powershell
.\run.ps1
```
This launches the backend + frontend and opens http://localhost:4200. On the **Capture**
tab, click **Connect Spotify** once, then search a song and hit **Record**.

> **First separation downloads the Demucs model (~1 GB), once.** The first song will sit
> in “Separating…” longer than usual while that downloads — it's not stuck.

> If PowerShell blocks the scripts with an execution-policy error, run once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

---

## One-time setup

### 1. VB-CABLE (audio capture)
1. Download & install **VB-CABLE** from https://vb-audio.com/Cable/ (run as admin, reboot).
2. In Windows Sound settings (or Spotify → Settings), set Spotify's playback device to
   **CABLE Input**. The app records from **CABLE Output**.
   - Tip: to also *hear* the music, use VoiceMeeter, or just listen to the separated
     playback in the app afterward.

### 2. Spotify Developer app (metadata + track boundaries)
1. Go to https://developer.spotify.com/dashboard and create an app (free).
2. Add the Redirect URI: `http://127.0.0.1:8000/api/spotify/callback`
3. Copy `backend/.env.example` to `backend/.env` and fill in:
   ```
   SPOTIPY_CLIENT_ID=...
   SPOTIPY_CLIENT_SECRET=...
   SPOTIPY_REDIRECT_URI=http://127.0.0.1:8000/api/spotify/callback
   ```

### 3. Dependencies (already installed in this workspace)
- **Backend venv:** `backend/.venv` (CUDA PyTorch + torchaudio + demucs + FastAPI + …).
  Recreate with:
  ```
  cd backend
  py -3.13 -m venv .venv
  .venv\Scripts\python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
  .venv\Scripts\python -m pip install -r requirements.txt
  ```
- **Node:** installed via nvm-windows (symlink `C:\nvm4w\nodejs`); Angular CLI global.
- **ffmpeg:** installed (used for decoding imported non-FLAC/WAV takes).

---

## Running

**Backend** (terminal 1):
```
cd backend
.venv\Scripts\python run.py        # http://127.0.0.1:8000
```

**Frontend** (terminal 2):
```
cd frontend
ng serve                            # http://localhost:4200  (proxies /api to backend)
```

Open **http://localhost:4200**.

## Desktop app (Tauri)

The app can also run as a **native desktop window** instead of a browser tab, using
[Tauri](https://tauri.app) (a lightweight Electron alternative: the OS webview + a small
Rust shell, no bundled Chromium). The Rust shell provisions the app on first launch,
starts the Python backend itself, and shuts it down when you close the window — so it's
a single app, nothing else to manage.

How it's wired: the **backend serves the built Angular app** on its own origin
(`http://127.0.0.1:8000`), and the desktop window just points at it. That keeps every
`/api` call and the Spotify OAuth redirect same-origin, so no frontend code changes.

**Run it (that's it):**
```powershell
.\desktop.ps1
```
**Almost everything is automatic.** `desktop.ps1` installs Rust + the Tauri CLI if
missing; then, on first launch, the window runs `setup.ps1` (which installs Python / Node
/ ffmpeg as needed and the GPU-aware PyTorch + deps — ~2-3 GB, several minutes) and builds
the UI, all behind a loading screen. The first launch also compiles the Rust shell; later
runs are fast. Backend logs go to `backend/data/desktop-backend.log`.

The only things that can't be automated are the same two as above: **VB-CABLE** (a
driver — admin install + reboot) and your **Spotify credentials** in `backend\.env`
(setup creates the file from the example for you to fill in). Windows also needs the MSVC
C++ build tools (come with Visual Studio) to compile the Rust shell; WebView2 ships with
Windows 11.

**Build a distributable installer** (`.msi` / `.exe`) instead of running in dev:
```powershell
cd src-tauri
cargo tauri build
```
> Note: the bundled app still runs the Python backend from this repo on the build
> machine — packaging Python itself into the installer for a clean other-PC install is a
> separate, larger step (not done yet).

## Using it
1. **Capture** tab → Connect Spotify → Start capturing.
2. Play music on Spotify (output = CABLE Input). Each finished song is auto-named,
   separated, and added to the **Library**.
3. **Library** → open a finished song → toggle stems, hit **🎸 Practice mode** to mute
   vocals + guitar, or **Add your own take** to import a recording (nudge with the offset).

## Handy scripts (backend/)
- `smoke_separate.py [audio]` — sanity-check 6-stem separation on the GPU.
- `seed_demo.py` — add a built-in synthetic demo song to the library.

## Notes / limits (v1)
- Guitar/piano separation is the messiest (expect some bleed); vocal removal is clean.
- Capture stores songs caught near their start; joining a song late is skipped.
- Stretch ideas: per-stem spectrogram view, section looping. *(Tauri desktop wrapper: done — see “Desktop app” above.)*

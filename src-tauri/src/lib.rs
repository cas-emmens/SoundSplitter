//! SoundSplitter desktop shell.
//!
//! Architecture (see memory: desktop-app-tauri): the Python/FastAPI backend
//! serves the built Angular app over http://127.0.0.1:8000. This shell only:
//!   1. checks for an app update (packaged builds) and installs it if newer,
//!   2. ensures the app is provisioned — in a packaged build everything is
//!      already bundled; in-repo (dev) it falls back to setup.ps1 + npm build,
//!   3. launches the backend as a child process,
//!   4. waits until it is listening, then points the window at it,
//!   5. kills the backend when the window/app closes.
//!
//! No manual memory management: the backend `Child` is owned by managed state
//! and dropped/killed on exit; everything else is stack-owned and freed by RAII.

use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use tauri::{AppHandle, Manager};

const BACKEND_ADDR: &str = "127.0.0.1:8000";
const BACKEND_URL: &str = "http://127.0.0.1:8000";

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;
#[cfg(windows)]
const CREATE_NEW_CONSOLE: u32 = 0x0000_0010;

/// Owns the spawned backend process so we can kill it on exit.
struct BackendProcess(Mutex<Option<Child>>);

/// Resolved locations for everything the shell launches. In a packaged build
/// these point into the bundled payload + a per-user data dir; in-repo (dev)
/// they point at the repo and the backend's own `data/`.
struct AppPaths {
    /// True when running from the bundled payload (self-contained install).
    bundled: bool,
    /// Python interpreter to run the backend with.
    python: PathBuf,
    /// Directory containing `run.py` and the `app` package.
    backend: PathBuf,
    /// Built Angular app served by the backend at `/`.
    frontend_dist: PathBuf,
    /// Writable per-user dir for the library/DB/token cache + backend log.
    data_dir: PathBuf,
    /// Writable `.env` holding Spotify credentials.
    env_file: PathBuf,
    /// Bundled `.env.example` to seed `env_file` from on first run.
    env_example: PathBuf,
    /// Bundled tool locations (packaged build only).
    playwright_browsers: Option<PathBuf>,
    tesseract_cmd: Option<PathBuf>,
    ffmpeg_bin: Option<PathBuf>,
    torch_home: Option<PathBuf>,
}

/// Repo root: the folder containing `src-tauri`, `backend`, `frontend`,
/// `setup.ps1`. Resolved from the crate location (works in-repo for dev/build).
fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from("."))
}

/// Where the Python backend lives in-repo. Overridable via env var.
fn repo_backend_dir() -> PathBuf {
    if let Ok(p) = std::env::var("SOUND_SPLITTER_BACKEND_DIR") {
        return PathBuf::from(p);
    }
    repo_root().join("backend")
}

fn venv_python(backend: &Path) -> PathBuf {
    backend.join(".venv").join("Scripts").join("python.exe")
}

/// The self-contained payload dir, if this is a packaged build. The Inno installer
/// lays it out next to the exe as `<install>/payload`. We check both the exe's
/// directory and Tauri's resource dir (these are the same on Windows, but the
/// explicit exe-dir check is robust regardless of how resources resolve).
fn payload_dir(handle: &AppHandle) -> Option<PathBuf> {
    let has_python =
        |p: &Path| p.join("runtime").join("python").join("python.exe").exists();

    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let p = dir.join("payload");
            if has_python(&p) {
                return Some(p);
            }
        }
    }
    if let Ok(res) = handle.path().resource_dir() {
        let p = res.join("payload");
        if has_python(&p) {
            return Some(p);
        }
    }
    None
}

/// Decide where everything lives based on whether we're a packaged build.
fn resolve_paths(handle: &AppHandle) -> AppPaths {
    if let Some(payload) = payload_dir(handle) {
        let runtime = payload.join("runtime");
        let backend = payload.join("backend");
        // %APPDATA%\<identifier> — stable across installs/upgrades so the
        // library and credentials survive in-place updates.
        let data_dir = handle
            .path()
            .app_data_dir()
            .unwrap_or_else(|_| payload.join("data"));
        AppPaths {
            bundled: true,
            python: runtime.join("python").join("python.exe"),
            frontend_dist: payload.join("frontend-dist"),
            env_file: data_dir.join(".env"),
            env_example: backend.join(".env.example"),
            backend,
            data_dir,
            playwright_browsers: Some(runtime.join("ms-playwright")),
            tesseract_cmd: Some(runtime.join("tesseract").join("tesseract.exe")),
            ffmpeg_bin: Some(runtime.join("ffmpeg").join("bin")),
            torch_home: Some(runtime.join("torch")),
        }
    } else {
        let backend = repo_backend_dir();
        AppPaths {
            bundled: false,
            python: venv_python(&backend),
            frontend_dist: repo_root()
                .join("frontend")
                .join("dist")
                .join("frontend")
                .join("browser"),
            // In dev, leave data/env at the backend's defaults (config.py).
            data_dir: backend.join("data"),
            env_file: backend.join(".env"),
            env_example: backend.join(".env.example"),
            backend,
            playwright_browsers: None,
            tesseract_cmd: None,
            ffmpeg_bin: None,
            torch_home: None,
        }
    }
}

fn backend_already_running() -> bool {
    TcpStream::connect_timeout(
        &BACKEND_ADDR.parse().expect("valid socket addr"),
        Duration::from_millis(300),
    )
    .is_ok()
}

/// Update the splash screen's subtitle so the user knows what's happening.
fn set_status(handle: &AppHandle, msg: &str) {
    if let Some(win) = handle.get_webview_window("main") {
        let js = format!("var s=document.getElementById('sub'); if(s){{s.textContent={msg:?};}}");
        let _ = win.eval(&js);
    }
}

/// Run a command in its own visible console window and wait for it to finish, so
/// the user can watch the (long, verbose) first-run install progress.
#[allow(unused_mut)]
fn run_visible(mut cmd: Command) -> bool {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NEW_CONSOLE);
    }
    matches!(cmd.status(), Ok(s) if s.success())
}

/// Static update manifest (latest.json), matching the format we publish.
#[derive(serde::Deserialize)]
struct UpdateManifest {
    version: String,
    #[serde(default)]
    platforms: std::collections::HashMap<String, PlatformEntry>,
}
#[derive(serde::Deserialize)]
struct PlatformEntry {
    url: String,
    signature: String,
}

const UPDATE_ENDPOINT: &str =
    "https://github.com/cas-emmens/SoundSplitter/releases/latest/download/latest.json";
// base64 of the minisign public-key file (same key used to sign the installer).
const UPDATE_PUBKEY_B64: &str = "dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk6IDNCREVERDBCQkI0RjNCRjIKUldUeU8wKzdDOTNlTzBLTlFMK3dtWGxPMG1ldDdXN09LZldaaDZxL05hbG9kZkxyYW5aMjJxUnYK";

/// Is `remote` strictly newer than `local`? Dot-separated numeric compare.
fn version_gt(remote: &str, local: &str) -> bool {
    let parse = |v: &str| -> Vec<u64> { v.split('.').map(|x| x.trim().parse().unwrap_or(0)).collect() };
    let (r, l) = (parse(remote), parse(local));
    for i in 0..r.len().max(l.len()) {
        let (x, y) = (r.get(i).copied().unwrap_or(0), l.get(i).copied().unwrap_or(0));
        if x != y {
            return x > y;
        }
    }
    false
}

/// Verify installer `data` against a tauri-format signature (base64 of a minisign
/// .sig file) using the embedded public key. True only on a valid signature.
fn verify_signature(data: &[u8], signature_b64: &str) -> bool {
    use base64::Engine;
    use minisign_verify::{PublicKey, Signature};
    let b64 = base64::engine::general_purpose::STANDARD;
    // pubkey: base64(.pub file); the 2nd line is the actual minisign key.
    let Ok(pub_file) = b64.decode(UPDATE_PUBKEY_B64) else { return false };
    let pub_text = String::from_utf8_lossy(&pub_file);
    let Some(key_line) = pub_text.lines().nth(1) else { return false };
    let Ok(pk) = PublicKey::from_base64(key_line.trim()) else { return false };
    // signature: base64(.sig file).
    let Ok(sig_file) = b64.decode(signature_b64) else { return false };
    let Ok(sig) = Signature::decode(&String::from_utf8_lossy(&sig_file)) else { return false };
    pk.verify(data, &sig, false).is_ok()
}

/// Check the update endpoint and, if a newer signed version is published, download
/// + verify + run its installer, then exit so files can be replaced (the installer
/// relaunches us). Any failure (offline, no update, bad signature) is non-fatal.
fn check_for_updates(handle: &AppHandle) {
    use std::io::Read;
    set_status(handle, "Checking for updates…");
    let agent = ureq::AgentBuilder::new()
        .timeout_connect(Duration::from_secs(10))
        .timeout_read(Duration::from_secs(900))
        .build();

    let Ok(resp) = agent.get(UPDATE_ENDPOINT).call() else { return };
    let Ok(body) = resp.into_string() else { return };
    let Ok(manifest) = serde_json::from_str::<UpdateManifest>(&body) else { return };
    if !version_gt(&manifest.version, env!("CARGO_PKG_VERSION")) {
        return; // up to date
    }
    // Pick the build variant's entry so a CUDA install updates to the CUDA
    // installer (and CPU to CPU). The variant is a marker file in the payload.
    let key = match payload_dir(handle).and_then(|p| std::fs::read_to_string(p.join("variant")).ok()) {
        Some(v) if v.trim() == "cuda" => "windows-x86_64-cuda",
        _ => "windows-x86_64",
    };
    let Some(entry) = manifest.platforms.get(key) else { return };

    set_status(handle, "Downloading update…");
    let mut buf = Vec::new();
    let Ok(resp) = agent.get(&entry.url).call() else { return };
    if resp.into_reader().read_to_end(&mut buf).is_err() {
        return;
    }
    if !verify_signature(&buf, &entry.signature) {
        set_status(handle, "Update signature invalid — skipping.");
        return;
    }

    let installer = std::env::temp_dir().join("SoundSplitter-update.exe");
    if std::fs::write(&installer, &buf).is_err() {
        return;
    }
    set_status(handle, "Installing update — the app will restart…");
    let started = Command::new(&installer)
        .args(["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
        .spawn()
        .is_ok();
    if started {
        // Exit so the installer can replace our (locked) exe; it relaunches us.
        std::thread::sleep(Duration::from_millis(800));
        handle.exit(0);
    }
}

/// Packaged builds: make sure the writable per-user dir exists and seed `.env`
/// from the bundled example on first run so the backend can load it. Returns
/// false only on a hard failure (can't create the data dir).
fn ensure_user_data(handle: &AppHandle, paths: &AppPaths) -> bool {
    if std::fs::create_dir_all(&paths.data_dir).is_err() {
        set_status(handle, "Couldn't create the data folder. Check permissions and relaunch.");
        return false;
    }
    if !paths.env_file.exists() && paths.env_example.exists() {
        let _ = std::fs::copy(&paths.env_example, &paths.env_file);
        set_status(
            handle,
            &format!(
                "First run: add your Spotify credentials to {} to enable capture.",
                paths.env_file.display()
            ),
        );
    }
    true
}

/// In-repo (dev) provisioning: install Python deps via setup.ps1 if the venv is
/// missing, and build the Angular UI if it hasn't been built. Returns false if a
/// required step failed.
fn ensure_provisioned(handle: &AppHandle, paths: &AppPaths) -> bool {
    if !paths.python.exists() {
        set_status(
            handle,
            "First-time setup running in the terminal window — installing Python \
             dependencies (~2-3 GB, can take several minutes)…",
        );
        let mut cmd = Command::new("powershell");
        cmd.args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-File"])
            .arg(repo_root().join("setup.ps1"))
            .current_dir(repo_root());
        if !run_visible(cmd) {
            set_status(
                handle,
                "Setup failed. See the setup window for the error, then relaunch.",
            );
            return false;
        }
    }

    if !paths.frontend_dist.join("index.html").exists() {
        set_status(handle, "Building the app interface…");
        let mut cmd = Command::new("cmd");
        cmd.args(["/C", "npm", "run", "build"])
            .current_dir(repo_root().join("frontend"));
        if !run_visible(cmd) {
            set_status(handle, "Building the interface failed. See the build window.");
            return false;
        }
    }

    true
}

/// Launch the FastAPI backend; returns the child handle (None if one is already
/// running on the port — e.g. a dev server — so we reuse it and don't kill it).
fn spawn_backend(paths: &AppPaths) -> Option<Child> {
    if backend_already_running() {
        return None;
    }

    let python = if paths.python.exists() {
        paths.python.clone()
    } else {
        PathBuf::from("python")
    };

    // Capture backend output to a log file (no console window) for debugging.
    let _ = std::fs::create_dir_all(&paths.data_dir);
    let log = std::fs::File::create(paths.data_dir.join("desktop-backend.log")).ok();

    let mut cmd = Command::new(python);
    cmd.arg("run.py")
        .current_dir(&paths.backend)
        // Desktop mode: backend serves the frontend on its own origin, so the
        // OAuth callback must redirect back here, not to the dev server.
        .env("FRONTEND_ORIGIN", BACKEND_URL)
        .env("FRONTEND_DIST", &paths.frontend_dist);

    if paths.bundled {
        // Point the backend at the bundled tools + the per-user writable state.
        cmd.env("SOUND_SPLITTER_BACKEND_DIR", &paths.backend)
            .env("SOUND_SPLITTER_DATA_DIR", &paths.data_dir)
            .env("SOUND_SPLITTER_ENV_FILE", &paths.env_file);
        if let Some(p) = &paths.playwright_browsers {
            cmd.env("PLAYWRIGHT_BROWSERS_PATH", p);
        }
        if let Some(t) = &paths.tesseract_cmd {
            cmd.env("TESSERACT_CMD", t);
        }
        if let Some(h) = &paths.torch_home {
            cmd.env("TORCH_HOME", h);
        }
        if let Some(bin) = &paths.ffmpeg_bin {
            // Prepend bundled ffmpeg so soundfile/librosa can find it.
            let existing = std::env::var("PATH").unwrap_or_default();
            cmd.env("PATH", format!("{};{}", bin.display(), existing));
        }
    }

    if let Some(f) = log {
        if let Ok(err) = f.try_clone() {
            cmd.stdout(Stdio::from(f)).stderr(Stdio::from(err));
        }
    }

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    match cmd.spawn() {
        Ok(child) => Some(child),
        Err(e) => {
            eprintln!("failed to start backend: {e}");
            None
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            app.manage(BackendProcess(Mutex::new(None)));

            // Do the slow first-run/boot work off the main thread so the splash
            // shows immediately.
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let paths = resolve_paths(&handle);

                if paths.bundled {
                    // Packaged: self-update, then just seed the per-user data dir.
                    check_for_updates(&handle);
                    if !ensure_user_data(&handle, &paths) {
                        return; // status already set; stay on the splash
                    }
                } else if !ensure_provisioned(&handle, &paths) {
                    return; // status already set; stay on the splash
                }

                let child = spawn_backend(&paths);
                if let Some(state) = handle.try_state::<BackendProcess>() {
                    if let Ok(mut guard) = state.0.lock() {
                        *guard = child;
                    }
                }

                set_status(&handle, "Starting the audio engine…");
                let addr = BACKEND_ADDR.parse().expect("valid socket addr");
                loop {
                    if TcpStream::connect_timeout(&addr, Duration::from_millis(500)).is_ok() {
                        if let Some(win) = handle.get_webview_window("main") {
                            if let Ok(url) = BACKEND_URL.parse() {
                                let _ = win.navigate(url);
                            }
                        }
                        break;
                    }
                    std::thread::sleep(Duration::from_millis(500));
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building SoundSplitter")
        .run(|app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                if let Some(state) = app_handle.try_state::<BackendProcess>() {
                    if let Ok(mut guard) = state.0.lock() {
                        if let Some(child) = guard.as_mut() {
                            let _ = child.kill();
                        }
                    }
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_compare() {
        assert!(version_gt("0.1.1", "0.1.0"));
        assert!(version_gt("0.2.0", "0.1.9"));
        assert!(version_gt("1.0.0", "0.9.9"));
        assert!(!version_gt("0.1.0", "0.1.0"));
        assert!(!version_gt("0.1.0", "0.1.1"));
    }

    /// Round-trip the real update-verification path: a `tauri signer sign` signature
    /// of the built installer must verify against the embedded public key, and any
    /// tampering must be rejected. Skips if the signed installer isn't present.
    #[test]
    fn signature_roundtrip() {
        // Find any signed installer in dist/ (version-agnostic, cpu or cuda build).
        let dist = Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("dist");
        let exe = std::fs::read_dir(&dist).ok().and_then(|rd| {
            rd.filter_map(|e| e.ok().map(|e| e.path())).find(|p| {
                let name = p.file_name().and_then(|n| n.to_str()).unwrap_or("");
                name.starts_with("SoundSplitter-Setup-")
                    && name.ends_with(".exe")
                    && p.with_extension("exe.sig").exists()
            })
        });
        let Some(exe) = exe else {
            eprintln!("skipping: no signed installer in {}", dist.display());
            return;
        };
        let sig = exe.with_extension("exe.sig");
        let data = std::fs::read(&exe).unwrap();
        let signature = std::fs::read_to_string(&sig).unwrap();
        assert!(
            verify_signature(&data, signature.trim()),
            "valid signature must verify against the embedded pubkey"
        );
        // Tamper one byte -> must be rejected.
        let mut bad = data.clone();
        bad[0] ^= 0xFF;
        assert!(!verify_signature(&bad, signature.trim()), "tampered data must fail");
        // Garbage signature -> must be rejected.
        assert!(!verify_signature(&data, "not-base64-at-all!!"), "bad signature must fail");
    }
}

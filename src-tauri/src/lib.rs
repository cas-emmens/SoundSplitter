//! Sound Splitter desktop shell.
//!
//! Architecture (see memory: desktop-app-tauri): the Python/FastAPI backend
//! serves the built Angular app over http://127.0.0.1:8000. This shell only:
//!   1. on first run, provisions the app (setup.ps1: venv + PyTorch + deps) and
//!      builds the Angular UI if either is missing,
//!   2. launches the backend as a child process,
//!   3. waits until it is listening, then points the window at it,
//!   4. kills the backend when the window/app closes.
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

/// Repo root: the folder containing `src-tauri`, `backend`, `frontend`,
/// `setup.ps1`. Resolved from the crate location (works in-repo for dev/build).
fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from("."))
}

/// Where the Python backend lives. Overridable via env var.
fn backend_dir() -> PathBuf {
    if let Ok(p) = std::env::var("SOUND_SPLITTER_BACKEND_DIR") {
        return PathBuf::from(p);
    }
    repo_root().join("backend")
}

fn venv_python(backend: &Path) -> PathBuf {
    backend.join(".venv").join("Scripts").join("python.exe")
}

fn frontend_index(root: &Path) -> PathBuf {
    root.join("frontend")
        .join("dist")
        .join("frontend")
        .join("browser")
        .join("index.html")
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

/// First-run provisioning: install Python deps via setup.ps1 if the venv is
/// missing, and build the Angular UI if it hasn't been built. Returns false if a
/// required step failed.
fn ensure_provisioned(handle: &AppHandle, root: &Path, backend: &Path) -> bool {
    if !venv_python(backend).exists() {
        set_status(
            handle,
            "First-time setup running in the terminal window — installing Python \
             dependencies (~2-3 GB, can take several minutes)…",
        );
        let mut cmd = Command::new("powershell");
        cmd.args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-File"])
            .arg(root.join("setup.ps1"))
            .current_dir(root);
        if !run_visible(cmd) {
            set_status(
                handle,
                "Setup failed. See the setup window for the error, then relaunch.",
            );
            return false;
        }
    }

    if !frontend_index(root).exists() {
        set_status(handle, "Building the app interface…");
        let mut cmd = Command::new("cmd");
        cmd.args(["/C", "npm", "run", "build"])
            .current_dir(root.join("frontend"));
        if !run_visible(cmd) {
            set_status(handle, "Building the interface failed. See the build window.");
            return false;
        }
    }

    true
}

/// Launch the FastAPI backend; returns the child handle (None if one is already
/// running on the port — e.g. a dev server — so we reuse it and don't kill it).
fn spawn_backend(backend: &Path) -> Option<Child> {
    if backend_already_running() {
        return None;
    }

    let venv_py = venv_python(backend);
    let python = if venv_py.exists() {
        venv_py
    } else {
        PathBuf::from("python")
    };

    // Capture backend output to a log file (no console window) for debugging.
    let _ = std::fs::create_dir_all(backend.join("data"));
    let log = std::fs::File::create(backend.join("data").join("desktop-backend.log")).ok();

    let mut cmd = Command::new(python);
    cmd.arg("run.py")
        .current_dir(backend)
        // Desktop mode: backend serves the frontend on its own origin, so the
        // OAuth callback must redirect back here, not to the dev server.
        .env("FRONTEND_ORIGIN", BACKEND_URL);

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
                let root = repo_root();
                let backend = backend_dir();

                if !ensure_provisioned(&handle, &root, &backend) {
                    return; // status message already set; stay on the splash
                }

                let child = spawn_backend(&backend);
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
        .expect("error while building Sound Splitter")
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

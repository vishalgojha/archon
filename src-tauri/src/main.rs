#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use std::ffi::OsStr;
use tauri::{Manager, WindowEvent};

type SharedChild = Arc<Mutex<Option<Child>>>;

#[tauri::command]
fn server_health() -> bool {
    let addr: SocketAddr = "127.0.0.1:8000".parse().expect("valid addr");
    TcpStream::connect_timeout(&addr, Duration::from_millis(250)).is_ok()
}

fn is_child_alive(child: &mut Child) -> bool {
    match child.try_wait() {
        Ok(Some(_status)) => false,
        Ok(None) => true,
        Err(_) => false,
    }
}

fn find_repo_root() -> Option<PathBuf> {
    let mut cursor = std::env::current_dir().ok()?;
    for _ in 0..12 {
        if cursor.join("archon").join("archon_cli.py").exists() && cursor.join("src-tauri").exists() {
            return Some(cursor);
        }
        if cursor.file_name().is_some_and(|name| name == "src-tauri") {
            if let Some(parent) = cursor.parent() {
                cursor = parent.to_path_buf();
                continue;
            }
        }
        cursor = cursor.parent()?.to_path_buf();
    }
    None
}

fn find_archon_executable(repo_root: &Option<PathBuf>) -> Option<PathBuf> {
    let root = repo_root.as_ref()?;
    let candidates = [
        root.join(".venv").join("Scripts").join("archon.exe"),
        root.join("venv").join("Scripts").join("archon.exe"),
        root.join(".venv").join("bin").join("archon"),
        root.join("venv").join("bin").join("archon"),
    ];
    for candidate in candidates {
        if candidate.exists() {
            return Some(candidate);
        }
    }
    None
}

fn load_dotenv(repo_root: &Option<PathBuf>) {
    let Some(root) = repo_root.as_ref() else {
        return;
    };
    let path = root.join(".env");
    let Ok(contents) = std::fs::read_to_string(&path) else {
        return;
    };
    for line in contents.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        let Some((key, value)) = trimmed.split_once('=') else {
            continue;
        };
        let key = key.trim();
        if key.is_empty() || std::env::var_os(key).is_some() {
            continue;
        }
        std::env::set_var(key, value.trim());
    }
}

fn start_server_impl(child: &SharedChild) -> Result<&'static str, String> {
    if server_health() {
        return Ok("already_running");
    }

    {
        let mut guard = child.lock().map_err(|_| "server state poisoned")?;
        if let Some(existing) = guard.as_mut() {
            if is_child_alive(existing) {
                return Ok("already_started");
            }
        }
        *guard = None;
    }

    let repo_root = find_repo_root();
    load_dotenv(&repo_root);

    let archon_exe = find_archon_executable(&repo_root);
    let mut cmd = Command::new(archon_exe.as_deref().unwrap_or_else(|| std::path::Path::new("archon")));
    cmd.args(["serve", "--port", "8000"])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    if let Some(ref root) = repo_root {
        cmd.current_dir(root);
    }

    let spawned = match cmd.spawn() {
        Ok(child) => child,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => return Err("`archon` executable not found in PATH or .venv. Install ARCHON or activate the repo venv.".to_string()),
        Err(err) => return Err(format!("failed to spawn ARCHON server: {err}")),
    };
    {
        let mut guard = child.lock().map_err(|_| "server state poisoned")?;
        *guard = Some(spawned);
    }

    let start = std::time::Instant::now();
    while start.elapsed() < Duration::from_secs(12) {
        if server_health() {
            return Ok("started");
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    Ok("started")
}

#[tauri::command]
fn start_server(child: tauri::State<'_, SharedChild>) -> Result<&'static str, String> {
    start_server_impl(&child)
}

#[tauri::command]
fn create_token(tenant_id: String, tier: String, expires_in: u64) -> Result<String, String> {
    let repo_root = find_repo_root();
    load_dotenv(&repo_root);

    if std::env::var("ARCHON_JWT_SECRET").unwrap_or_default().trim().is_empty() {
        return Err("ARCHON_JWT_SECRET is not set. Add it to the repo `.env` (recommended) or your system env, then retry.".to_string());
    }

    let archon_exe = find_archon_executable(&repo_root);
    let expires_in_text = expires_in.to_string();
    let mut cmd = Command::new(archon_exe.as_deref().unwrap_or_else(|| std::path::Path::new("archon")));
    cmd.args([
        "token",
        "create",
        "--tenant-id",
        tenant_id.trim(),
        "--tier",
        tier.trim(),
        "--expires-in",
        expires_in_text.as_str(),
    ])
    .stdin(Stdio::null())
    .stdout(Stdio::piped())
    .stderr(Stdio::piped());
    if let Some(ref root) = repo_root {
        cmd.current_dir(root);
    }
    let output = cmd.output().map_err(|err| format!("failed to run `archon token create`: {err}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Err(if stderr.is_empty() { "token creation failed".to_string() } else { stderr });
    }
    let token = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if token.is_empty() {
        return Err("token creation returned empty output".to_string());
    }
    Ok(token)
}

#[tauri::command]
fn stop_server(child: tauri::State<'_, SharedChild>) -> Result<&'static str, String> {
    let mut guard = child.lock().map_err(|_| "server state poisoned")?;
    if let Some(mut running) = guard.take() {
        let _ = running.kill();
        let _ = running.wait();
        return Ok("stopped");
    }
    Ok("not_running")
}

fn spawn_detached<I, S>(program: &str, args: I, cwd: Option<&std::path::Path>) -> Result<(), String>
where
    I: IntoIterator<Item = S>,
    S: AsRef<OsStr>,
{
    let mut cmd = Command::new(program);
    cmd.args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    if let Some(dir) = cwd {
        cmd.current_dir(dir);
    }
    cmd.spawn()
        .map(|_| ())
        .map_err(|err| format!("failed to spawn {program}: {err}"))
}

#[tauri::command]
fn launch_archon_ez(app: tauri::AppHandle) -> Result<&'static str, String> {
    let script = app
        .path_resolver()
        .resolve_resource("archon-ez/archon-ez.ps1")
        .ok_or("Could not resolve bundled resource: archon-ez/archon-ez.ps1")?;

    // Use Windows PowerShell for maximum compatibility.
    spawn_detached(
        "powershell",
        [
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            script.to_string_lossy().as_ref(),
        ],
        None,
    )?;
    Ok("launched")
}
fn main() {
    let child: SharedChild = Arc::new(Mutex::new(None));

    tauri::Builder::default()
        .manage(child.clone())
        .invoke_handler(tauri::generate_handler![
            start_server,
            stop_server,
            server_health,
            create_token,
            launch_archon_ez
        ])
        .setup(move |app| {
            // Best-effort: start on launch so the dashboard is immediately usable.
            let child = app.state::<SharedChild>().clone();
            let _ = start_server_impl(&child);
            Ok(())
        })
        .on_window_event(move |event| {
            if let WindowEvent::CloseRequested { api, .. } = event.event() {
                api.prevent_close();
                let _ = stop_server(event.window().state::<SharedChild>());
                let _ = event.window().close();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}




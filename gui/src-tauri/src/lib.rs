/*!
lib.rs — Second Thought Tauri app entry point

Responsibilities:
  1. Spawn the Python FastAPI server (uvicorn) as a child process on startup
  2. Register the global hotkey (default: Ctrl+Shift+Space)
     • Read the hotkey string from config.toml [gui] hotkey
     • Fall back to "ctrl+shift+space" if the key is absent
  3. On hotkey press: show the main window + emit "trigger-capture" event to JS
  4. Create a system tray with "Vault", "Open Settings", "Inbox",
     "Stats", and "Quit" menu items
  5. Kill the Python child process cleanly on app exit

Config path: ../../omni_capture/config.toml (relative to the gui/ directory)
*/

use std::{
    fs::{self, File, OpenOptions},
    io::{BufRead, BufReader, Write},
    path::{Path, PathBuf},
    process::{Child, Stdio},
    sync::{
        atomic::{AtomicU32, AtomicU64, Ordering},
        Arc, Mutex, OnceLock,
    },
    thread,
    time::{SystemTime, UNIX_EPOCH},
};

use chrono::{SecondsFormat, Utc};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, Manager, Runtime,
};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};
use rand::Rng;

// ── App state (shared across Tauri commands / event handlers) ───────────────

struct AppState {
    python_child: Arc<Mutex<Option<Child>>>,
    gui_secret: String,
    active_shortcut: Mutex<Option<Shortcut>>,
}

// ── Logging ──────────────────────────────────────────────────────────────────
//
// Each launch gets its own plain-text log file alongside the project root in
// `logs/`, named by the launch's start time plus PID so concurrent launches
// can never collide. Within a launch the file still rolls over by size, with
// old files pruned by age on boot. The frontend logger (src/lib/logger.ts)
// formats its own lines and ships them here in batches via the `append_log`
// command; Rust-origin events (including panics and the Python child's
// stdout/stderr) go through `log_line` so every source shares one timeline
// and one timestamp format (ISO-8601, matching `Date.prototype.toISOString`).
//
// Writes are serialized through a single `Mutex<LogHandle>` held in a
// process-wide `OnceLock` (rather than reopening the file per call) so
// concurrent `append_log` invocations from the frontend, Rust-origin events,
// and the Python reader threads can never interleave or corrupt a line.

const MAX_LOG_SIZE_BYTES: u64 = 10 * 1024 * 1024; // 10 MiB before rolling within a launch
const RETENTION_DAYS: u64 = 14;

/// Log level numbers mirror the frontend's `LogLevel` enum so one runtime
/// toggle (see `set_log_level`) can gate both sides.
const LVL_TRACE: u32 = 10;
const LVL_INFO: u32 = 30;
const LVL_WARN: u32 = 40;
const LVL_ERROR: u32 = 50;

static LOG: OnceLock<Mutex<LogHandle>> = OnceLock::new();
static LOG_LEVEL: AtomicU32 = AtomicU32::new(LVL_TRACE);

/// Milliseconds since the Unix epoch.
fn epoch_millis() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0)
}

/// ISO-8601 / RFC3339 timestamp with millisecond precision and a `Z` suffix —
/// identical shape to the frontend's `new Date().toISOString()`, so merged
/// logs sort and read as one timeline.
fn now_iso() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true)
}

/// Unique id for this process's launch — start-time millis + PID, so two
/// instances launched in the same millisecond still get distinct files.
fn launch_id() -> String {
    format!("{}-{}", epoch_millis(), std::process::id())
}

fn log_dir() -> PathBuf {
    compute_project_root().join("logs")
}

fn base_log_path(dir: &Path, launch: &str) -> PathBuf {
    dir.join(format!("second-thought-{launch}.log"))
}

fn seq_log_path(dir: &Path, launch: &str, seq: u32) -> PathBuf {
    dir.join(format!("second-thought-{launch}.{seq}.log"))
}

/// Delete log files whose last-modified time is older than `RETENTION_DAYS`
/// — run once on boot so disk usage doesn't grow without bound.
fn prune_old_logs(dir: &Path) {
    let cutoff = SystemTime::now()
        .checked_sub(std::time::Duration::from_secs(RETENTION_DAYS * 86_400))
        .unwrap_or(SystemTime::UNIX_EPOCH);
    let Ok(entries) = fs::read_dir(dir) else { return };
    for entry in entries.flatten() {
        let is_old = entry
            .metadata()
            .and_then(|m| m.modified())
            .is_ok_and(|modified| modified < cutoff);
        if is_old {
            let _ = fs::remove_file(entry.path());
        }
    }
}

/// A single open log file plus enough state to decide when to roll over.
struct LogHandle {
    file: File,
    dir: PathBuf,
    launch: String,
    seq: u32,
    size: u64,
}

impl LogHandle {
    fn open(dir: PathBuf) -> Self {
        let _ = fs::create_dir_all(&dir);
        prune_old_logs(&dir);
        let launch = launch_id();
        let path = base_log_path(&dir, &launch);
        let file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
            .unwrap_or_else(|_| {
                // Last-resort fallback so the app never fails to start over logging.
                OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(dir.join("second-thought-fallback.log"))
                    .expect("could not open fallback log file")
            });
        Self { file, dir, launch, seq: 0, size: 0 }
    }

    fn path(&self) -> PathBuf {
        if self.seq == 0 {
            base_log_path(&self.dir, &self.launch)
        } else {
            seq_log_path(&self.dir, &self.launch, self.seq)
        }
    }

    fn reopen(&mut self) {
        let path = self.path();
        if let Ok(f) = OpenOptions::new().create(true).append(true).open(&path) {
            self.file = f;
            self.size = fs::metadata(&path).map(|m| m.len()).unwrap_or(0);
        }
    }

    fn rotate_if_needed(&mut self, incoming_len: u64) {
        if self.size + incoming_len > MAX_LOG_SIZE_BYTES {
            self.seq += 1;
            self.size = 0;
            self.reopen();
        }
    }

    fn write_line(&mut self, text: &str) {
        let incoming = text.len() as u64 + 1;
        self.rotate_if_needed(incoming);
        if writeln!(self.file, "{text}").is_ok() {
            self.size += incoming;
        }
    }
}

/// Install the global logger (file handle + panic hook). Call once at startup,
/// before anything else that might log or panic. Returns the active log path.
fn init_logging() -> PathBuf {
    let handle = LogHandle::open(log_dir());
    let path = handle.path();
    let _ = LOG.set(Mutex::new(handle));
    install_panic_hook();
    path
}

/// Rust panics bypass the normal log call sites entirely; this hook makes
/// sure one still lands in the unified file before the default handler runs.
fn install_panic_hook() {
    let default_hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        log_line_raw("ERROR", "panic", &info.to_string());
        default_hook(info);
    }));
}

/// Append a single pre-formatted line, serialized through the shared file
/// handle. Best-effort and re-entrancy-safe: a failed write is never retried
/// through the logger itself (which could recurse) — it's dropped, console
/// output (eprintln, in debug builds only) is the only fallback.
fn append_to_log(text: &str) {
    let Some(log) = LOG.get() else { return };
    if let Ok(mut h) = log.lock() {
        h.write_line(text);
    }
}

/// Write a line without the level gate — used by the panic hook and as the
/// shared formatter for `log_line`.
fn log_line_raw(level: &str, scope: &str, msg: &str) {
    append_to_log(&format!("{} [{level}] [rust:{scope}] {msg}", now_iso()));
}

/// Log a Rust-origin event in the same shape the frontend emits, gated by the
/// runtime-adjustable level (see `set_log_level`).
fn log_line(level_num: u32, level: &str, scope: &str, msg: &str) {
    if level_num < LOG_LEVEL.load(Ordering::Relaxed) {
        return;
    }
    log_line_raw(level, scope, msg);
}

#[tauri::command]
fn append_log(line: String) {
    append_to_log(&line);
}

#[tauri::command]
fn log_file_path() -> String {
    LOG.get()
        .and_then(|m| m.lock().ok())
        .map(|h| h.path().to_string_lossy().to_string())
        .unwrap_or_default()
}

/// Current runtime log level (mirrors frontend `LogLevel` numeric values).
#[tauri::command]
fn get_log_level() -> u32 {
    LOG_LEVEL.load(Ordering::Relaxed)
}

/// Change the runtime log level without a rebuild — e.g. from a Settings
/// toggle. Only gates Rust-origin `log_line` calls; the frontend's own level
/// is controlled separately via `logger.setLevel()`.
#[tauri::command]
fn set_log_level(level: u32) {
    LOG_LEVEL.store(level, Ordering::Relaxed);
}

/// Resolve the project root (works in both debug and release layouts).
fn compute_project_root() -> PathBuf {
    if cfg!(debug_assertions) {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()                  // gui/
            .and_then(|p| p.parent())  // project root
            .map(|p| p.to_path_buf())
            .unwrap_or_else(|| PathBuf::from("."))
    } else {
        std::env::current_exe()
            .unwrap_or_else(|_| PathBuf::from("."))
            .parent()                  // target/release (binary dir)
            .and_then(|p| p.parent())  // target
            .and_then(|p| p.parent())  // src-tauri
            .and_then(|p| p.parent())  // gui
            .and_then(|p| p.parent())  // project root
            .map(|p| p.to_path_buf())
            .unwrap_or_else(|| PathBuf::from("."))
    }
}

/// Generate a random 32-char alphanumeric secret for X-Omni-Secret auth.
/// Never logged or printed — passed only via env to the Python child and
/// returned to the webview through `get_gui_secret`.
fn generate_gui_secret() -> String {
    const CHARSET: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    let mut rng = rand::thread_rng();
    (0..32)
        .map(|_| CHARSET[rng.gen_range(0..CHARSET.len())] as char)
        .collect()
}

#[tauri::command]
fn get_gui_secret(state: tauri::State<AppState>) -> String {
    state.gui_secret.clone()
}

/// Unregister the currently-active global shortcut and register `hotkey` in its
/// place. Called from Settings on save so a new hotkey takes effect without an
/// app restart. Unregister happens strictly before register; on registration
/// failure (e.g. the combo is already claimed by another app) the previous
/// shortcut is restored so the app isn't left with no working hotkey at all.
#[tauri::command]
fn set_hotkey(app: AppHandle, state: tauri::State<AppState>, hotkey: String) -> Result<(), String> {
    let new_shortcut = parse_shortcut(&hotkey).ok_or_else(|| format!("Could not parse hotkey '{hotkey}'"))?;

    let mut guard = state
        .active_shortcut
        .lock()
        .map_err(|_| "internal lock error".to_string())?;
    let previous = guard.clone();

    if let Some(prev) = previous.clone() {
        let _ = app.global_shortcut().unregister(prev);
    }

    let register_result = app.global_shortcut().on_shortcut(new_shortcut, capture_shortcut_handler(app.clone()));

    match register_result {
        Ok(()) => {
            *guard = Some(new_shortcut);
            Ok(())
        }
        Err(e) => {
            if let Some(prev) = previous {
                let _ = app.global_shortcut().on_shortcut(prev, capture_shortcut_handler(app.clone()));
            }
            Err(format!("Failed to register hotkey '{hotkey}': {e}"))
        }
    }
}

// ── Read hotkey from config.toml ────────────────────────────────────────────

/// Parse config.toml for [gui] hotkey = "..." without pulling in a full TOML crate.
/// Returns None if the key is absent or the file can't be read.
fn read_hotkey_from_config(config_path: &PathBuf) -> Option<String> {
    let text = std::fs::read_to_string(config_path).ok()?;
    let mut in_gui_section = false;

    for line in text.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with('[') {
            in_gui_section = trimmed == "[gui]";
            continue;
        }
        if in_gui_section {
            if let Some(rest) = trimmed.strip_prefix("hotkey") {
                let rest = rest.trim();
                if let Some(rest) = rest.strip_prefix('=') {
                    let value = rest.trim().trim_matches('"').trim_matches('\'');
                    if !value.is_empty() {
                        return Some(value.to_string());
                    }
                }
            }
        }
    }
    None
}

/// Convert a hotkey string like "ctrl+shift+space" into a Tauri Shortcut.
fn parse_shortcut(hotkey: &str) -> Option<Shortcut> {
    let mut modifiers = Modifiers::empty();
    let mut key_code: Option<Code> = None;

    for part in hotkey.split('+') {
        match part.trim().to_lowercase().as_str() {
            "ctrl" | "control" => modifiers |= Modifiers::CONTROL,
            "cmd"  | "meta"    => modifiers |= Modifiers::META,
            "alt"  | "option"  => modifiers |= Modifiers::ALT,
            "shift"            => modifiers |= Modifiers::SHIFT,
            "space"            => key_code = Some(Code::Space),
            "enter" | "return" => key_code = Some(Code::Enter),
            "tab"              => key_code = Some(Code::Tab),
            "backspace"        => key_code = Some(Code::Backspace),
            k if k.len() == 1  => {
                // Single character keys: A–Z, 0–9
                let c = k.chars().next().unwrap().to_ascii_uppercase();
                key_code = match c {
                    'A'..='Z' => {
                        let idx = (c as u8 - b'A') as usize;
                        [
                            Code::KeyA, Code::KeyB, Code::KeyC, Code::KeyD, Code::KeyE,
                            Code::KeyF, Code::KeyG, Code::KeyH, Code::KeyI, Code::KeyJ,
                            Code::KeyK, Code::KeyL, Code::KeyM, Code::KeyN, Code::KeyO,
                            Code::KeyP, Code::KeyQ, Code::KeyR, Code::KeyS, Code::KeyT,
                            Code::KeyU, Code::KeyV, Code::KeyW, Code::KeyX, Code::KeyY,
                            Code::KeyZ,
                        ].get(idx).copied()
                    }
                    '0'..='9' => {
                        let idx = (c as u8 - b'0') as usize;
                        [
                            Code::Digit0, Code::Digit1, Code::Digit2, Code::Digit3,
                            Code::Digit4, Code::Digit5, Code::Digit6, Code::Digit7,
                            Code::Digit8, Code::Digit9,
                        ].get(idx).copied()
                    }
                    _ => None,
                };
            }
            _ => {} // unknown key part — skip
        }
    }

    key_code.map(|code| Shortcut::new(Some(modifiers), code))
}

// ── Non-activating pill window + click-away hook (for_sonnet.md) ───────────
//
// Windows activates a window's HWND on click, which deactivates whatever app
// was previously foreground — the pill must never do that. There's no Tauri
// API for "non-activating window"; WS_EX_NOACTIVATE is the only real fix, so
// it's toggled directly on the HWND. A non-activating window also never
// fires Tauri's focus-loss event, so click-away dismissal is replaced by a
// WH_MOUSE_LL low-level hook, armed only while a menu is open.
#[cfg(windows)]
mod noactivate {
    use std::sync::{Mutex, OnceLock};
    use tauri::{AppHandle, Emitter, Manager};
    use windows_sys::Win32::Foundation::{HWND, LPARAM, LRESULT, POINT, RECT, WPARAM};
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        CallNextHookEx, GetWindowLongPtrW, GetWindowRect, SetWindowLongPtrW, SetWindowPos,
        SetWindowsHookExW, UnhookWindowsHookEx, GWL_EXSTYLE, HHOOK, MSLLHOOKSTRUCT, SWP_FRAMECHANGED,
        SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER, WH_MOUSE_LL, WM_LBUTTONDOWN,
        WM_RBUTTONDOWN, WS_EX_NOACTIVATE,
    };

    /// Inclusive on the top/left edges, exclusive on bottom/right — matches
    /// Win32's RECT convention (`right`/`bottom` are one past the last pixel).
    fn point_in_rect(rect: &RECT, x: i32, y: i32) -> bool {
        x >= rect.left && x < rect.right && y >= rect.top && y < rect.bottom
    }

    // HWND/HHOOK are opaque Win32 handle values (never dereferenced as
    // pointers here, only passed back into Win32 calls), so it's safe to
    // move them across threads despite the raw-pointer-shaped type.
    struct SendHwnd(HWND);
    unsafe impl Send for SendHwnd {}
    struct SendHook(HHOOK);
    unsafe impl Send for SendHook {}

    struct ArmedState {
        hwnd: SendHwnd,
        app: AppHandle,
    }
    impl Clone for ArmedState {
        fn clone(&self) -> Self {
            Self { hwnd: SendHwnd(self.hwnd.0), app: self.app.clone() }
        }
    }

    static ARMED: OnceLock<Mutex<Option<ArmedState>>> = OnceLock::new();
    static HOOK: OnceLock<Mutex<Option<SendHook>>> = OnceLock::new();

    fn armed_slot() -> &'static Mutex<Option<ArmedState>> {
        ARMED.get_or_init(|| Mutex::new(None))
    }
    fn hook_slot() -> &'static Mutex<Option<SendHook>> {
        HOOK.get_or_init(|| Mutex::new(None))
    }

    unsafe extern "system" fn mouse_hook_proc(code: i32, wparam: WPARAM, lparam: LPARAM) -> LRESULT {
        if code >= 0 && (wparam as u32 == WM_LBUTTONDOWN || wparam as u32 == WM_RBUTTONDOWN) {
            let info = &*(lparam as *const MSLLHOOKSTRUCT);
            let pt: POINT = info.pt;
            if let Ok(guard) = armed_slot().lock() {
                if let Some(state) = guard.as_ref() {
                    let mut rect: RECT = std::mem::zeroed();
                    if GetWindowRect(state.hwnd.0, &mut rect) != 0 && !point_in_rect(&rect, pt.x, pt.y) {
                        let _ = state.app.emit("menu:dismiss", ());
                    }
                }
            }
        }
        CallNextHookEx(std::ptr::null_mut(), code, wparam, lparam)
    }

    fn hwnd_for(app: &AppHandle, label: &str) -> Result<HWND, String> {
        let window = app
            .get_webview_window(label)
            .ok_or_else(|| format!("window '{label}' not found"))?;
        let raw = window.hwnd().map_err(|e| e.to_string())?;
        Ok(raw.0 as HWND)
    }

    /// Toggle WS_EX_NOACTIVATE on `window`'s HWND. The pill (and its menu
    /// overlay) stay non-activating; only the expanded full view turns it
    /// off so search/settings inputs can receive keyboard focus.
    #[tauri::command]
    pub fn set_window_noactivate(window: tauri::Window, enabled: bool) -> Result<(), String> {
        let raw = window.hwnd().map_err(|e| e.to_string())?;
        let hwnd = raw.0 as HWND;
        unsafe {
            let ex = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
            let next = if enabled {
                ex | WS_EX_NOACTIVATE as isize
            } else {
                ex & !(WS_EX_NOACTIVATE as isize)
            };
            SetWindowLongPtrW(hwnd, GWL_EXSTYLE, next);
            // GWL_EXSTYLE changes don't take effect on an already-created
            // window until the frame is flushed via SetWindowPos.
            SetWindowPos(
                hwnd,
                std::ptr::null_mut(),
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            );
        }
        Ok(())
    }

    /// Install the low-level mouse hook and point it at `window_label`'s
    /// HWND for hit-testing. Only ever one hook installed at a time — a
    /// second `arm` while already armed just re-targets it.
    #[tauri::command]
    pub fn arm_menu_click_away(app: AppHandle, window_label: String) -> Result<(), String> {
        let hwnd = hwnd_for(&app, &window_label)?;
        *armed_slot().lock().map_err(|_| "lock poisoned".to_string())? =
            Some(ArmedState { hwnd: SendHwnd(hwnd), app: app.clone() });

        let already_installed = hook_slot().lock().map_err(|_| "lock poisoned".to_string())?.is_some();
        if already_installed {
            return Ok(()); // already installed — just re-targeted above
        }
        // SetWindowsHookExW must be called on a thread with a running
        // message loop; queue it onto the main thread rather than requiring
        // every caller to already be there.
        app.run_on_main_thread(move || unsafe {
            let h = SetWindowsHookExW(WH_MOUSE_LL, Some(mouse_hook_proc), std::ptr::null_mut(), 0);
            if let Ok(mut g) = hook_slot().lock() {
                *g = if h.is_null() { None } else { Some(SendHook(h)) };
            }
        })
        .map_err(|e| e.to_string())?;
        Ok(())
    }

    /// Remove the click-away hook. Idempotent — safe to call even if nothing
    /// is currently armed (every menu-close path calls this unconditionally).
    #[tauri::command]
    pub fn disarm_menu_click_away(app: AppHandle) -> Result<(), String> {
        *armed_slot().lock().map_err(|_| "lock poisoned".to_string())? = None;
        app.run_on_main_thread(|| unsafe {
            if let Ok(mut g) = hook_slot().lock() {
                if let Some(h) = g.take() {
                    UnhookWindowsHookEx(h.0);
                }
            }
        })
        .map_err(|e| e.to_string())
    }

    /// Atomic move+resize via a single Win32 `SetWindowPos` call, so the
    /// capsule's right-zone open (window widens *and* shifts left in one
    /// step) never lands as two separate compositor frames — see
    /// PLAN_capsule_right_motion.md Gripe 2. All args are physical px; the
    /// JS caller converts logical→physical via `scaleFactor()` once, the
    /// one sanctioned physical-coordinate path (mirrors `monitor.ts`).
    #[tauri::command]
    pub fn set_window_bounds(window: tauri::Window, x: i32, y: i32, w: i32, h: i32) -> Result<(), String> {
        let raw = window.hwnd().map_err(|e| e.to_string())?;
        let hwnd = raw.0 as HWND;
        unsafe {
            SetWindowPos(hwnd, std::ptr::null_mut(), x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE);
        }
        Ok(())
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        fn rect() -> RECT {
            RECT { left: 10, top: 10, right: 20, bottom: 20 }
        }

        #[test]
        fn inside_is_true() {
            assert!(point_in_rect(&rect(), 15, 15));
        }

        #[test]
        fn left_top_edges_are_inside() {
            assert!(point_in_rect(&rect(), 10, 10));
        }

        #[test]
        fn right_bottom_edges_are_outside() {
            assert!(!point_in_rect(&rect(), 20, 15));
            assert!(!point_in_rect(&rect(), 15, 20));
        }

        #[test]
        fn outside_each_side_is_false() {
            assert!(!point_in_rect(&rect(), 5, 15));   // left
            assert!(!point_in_rect(&rect(), 25, 15));  // right
            assert!(!point_in_rect(&rect(), 15, 5));   // top
            assert!(!point_in_rect(&rect(), 15, 25));  // bottom
        }
    }
}

// ponytail: WS_EX_NOACTIVATE / WH_MOUSE_LL have no Linux equivalent (X11/Wayland
// window activation isn't controlled this way); these are no-ops until a Linux
// pill window ever needs the same non-activating behavior.
#[cfg(not(windows))]
mod noactivate {
    #[tauri::command]
    pub fn set_window_noactivate(_window: tauri::Window, _enabled: bool) -> Result<(), String> {
        Ok(())
    }

    #[tauri::command]
    pub fn arm_menu_click_away(_app: tauri::AppHandle, _window_label: String) -> Result<(), String> {
        Ok(())
    }

    #[tauri::command]
    pub fn disarm_menu_click_away(_app: tauri::AppHandle) -> Result<(), String> {
        Ok(())
    }

    #[tauri::command]
    pub fn set_window_bounds(_window: tauri::Window, _x: i32, _y: i32, _w: i32, _h: i32) -> Result<(), String> {
        Ok(())
    }
}

// ── Job Object: reap the Python child on an UNGRACEFUL parent death ──────────
//
// The RunEvent::Exit hook (see run()) and the tray "quit" arm both kill the
// child on a *graceful* exit. Neither runs if the parent is force-killed
// (Task Manager "End task", a crash with no unwind, SIGKILL-equivalent). On
// Windows the only OS-level guarantee is a Job Object with
// JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: every handle to the job closes when the
// parent process dies for ANY reason, and Windows then terminates every
// process assigned to that job. So we create one job, set the kill-on-close
// limit, assign the freshly-spawned child to it, and deliberately LEAK the
// job handle for the life of the process (storing it in a OnceLock) — closing
// it early would trip the same kill limit and take the child down with it.
//
// This is raw Win32 FFI (matches the `mod noactivate` commenting style). We
// get the child's process HANDLE from `Child::as_raw_handle()`, avoiding an
// OpenProcess round-trip. (windows-sys still gates the extended-limit struct
// itself behind Win32_System_Threading, so that feature is enabled too.)
#[cfg(windows)]
mod jobkill {
    use std::os::windows::io::AsRawHandle;
    use std::process::Child;
    use std::sync::OnceLock;
    use windows_sys::Win32::Foundation::HANDLE;
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    // A Win32 HANDLE is an opaque, raw-pointer-shaped value we only ever hand
    // back to Win32 (never dereference), so it's safe to hold in a static. The
    // field is never read: it exists solely so the job handle is NOT dropped
    // (dropping it would fire KILL_ON_JOB_CLOSE and kill the child early).
    #[allow(dead_code)]
    struct SendHandle(HANDLE);
    unsafe impl Send for SendHandle {}
    unsafe impl Sync for SendHandle {}

    // Keeps the job handle alive for the whole process. Never closed on
    // purpose — dropping/closing it would fire KILL_ON_JOB_CLOSE early.
    static JOB: OnceLock<SendHandle> = OnceLock::new();

    /// The single job-limit flag we set. Exposed so a unit test can assert the
    /// intended (non-zero) kill-on-close semantics without a live child.
    #[allow(dead_code)] // referenced only from the #[cfg(test)] module below
    pub fn kill_on_close_flag() -> u32 {
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    }

    /// Create a kill-on-job-close Job Object and assign `child` to it. On
    /// success the OS will terminate the child whenever this (parent) process
    /// dies, even without any Rust hook running. Best-effort: errors are
    /// returned for the caller to log, never fatal to startup.
    pub fn assign_child_to_kill_on_close_job(child: &Child) -> Result<(), String> {
        // Only one job for the process lifetime; a second spawn (there isn't
        // one today) would need its own job rather than reusing this slot.
        if JOB.get().is_some() {
            return Err("job object already created".to_string());
        }
        unsafe {
            let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
            if job.is_null() {
                return Err("CreateJobObjectW returned null".to_string());
            }
            let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            let set_ok = SetInformationJobObject(
                job,
                JobObjectExtendedLimitInformation,
                &info as *const _ as *const core::ffi::c_void,
                std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            );
            if set_ok == 0 {
                return Err("SetInformationJobObject failed".to_string());
            }
            let child_handle = child.as_raw_handle() as HANDLE;
            if AssignProcessToJobObject(job, child_handle) == 0 {
                return Err("AssignProcessToJobObject failed".to_string());
            }
            // Leak the handle into the static so it outlives this function.
            let _ = JOB.set(SendHandle(job));
        }
        Ok(())
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        // Decidable part of the FFI path: the limit flag we hand to Windows is
        // the kill-on-close flag and is non-zero (0 would be a silent no-op).
        #[test]
        fn flag_is_kill_on_job_close() {
            assert_eq!(kill_on_close_flag(), JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE);
            assert_ne!(kill_on_close_flag(), 0);
        }
    }
}

// ponytail: no Job Object equivalent needed off-Windows yet — the POSIX
// analogue (prctl PR_SET_PDEATHSIG or a process group + kill) is only worth
// adding when a non-Windows target actually ships. No-op keeps the call site
// cfg-free.
#[cfg(not(windows))]
mod jobkill {
    use std::process::Child;

    #[allow(dead_code)] // referenced only from tests; parity with the windows path
    pub fn kill_on_close_flag() -> u32 {
        0
    }

    pub fn assign_child_to_kill_on_close_job(_child: &Child) -> Result<(), String> {
        Ok(())
    }
}

// ── Python child lifecycle ──────────────────────────────────────────────────

/// Kill the tracked Python child, if one is still alive. Idempotent — takes
/// the child out of the shared slot, so a second call (e.g. the RunEvent::Exit
/// hook firing right after the tray "quit" arm already killed it) is a no-op.
/// This is the ONE kill implementation; both the tray "quit" arm and the
/// app-level exit hook call it so there's never a divergent second copy.
fn kill_python_child<R: Runtime>(app: &AppHandle<R>) {
    if let Some(state) = app.try_state::<AppState>() {
        if let Ok(mut guard) = state.python_child.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
            }
        }
    }
}

// ── Tray icon setup ─────────────────────────────────────────────────────────

fn setup_tray<R: Runtime>(app: &tauri::App<R>) -> tauri::Result<()> {
    let quit_item   = MenuItem::with_id(app, "quit",     "Quit",             true, None::<&str>)?;
    let vault_item    = MenuItem::with_id(app, "vault",    "Vault",            true, None::<&str>)?;
    let settings_item = MenuItem::with_id(app, "settings", "Settings",         true, None::<&str>)?;
    let inbox_item    = MenuItem::with_id(app, "inbox",    "Inbox",            true, None::<&str>)?;
    let stats_item    = MenuItem::with_id(app, "stats",    "Stats",            true, None::<&str>)?;
    let hide_item     = MenuItem::with_id(app, "hide",     "Hide",             true, None::<&str>)?;

    let menu = Menu::with_items(app, &[&vault_item, &settings_item, &inbox_item, &stats_item, &hide_item, &quit_item])?;

    let mut builder = TrayIconBuilder::new();
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }

    builder
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "quit" => {
                // Kill Python child before exiting. app.exit(0) below also
                // fires RunEvent::Exit -> kill_python_child again, but that's a
                // no-op once the child has been taken out of the slot here.
                kill_python_child(app);
                app.exit(0);
            }
            "settings" => {
                show_window_emit(app, "open-settings");
            }
            "vault" => {
                show_window_emit(app, "open-vault");
            }
            "inbox" => {
                show_window_emit(app, "open-inbox");
            }
            "stats" => {
                show_window_emit(app, "open-stats");
            }
            "hide" => {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.hide();
                }
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            // Left-click on tray → show window and emit trigger-capture
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                let app = tray.app_handle();
                show_window_emit(app, "trigger-capture");
            }
        })
        .build(app)?;

    Ok(())
}

// ── Utility: show window and emit an event to the frontend ──────────────────

fn show_window_emit<R: Runtime>(app: &AppHandle<R>, event: &str) {
    // trigger-capture only shows the non-activating pill — the app must
    // never steal foreground focus from whatever the user was in. The
    // open-* events expand to the full view, which does need focus.
    let take_focus = event != "trigger-capture";
    let Some(window) = app.get_webview_window("main") else {
        log_line(LVL_ERROR, "ERROR", "tray", &format!("main window not found for event '{event}'"));
        return;
    };
    if let Err(e) = window.show() {
        log_line(LVL_WARN, "WARN", "tray", &format!("show() failed for event '{event}': {e}"));
    }
    if take_focus {
        if let Err(e) = window.set_focus() {
            log_line(LVL_WARN, "WARN", "tray", &format!("set_focus() failed for event '{event}': {e}"));
        }
    }
    if let Err(e) = app.emit(event, ()) {
        log_line(LVL_ERROR, "ERROR", "tray", &format!("emit('{event}') failed: {e}"));
    }
}

/// Minimum gap (ms) between accepted `trigger-capture` hotkey firings. OS key
/// auto-repeat (holding the combo) and some AHK/Hammerspoon bindings can emit
/// `Pressed` more than once for what the user experiences as a single press;
/// without this gate each one starts its own concurrent `runCapture` in the
/// frontend, which corrupts shared per-run state there (see useCapture.ts).
const HOTKEY_DEBOUNCE_MS: u64 = 350;

static LAST_HOTKEY_FIRE_MS: AtomicU64 = AtomicU64::new(0);

/// Build the `on_shortcut` closure used for every capture hotkey registration.
/// All three sites (setup, set_hotkey register, set_hotkey rollback) share one body.
fn capture_shortcut_handler<R: Runtime>(
    app: AppHandle<R>,
) -> impl Fn(&AppHandle<R>, &tauri_plugin_global_shortcut::Shortcut, tauri_plugin_global_shortcut::ShortcutEvent) + Send + Sync + 'static {
    move |_app, _sc, event| {
        if event.state == ShortcutState::Pressed {
            show_window_emit_debounced(&app, "trigger-capture");
        }
    }
}

/// Debounced version of `show_window_emit` for hotkey press handlers — every
/// `on_shortcut` callback (primary, rollback, and the one installed by
/// `set_hotkey`) should route through this instead of calling
/// `show_window_emit` directly, so they share one debounce clock.
fn show_window_emit_debounced<R: Runtime>(app: &AppHandle<R>, event: &str) {
    let now = epoch_millis() as u64;
    let last = LAST_HOTKEY_FIRE_MS.load(Ordering::Relaxed);
    if now.saturating_sub(last) < HOTKEY_DEBOUNCE_MS {
        log_line(LVL_TRACE, "TRACE", "hotkey", "debounced repeat-fire ignored");
        return;
    }
    LAST_HOTKEY_FIRE_MS.store(now, Ordering::Relaxed);
    show_window_emit(app, event);
}

// ── Main run() ──────────────────────────────────────────────────────────────

pub fn run() {
    let python_child: Arc<Mutex<Option<Child>>> = Arc::new(Mutex::new(None));
    let python_child_clone = python_child.clone();
    let gui_secret = generate_gui_secret();
    let gui_secret_for_spawn = gui_secret.clone();

    // Install the file logger + panic hook before anything else can log or panic.
    init_logging();
    log_line(LVL_INFO, "INFO", "boot", "Second Thought starting up");

    tauri::Builder::default()
        // Must be registered FIRST: on a second launch this callback fires in
        // the ALREADY-RUNNING first instance and the second process exits
        // before setup() runs — so no second Python child ever spawns to fight
        // over port 7070 / disagree on X-Omni-Secret. We just surface the
        // existing window (show + unminimize + focus; no coordinates touched).
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .manage(AppState { python_child, gui_secret, active_shortcut: Mutex::new(None) })
        .invoke_handler(tauri::generate_handler![
            get_gui_secret, set_hotkey, append_log, log_file_path, get_log_level, set_log_level,
            noactivate::set_window_noactivate, noactivate::arm_menu_click_away, noactivate::disarm_menu_click_away,
            noactivate::set_window_bounds
        ])
        .setup(move |app| {
            // ── 1. Spawn Python FastAPI server ─────────────────────────────
            //
            // In debug mode: CARGO_MANIFEST_DIR is src-tauri/ at compile time,
            // so two .parent() calls reach the project root reliably.
            // In release mode: walk up from the exe path.
            let project_root = compute_project_root();

            // Try "python" first, fall back to "python3"
            let server_args = [
                "-m", "uvicorn",
                "omni_capture.server:app",
                "--port", "7070",
                "--log-level", "error",
            ];

            #[cfg(windows)]
            const CREATE_NO_WINDOW: u32 = 0x08000000;

            let mut cmd = std::process::Command::new("python");
            cmd.args(server_args)
                .current_dir(&project_root)
                .env("OMNI_GUI_SECRET", &gui_secret_for_spawn)
                .env("PYTHONPATH", &project_root)
                .stdout(Stdio::piped())
                .stderr(Stdio::piped());
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                cmd.creation_flags(CREATE_NO_WINDOW);
            }

            let child = cmd.spawn().or_else(|_| {
                let mut cmd = std::process::Command::new("python3");
                cmd.args(server_args)
                    .current_dir(&project_root)
                    .env("OMNI_GUI_SECRET", &gui_secret_for_spawn)
                    .env("PYTHONPATH", &project_root)
                    .stdout(Stdio::piped())
                    .stderr(Stdio::piped());
                #[cfg(windows)]
                {
                    use std::os::windows::process::CommandExt;
                    cmd.creation_flags(CREATE_NO_WINDOW);
                }
                cmd.spawn()
            });

            match child {
                Ok(mut c) => {
                    log_line(LVL_INFO, "INFO", "server", &format!("Python server spawned (pid {})", c.id()));

                    // Assign the child to a kill-on-job-close Job Object so an
                    // ungraceful parent death (crash / Task Manager kill, where
                    // no Rust hook runs) still reaps it — the OS-level backstop
                    // to the RunEvent::Exit hook. No-op on non-Windows.
                    match jobkill::assign_child_to_kill_on_close_job(&c) {
                        Ok(()) => log_line(LVL_INFO, "INFO", "server", "child assigned to kill-on-close job object"),
                        Err(e) => log_line(LVL_WARN, "WARN", "server", &format!("job object assignment failed (child may orphan on crash): {e}")),
                    }

                    // uvicorn/server.py write to stdout/stderr; pipe both into the
                    // same unified log file instead of letting them vanish into the
                    // (often invisible, in a packaged build) parent console.
                    if let Some(stdout) = c.stdout.take() {
                        thread::spawn(move || {
                            for line in BufReader::new(stdout).lines().flatten() {
                                log_line(LVL_INFO, "INFO", "python:stdout", &line);
                            }
                        });
                    }
                    if let Some(stderr) = c.stderr.take() {
                        thread::spawn(move || {
                            for line in BufReader::new(stderr).lines().flatten() {
                                log_line(LVL_WARN, "WARN", "python:stderr", &line);
                            }
                        });
                    }

                    if let Ok(mut guard) = python_child_clone.lock() {
                        *guard = Some(c);
                    }
                }
                Err(e) => {
                    log_line(LVL_ERROR, "ERROR", "server", &format!("could not start Python server: {e}"));
                    eprintln!("[Second Thought] Warning: could not start Python server: {e}");
                    eprintln!("  Make sure 'python' is in PATH and uvicorn + fastapi are installed.");
                }
            }

            // ── 2. Register global hotkey ──────────────────────────────────

            let config_path = project_root.join("omni_capture").join("config.toml");
            let hotkey_str = read_hotkey_from_config(&config_path)
                .unwrap_or_else(|| "ctrl+shift+space".to_string());

            if let Some(shortcut) = parse_shortcut(&hotkey_str) {
                app.global_shortcut().on_shortcut(shortcut, capture_shortcut_handler(app.handle().clone()))?;
                if let Some(state) = app.try_state::<AppState>() {
                    if let Ok(mut guard) = state.active_shortcut.lock() {
                        *guard = Some(shortcut);
                    }
                }
                log_line(LVL_INFO, "INFO", "hotkey", &format!("registered: {hotkey_str}"));
                println!("[Second Thought] Hotkey registered: {hotkey_str}");
            } else {
                log_line(LVL_WARN, "WARN", "hotkey", &format!("could not parse hotkey '{hotkey_str}'"));
                eprintln!("[Second Thought] Warning: could not parse hotkey '{hotkey_str}'");
            }

            // ── 3. System tray ─────────────────────────────────────────────
            setup_tray(app)?;

            Ok(())
        })
        .on_window_event(|window, event| {
            // Hide instead of close when the user presses the OS close button
            // (though the window has no decorations, so this is for safety)
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                window.hide().ok();
                api.prevent_close();
            }
            // Belt-and-suspenders: if the window somehow gets maximized despite
            // config.maximizable=false, immediately unmaximize it.
            if let tauri::WindowEvent::Resized(_) = event {
                if window.is_maximized().unwrap_or(false) {
                    let _ = window.unmaximize();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building Second Thought")
        // App-level exit hook: kill the Python child on ANY graceful exit path
        // (app.exit(), last-window logic, OS shutdown) — not just the tray
        // "quit" menu item. The Job Object above covers the ungraceful paths
        // where this closure never runs. Both routes share kill_python_child,
        // so there's no divergent second kill implementation.
        .run(|app_handle, event| {
            if matches!(event, tauri::RunEvent::Exit | tauri::RunEvent::ExitRequested { .. }) {
                kill_python_child(app_handle);
            }
        });
}

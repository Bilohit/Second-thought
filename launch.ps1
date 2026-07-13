# launch.ps1 - Build if stale, then run Second Thought
# Run from project root:  .\launch.ps1
# (Invoked by launch.bat / launch.vbs)
#
# Environment variables:
#   OMNI_DEV=1   Force dev mode (npx tauri dev) instead of the release binary.

$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$gui  = Join-Path $root "gui"
$exe  = Join-Path $gui "src-tauri\target\release\second-thought.exe"
$logDir = Join-Path $root "logs"
$logFile = Join-Path $logDir ("launch-{0}.log" -f (Get-Date -Format "yyyyMMdd"))

# Source paths that, when changed, require a NEW Tauri binary.
# NOTE: omni_capture (the Python backend) is intentionally NOT here. It runs
# from source via uvicorn, so editing Python must not trigger a Rust rebuild.
$watchPaths = @(
    (Join-Path $gui "src"),
    (Join-Path $gui "src-tauri\src"),
    (Join-Path $gui "src-tauri\capabilities"),
    (Join-Path $gui "src-tauri\tauri.conf.json"),
    (Join-Path $gui "src-tauri\Cargo.toml"),
    (Join-Path $gui "index.html"),
    (Join-Path $gui "vite.config.ts"),
    (Join-Path $gui "tsconfig.json"),
    (Join-Path $gui "tailwind.config.js"),
    (Join-Path $gui "postcss.config.js")
)

# ── Logging ───────────────────────────────────────────────────────────────
# Writes to both the console (visible when run via launch.bat) and a
# per-day log file (the only output visible when run via launch.vbs, which
# hides the console window entirely).

function Write-Launch([string]$Message, [string]$Level = "info") {
    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format "HH:mm:ss"), $Level.ToUpper(), $Message
    $color = switch ($Level) {
        "error" { "Red" }
        "warn"  { "Yellow" }
        "ok"    { "Green" }
        default { "Gray" }
    }
    Write-Host $line -ForegroundColor $color
    try {
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
        Add-Content -Path $logFile -Value $line
    } catch { <# logging must never block startup #> }
}

function Get-NewestWriteTime([string[]]$Paths) {
    $newest = [datetime]::MinValue
    foreach ($p in $Paths) {
        if (Test-Path $p -PathType Leaf) {
            $t = (Get-Item $p).LastWriteTime
            if ($t -gt $newest) { $newest = $t }
        } elseif (Test-Path $p -PathType Container) {
            $t = (Get-ChildItem $p -Recurse -File -ErrorAction SilentlyContinue |
                  Measure-Object -Property LastWriteTime -Maximum).Maximum
            if ($null -ne $t -and $t -gt $newest) { $newest = $t }
        }
    }
    return $newest
}

# ── Preconditions ────────────────────────────────────────────────────────

function Test-Preconditions {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
    if (-not $python) {
        Write-Launch "Python was not found on PATH. Install Python 3.10+ and reopen." "error"
        exit 1
    }
    Write-Launch "Python found: $($python.Source)" "ok"

    # Rustup installs cargo to ~/.cargo/bin but doesn't always persist that on
    # PATH for GUI/vbs-launched shells. Tauri build AND dev shell out to `cargo`
    # (cargo metadata), so make it reachable here -- otherwise the build dies
    # instantly with "cargo metadata ... program not found" and, under the
    # hidden vbs console, nothing but a bare "exit 1" reaches the log.
    if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
        $cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
        if (Test-Path (Join-Path $cargoBin "cargo.exe")) {
            $env:PATH = "$cargoBin;$env:PATH"
            Write-Launch "Added $cargoBin to PATH (cargo was not visible)." "warn"
        } else {
            Write-Launch "cargo (Rust) not found on PATH and not at $cargoBin. Install Rust via rustup (https://rustup.rs) to build." "error"
            exit 1
        }
    }

    # NOTE: no longer checking $exeParent ("target/release/") existence here.
    # On a fresh clone that directory does not exist yet -- it is CREATED by
    # the `npx tauri build` step in Invoke-BuildIfStale below (which already
    # handles the "no exe yet" case via its own `-not (Test-Path $exe)`
    # check). Hard-exiting on a missing directory that only the build itself
    # produces made a fresh clone unable to ever launch (B-6).
    $needsBuild = -not (Test-Path $exe)
    if ($needsBuild -and -not (Get-Command npx -ErrorAction SilentlyContinue)) {
        Write-Launch "No release binary found and 'npx' (Node.js) is missing -- cannot build. Install Node.js or run with OMNI_DEV=1." "error"
        exit 1
    }
}

function Test-AlreadyRunning {
    # If the app is already running, a second launch should no-op rather than
    # erroring -- the user likely double-clicked the launcher again.
    $existing = Get-Process -Name "second-thought" -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Launch "Second Thought is already running (PID $($existing[0].Id)). Exiting silently." "ok"
        exit 0
    }
}

function Test-Port7070 {
    # The Tauri app spawns its own Python backend bound to 7070 on startup
    # (see gui/src-tauri/src/lib.rs setup()). If something is already
    # listening there, a second instance would lose the port race and run
    # an orphaned, unauthenticated backend -- so abort instead of "fixing"
    # it by killing whatever holds the port.
    $listener = Get-NetTCPConnection -LocalPort 7070 -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        Write-Launch "Port 7070 is already in use (PID $($listener[0].OwningProcess)). Is Second Thought already running? Close it first." "error"
        exit 1
    }
}

# ── Build ────────────────────────────────────────────────────────────────

function Invoke-BuildIfStale {
    $needsBuild = $false

    if (-not (Test-Path $exe)) {
        Write-Launch "No release binary found - building..." "warn"
        $needsBuild = $true
    } else {
        $exeTime = (Get-Item $exe).LastWriteTime
        $srcTime = Get-NewestWriteTime -Paths $watchPaths
        if ($srcTime -gt $exeTime) {
            Write-Launch "GUI source changed ($srcTime > $exeTime) - rebuilding..." "warn"
            $needsBuild = $true
        } else {
            Write-Launch "Binary is up to date." "ok"
        }
    }

    if (-not $needsBuild) { return }

    Push-Location $gui
    # Capture the build's stdout+stderr to a file via cmd's own redirection.
    # Under launch.vbs the console is hidden, so without this a build failure
    # leaves only a bare "exit 1" with no cause -- the gap that made the
    # cargo/stale-cache failures hard to diagnose. cmd handles the redirect so
    # PowerShell never wraps native stderr in NativeCommandError records (which,
    # under the script-wide "Stop", would also flood the log with per-line
    # boilerplate around cargo's hundreds of progress lines). $LASTEXITCODE from
    # `cmd /c` is npx's own exit code.
    $buildOut = Join-Path $logDir "build-last.log"
    try {
        Write-Launch "Running: npx tauri build --no-bundle (full output -> $buildOut)"
        & cmd /c "npx tauri build --no-bundle > `"$buildOut`" 2>&1"
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if (Test-Path $buildOut) {
        $buildText = Get-Content $buildOut -Raw
        Write-Host $buildText
        Add-Content -Path $logFile -Value $buildText
    }
    if ($exitCode -ne 0) {
        Write-Launch "Build failed (exit $exitCode). Fix errors and retry." "error"
        exit 1
    }
    if (-not (Test-Path $exe)) {
        Write-Launch "Build reported success but $exe is missing." "error"
        exit 1
    }
    Write-Launch "Build complete." "ok"
}

# ── Launch ───────────────────────────────────────────────────────────────

function Start-DevMode {
    Write-Launch "Starting in dev mode: npx tauri dev" "warn"
    Push-Location $gui
    try {
        npx tauri dev
    } finally {
        Pop-Location
    }
}

function Wait-ForReady {
    # Best-effort liveness probe against the unauthenticated /health endpoint.
    # The console is hidden when launched via launch.vbs, so this is the only
    # way a failed Python backend (e.g. missing deps) gets logged anywhere.
    for ($i = 0; $i -lt 10; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:7070/health" -TimeoutSec 2 -UseBasicParsing
            if ($resp.StatusCode -eq 200) {
                Write-Launch "Backend ready after $([math]::Round(($i + 1) * 0.5, 1))s." "ok"
                return
            }
        } catch { <# not ready yet -- keep polling #> }
    }
    Write-Launch "Backend did not respond on /health within 5s -- it may still be starting, or Python deps may be missing." "warn"
}

function Start-App {
    # The Tauri app itself spawns and manages the Python backend on startup,
    # generating a fresh X-Omni-Secret for this session. Do NOT also start a
    # backend here -- a second uvicorn process would lose the port race
    # against the GUI's own instance, leaving the GUI's secret-equipped
    # server unbound and the unauthenticated one answering requests instead.
    Write-Launch "Launching Second Thought..." "ok"
    $app = Start-Process $exe -PassThru
    Wait-ForReady
    $app.WaitForExit()
    Write-Launch "Second Thought exited (code $($app.ExitCode))."
}

# ── Entry point ──────────────────────────────────────────────────────────

Write-Launch "==== launch.ps1 starting ===="
Test-AlreadyRunning
Test-Preconditions
Test-Port7070

$devMode = ($env:OMNI_DEV -eq "1") -or (-not (Get-Command npx -ErrorAction SilentlyContinue))
if ($env:OMNI_DEV -eq "1") {
    Write-Launch "OMNI_DEV=1 set - using dev mode." "warn"
} elseif ($devMode) {
    Write-Launch "'npx' not found - falling back to dev mode (requires Node.js)." "warn"
}

if ($devMode) {
    Start-DevMode
} else {
    Invoke-BuildIfStale
    Start-App
}

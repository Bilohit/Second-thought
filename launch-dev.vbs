' launch-dev.vbs - Dev entry point: runs launch.ps1 in dev mode (npx tauri dev)
' with a VISIBLE console, so Vite/Tauri/Rust output and hot-reload logs are
' readable. Double-click this during active development.
'
' Difference from launch.vbs: that one hides its window and runs the
' compiled release .exe (building it first if GUI sources changed) -- built
' for "just run the app." This one sets OMNI_DEV=1 and keeps the window
' open, running `npx tauri dev`: Vite hot-reloads TS/React instantly, Rust
' recompiles incrementally only when .rs/tauri.conf.json change, and Python
' runs straight from source via uvicorn -- no compile step for either.

Dim shell, scriptDir, psScript
Set shell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
psScript = """" & scriptDir & "\launch.ps1" & """"

shell.Environment("Process")("OMNI_DEV") = "1"
shell.Run "powershell -NoProfile -WindowStyle Normal -ExecutionPolicy Bypass -File " & psScript, 1, False

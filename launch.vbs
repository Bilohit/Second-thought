' launch.vbs - Recommended entry point: runs launch.ps1 with no visible console
' window (neither a cmd box nor a PowerShell box flashes up). Double-click this
' file, or point a shortcut/Start Menu tile/Run-on-login entry at it.
'
' Errors still go to logs\launch-<date>.log (see launch.ps1's Write-Launch),
' so failures are diagnosable even though nothing is printed to screen.

Dim shell, scriptDir, psScript
Set shell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
psScript = """" & scriptDir & "\launch.ps1" & """"

shell.Run "powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File " & psScript, 0, False

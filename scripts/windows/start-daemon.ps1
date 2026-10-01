# Starts the Latch warm daemon in background
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..\..")

Push-Location $ProjectRoot
try {
    & "$ProjectRoot\.venv\Scripts\python.exe" -m latch.cli daemon start
}
finally {
    Pop-Location
}

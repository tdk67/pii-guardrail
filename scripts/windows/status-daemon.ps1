# Checks the status of the Latch warm daemon
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..\..")

Push-Location $ProjectRoot
try {
    & .\.venv\Scripts\python.exe -m latch.cli daemon status
}
finally {
    Pop-Location
}

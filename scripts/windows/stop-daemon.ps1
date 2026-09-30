# Stops the running Latch daemon
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..\..")

Push-Location $ProjectRoot
try {
    & .\.venv\Scripts\python.exe -m latch.cli daemon stop
}
finally {
    Pop-Location
}

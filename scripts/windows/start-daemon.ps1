# Starts the Latch warm daemon in background
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..\..")

Push-Location $ProjectRoot
try {
    Write-Host "Starting Latch background daemon on 127.0.0.1:5138..."
    Start-Process -FilePath "$ProjectRoot\.venv\Scripts\python.exe" -ArgumentList "-m latch.daemon" -WorkingDirectory $ProjectRoot -WindowStyle Hidden
    Start-Sleep -Seconds 2
    Write-Host "[OK] Latch daemon process launched. Pre-warming weights..."
}
finally {
    Pop-Location
}

<#
.SYNOPSIS
    Realistic Git Branch & Merge Simulation Runner for Latch.
.DESCRIPTION
    Creates temporary base and feature branches, merges a 9-file enterprise microservices
    PR with unit tests and customer synchronization PII, demonstrates the pre-commit block,
    remediates, commits cleanly, and deletes the test branches.
#>

$ErrorActionPreference = "Stop"

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host " [DEMO] Running Realistic Git Branch Merge Simulation" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan

# Pre-flight Check: Hook Installation
$hookPath = ".git/hooks/pre-commit"
if (-not (Test-Path $hookPath) -or -not (Select-String -Path $hookPath -Pattern "Latch" -SimpleMatch -Quiet)) {
    Write-Host "[WARN] Latch pre-commit hook not detected. Installing hook..." -ForegroundColor Yellow
    .\.venv\Scripts\python -m latch.cli install
} else {
    Write-Host "[OK] Latch pre-commit hook is verified and active." -ForegroundColor Green
}

# Pre-flight Check: Daemon Health
try {
    $probe = Invoke-RestMethod -Uri "http://127.0.0.1:5138/v1/health" -Method Get -TimeoutSec 2
    Write-Host "[OK] Latch daemon is active on 127.0.0.1:5138" -ForegroundColor Green
} catch {
    Write-Host "[WARN] Latch daemon not running. Starting in background..." -ForegroundColor Yellow
    powershell -ExecutionPolicy Bypass -File "scripts/windows/start-daemon.ps1"
    Start-Sleep -Seconds 3
}

# Run the Python simulation engine
.\.venv\Scripts\python scripts/demo/simulate_git_pr_workflow.py

Write-Host ""
Write-Host "================================================================================" -ForegroundColor Green
Write-Host " [DEMO COMPLETE] Simulation finished successfully. Git is back on main." -ForegroundColor Green
Write-Host "================================================================================" -ForegroundColor Green

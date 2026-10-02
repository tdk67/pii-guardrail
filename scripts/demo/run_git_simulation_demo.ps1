<#
.SYNOPSIS
    Realistic Git Branch & Merge Simulation Runner for Latch.
.DESCRIPTION
    Creates temporary base and feature branches from real git history (88d16a9 -> 8df97dd),
    merges them to produce a realistic 12-file, 464-line multi-chunk diff, injects PII,
    demonstrates the pre-commit block, remediates, commits cleanly, and deletes the test branches.
#>

$ErrorActionPreference = "Stop"

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host " [DEMO] Running Realistic Git Branch Merge Simulation" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan

# Check daemon health first
try {
    $probe = Invoke-RestMethod -Uri "http://127.0.0.1:5138/health" -Method Get -TimeoutSec 2
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

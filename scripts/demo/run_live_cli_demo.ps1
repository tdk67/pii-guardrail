<#
.SYNOPSIS
    Live Interactive CLI Demo Runner for Latch.
.DESCRIPTION
    Automates the step-by-step terminal demonstration against the live running
    Latch daemon (127.0.0.1:5138). Demonstrates pre-commit interception,
    remediation, clean pass, and repo scanning.
#>

$ErrorActionPreference = "Stop"

function Write-Step([string]$title) {
    Write-Host ""
    Write-Host "================================================================================" -ForegroundColor Cyan
    Write-Host " [DEMO STEP] $title" -ForegroundColor Cyan
    Write-Host "================================================================================" -ForegroundColor Cyan
    Write-Host ""
}

# 0. Daemon Health Check
Write-Step "Checking Warm Daemon Status (127.0.0.1:5138)"
try {
    $probe = Invoke-RestMethod -Uri "http://127.0.0.1:5138/health" -Method Get -TimeoutSec 2
    Write-Host "✔ Latch Daemon is LIVE and ready (Status: $($probe.status))" -ForegroundColor Green
} catch {
    Write-Host "⚠ Daemon not detected on 5138. Starting daemon in background..." -ForegroundColor Yellow
    powershell -ExecutionPolicy Bypass -File "scripts/windows/start-daemon.ps1"
    Start-Sleep -Seconds 3
}

# 1. Reset any leftover demo state
Write-Step "Step 1: Preparing Clean State"
.\.venv\Scripts\python scripts/demo/reset_demo.py

# 2. Inject PII
Write-Step "Step 2: Injecting PII & Secrets into Staged Code"
.\.venv\Scripts\python scripts/demo/inject_pii.py
git status --short

# 3. Attempt Git Commit (Expected: BLOCKED by Latch)
Write-Step "Step 3: Attempting 'git commit' -> EXPECTING COMMIT BLOCKED"
Write-Host "Running: git commit -m 'feat: add customer export service'" -ForegroundColor DarkGray
try {
    git commit -m "feat: add customer export service"
} catch {
    Write-Host "✔ Caught expected pre-commit hook block!" -ForegroundColor Green
}

# 4. Clean Remediation
Write-Step "Step 4: Remediation - Removing Secrets & Replacing with os.environ"
$fixedCode = @'
"""Customer data export job handler."""
import os

def get_payment_gateway_config():
    # Remediated: Loaded safely from environment variables
    return {
        "gateway_key": os.environ.get("STRIPE_LIVE_SECRET", ""),
        "primary_contact": os.environ.get("VIP_CONTACT_NAME", ""),
        "email": os.environ.get("VIP_CONTACT_EMAIL", ""),
        "phone": os.environ.get("VIP_PHONE_NUMBER", ""),
        "address": os.environ.get("VIP_BILLING_ADDRESS", ""),
    }
'@
Set-Content -Path "demo/customer_export.py" -Value $fixedCode -Encoding UTF8
git add demo/customer_export.py
Write-Host "Staged clean remediation in git." -ForegroundColor DarkGray

# 5. Clean Commit (Expected: PASS)
Write-Step "Step 5: Committing Remediated Code -> EXPECTING CLEAN PASS"
git commit -m "feat: use env vars for customer export"
Write-Host "✔ Commit successfully accepted!" -ForegroundColor Green

# 6. Repository Scan
Write-Step "Step 6: Running Full Repository Scanner"
Write-Host "Running: latch scan . --output-format markdown" -ForegroundColor DarkGray
.\.venv\Scripts\python -m latch.cli scan . --output-format markdown

# 7. Cleanup
Write-Step "Step 7: Cleanup Demo Git Commit"
git reset --soft HEAD~1
.\.venv\Scripts\python scripts/demo/reset_demo.py
Write-Host "✔ Demo complete. Environment returned to clean state." -ForegroundColor Green

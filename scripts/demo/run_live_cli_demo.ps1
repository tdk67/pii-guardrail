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

# Pre-flight Check: Hook Installation
Write-Step "Checking Pre-Commit Hook Installation"
$hookPath = ".git/hooks/pre-commit"
if (-not (Test-Path $hookPath) -or -not (Select-String -Path $hookPath -Pattern "Latch" -SimpleMatch -Quiet)) {
    Write-Host "⚠ Latch pre-commit hook not detected. Installing hook..." -ForegroundColor Yellow
    .\.venv\Scripts\python -m latch.cli install
} else {
    Write-Host "✔ Latch pre-commit hook is verified and active." -ForegroundColor Green
}

# Pre-flight Check: Daemon Health
Write-Step "Checking Warm Daemon Status (127.0.0.1:5138)"
try {
    $probe = Invoke-RestMethod -Uri "http://127.0.0.1:5138/v1/health" -Method Get -TimeoutSec 2
    Write-Host "✔ Latch Daemon is LIVE and ready (Status: $($probe.status))" -ForegroundColor Green
} catch {
    Write-Host "⚠ Daemon not detected on 5138. Starting daemon in background..." -ForegroundColor Yellow
    powershell -ExecutionPolicy Bypass -File "scripts/windows/start-daemon.ps1"
    Start-Sleep -Seconds 3
}

# Record starting commit SHA to ensure guaranteed clean rollback
$initialSha = (git rev-parse HEAD).Trim()

try {
    # 1. Reset any leftover demo state
    Write-Step "Step 1: Preparing Clean State"
    .\.venv\Scripts\python scripts/demo/reset_demo.py

    # 2. Inject PII
    Write-Step "Step 2: Injecting PII & Secrets into Staged Code"
    .\.venv\Scripts\python scripts/demo/inject_pii.py
    git status --short

    # 2b. Pre-commit guard verification (Fail-fast self check)
    Write-Host "Running pre-flight guardrail self-check..." -ForegroundColor DarkGray
    $checkProc = Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-m", "latch.cli", "check" -NoNewWindow -Wait -PassThru
    if ($checkProc.ExitCode -eq 0) {
        Write-Host "❌ ERROR: Model failed to flag injected PII! Aborting commit to protect repository." -ForegroundColor Red
        exit 1
    }
    Write-Host "✔ Self-check confirmed: Latch detected sensitive data (exit code 1)." -ForegroundColor Green

    # 3. Attempt Git Commit (Expected: BLOCKED by Latch)
    Write-Step "Step 3: Attempting 'git commit' -> EXPECTING COMMIT BLOCKED"
    Write-Host "Running: git commit -m 'feat: add customer export service'" -ForegroundColor DarkGray
    $commitProc = Start-Process -FilePath "git" -ArgumentList "commit", "-m", "feat: add customer export service" -NoNewWindow -Wait -PassThru
    if ($commitProc.ExitCode -ne 0) {
        Write-Host "✔ Caught expected pre-commit hook block! Exit code: $($commitProc.ExitCode)" -ForegroundColor Green
    } else {
        Write-Host "❌ UNEXPECTED: Commit succeeded when it should have been blocked!" -ForegroundColor Red
        exit 1
    }

    # 4. Clean Remediation
    Write-Step "Step 4: Remediation - Removing Secrets & Replacing with os.environ"
    $fixedCode = @'
"""Customer data export job handler."""
import os

def get_user_contact():
    # Safely loaded from environment variables
    customer_name = os.environ.get("CUSTOMER_NAME", "")
    customer_phone = os.environ.get("CUSTOMER_PHONE", "")
    customer_email = os.environ.get("CUSTOMER_EMAIL", "")
    return {"name": customer_name, "phone": customer_phone, "email": customer_email}


def get_payment_auth():
    # Safely loaded from environment variables
    auth_token = os.environ.get("PAYMENT_AUTH_TOKEN", "")
    return auth_token
'@
    Set-Content -Path "demo/customer_export.py" -Value $fixedCode -Encoding UTF8
    git add demo/customer_export.py
    Write-Host "Staged clean remediation in git." -ForegroundColor DarkGray

    # 5. Clean Commit (Expected: PASS)
    Write-Step "Step 5: Committing Remediated Code -> EXPECTING CLEAN PASS"
    $cleanCommitProc = Start-Process -FilePath "git" -ArgumentList "commit", "-m", "feat: use env vars for customer export" -NoNewWindow -Wait -PassThru
    if ($cleanCommitProc.ExitCode -eq 0) {
        Write-Host "✔ Commit successfully accepted by Latch!" -ForegroundColor Green
    } else {
        Write-Host "❌ Clean commit unexpectedly failed!" -ForegroundColor Red
        exit 1
    }

    # 6. Repository Scan
    Write-Step "Step 6: Running Full Repository Scanner"
    Write-Host "Running: latch scan ." -ForegroundColor DarkGray
    .\.venv\Scripts\python -m latch.cli scan .

} finally {
    # 7. Cleanup: Guaranteed rollback to starting commit SHA
    Write-Step "Step 7: Guaranteed Rollback to Clean State"
    git reset --hard $initialSha
    .\.venv\Scripts\python scripts/demo/reset_demo.py
    Write-Host "✔ Demo complete. Environment returned to clean initial state ($initialSha)." -ForegroundColor Green
}

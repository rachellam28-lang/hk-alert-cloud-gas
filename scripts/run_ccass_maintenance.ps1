[CmdletBinding()]
param([int]$RequestBudget = 1200)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$LogDir = Join-Path $RepoRoot "logs\automation"
$Mutex = $null
$HasMutex = $false

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir ("ccass_maintenance_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
Start-Transcript -Path $LogFile -Append | Out-Null

try {
    $Mutex = [System.Threading.Mutex]::new($false, "Local\HKAlertDailyAutomation")
    $HasMutex = $Mutex.WaitOne(0)
    if (-not $HasMutex) {
        Write-Host "Daily refresh or another maintenance run is active; skip without touching the DB"
        exit 75
    }

    Set-Location $RepoRoot
    $env:HOLDINGS_ULTRA_FAST = "1"
    $env:FILL_TIMEOUT = "20"
    $env:FILL_RETRIES = "1"
    $env:SENTRY_CRON_DISABLED = "1"

    & $Python (Join-Path $RepoRoot "ccass\scripts\hkex_gap_backfill.py") `
        --auto --request-budget $RequestBudget --target-coverage 0.99
    if ($LASTEXITCODE -ne 0) { throw "CCASS maintenance exited $LASTEXITCODE" }

    & $Python (Join-Path $RepoRoot "scripts\repo_audit.py") export --threshold 99
    if ($LASTEXITCODE -ne 0) { throw "Repo audit export exited $LASTEXITCODE" }
    exit 0
} catch {
    Write-Host "CCASS MAINTENANCE FAILED: $($_.Exception.Message)"
    exit 1
} finally {
    if ($HasMutex -and $Mutex) { $Mutex.ReleaseMutex() }
    if ($Mutex) { $Mutex.Dispose() }
    try { Stop-Transcript | Out-Null } catch {}
}

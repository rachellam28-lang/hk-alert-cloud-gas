[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Probe = Join-Path $RepoRoot "scripts\check_futu_setup.py"
$Starter = Join-Path $RepoRoot "scripts\start_futu_opend_rs.py"
$Mutex = [System.Threading.Mutex]::new($false, "Local\HKAlertFutuWatchdog")
$locked = $false

try {
    $locked = $Mutex.WaitOne(0)
    if (-not $locked) { exit 0 }
    Set-Location $RepoRoot

    & $Python $Probe
    if ($LASTEXITCODE -eq 0) { exit 0 }

    # A listening socket is not enough: the gateway can stay alive after its
    # upstream quote session dies. Replace that unhealthy process so the new
    # instance can bind 11111 and re-establish the backend session.
    & $Python $Starter --stop-existing --background
    if ($LASTEXITCODE -ne 0) { exit 1 }
    for ($attempt = 1; $attempt -le 12; $attempt++) {
        Start-Sleep -Seconds 5
        & $Python $Probe
        if ($LASTEXITCODE -eq 0) { exit 0 }
    }
    exit 1
} finally {
    if ($locked) { $Mutex.ReleaseMutex() }
    $Mutex.Dispose()
}

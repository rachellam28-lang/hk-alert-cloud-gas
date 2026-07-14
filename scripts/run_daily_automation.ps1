[CmdletBinding()]
param(
    [switch]$PreflightOnly,
    [switch]$SkipRefresh,
    [switch]$SkipDeploy,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LogDir = Join-Path $RepoRoot "logs\automation"
$StateFile = Join-Path $LogDir "last_success.json"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Bash = "C:\Program Files\Git\bin\bash.exe"
$CanonicalBase = "https://hk-alert-cloud-gas.pages.dev"
$Mutex = $null
$HasMutex = $false

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir ("daily_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
Start-Transcript -Path $LogFile -Append | Out-Null

function Write-Step([string]$Message) {
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message)
}

function Import-RepoEnv {
    $path = Join-Path $RepoRoot ".env"
    if (-not (Test-Path -LiteralPath $path)) { return }
    foreach ($line in Get-Content -LiteralPath $path -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) { continue }
        $name, $value = $trimmed.Split("=", 2)
        $name = $name.Trim()
        if ($name -notmatch "^[A-Za-z_][A-Za-z0-9_]*$") { continue }
        $value = $value.Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}

function Test-TcpPort([string]$HostName, [int]$Port, [int]$TimeoutMs = 1500) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $result = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $result.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { return $false }
        $client.EndConnect($result)
        return $true
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Invoke-Native([string]$Name, [scriptblock]$Command, [switch]$AllowFailure) {
    Write-Step $Name
    & $Command | ForEach-Object { Write-Host $_ }
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 0 }
    if ($code -ne 0 -and -not $AllowFailure) {
        throw "$Name failed with exit code $code"
    }
    return [int]$code
}

function Ensure-Futu {
    $hostName = if ($env:FUTU_HOST) { $env:FUTU_HOST } else { "127.0.0.1" }
    $port = if ($env:FUTU_PORT) { [int]$env:FUTU_PORT } else { 11111 }
    $probe = Join-Path $RepoRoot "scripts\check_futu_setup.py"
    $starter = Join-Path $RepoRoot "scripts\start_futu_opend_rs.py"

    if (Test-TcpPort $hostName $port) {
        & $Python $probe
        if ($LASTEXITCODE -eq 0) {
            Write-Step "Futu OpenD is ready at ${hostName}:${port}"
            return $true
        }
    }

    Write-Step "Futu OpenD is unavailable; starting the local gateway"
    & $Python $starter --background
    for ($attempt = 1; $attempt -le 12; $attempt++) {
        Start-Sleep -Seconds 5
        if (-not (Test-TcpPort $hostName $port)) { continue }
        & $Python $probe
        if ($LASTEXITCODE -eq 0) {
            Write-Step "Futu OpenD started and quote verification passed"
            return $true
        }
    }
    Write-Step "WARN: Futu did not become quote-ready; the refresh will use Longbridge fallback"
    return $false
}

function Invoke-WithRetry([string]$Name, [int]$Attempts, [scriptblock]$Command) {
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        Write-Step "$Name attempt $attempt/$Attempts"
        & $Command | ForEach-Object { Write-Host $_ }
        $code = $LASTEXITCODE
        if ($null -eq $code) { $code = 0 }
        if ($code -eq 0) { return }
        if ($attempt -lt $Attempts) { Start-Sleep -Seconds (15 * $attempt) }
    }
    throw "$Name failed after $Attempts attempts"
}

function Get-PublishBundle {
    $path = Join-Path $RepoRoot "data\publish_bundle.json"
    if (-not (Test-Path -LiteralPath $path)) { throw "publish_bundle.json is missing" }
    return Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Assert-Publishable($Bundle) {
    $status = [string]$Bundle.publish.status
    if ($status -notin @("PASS", "WARN")) {
        throw "Publish gate rejected status '$status'; Cloudflare deploy blocked"
    }
    if (-not $Bundle.generated_at) { throw "Publish bundle has no generated_at" }
    Write-Step "Publish gate accepted $status (generated $($Bundle.generated_at))"
}

function Test-LiveBundle([string]$ExpectedGeneratedAt) {
    for ($attempt = 1; $attempt -le 8; $attempt++) {
        try {
            $uri = "$CanonicalBase/data/publish_bundle.json?automation=$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
            $live = Invoke-RestMethod -Uri $uri -TimeoutSec 25 -Headers @{ "Cache-Control" = "no-cache" }
            if ([string]$live.generated_at -eq $ExpectedGeneratedAt) {
                Write-Step "Canonical Cloudflare verification passed: $ExpectedGeneratedAt"
                return
            }
            Write-Step "Cloudflare still serves $($live.generated_at); waiting for canonical propagation"
        } catch {
            Write-Step "Cloudflare verification attempt $attempt failed: $($_.Exception.Message)"
        }
        Start-Sleep -Seconds 12
    }
    throw "Canonical Cloudflare bundle did not match $ExpectedGeneratedAt"
}

try {
    $Mutex = [System.Threading.Mutex]::new($false, "Local\HKAlertDailyAutomation")
    $HasMutex = $Mutex.WaitOne(0)
    if (-not $HasMutex) {
        Write-Step "Another refresh is already running; this trigger exits without touching the DB"
        exit 75
    }

    Set-Location $RepoRoot
    Import-RepoEnv

    if (-not $Force -and -not $PreflightOnly -and -not $SkipRefresh -and (Test-Path -LiteralPath $StateFile)) {
        try {
            $state = Get-Content -LiteralPath $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json
            if ([string]$state.local_date -eq (Get-Date -Format "yyyy-MM-dd")) {
                Write-Step "Today's full refresh already succeeded at $($state.completed_at); retry trigger skipped"
                exit 0
            }
        } catch {
            Write-Step "WARN: unreadable success state; running the refresh"
        }
    }

    if (-not (Test-Path -LiteralPath $Python)) { throw "Repo Python not found: $Python" }
    if (-not (Test-Path -LiteralPath $Bash)) { throw "Git Bash not found: $Bash" }
    if (-not (Get-Command longbridge -ErrorAction SilentlyContinue)) { throw "Longbridge CLI is not installed" }
    if (-not (Get-Command npx -ErrorAction SilentlyContinue)) { throw "npx/Wrangler is not installed" }

    $futuReady = Ensure-Futu
    Invoke-Native "Verify Longbridge fallback with live NVDA quote" { longbridge quote NVDA.US } | Out-Null
    if (-not $SkipDeploy) {
        Invoke-Native "Verify Cloudflare Wrangler OAuth" { npx wrangler whoami } | Out-Null
    }

    if ($PreflightOnly) {
        Write-Step "Preflight passed"
        exit 0
    }

    if (-not $SkipRefresh) {
        $env:AUTO_STAGE_REFRESHED_FILES = "0"
        $env:FUTU_PRICE_TIMEOUT_SECONDS = if ($futuReady) { "180" } else { "12" }
        $env:HOLDINGS_PROVIDER = if ($env:HOLDINGS_PROVIDER) { $env:HOLDINGS_PROVIDER } else { "longbridge" }
        $bashRoot = $RepoRoot.Replace("\", "/").Replace("C:", "/c")
        Invoke-Native "Run complete daily refresh" { & $Bash -lc "cd '$bashRoot' && ./ccass/scripts/daily_refresh.sh" } | Out-Null
    }

    $bundle = Get-PublishBundle
    Assert-Publishable $bundle

    $healthRc = Invoke-Native "Generate health snapshot and Hermes summary" { & $Python (Join-Path $RepoRoot "scripts\health_check.py") --telegram } -AllowFailure
    if ($healthRc -ne 0) {
        throw "Health gate contains a red data/integrity item; Cloudflare deploy blocked"
    }
    $healthPath = Join-Path $RepoRoot "health.json"
    $health = Get-Content -LiteralPath $healthPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$health.overall_status -eq "FAIL") {
        throw "Health gate reported FAIL; Cloudflare deploy blocked"
    }

    if (-not $SkipDeploy) {
        $deployScript = Join-Path $RepoRoot "ccass\scripts\_deploy_cf.py"
        Invoke-WithRetry "Direct Cloudflare Pages deploy" 3 { & $Python $deployScript --dir $RepoRoot }
        Test-LiveBundle ([string]$bundle.generated_at)
    }

    if (-not $SkipRefresh) {
        [ordered]@{
            local_date = Get-Date -Format "yyyy-MM-dd"
            completed_at = (Get-Date).ToString("o")
            publish_status = [string]$bundle.publish.status
            bundle_generated_at = [string]$bundle.generated_at
            futu_ready = $futuReady
            deployed = -not $SkipDeploy
        } | ConvertTo-Json | Set-Content -LiteralPath $StateFile -Encoding UTF8
    }
    Write-Step "Automation completed successfully"
    exit 0
} catch {
    Write-Step "AUTOMATION FAILED: $($_.Exception.Message)"
    exit 1
} finally {
    if ($HasMutex -and $Mutex) { $Mutex.ReleaseMutex() }
    if ($Mutex) { $Mutex.Dispose() }
    try { Stop-Transcript | Out-Null } catch {}
}

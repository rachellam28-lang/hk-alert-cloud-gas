param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Symbol,
    [switch]$Verify,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$VibeRoot = Join-Path $Root '.tools\vibe-trading'
$Python = Join-Path $VibeRoot '.venv\Scripts\python.exe'
$Bridge = Join-Path $Root 'scripts\vibe_ccass_bridge.py'

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Vibe-Trading is not installed at $Python"
}

$env:HOME = Join-Path $VibeRoot 'home'
$env:USERPROFILE = $env:HOME
$Arguments = @($Bridge, $Symbol)
if ($Verify) { $Arguments += '--verify' }
if ($Json) { $Arguments += '--json' }

& $Python @Arguments
exit $LASTEXITCODE

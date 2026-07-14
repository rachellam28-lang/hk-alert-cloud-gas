[CmdletBinding()]
param(
    [string]$RefreshTask = "HKAlert-DailyRefresh",
    [string]$FutuTask = "HKAlert-FutuOpenD"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PowerShell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Runner = Join-Path $RepoRoot "scripts\run_daily_automation.ps1"
$FutuWatchdog = Join-Path $RepoRoot "scripts\ensure_futu_opend.ps1"
$UserId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

foreach ($path in @($PowerShell, $Python, $Runner, $FutuWatchdog)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required automation path is missing: $path" }
}

$refreshAction = New-ScheduledTaskAction `
    -Execute $PowerShell `
    -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $Runner) `
    -WorkingDirectory $RepoRoot
$refreshTriggers = @(
    (New-ScheduledTaskTrigger -Daily -At "18:30"),
    (New-ScheduledTaskTrigger -Daily -At "22:00")
)
$principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Hours 5) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $RefreshTask `
    -Action $refreshAction `
    -Trigger $refreshTriggers `
    -Principal $principal `
    -Settings $settings `
    -Description "Refresh all CCASS pages, audit real data, and deploy directly to Cloudflare. 22:00 is a same-day retry only." `
    -Force | Out-Null

$futuAction = New-ScheduledTaskAction `
    -Execute $PowerShell `
    -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $FutuWatchdog) `
    -WorkingDirectory $RepoRoot
$futuTriggers = @(
    (New-ScheduledTaskTrigger -AtLogOn -User $UserId),
    (New-ScheduledTaskTrigger -Daily -At "08:30"),
    (New-ScheduledTaskTrigger -Daily -At "12:30"),
    (New-ScheduledTaskTrigger -Daily -At "17:45")
)
$futuSettings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 3) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $FutuTask `
    -Action $futuAction `
    -Trigger $futuTriggers `
    -Principal $principal `
    -Settings $futuSettings `
    -Description "Keep the local Futu OpenD quote gateway healthy; start it only when the real quote probe fails." `
    -Force | Out-Null

Get-ScheduledTask -TaskName $FutuTask, $RefreshTask | ForEach-Object {
    $info = Get-ScheduledTaskInfo -TaskName $_.TaskName
    [pscustomobject]@{
        TaskName = $_.TaskName
        State = $_.State
        NextRunTime = $info.NextRunTime
        LastTaskResult = $info.LastTaskResult
        User = $_.Principal.UserId
    }
} | Format-Table -AutoSize

# register_injury_snapshot_task.ps1
# Registers the Task Scheduler job that archives the official NBA injury report every 30 minutes
# from 11:00 to 23:00 (laptop local time, US Eastern). It is separate from NBA-Predictor-Daily and runs
# scheduler\run_injury_snapshot.bat of the checkout this script lives in (or of -RepoRoot).
#
# Usage (run once, as the user who owns the checkout):
#   powershell -ExecutionPolicy Bypass -File scheduler\register_injury_snapshot_task.ps1
#   powershell -ExecutionPolicy Bypass -File scheduler\register_injury_snapshot_task.ps1 -RepoRoot C:\path\to\checkout
#
# Remove:   Unregister-ScheduledTask -TaskName "NBA-Predictor-Injury-Snapshot" -Confirm:$false
# Test run: Start-ScheduledTask -TaskName "NBA-Predictor-Injury-Snapshot"

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)),
    [string]$TaskName = "NBA-Predictor-Injury-Snapshot",
    [string]$Start = "11:00AM",
    [int]$EveryMinutes = 30,
    [int]$ForHours = 12
)

$batPath = Join-Path $RepoRoot "scheduler\run_injury_snapshot.bat"
if (-not (Test-Path $batPath)) { throw "Not found: $batPath" }

$vbsPath = Join-Path $RepoRoot "scheduler\run_hidden.vbs"
$action  = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "//B //Nologo `"$vbsPath`" `"$batPath`"" -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $Start
$repeat  = New-ScheduledTaskTrigger -Once -At $Start `
    -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) `
    -RepetitionDuration (New-TimeSpan -Hours $ForHours)
$trigger.Repetition = $repeat.Repetition
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances IgnoreNew

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Set-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings | Out-Null
    Write-Host "Updated Task Scheduler job: $TaskName"
} else {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Description "NBA Predictor: archive the official NBA injury report every $EveryMinutes minutes" | Out-Null
    Write-Host "Registered Task Scheduler job: $TaskName"
}
Write-Host "  Runs : $batPath"
Write-Host "  When : daily from $Start, every $EveryMinutes min for $ForHours h"
Write-Host "  Log  : $(Join-Path $RepoRoot 'logs\injury_snapshot.log')"

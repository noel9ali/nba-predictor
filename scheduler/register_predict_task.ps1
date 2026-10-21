# register_predict_task.ps1
# Registers the predict stage: injury snapshot + predictions + picks SMS, every 15 minutes from 10:05 to 22:05
# (laptop local time, US Eastern). The :05/:20/:35/:50 offsets sit just after the NBA's 15-minute report slots and
# never collide with the injury-snapshot task (:00/:30), which writes the same sqlite file. Each run prices only
# games that tip within the next 75 minutes and have no prediction yet, so every game is priced 60-75 minutes before
# its tip with the newest injury report; a run with nothing to price exits quietly (no SMS, no log row, no odds
# request, no Elo/games table reads).
# NBA-Predictor-Daily (6:00 AM) is the morning stage: pipeline, settle yesterday, results SMS.
#
# Usage (run once, as the user who owns the checkout):
#   powershell -ExecutionPolicy Bypass -File scheduler\register_predict_task.ps1
#
# Remove:   Unregister-ScheduledTask -TaskName "NBA-Predictor-Predict" -Confirm:$false
# Test run: Start-ScheduledTask -TaskName "NBA-Predictor-Predict"   (talks to live Supabase; sends an SMS if it prices a game)

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)),
    [string]$TaskName = "NBA-Predictor-Predict",
    [string]$Start = "10:05AM",
    [int]$EveryMinutes = 15,
    [int]$ForHours = 12
)

$batPath = Join-Path $RepoRoot "scheduler\run_predict_stage.bat"
if (-not (Test-Path $batPath)) { throw "Not found: $batPath" }

$action  = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$batPath`"" -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $Start
$repeat  = New-ScheduledTaskTrigger -Once -At $Start `
    -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) `
    -RepetitionDuration (New-TimeSpan -Hours $ForHours)
$trigger.Repetition = $repeat.Repetition
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 14) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances IgnoreNew

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Set-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings | Out-Null
    Write-Host "Updated Task Scheduler job: $TaskName"
} else {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Description "NBA Predictor: price each game shortly before tip, after the newest injury report" | Out-Null
    Write-Host "Registered Task Scheduler job: $TaskName"
}
Write-Host "  Runs : $batPath"
Write-Host "  When : daily from $Start, every $EveryMinutes min for $ForHours h"
Write-Host "  Log  : $(Join-Path $RepoRoot 'logs\workflow.log')"

# register_predict_task.ps1
# Registers the evening predict stage: injury snapshot + predictions + picks SMS, after the evening NBA injury
# reports are out, so the availability model sees game-day statuses. Fires at 5:15 PM and again at 6:00 PM
# (laptop local time, US Eastern); a run that finds every game already predicted does nothing.
# NBA-Predictor-Daily (6:00 AM) becomes the morning stage: pipeline, settle yesterday, results SMS.
#
# Usage (run once, as the user who owns the checkout):
#   powershell -ExecutionPolicy Bypass -File scheduler\register_predict_task.ps1
#
# Remove:   Unregister-ScheduledTask -TaskName "NBA-Predictor-Predict" -Confirm:$false
# Test run: Start-ScheduledTask -TaskName "NBA-Predictor-Predict"   (talks to live Supabase and sends an SMS)

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)),
    [string]$TaskName = "NBA-Predictor-Predict",
    [string]$First = "5:15PM",
    [string]$Retry = "6:00PM"
)

$batPath = Join-Path $RepoRoot "scheduler\run_predict_stage.bat"
if (-not (Test-Path $batPath)) { throw "Not found: $batPath" }

$action   = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$batPath`"" -WorkingDirectory $RepoRoot
$triggers = @((New-ScheduledTaskTrigger -Daily -At $First), (New-ScheduledTaskTrigger -Daily -At $Retry))
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 45) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances IgnoreNew

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Set-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Settings $settings | Out-Null
    Write-Host "Updated Task Scheduler job: $TaskName"
} else {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Settings $settings `
        -Description "NBA Predictor: evening predict stage (after the injury reports)" | Out-Null
    Write-Host "Registered Task Scheduler job: $TaskName"
}
Write-Host "  Runs : $batPath"
Write-Host "  When : daily at $First, retry at $Retry"
Write-Host "  Log  : $(Join-Path $RepoRoot 'logs\workflow.log')"

# task_scheduler_setup.ps1
# Registers a Windows Task Scheduler job that runs the NBA Predictor daily workflow
# at 6:00 AM every day.
#
# Usage (run once as Administrator):
#   powershell -ExecutionPolicy Bypass -File scheduler\task_scheduler_setup.ps1
#
# To remove the task:
#   Unregister-ScheduledTask -TaskName "NBA-Predictor-Daily" -Confirm:$false

$taskName   = "NBA-Predictor-Daily"
$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot   = Split-Path -Parent $scriptDir
$batPath    = Join-Path $scriptDir "run_daily.bat"
$logsDir    = Join-Path $repoRoot "logs"

# Ensure logs directory exists
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
    Write-Host "Created logs directory: $logsDir"
}

# Build the scheduled task
$action  = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$batPath`""
$trigger = New-ScheduledTaskTrigger -Daily -At "06:00AM"
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartCount 1 `
    -RestartInterval (New-TimeSpan -Minutes 30) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

# Register (or update) the task
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Set-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings
    Write-Host "✓ Updated existing Task Scheduler job: $taskName"
} else {
    Register-ScheduledTask `
        -TaskName  $taskName `
        -Action    $action `
        -Trigger   $trigger `
        -Settings  $settings `
        -RunLevel  Highest `
        -Description "NBA Predictor: runs pipeline + predictions + SMS summary daily at 6 AM"
    Write-Host "✓ Registered new Task Scheduler job: $taskName"
}

Write-Host ""
Write-Host "Task details:"
Write-Host "  Name    : $taskName"
Write-Host "  Trigger : Daily at 06:00 AM"
Write-Host "  Action  : $batPath"
Write-Host "  Log     : $logsDir\workflow.log"
Write-Host ""
Write-Host "To run immediately for testing:"
Write-Host "  Start-ScheduledTask -TaskName '$taskName'"

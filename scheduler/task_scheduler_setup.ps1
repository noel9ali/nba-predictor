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
$description = "NBA Predictor: 6 AM morning stage (collect, settle, features, temporary picks, results push and email)"
$vbsPath   = Join-Path $scriptDir "run_hidden.vbs"
$action  = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "//B //Nologo `"$vbsPath`" `"$batPath`"" -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -Daily -At "06:00AM"
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartCount 1 `
    -RestartInterval (New-TimeSpan -Minutes 30) `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RunOnlyIfNetworkAvailable

# Register (or update) the task
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Set-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings
    # Set-ScheduledTask has no -Description parameter; it lives on the task object
    $existingTask = Get-ScheduledTask -TaskName $taskName
    $existingTask.Description = $description
    Set-ScheduledTask -InputObject $existingTask | Out-Null
    Write-Host "✓ Updated existing Task Scheduler job: $taskName"
} else {
    Register-ScheduledTask `
        -TaskName  $taskName `
        -Action    $action `
        -Trigger   $trigger `
        -Settings  $settings `
        -RunLevel  Highest `
        -Description $description
    Write-Host "✓ Registered new Task Scheduler job: $taskName"
}

Write-Host ""
Write-Host "Task details:"
Write-Host "  Name    : $taskName"
Write-Host "  Trigger : Daily at 06:00 AM"
Write-Host "  Action  : $batPath"
Write-Host "  Log     : $logsDir\morning.log"
Write-Host ""
Write-Host "To run immediately for testing:"
Write-Host "  Start-ScheduledTask -TaskName '$taskName'"

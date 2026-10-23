@echo off
:: run_predict_stage.bat - Task Scheduler entry point for the predict stage.
:: Registered by register_predict_task.ps1: every 15 min, 10:05-22:05 ET.
:: Runs the injury snapshot + predictions + the picks push (daily_workflow.py --stage predict). Each run prices only
:: games tipping within 75 minutes that have no prediction yet; a run with nothing to price does nothing.
:: Logs to logs\predict.log (its own file; never shared with the morning stage).

cd /d "%~dp0.."
if not exist logs mkdir logs

:: Skip quietly while the morning stage is running (logs\morning.running younger than 2 hours).
powershell -NoProfile -Command "if ((Test-Path 'logs\morning.running') -and (((Get-Date) - (Get-Item 'logs\morning.running').LastWriteTime).TotalHours -lt 2)) { exit 1 } else { exit 0 }"
if errorlevel 1 exit /b 0

call venv\Scripts\activate

echo ==== %DATE% %TIME% predict stage >> logs\predict.log
if errorlevel 1 exit /b 1
python daily_workflow.py --stage predict >> logs\predict.log 2>&1
exit /b %errorlevel%

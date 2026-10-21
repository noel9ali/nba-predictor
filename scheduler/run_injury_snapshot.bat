@echo off
:: run_injury_snapshot.bat - Task Scheduler entry point for the injury report archiver.
:: Registered by register_injury_snapshot_task.ps1 to run every 30 minutes, 11:00 to 23:00.
:: Archives the newest official NBA injury report PDF (data\raw\injury_reports\) and its parsed rows
:: (data\injuries\injury_snapshots.sqlite). Always exits 0, so a failure never blocks anything else.

setlocal
cd /d "%~dp0.."
if not exist logs mkdir logs
call venv\Scripts\activate.bat
echo ==== %DATE% %TIME% >> logs\injury_snapshot.log
python -m src.injuries --snapshot >> logs\injury_snapshot.log 2>&1
exit /b 0

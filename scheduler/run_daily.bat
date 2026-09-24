@echo off
:: run_daily.bat — Windows Task Scheduler entry point for the NBA Predictor daily workflow.
:: Registered by task_scheduler_setup.ps1 to run at 6:00 AM every day.
:: To migrate to a cloud server, replace this file with an equivalent shell script (see README_scheduler.md).

cd /d "%~dp0.."

echo Activating virtual environment...
call venv\Scripts\activate

echo.
echo Running daily workflow...
python daily_workflow.py >> logs\workflow.log 2>&1

echo.
echo Done.

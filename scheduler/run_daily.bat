@echo off
:: run_daily.bat — Windows Task Scheduler entry point for the NBA Predictor daily workflow.
:: Registered by task_scheduler_setup.ps1 to run at 6:00 AM every day.
:: This is the MORNING stage (pipeline, settle yesterday, results push + email). Predictions run in the evening, after the
:: injury reports, via run_predict_stage.bat (register_predict_task.ps1); register that task BEFORE using this
:: file, or no predictions get made. For the old all-in-one run, use: python daily_workflow.py
:: To migrate to a cloud server, replace this file with an equivalent shell script (see README_scheduler.md).

cd /d "%~dp0.."

echo Activating virtual environment...
call venv\Scripts\activate

echo.
echo Running morning stage...
python daily_workflow.py --stage morning >> logs\workflow.log 2>&1

echo.
echo Done.

@echo off
:: run_predict_stage.bat - Task Scheduler entry point for the predict stage.
:: Registered by register_predict_task.ps1: every 15 min, 10:05-22:05 ET.
:: Runs the injury snapshot + predictions + the picks SMS (daily_workflow.py --stage predict). Each run prices only
:: games tipping within 75 minutes that have no prediction yet; a run with nothing to price does nothing.

cd /d "%~dp0.."
if not exist logs mkdir logs
call venv\Scripts\activate

echo ==== %DATE% %TIME% predict stage >> logs\workflow.log
python daily_workflow.py --stage predict >> logs\workflow.log 2>&1
exit /b %errorlevel%

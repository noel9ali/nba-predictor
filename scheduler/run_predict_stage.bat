@echo off
:: run_predict_stage.bat - Task Scheduler entry point for the evening predict stage.
:: Registered by register_predict_task.ps1: 17:15 ET, with a retry at 18:00.
:: Runs the injury snapshot + predictions + the picks SMS (daily_workflow.py --stage predict), after the
:: evening injury reports exist. A retry that finds every game already predicted does nothing.

cd /d "%~dp0.."
if not exist logs mkdir logs
call venv\Scripts\activate

echo ==== %DATE% %TIME% predict stage >> logs\workflow.log
python daily_workflow.py --stage predict >> logs\workflow.log 2>&1
exit /b %errorlevel%

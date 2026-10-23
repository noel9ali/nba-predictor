@echo off
:: run_daily.bat - Windows Task Scheduler entry point for the NBA Predictor daily workflow.
:: Registered by task_scheduler_setup.ps1 to run at 6:00 AM every day.
:: This is the MORNING stage (pipeline, settle yesterday, results push + email). Predictions run in the evening, after the
:: injury reports, via run_predict_stage.bat (register_predict_task.ps1); register that task BEFORE using this
:: file, or no predictions get made. For the old all-in-one run, use: python daily_workflow.py
:: To migrate to a cloud server, replace this file with an equivalent shell script (see README_scheduler.md).
:: Logs to logs\morning.log (its own file; the predict stage uses logs\predict.log, so they can never collide).

cd /d "%~dp0.."
if not exist logs mkdir logs

:: If the log can't be opened, fail loudly instead of running blind.
echo ==== %DATE% %TIME% morning stage >> logs\morning.log || (echo ERROR: cannot open logs\morning.log 1>&2 & exit /b 1)

:: Marker so the predict stage can skip while this runs (it ignores a marker older than 2 hours).
echo %DATE% %TIME% > logs\morning.running

call venv\Scripts\activate
python daily_workflow.py --stage morning >> logs\morning.log 2>&1
set RC=%errorlevel%

del logs\morning.running >nul 2>&1
exit /b %RC%

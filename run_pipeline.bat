@echo off
setlocal
cd /d "%~dp0"
call venv\Scripts\activate.bat

rem Every step runs even if an earlier one fails; the exit code reports any failure.
set FAILED=
call :step collect

rem Player data (player-data work): after collect, before features. These steps are
rem non-fatal for now; a failure is logged and does not change the pipeline's exit code.
for %%P in (collect_players absences) do (
    echo.
    echo Running src\%%P.py...
    python src\%%P.py
    if errorlevel 1 echo   src\%%P.py FAILED ^(non-fatal^)
)

for %%S in (elo features model track) do call :step %%S

rem Injury report snapshot. Never fails the pipeline: the command exits 0 on errors.
echo.
echo Running injury report snapshot...
python -m src.injuries --snapshot

echo.
if defined FAILED (
    echo Pipeline finished with failures.
    exit /b 1
)
echo Pipeline complete.
exit /b 0

:step
echo.
echo Running src\%1.py...
python src\%1.py
if errorlevel 1 (
    echo   src\%1.py FAILED
    set FAILED=1
)
exit /b 0

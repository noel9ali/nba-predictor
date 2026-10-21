@echo off
setlocal
cd /d "%~dp0"
call venv\Scripts\activate.bat

rem Take an injury report snapshot first. It never fails the run (exits 0 on errors).
echo Running injury report snapshot...
python -m src.injuries --snapshot

echo Running src\predict.py...
python src\predict.py
if errorlevel 1 (
    echo Predictions FAILED
    exit /b 1
)
echo Predictions complete.
exit /b 0

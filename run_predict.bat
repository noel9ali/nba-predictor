@echo off
setlocal
cd /d "%~dp0"
call venv\Scripts\activate.bat

echo Running src\predict.py...
python src\predict.py
if errorlevel 1 (
    echo Predictions FAILED
    exit /b 1
)
echo Predictions complete.
exit /b 0

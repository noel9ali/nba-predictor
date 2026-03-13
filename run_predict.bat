@echo off
echo Activating virtual environment...
call venv\Scripts\activate

echo.
echo Running predict.py...
python src/predict.py

echo.
echo Predictions complete.
pause
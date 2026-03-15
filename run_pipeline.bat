@echo off
echo Activating virtual environment...
call venv\Scripts\activate

echo.
echo Running collect.py...
python src/collect.py

echo.
echo Running features.py...
python src/features.py

echo.
echo Running elo.py...
python src/elo.py

echo.
echo Running model.py...
python src/model.py

echo.
echo Running track.py...
python src/track.py

echo.
echo Pipeline complete.
pause
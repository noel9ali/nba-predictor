@echo off
setlocal

python scripts\seed_test_games.py --reset
if errorlevel 1 exit /b %errorlevel%

python src\elo.py
if errorlevel 1 exit /b %errorlevel%

python src\features.py
if errorlevel 1 exit /b %errorlevel%

python src\model.py
exit /b %errorlevel%

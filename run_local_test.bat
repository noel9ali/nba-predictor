@echo off
setlocal

python -m unittest discover -s tests -v
exit /b %errorlevel%

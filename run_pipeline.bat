@echo off
setlocal
cd /d "%~dp0"
call venv\Scripts\activate.bat

rem Every step runs even if an earlier one fails; the exit code reports any failure.
set FAILED=
for %%S in (collect elo features model track) do (
    echo.
    echo Running src\%%S.py...
    python src\%%S.py
    if errorlevel 1 (
        echo   src\%%S.py FAILED
        set FAILED=1
    )
)

echo.
if defined FAILED (
    echo Pipeline finished with failures.
    exit /b 1
)
echo Pipeline complete.
exit /b 0

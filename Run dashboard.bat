@echo off
setlocal
cd /d "%~dp0"

echo Luma Vale unit-economics dashboard
echo ----------------------------------

where py >nul 2>nul
if not errorlevel 1 (
  py -3 src\run_excel_dashboard.py --open
  goto check_result
)

where python >nul 2>nul
if not errorlevel 1 (
  python src\run_excel_dashboard.py --open
  goto check_result
)

echo.
echo Python 3 was not found. Install it from https://www.python.org/downloads/
echo During installation, select "Add Python to PATH".
echo Then double-click this file again.
echo.
pause
exit /b 1

:check_result
if errorlevel 1 goto build_failed
exit /b 0

:build_failed
echo.
echo Dashboard could not be generated. The error above explains what to fix.
echo For the shortest instructions, open TLDR.README\README.md.
echo.
pause
exit /b 1

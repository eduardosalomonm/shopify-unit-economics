@echo off
setlocal
cd /d "%~dp0"

echo Luma Vale unit-economics dashboard
echo ----------------------------------

where py >nul 2>nul
if not errorlevel 1 (
  py -3 src\run_excel_dashboard.py
  goto check_result
)

where python >nul 2>nul
if not errorlevel 1 (
  python src\run_excel_dashboard.py
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
if not exist output\dashboard.html goto missing_output
start "" output\dashboard.html
echo Dashboard opened in your browser.
exit /b 0

:build_failed
echo.
echo Dashboard could not be generated. The error above explains what to fix.
echo For the shortest instructions, open TLDR.README\README.md.
echo.
pause
exit /b 1

:missing_output
echo Dashboard could not be generated: output\dashboard.html is missing.
pause
exit /b 1

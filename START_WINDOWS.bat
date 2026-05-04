@echo off
setlocal
cd /d "%~dp0app"

if not exist ".venv\Scripts\python.exe" (
  echo First-time setup. This may take a minute...
  where py >nul 2>nul && (py -3 install.py) || (python install.py)
)

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" app.py %*
) else (
  echo.
  echo Could not start. Open app\INSTALL_WINDOWS.bat and try again.
  pause
  exit /b 1
)

if errorlevel 1 (
  echo.
  echo The panel stopped with an error. Run app\INSTALL_WINDOWS.bat to repair.
  pause
)

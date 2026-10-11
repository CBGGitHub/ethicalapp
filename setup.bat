@echo off
rem One-time setup for developers / anyone who received this folder.
rem Needs Python 3.12+ installed (https://www.python.org/downloads/ - tick "Add python.exe to PATH").
rem End users should use the installer instead (once it exists).
cd /d "%~dp0"
where python >nul 2>nul || (echo Python is not installed. Get it from https://www.python.org/downloads/ & pause & exit /b 1)
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>nul || rmdir /s /q .venv
)
if not exist ".venv\Scripts\python.exe" (
    echo Creating Python environment...
    python -m venv .venv || (pause & exit /b 1)
)
echo Installing libraries...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt || (pause & exit /b 1)
echo Adding right-click "Open with" entries...
".venv\Scripts\python.exe" apps\register_windows.py
echo Adding Start Menu shortcuts (folder "Ethical Suite")...
".venv\Scripts\python.exe" apps\make_shortcuts.py
echo.
echo Done! Start the apps from the Start Menu ("Ethical Suite" folder) or the "Ethical ....bat" files.
echo Tip: for desktop shortcuts too, run:  .venv\Scripts\python apps\make_shortcuts.py --desktop
pause

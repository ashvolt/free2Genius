@echo off
REM Windows wrapper for run.py.
REM
REM Windows installs Python's launcher as `py`, and a bare `python` often hits
REM the Microsoft Store alias instead of a real interpreter ("Python was not
REM found"). This tries the launcher first, then python, then python3, and
REM prints install instructions if none of them is a working interpreter.

setlocal

py -3 --version >nul 2>&1 && (
  py -3 "%~dp0run.py" %*
  exit /b %errorlevel%
)

python --version >nul 2>&1 && (
  python "%~dp0run.py" %*
  exit /b %errorlevel%
)

python3 --version >nul 2>&1 && (
  python3 "%~dp0run.py" %*
  exit /b %errorlevel%
)

echo.
echo   No working Python interpreter was found.
echo.
echo   Install Python 3.11 or newer:
echo     winget install Python.Python.3.12
echo   or download it from https://www.python.org/downloads/
echo   and tick "Add python.exe to PATH" during installation.
echo.
echo   If Python IS installed but Windows opens the Microsoft Store:
echo     Settings ^> Apps ^> Advanced app settings ^> App execution aliases
echo     turn OFF "python.exe" and "python3.exe"
echo.
echo   Then close and reopen this terminal and run:  run.bat setup
echo.
exit /b 1

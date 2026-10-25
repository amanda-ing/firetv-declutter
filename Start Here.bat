@echo off
rem Windows: double-click to declutter your Fire TV.
cd /d "%~dp0"
where py >nul 2>nul && (py -3 firetv_declutter.py %* & goto :eof)
where python >nul 2>nul && (python firetv_declutter.py %* & goto :eof)
echo Python 3 is needed. Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"), then try again.
pause

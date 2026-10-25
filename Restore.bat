@echo off
rem Windows: double-click to undo everything firetv-declutter changed on your Fire TV.
cd /d "%~dp0"
where py >nul 2>nul && (py -3 firetv_declutter.py --restore & goto :eof)
python firetv_declutter.py --restore

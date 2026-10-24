@echo off
cd /d "%~dp0"
python -X utf8 -B -m blitzcam overlay
if errorlevel 1 pause

@echo off
cd /d "%~dp0"
python -X utf8 -B research/scripts/tank_tracking_launcher.py
if errorlevel 1 pause

@echo off
cd /d "%~dp0"
python -m pip install -r ..\requirements.txt
python run_programadora.py
if errorlevel 1 pause

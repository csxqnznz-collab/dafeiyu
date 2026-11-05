@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "pet_launcher.pyw"
) else (
    start "" pythonw "pet_launcher.pyw"
)

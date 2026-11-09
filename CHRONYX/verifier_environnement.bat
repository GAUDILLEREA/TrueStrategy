@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" verifier_environnement.py
) else (
    python verifier_environnement.py
)
pause

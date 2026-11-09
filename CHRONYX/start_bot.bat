@echo off
REM ==================================================================
REM  CHRONYX AI TRADING BOT - Lancement
REM  - met a jour le calendrier economique
REM  - demarre le moteur (fenetre separee, protege le compte meme sans dashboard)
REM  - ouvre le dashboard dans le navigateur
REM ==================================================================
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo  Premiere utilisation : installation...
    call installer.bat
)
set "PY=.venv\Scripts\python.exe"

echo  Mise a jour du calendrier economique...
"%PY%" -m chronyx.news.importer

echo  Demarrage du moteur CHRONYX...
start "CHRONYX - Moteur" cmd /k ""%PY%" -m chronyx.engine.bot"

echo  Ouverture du dashboard (http://localhost:8501)...
"%PY%" -m streamlit run dashboard\app.py

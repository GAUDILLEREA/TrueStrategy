@echo off
REM ==================================================================
REM  CHRONYX AI TRADING BOT - Lancement
REM  - met a jour le calendrier economique
REM  - demarre le moteur (fenetre separee, protege le compte meme sans dashboard)
REM  - demarre le dashboard et ouvre le navigateur sur http://localhost:8501
REM ==================================================================
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo  Premiere utilisation : installation...
    call installer.bat
)
set "PY=.venv\Scripts\python.exe"
"%PY%" -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo  [ERREUR] Le dashboard n'est pas installe correctement. Relancez installer.bat.
    pause
    exit /b 1
)

echo  Mise a jour du calendrier economique...
"%PY%" -m chronyx.news.importer

echo  Demarrage du moteur CHRONYX...
start "CHRONYX - Moteur" cmd /k ""%PY%" -m chronyx.engine.bot"

echo  Demarrage du dashboard...
REM Ouvre le navigateur apres 8 secondes (le temps que le dashboard demarre)
start "" cmd /c "timeout /t 8 /nobreak >nul & start http://localhost:8501"
echo.
echo  ============================================================
echo   Dashboard : http://localhost:8501
echo   (a ouvrir sur CE PC uniquement, pas sur le telephone)
echo   NE FERMEZ PAS cette fenetre tant que vous utilisez le dashboard.
echo  ============================================================
echo.
"%PY%" -m streamlit run dashboard\app.py --server.headless true --server.port 8501
echo.
echo  Le dashboard s'est arrete. Si un message d'erreur est affiche ci-dessus,
echo  faites-en une capture d'ecran.
pause

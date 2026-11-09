@echo off
REM ==================================================================
REM  CHRONYX AI TRADING BOT - Installation (a lancer une seule fois)
REM ==================================================================
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo  === Installation de CHRONYX ===
echo.

REM 1) Recherche de Python (lanceur "py" de preference, version 3.12 recommandee)
set "PYEXE="
py -3.12 --version >nul 2>&1 && set "PYEXE=py -3.12"
if not defined PYEXE py -3.13 --version >nul 2>&1 && set "PYEXE=py -3.13"
if not defined PYEXE py -3.11 --version >nul 2>&1 && set "PYEXE=py -3.11"
if not defined PYEXE python --version >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE (
    echo  [ERREUR] Python est introuvable.
    echo  Installez Python 3.12 64 bits depuis https://www.python.org/downloads/windows/
    echo  et COCHEZ la case "Add python.exe to PATH" pendant l'installation.
    pause
    exit /b 1
)
echo  Python utilise : %PYEXE%

REM 2) Environnement virtuel isole (dossier .venv)
if not exist ".venv\Scripts\python.exe" (
    echo  Creation de l'environnement virtuel...
    %PYEXE% -m venv .venv
    if errorlevel 1 (
        echo  [ERREUR] Impossible de creer l'environnement virtuel.
        pause
        exit /b 1
    )
)

REM 3) Dependances
echo  Installation des dependances (quelques minutes)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo  [ERREUR] L'installation des dependances a echoue. Voir le message ci-dessus.
    pause
    exit /b 1
)

REM 4) Fichier .env (sans mot de passe)
if not exist ".env" copy ".env.example" ".env" >nul

REM 5) Premier calendrier economique
".venv\Scripts\python.exe" -m chronyx.news.importer

REM 6) Verification
echo.
".venv\Scripts\python.exe" verifier_environnement.py
echo.
echo  Installation terminee. Lancez start_bot.bat pour demarrer.
pause

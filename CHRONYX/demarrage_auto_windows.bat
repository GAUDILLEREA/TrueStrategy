@echo off
REM ==================================================================
REM  FACULTATIF : lancer CHRONYX automatiquement a l'ouverture de session.
REM  Cree un raccourci dans le dossier Demarrage de Windows.
REM  Pour annuler : relancer ce script avec le parametre /supprimer
REM ==================================================================
chcp 65001 >nul
cd /d "%~dp0"
set "LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\CHRONYX.lnk"
if /i "%~1"=="/supprimer" (
    del "%LNK%" 2>nul
    echo  Demarrage automatique supprime.
    pause
    exit /b 0
)
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%LNK%'); $s.TargetPath='%~dp0start_bot.bat'; $s.WorkingDirectory='%~dp0'; $s.Save()"
echo  CHRONYX demarrera a chaque ouverture de session.
echo  Rappel : MetaTrader 5 doit aussi etre ouvert et connecte.
pause

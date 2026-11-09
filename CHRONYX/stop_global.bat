@echo off
REM Active le STOP GLOBAL sans passer par le dashboard.
REM Le moteur ferme alors les positions CHRONYX et n'ouvre plus rien.
chcp 65001 >nul
cd /d "%~dp0"
".venv\Scripts\python.exe" -c "from chronyx.risk.guards import activate_kill_switch; activate_kill_switch('stop_global.bat')"
echo  STOP GLOBAL ACTIVE. Pour le lever : bouton dans le dashboard.
pause

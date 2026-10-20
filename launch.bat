@echo off
title Shadow Voice — Autonomous Studio & Cognitive Brain
color 0B
cls

echo =====================================================================
echo    SHADOW VOICE — AUTONOMOUS VOICE STUDIO & COGNITIVE BRAIN
echo =====================================================================
echo.
echo Starting Shadow Voice Studio Server on http://localhost:9000 ...
echo.

cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" run.py
) else (
    python run.py
)

pause

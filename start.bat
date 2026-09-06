@echo off
setlocal
cd /d "%~dp0"
set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"
start "Vellum API" /D "%~dp0" "%PYTHON_EXE%" -m server.main
start "Vellum UI" /D "%~dp0client" npm.cmd run dev

echo Vellum is starting...
echo UI:  http://localhost:5173
echo API: http://localhost:3001/docs

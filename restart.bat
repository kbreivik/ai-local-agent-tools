@echo off
:: HP1 AI Agent -- restart FastAPI backend + React dev server
:: Usage: restart.bat [api-only | gui-only]

set PROJECT_DIR=%~dp0

echo.
echo  HP1 AI Agent -- restarting...
echo  ==============================

call "%PROJECT_DIR%stop.bat"

timeout /t 2 /nobreak >nul

call "%PROJECT_DIR%start.bat" %1

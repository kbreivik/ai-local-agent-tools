@echo off
setlocal

:: HP1 AI Agent — start FastAPI backend + React dev server
:: Usage: start.bat [api-only | gui-only]

set PROJECT_DIR=%~dp0
set LM_STUDIO_API_KEY=%LM_STUDIO_API_KEY%

:: Load from mcp.json if key not set
if "%LM_STUDIO_API_KEY%"=="" (
    for /f "tokens=2 delims=:," %%a in ('findstr /c:"LM_STUDIO_API_KEY" "%PROJECT_DIR%.mcp.json" 2^>nul') do (
        set LM_STUDIO_API_KEY=%%~a
        set LM_STUDIO_API_KEY=!LM_STUDIO_API_KEY: =!
        set LM_STUDIO_API_KEY=!LM_STUDIO_API_KEY:"=!
    )
)

set DOCKER_HOST=npipe:////./pipe/docker_engine
set KAFKA_BOOTSTRAP_SERVERS=localhost:9092,localhost:9093,localhost:9094
set AUDIT_LOG_PATH=%PROJECT_DIR%logs\audit.log
set CHECKPOINT_PATH=%PROJECT_DIR%checkpoints
set DB_PATH=%PROJECT_DIR%data\hp1_agent.db
set LM_STUDIO_BASE_URL=http://localhost:1234/v1
set LM_STUDIO_MODEL=lmstudio-community/qwen3-coder-30b-a3b-instruct
set CORS_ALLOW_ALL=true

echo.
echo  HP1 AI Agent
echo  ============
echo  API  ^> http://localhost:8000
echo  GUI  ^> http://localhost:5173
echo  Docs ^> http://localhost:8000/docs
echo.

if "%1"=="api-only" goto :api
if "%1"=="gui-only" goto :gui

:: Start both in separate windows
start "HP1 FastAPI" cmd /k "cd /d %PROJECT_DIR% && python run_api.py"
timeout /t 2 /nobreak >nul
start "HP1 React" cmd /k "cd /d %PROJECT_DIR%\gui && npm run dev"
echo Started both servers. Press any key to exit this window.
pause >nul
goto :eof

:api
cd /d %PROJECT_DIR%
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
goto :eof

:gui
cd /d %PROJECT_DIR%\gui
npm run dev
goto :eof

@echo off
setlocal EnableDelayedExpansion

:: HP1 AI Agent — start FastAPI backend + React dev server
:: Usage: start.bat [api-only | gui-only | pg | migrate]

set PROJECT_DIR=%~dp0

:: ── 1. Ensure .env exists — never create/overwrite if it does ─────────────────
if not exist "%PROJECT_DIR%.env" (
    echo [WARN] .env not found — copying from .env.defaults
    if not exist "%PROJECT_DIR%.env.defaults" (
        echo [ERROR] .env.defaults also missing. Cannot start.
        exit /b 1
    )
    copy "%PROJECT_DIR%.env.defaults" "%PROJECT_DIR%.env" >nul
    echo [WARN] Edit .env with your real values before running.
    pause
    exit /b 1
)

:: ── 2. Load .env — READ ONLY, never write back ────────────────────────────────
for /f "usebackq tokens=1,* delims==" %%a in ("%PROJECT_DIR%.env") do (
    if not "%%a"=="" if not "%%~a"=="" (
        set "_k=%%a"
        if not "!_k:~0,1!"=="#" set "%%a=%%b"
    )
)

:: ── 3. Apply hardcoded runtime-only defaults (not persisted to .env) ──────────
if "%AUDIT_LOG_PATH%"==""  set "AUDIT_LOG_PATH=%PROJECT_DIR%logs\audit.log"
if "%CHECKPOINT_PATH%"=="" set "CHECKPOINT_PATH=%PROJECT_DIR%checkpoints"
if "%DB_PATH%"==""         set "DB_PATH=%PROJECT_DIR%data\hp1_agent.db"

:: ── 4. Load LM_STUDIO_API_KEY from mcp.json if not set in .env ───────────────
if "%LM_STUDIO_API_KEY%"=="" (
    for /f "tokens=2 delims=:," %%a in ('findstr /c:"LM_STUDIO_API_KEY" "%PROJECT_DIR%.mcp.json" 2^>nul') do (
        set LM_STUDIO_API_KEY=%%~a
        set LM_STUDIO_API_KEY=!LM_STUDIO_API_KEY: =!
        set LM_STUDIO_API_KEY=!LM_STUDIO_API_KEY:"=!
    )
)

:: ── 5. Validate critical vars ─────────────────────────────────────────────────
if "%ELASTIC_URL%"==""              echo [WARN] ELASTIC_URL is empty in .env
if "%MUNINN_URL%"==""               echo [WARN] MUNINN_URL is empty in .env
if "%KAFKA_BOOTSTRAP_SERVERS%"==""  echo [WARN] KAFKA_BOOTSTRAP_SERVERS is empty in .env
if "%LM_STUDIO_BASE_URL%"==""       echo [WARN] LM_STUDIO_BASE_URL is empty in .env

:: ── 6. Print startup banner ───────────────────────────────────────────────────
echo.
echo  HP1 AI Agent v1.6.5
echo  ===================
echo  API  ^> http://localhost:8000
echo  GUI  ^> http://localhost:5173
echo  Docs ^> http://localhost:8000/docs
if defined DATABASE_URL (
    echo  DB   ^> Postgres [DATABASE_URL set]
) else (
    echo  DB   ^> SQLite %DB_PATH%
)
echo  .env ^> %PROJECT_DIR%.env
echo.

:: ── 7. Subcommands ────────────────────────────────────────────────────────────

:: pg -- start only the postgres container first, then full stack
if "%1"=="pg" (
    echo Starting Postgres container...
    cd /d "%PROJECT_DIR%"
    docker compose -f docker/docker-compose.yml up -d postgres
    echo Waiting for Postgres to be healthy...
    :pg_wait
    docker inspect --format="{{.State.Health.Status}}" hp1_postgres 2>nul | findstr /c:"healthy" >nul
    if errorlevel 1 (
        timeout /t 2 /nobreak >nul
        goto pg_wait
    )
    echo Postgres healthy.
    echo.
    goto :start_both
)

:: migrate -- run SQLite to Postgres migration
if "%1"=="migrate" (
    cd /d "%PROJECT_DIR%"
    python -m api.db.migrate_sqlite
    goto :eof
)

if "%1"=="api-only" goto :api
if "%1"=="gui-only" goto :gui

:: ── 8. Kill existing API on port 8000 before restarting ──────────────────────
for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr ":8000 "') do (
    taskkill /PID %%p /F >nul 2>&1
)

:start_both
:: Start both in separate windows
start "HP1 FastAPI" cmd /k "cd /d %PROJECT_DIR% && python run_api.py"

:: Wait for API to be healthy (poll /api/health up to 20 seconds)
echo  Waiting for API to start...
set _api_wait=0
:api_health_wait
timeout /t 1 /nobreak >nul
curl -s -o nul -w "%%{http_code}" http://localhost:8000/api/health 2>nul | findstr "200" >nul
if errorlevel 1 (
    set /a _api_wait+=1
    if %_api_wait% lss 20 goto api_health_wait
    echo [WARN] API did not respond after 20s — check the HP1 FastAPI window for errors.
) else (
    echo  API  ^> healthy at http://localhost:8000
)

start "HP1 React" cmd /k "cd /d %PROJECT_DIR%\gui && npm run dev"
echo  GUI  ^> starting at http://localhost:5173
echo [HP1] .env loaded from: %PROJECT_DIR%.env
pause >nul
goto :eof

:api
cd /d "%PROJECT_DIR%"
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
goto :eof

:gui
cd /d "%PROJECT_DIR%\gui"
npm run dev
goto :eof

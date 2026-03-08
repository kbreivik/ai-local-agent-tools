@echo off
:: HP1 AI Agent -- stop FastAPI backend + React dev server

echo.
echo  HP1 AI Agent -- stopping...
echo  ============================

:: Kill by named window titles (set in start.bat)
taskkill /FI "WINDOWTITLE eq HP1 FastAPI*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq HP1 React*"   /T /F >nul 2>&1

:: Also kill by port in case processes were started another way
:: Note: findstr ":8000" (no leading space) matches "0.0.0.0:8000" format
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000"') do (
    if not "%%a"=="0" taskkill /PID %%a /F >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":5173"') do (
    if not "%%a"=="0" taskkill /PID %%a /F >nul 2>&1
)

:: Wait up to 8 seconds for port 8000 to be released
set _wait=0
:wait_free
netstat -aon 2>nul | findstr ":8000" >nul 2>&1
if not errorlevel 1 (
    if %_wait% lss 8 (
        timeout /t 1 /nobreak >nul
        set /a _wait+=1
        goto wait_free
    )
)

echo  API  ^> stopped
echo  GUI  ^> stopped
echo.

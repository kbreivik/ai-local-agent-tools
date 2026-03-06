@echo off
:: HP1 AI Agent -- stop FastAPI backend + React dev server

echo.
echo  HP1 AI Agent -- stopping...
echo  ============================

:: Kill by named window titles (set in start.bat)
taskkill /FI "WINDOWTITLE eq HP1 FastAPI*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq HP1 React*"   /T /F >nul 2>&1

:: Also kill by port in case processes were started another way
for /f "tokens=5" %%a in ('netstat -aon ^| findstr " :8000 "') do (
    taskkill /PID %%a /F >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr " :5173 "') do (
    taskkill /PID %%a /F >nul 2>&1
)

echo  API  ^> stopped
echo  GUI  ^> stopped
echo.

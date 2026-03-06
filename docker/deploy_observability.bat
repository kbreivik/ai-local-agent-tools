@echo off
setlocal

REM ─── HP1 Observability Stack Deployment ───────────────────────────────────
REM Deploy Elasticsearch, then Filebeat to Swarm.
REM Requires ELASTIC_URL set or defaults to http://localhost:9200.
REM Usage: deploy_observability.bat [--with-kibana]

set ELASTIC_URL=%ELASTIC_URL%
if "%ELASTIC_URL%"=="" set ELASTIC_URL=http://localhost:9200

set ENABLE_KIBANA=false
if "%1"=="--with-kibana" set ENABLE_KIBANA=true

echo ============================================================
echo  HP1 Observability Stack Deployment
echo  Elasticsearch: %ELASTIC_URL%
echo  Kibana: %ENABLE_KIBANA%
echo ============================================================

REM Step 1: Start Elasticsearch
echo.
echo [1/5] Starting Elasticsearch...
cd /d "%~dp0elastic"
if "%ENABLE_KIBANA%"=="true" (
    docker compose --profile kibana up -d
) else (
    docker compose up -d elasticsearch
)
if errorlevel 1 goto :error

REM Step 2: Wait for Elasticsearch to be healthy
echo.
echo [2/5] Waiting for Elasticsearch health (up to 120s)...
set /a attempts=0
:wait_loop
set /a attempts+=1
if %attempts% gtr 24 (
    echo ERROR: Elasticsearch did not become healthy after 120s
    goto :error
)
timeout /t 5 /nobreak >nul
curl -sf "%ELASTIC_URL%/_cluster/health" | findstr /C:"green" /C:"yellow" >nul 2>&1
if not errorlevel 1 goto :es_ready
echo   Attempt %attempts%/24...
goto :wait_loop

:es_ready
echo   Elasticsearch is healthy!
curl -sf "%ELASTIC_URL%/_cluster/health?pretty" 2>nul

REM Step 3: Create hp1-logs index template
REM IMPORTANT: Must use priority>=100 and no data_stream config so ES treats these as regular indices.
REM Filebeat 8.x has setup.template.enabled:false — we always create the template here.
echo.
echo [3/5] Creating hp1-logs index template...
curl -s -X DELETE "%ELASTIC_URL%/_data_stream/hp1-logs*" >nul 2>&1
curl -s -X DELETE "%ELASTIC_URL%/_index_template/hp1-logs" >nul 2>&1
curl -sf -X PUT "%ELASTIC_URL%/_index_template/hp1-logs" ^
  -H "Content-Type: application/json" ^
  -d "{\"index_patterns\":[\"hp1-logs-*\"],\"priority\":100,\"template\":{\"settings\":{\"number_of_shards\":1,\"number_of_replicas\":0,\"refresh_interval\":\"5s\"},\"mappings\":{\"dynamic\":true,\"properties\":{\"@timestamp\":{\"type\":\"date\"},\"message\":{\"type\":\"text\"},\"hp1_node_role\":{\"type\":\"keyword\"},\"hp1_environment\":{\"type\":\"keyword\"}}}}}" ^
  2>nul
if errorlevel 1 echo   WARNING: Template creation failed
echo   Template created.

REM Step 4: Deploy Filebeat (standalone on this host)
echo.
echo [4/5] Starting Filebeat...
cd /d "%~dp0filebeat"
set ELASTIC_URL=%ELASTIC_URL%
docker compose up -d
if errorlevel 1 goto :error

REM Step 5: Verify logs flowing
echo.
echo [5/5] Verifying log ingestion (wait 30s for first batch)...
timeout /t 30 /nobreak >nul
curl -sf "%ELASTIC_URL%/hp1-logs-*/_count" 2>nul
echo.
curl -sf "%ELASTIC_URL%/_cat/indices/hp1-logs-*?v&h=index,docs.count,store.size" 2>nul

echo.
echo ============================================================
echo  Deployment complete!
echo  Elasticsearch: %ELASTIC_URL%
if "%ENABLE_KIBANA%"=="true" (
    for /f "tokens=3 delims=/" %%a in ("%ELASTIC_URL%") do set ES_HOST=%%a
    echo  Kibana: http://%ES_HOST:9200=5601%
)
echo  Set ELASTIC_URL in your .env to enable monitoring.
echo ============================================================
goto :end

:error
echo.
echo ERROR: Deployment failed. Check Docker logs.
exit /b 1

:end
endlocal

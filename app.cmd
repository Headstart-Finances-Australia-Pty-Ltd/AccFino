@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title AccFino Launcher

set PYTHONPATH=%~dp0
set PYTHONIOENCODING=utf-8
set PYTHONWARNINGS=ignore
set APP_URL=http://localhost:3000
set DATABASE_URL=postgresql+psycopg2://neondb_owner:npg_XH2QFas3gYDd@ep-dawn-scene-aqma9lhs.c-8.us-east-1.aws.neon.tech/neondb

echo.
echo  AccFino starting...
echo.

python --version >nul 2>&1
if errorlevel 1 ( echo ERROR: Python not found & pause & exit /b 1 )
echo [OK] Python found.

node --version >nul 2>&1
if errorlevel 1 ( echo ERROR: Node.js not found & pause & exit /b 1 )
echo [OK] Node.js found.

python -c "import psycopg2" >nul 2>&1
if errorlevel 1 ( pip install psycopg2-binary >nul 2>&1 )

python -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo Installing Python packages...
    pip install -r "%~dp0requirements.txt"
    if errorlevel 1 ( echo ERROR: pip install failed & pause & exit /b 1 )
)
echo [OK] Python packages ready.

if not exist "%~dp0react_frontend\node_modules" (
    echo Installing Node packages...
    cd /d "%~dp0react_frontend"
    call npm install
    cd /d "%~dp0"
)
echo [OK] Node packages ready.

echo Freeing ports...
for /f "tokens=5" %%i in ('netstat -aon 2^>nul ^| findstr ":8000 "') do taskkill /PID %%i /F >nul 2>&1
for /f "tokens=5" %%i in ('netstat -aon 2^>nul ^| findstr ":8001 "') do taskkill /PID %%i /F >nul 2>&1
for /f "tokens=5" %%i in ('netstat -aon 2^>nul ^| findstr ":3000 "') do taskkill /PID %%i /F >nul 2>&1
timeout /t 2 /nobreak >nul

set AFROOT=%~dp0
set AFROOT=%AFROOT:~0,-1%

REM ── Auth API ────────────────────────────────────────────────────
echo [OK] Auth API starting...
start "AccFino Auth :8000" cmd /k "cd /d "%AFROOT%" && set PYTHONPATH=%AFROOT% && set PYTHONIOENCODING=utf-8 && set PYTHONWARNINGS=ignore && set DATABASE_URL=postgresql+psycopg2://neondb_owner:npg_XH2QFas3gYDd@ep-dawn-scene-aqma9lhs.c-8.us-east-1.aws.neon.tech/neondb && python -m uvicorn main_app.api_call:app --host 127.0.0.1 --port 8000 --workers 1 || (echo. && echo AUTH API CRASHED && pause)"

:wait8000
timeout /t 2 /nobreak >nul
netstat -an 2>nul | findstr "8000" >nul 2>&1
if errorlevel 1 (
    set /a W8000+=1
    if !W8000! lss 30 goto wait8000
    echo ERROR: Auth API failed. Check the Auth window.
    pause & exit /b 1
)
echo [OK] Auth API ready.

REM ── Main API ────────────────────────────────────────────────────
echo [OK] Main API starting (ML models 15-60s)...
start "AccFino API :8001" cmd /k "cd /d "%AFROOT%" && set PYTHONPATH=%AFROOT% && set PYTHONIOENCODING=utf-8 && set PYTHONWARNINGS=ignore && set DATABASE_URL=postgresql+psycopg2://neondb_owner:npg_XH2QFas3gYDd@ep-dawn-scene-aqma9lhs.c-8.us-east-1.aws.neon.tech/neondb && python -m uvicorn main_app.react_api:app --host 127.0.0.1 --port 8001 --workers 1 || (echo. && echo MAIN API CRASHED && pause)"

:wait8001
timeout /t 2 /nobreak >nul
netstat -an 2>nul | findstr "8001" >nul 2>&1
if errorlevel 1 (
    set /a W8001+=1
    if !W8001! lss 45 goto wait8001
    echo ERROR: Main API failed. Check the API window.
    pause & exit /b 1
)
echo [OK] Main API ready.

REM ── React UI ────────────────────────────────────────────────────
start "AccFino UI :3000" cmd /k "cd /d "%AFROOT%\react_frontend" && npm run dev"

echo [..] Waiting for UI...
:wait3000
timeout /t 1 /nobreak >nul
netstat -an 2>nul | findstr "3000" >nul 2>&1
if errorlevel 1 goto wait3000
timeout /t 2 /nobreak >nul

echo.
echo ================================================
echo   AccFino is READY
echo   http://localhost:3000/login
echo   Email:    admin@accfino.com
echo   Password: Accfino@1
echo ================================================
echo.

set B1=%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe
set B2=%PROGRAMFILES%\BraveSoftware\Brave-Browser\Application\brave.exe
if exist "%B1%" ( start "" "%B1%" "http://localhost:3000/login"
) else if exist "%B2%" ( start "" "%B2%" "http://localhost:3000/login"
) else ( start "" "http://localhost:3000/login" )

exit

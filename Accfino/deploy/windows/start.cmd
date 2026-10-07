@echo off
setlocal EnableDelayedExpansion
title AccFino Launcher
REM ============================================================================
REM  AccFino local launcher (Windows)
REM  - Reads settings from the .env file in the repository root (never commit it)
REM  - Starts the API on :8001 and the React dev server on :3000
REM  The old separate "Auth API" on :8000 no longer exists;
REM  all /auth routes are served by the main API.
REM ============================================================================
pushd "%~dp0..\.."
set "ROOT=%CD%"
popd

if not exist "%ROOT%\.env" (
    echo ERROR: %ROOT%\.env not found.
    echo Copy .env.example to .env and fill in DATABASE_URL and JWT_SECRET.
    echo Use a LOCAL or STAGING database - never production - for development.
    pause & exit /b 1
)
for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%ROOT%\.env") do (
    if not "%%a"=="" set "%%a=%%b"
)
if "%DATABASE_URL%"=="" ( echo ERROR: DATABASE_URL missing in .env & pause & exit /b 1 )
if "%JWT_SECRET%"=="" (
    echo [..] JWT_SECRET missing - generating one and saving it to .env
    python -c "import secrets,pathlib;p=pathlib.Path(r'%ROOT%\.env');t=p.read_text(encoding='utf-8');p.write_text(t+('' if t.endswith(chr(10)) or not t else chr(10))+'JWT_SECRET='+secrets.token_urlsafe(48)+chr(10),encoding='utf-8')"
    for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%ROOT%\.env") do if "%%a"=="JWT_SECRET" set "JWT_SECRET=%%b"
)

set "PYTHONPATH=%ROOT%\backend"
set "ACCFINO_ROOT=%ROOT%"
REM Business data + documents live OUTSIDE the application folder (default: AccFino_Data next to it).
if "%ACCFINO_DATA_ROOT%"=="" set "ACCFINO_DATA_ROOT=%ROOT%\..\AccFino_Data"
set PYTHONIOENCODING=utf-8
set PYTHONWARNINGS=ignore

python --version >nul 2>&1 || ( echo ERROR: Python not found & pause & exit /b 1 )
node --version   >nul 2>&1 || ( echo ERROR: Node.js not found & pause & exit /b 1 )
echo [OK] Python and Node found.

REM Full install only on a new machine; otherwise just add what's missing so an
REM existing, working environment is never downgraded or rebuilt.
python -c "import fastapi, sqlalchemy, psycopg2" >nul 2>&1
if errorlevel 1 (
    echo Installing Python packages ^(first run, a few minutes^)...
    python -m pip install -r "%ROOT%\backend\requirements.txt" || ( echo ERROR: pip install failed - see messages above & pause & exit /b 1 )
) else (
    python -c "import pyotp, qrcode, webauthn, jwt" >nul 2>&1
    if errorlevel 1 (
        echo Adding sign-in security packages...
        python -m pip install "pyotp>=2.9.0" "qrcode[pil]>=7.4" "webauthn>=2.7.0,<4" "PyJWT>=2.8.0" || ( echo ERROR: pip install failed - see messages above & pause & exit /b 1 )
    )
)
if not exist "%ROOT%\frontend\node_modules" (
    echo Installing Node packages...
    pushd "%ROOT%\frontend" & call npm install & popd
)
echo [OK] Packages ready.

echo Freeing ports 8001 and 3000...
for /f "tokens=5" %%i in ('netstat -aon 2^>nul ^| findstr ":8001 "') do taskkill /PID %%i /F >nul 2>&1
for /f "tokens=5" %%i in ('netstat -aon 2^>nul ^| findstr ":3000 "') do taskkill /PID %%i /F >nul 2>&1
timeout /t 2 /nobreak >nul

echo [..] Initialising database (safe to run every time)...
pushd "%ROOT%\backend"
python -m accfino.core.init_db || ( echo ERROR: database initialisation failed & popd & pause & exit /b 1 )
popd

echo [..] Starting API on :8001 (ML models take 15-60s)...
start "AccFino API :8001" cmd /k "cd /d "%ROOT%\backend" && python -m uvicorn accfino.app:app --host 127.0.0.1 --port 8001 --workers 1 || (echo. && echo API CRASHED - see messages above && pause)"

REM Ask the API itself (GET /health) - matching text in "netstat" also matches leftover connections
REM from a previous run and could report "ready" while the API is still starting or has crashed.
set /a W8001=0
:wait8001
timeout /t 2 /nobreak >nul
python -c "import urllib.request as u;u.urlopen('http://127.0.0.1:8001/health',timeout=3)" >nul 2>&1
if errorlevel 1 (
    set /a W8001+=1
    if !W8001! lss 90 goto wait8001
    echo ERROR: the API did not answer on :8001 within 3 minutes.
    echo Look at the "AccFino API :8001" window - the reason is printed there.
    pause & exit /b 1
)
echo [OK] API is answering on :8001.

start "AccFino UI :3000" cmd /k "cd /d "%ROOT%\frontend" && npm run dev"
set /a W3000=0
:wait3000
timeout /t 1 /nobreak >nul
python -c "import urllib.request as u;u.urlopen('http://localhost:3000/',timeout=3)" >nul 2>&1
if errorlevel 1 (
    set /a W3000+=1
    if !W3000! lss 120 goto wait3000
    echo WARNING: the web app did not answer on :3000. Look at the "AccFino UI :3000" window.
)

echo.
echo ================================================
echo   AccFino is READY:  http://localhost:3000/login
echo ================================================
start "" "http://localhost:3000/login"
exit

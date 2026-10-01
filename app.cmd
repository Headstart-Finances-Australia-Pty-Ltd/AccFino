@echo off
REM ============================================================================
REM  AccFino - double-click to start (Windows)
REM  Starts the API (:8001) and the web app (:3000), then opens the login page.
REM  Settings (database, secrets) come from the .env file in this folder.
REM  The actual launcher is scripts\windows\start.cmd
REM ============================================================================
cd /d "%~dp0"

if not exist "%~dp0.env" (
    echo.
    echo  First run: no .env settings file found.
    echo  Creating .env from .env.example and opening it in Notepad...
    echo.
    echo  Please set:
    echo    DATABASE_URL  - a LOCAL or STAGING PostgreSQL database ^(not production^)
    echo    JWT_SECRET    - any long random text, e.g. 64 characters
    echo.
    echo  Save the file, close Notepad, then run app.cmd again.
    echo.
    copy "%~dp0.env.example" "%~dp0.env" >nul
    start /wait notepad "%~dp0.env"
    pause
    exit /b 0
)

call "%~dp0scripts\windows\start.cmd"

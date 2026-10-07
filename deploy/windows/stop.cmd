@echo off
title Stop AccFino

echo.
echo  Stopping AccFino — please wait...
echo.

REM Kill Python and Node by name
taskkill /F /IM python.exe  >nul 2>&1
taskkill /F /IM pythonw.exe >nul 2>&1
taskkill /F /IM node.exe    >nul 2>&1

REM Kill by port (catches hidden processes with no window title)
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| find ":8000"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| find ":8001"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| find ":3000"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| find ":5173"') do taskkill /F /PID %%a >nul 2>&1

REM Kill the React UI visible window (has a title)
taskkill /F /FI "WINDOWTITLE eq AccFino UI :3000" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq AccFino*"          >nul 2>&1

REM Second pass after 2s
timeout /t 2 /nobreak >nul
taskkill /F /IM python.exe >nul 2>&1
taskkill /F /IM node.exe   >nul 2>&1

REM Wait for OS to release file handles
echo  Waiting for file handles to release...
timeout /t 5 /nobreak >nul

echo.
echo  ================================================
echo   All AccFino services stopped.
echo.
echo   To delete the folder:
echo   1. Close THIS stop.bat window
echo   2. Close the AccFino Launcher window  
echo   3. Delete the folder in Explorer
echo  ================================================
echo.

@echo off
setlocal enabledelayedexpansion
set "SCRIPT_DIR=%~dp0"

echo ===============================================
echo  Installer: Bambu print history sync
echo ===============================================
echo.

if not exist "%SCRIPT_DIR%config.json" (
    echo Can't find config.json in this folder. Keep all the files together.
    pause
    exit /b 1
)

findstr /C:"CHANGE_IP" "%SCRIPT_DIR%config.json" >nul
if not errorlevel 1 (
    echo NOTE: you haven't edited config.json with your printer's info yet.
    echo Open it with Notepad and fill in:
    echo   - printer_ip   : your printer's IP address on your network
    echo   - access_code  : your printer's LAN access code
    echo   - serial       : your printer's serial number
    echo You'll find these 3 values on the printer's screen: Settings - Network / WLAN.
    echo.
    echo Run this installer again after saving your changes.
    pause
    exit /b 1
)

set "PYTHONW="
for /f "delims=" %%P in ('where pythonw 2^>nul') do (
    if not defined PYTHONW set "PYTHONW=%%P"
)

if not defined PYTHONW (
    echo Couldn't find Python installed ^(pythonw.exe^) on the PATH.
    echo Install Python from https://www.python.org/downloads/ and check
    echo "Add python.exe to PATH" during installation. Then run this installer again.
    pause
    exit /b 1
)

for %%F in ("%PYTHONW%") do set "PYDIR=%%~dpF"
set "PYTHONEXE=%PYDIR%python.exe"

echo Python found at: %PYTHONW%
echo.
echo Installing dependencies (openpyxl, pandas, paho-mqtt)...
"%PYTHONEXE%" -m pip install --quiet openpyxl pandas paho-mqtt
if errorlevel 1 (
    echo There was a problem installing the dependencies. Check your internet connection.
    pause
    exit /b 1
)

echo.
echo Testing the connection to the printer...
"%PYTHONEXE%" "%SCRIPT_DIR%test_connection.py"
if errorlevel 1 (
    echo.
    echo Could not connect. Check the IP / access code / serial number in config.json,
    echo and make sure the printer is on and on the same WiFi network.
    pause
    exit /b 1
)

echo.
echo Connection OK. Setting up automatic startup with Windows...

set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LAUNCHER=%STARTUP%\bambu_sync_launcher.vbs"

> "%LAUNCHER%" (
    echo Set WshShell = CreateObject("WScript.Shell"^)
    echo Do
    echo     WshShell.Run """%PYTHONW%"" ""%SCRIPT_DIR%bambu_sync.py""", 0, True
    echo     WScript.Sleep 5000
    echo Loop
)

echo Done. The service will start automatically every time you log in to Windows.
echo Starting it now...
wscript.exe "%LAUNCHER%"

echo.
echo ===============================================
echo  Installation complete. Your spreadsheet is at:
echo  %SCRIPT_DIR%prints_log.xlsx
echo  It will fill itself in as you print.
echo ===============================================
pause

@echo off
setlocal enabledelayedexpansion
set "SCRIPT_DIR=%~dp0"

echo ===============================================
echo  Instalador: Sincronizador de historial Bambu
echo ===============================================
echo.

if not exist "%SCRIPT_DIR%config.json" (
    echo No encuentro config.json en esta carpeta. Copia todos los archivos juntos.
    pause
    exit /b 1
)

findstr /C:"CAMBIAR_IP" "%SCRIPT_DIR%config.json" >nul
if not errorlevel 1 (
    echo ATENCION: todavia no editaste config.json con los datos de tu impresora.
    echo Abrilo con el Bloc de notas y completa:
    echo   - printer_ip   : IP de la impresora en tu red
    echo   - access_code  : codigo de acceso LAN de la impresora
    echo   - serial       : numero de serie de la impresora
    echo Encontras estos 3 datos en la pantalla de la impresora: Configuracion - Red / WLAN.
    echo.
    echo Ejecuta este instalador de nuevo despues de guardar los cambios.
    pause
    exit /b 1
)

set "PYTHONW="
for /f "delims=" %%P in ('where pythonw 2^>nul') do (
    if not defined PYTHONW set "PYTHONW=%%P"
)

if not defined PYTHONW (
    echo No encontre Python instalado ^(pythonw.exe^) en el PATH.
    echo Instala Python desde https://www.python.org/downloads/ y marca la opcion
    echo "Add python.exe to PATH" durante la instalacion. Despues volve a correr este instalador.
    pause
    exit /b 1
)

for %%F in ("%PYTHONW%") do set "PYDIR=%%~dpF"
set "PYTHONEXE=%PYDIR%python.exe"

echo Python encontrado en: %PYTHONW%
echo.
echo Instalando dependencias (openpyxl, pandas, paho-mqtt)...
"%PYTHONEXE%" -m pip install --quiet openpyxl pandas paho-mqtt
if errorlevel 1 (
    echo Hubo un problema instalando las dependencias. Revisa tu conexion a internet.
    pause
    exit /b 1
)

echo.
echo Probando conexion con la impresora...
"%PYTHONEXE%" "%SCRIPT_DIR%test_connection.py"
if errorlevel 1 (
    echo.
    echo No se pudo conectar. Revisa IP / codigo de acceso / numero de serie en config.json,
    echo y que la impresora este prendida, en la misma red WiFi.
    pause
    exit /b 1
)

echo.
echo Conexion OK. Configurando inicio automatico con Windows...

set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LAUNCHER=%STARTUP%\bambu_sync_launcher.vbs"

> "%LAUNCHER%" (
    echo Set WshShell = CreateObject("WScript.Shell"^)
    echo Do
    echo     WshShell.Run """%PYTHONW%"" ""%SCRIPT_DIR%bambu_sync.py""", 0, True
    echo     WScript.Sleep 5000
    echo Loop
)

echo Listo. El servicio va a arrancar solo cada vez que inicies sesion en Windows.
echo Arrancandolo ahora mismo...
wscript.exe "%LAUNCHER%"

echo.
echo ===============================================
echo  Instalacion completa. El Excel esta en:
echo  %SCRIPT_DIR%impresiones_3d.xlsx
echo  Se va a ir completando solo con cada impresion.
echo ===============================================
pause

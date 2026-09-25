@echo off
chcp 65001 > nul
title MediaGet Server

echo.
echo ============================================
echo         MediaGet - Media Yukleyici
echo ============================================
echo.

rem Virtual environment yoxlanisi
if not exist "backend\venv" (
    echo [*] Ilk defe ise salinir - asililiqlar qurasdirilir...
    python -m venv backend\venv
    if errorlevel 1 (
        echo [XETA] Python tapilmadi. Zehmet olmasa Python 3.10+ qurasdirin.
        pause
        exit /b 1
    )
    call backend\venv\Scripts\activate.bat
    echo [*] Paketler yuklenir...
    pip install -r backend\requirements.txt --quiet
    echo [OK] Qurasdirma tamamlandi!
    echo.
) else (
    call backend\venv\Scripts\activate.bat
)

rem Deno JS runtime yoxlanisi
if not exist "backend\bin\deno.exe" (
    echo [*] YouTube JS mühərriki (Deno) yüklənir...
    powershell -Command "New-Item -ItemType Directory -Force -Path 'backend\bin' | Out-Null; Invoke-WebRequest -Uri 'https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip' -OutFile 'backend\bin\deno.zip'; Expand-Archive -Path 'backend\bin\deno.zip' -DestinationPath 'backend\bin' -Force; Remove-Item 'backend\bin\deno.zip' -Force"
)

echo [*] Server basladilir: http://localhost:8000
echo [*] Sayt brauzerinizde acilir...
echo [*] Dayandirmaq ucun: Ctrl+C
echo --------------------------------------------
echo.

rem Brauzeri avtomatik ac
start http://localhost:8000

rem Serveri venv python ile ise sal
backend\venv\Scripts\python.exe backend\main.py

pause

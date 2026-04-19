@echo off
REM Overnight Momentum Strategy - Windows one-click build script
REM Produces dist\oms.exe

setlocal

REM Locate project root (directory of this script)
pushd "%~dp0"

echo [1/4] Checking venv...
if not exist "venv\Scripts\python.exe" (
    echo   ERROR: venv not found. Run: python -m venv venv ^&^& venv\Scripts\pip install -r requirements.txt
    popd
    exit /b 1
)

echo [2/4] Installing PyInstaller if missing...
venv\Scripts\pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    venv\Scripts\pip install pyinstaller || (popd & exit /b 1)
)

echo [3/4] Cleaning previous build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [4/4] Building oms.exe (this may take 3-5 minutes)...
venv\Scripts\pyinstaller oms.spec --clean --noconfirm
if errorlevel 1 (
    echo BUILD FAILED
    popd
    exit /b 1
)

echo.
echo ====== BUILD OK ======
echo Output: %CD%\dist\oms.exe
echo Test with: dist\oms.exe selftest
echo =======================

popd
endlocal

@echo off
cd /d "%~dp0"
echo Installing dependencies...
pip install -r requirements.txt pyinstaller -q
echo Building PC-Checker.exe...
pyinstaller --noconfirm pc-checker.spec
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)
echo.
echo Done: dist\PC-Checker.exe
pause

@echo off
cd /d "%~dp0"
echo Installing dependencies...
pip install -r requirements.txt pyinstaller -q
echo Building PC Checker.exe...
pyinstaller --noconfirm --onefile --windowed --name "PC Checker" ^
  --add-data "src;src" ^
  --paths "." ^
  --collect-all customtkinter ^
  main.py
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)
echo.
echo Done! Run: dist\PC Checker.exe
pause

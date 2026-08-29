@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-market-test-bench.ps1"
if errorlevel 1 (
  echo.
  echo MarketTestBench could not start. The error is shown above.
  pause
)
endlocal

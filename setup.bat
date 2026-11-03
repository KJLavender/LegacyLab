@echo off
rem One-time setup: Python venv + optional deps, sample data, build LegacyApp. No admin rights needed.
setlocal
cd /d "%~dp0"
where uv >nul 2>nul
if %ERRORLEVEL%==0 (
  uv venv --python 3.11 .venv || exit /b 1
  uv pip install --python .venv\Scripts\python.exe -e ".[ocr,changepoint,spc,portal,inspect,dev]" || exit /b 1
) else (
  python -m venv .venv || exit /b 1
  .venv\Scripts\python -m pip install -e ".[ocr,changepoint,spc,portal,inspect,dev]" || exit /b 1
)
.venv\Scripts\python -m sim.datagen.generate --seed 42 || exit /b 1
call sim\legacyapp\build.bat || exit /b 1
echo.
echo Setup done. Try:  .venv\Scripts\python -m bench.analysis_bench

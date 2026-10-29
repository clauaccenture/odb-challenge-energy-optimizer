@echo off
cd /d "%~dp0"
"%~dp0EnergyOptimizer.exe" --dashboard-only
if errorlevel 1 (
    echo.
    echo No se ha podido abrir el dashboard. Revisa el error anterior.
    pause
)

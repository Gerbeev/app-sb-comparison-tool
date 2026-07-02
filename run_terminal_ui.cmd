@echo off
setlocal
cd /d "%~dp0"
echo Starting Stonebranch Dependency Tool terminal UI...
echo.
python -m stonebranch_graph.cli tui
pause

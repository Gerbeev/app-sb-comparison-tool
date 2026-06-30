@echo off
setlocal
cd /d "%~dp0"
echo Starting Stonebranch Dependency Tool terminal UI...
echo.
py -3 -m stonebranch_graph.cli tui
pause

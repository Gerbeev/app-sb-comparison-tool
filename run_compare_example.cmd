@echo off
setlocal
py -3 -m stonebranch_graph.cli compare --stonebranch examples\stonebranch\PROD --jil examples\jil\PROD --env PROD -o out-example
echo.
echo Open out-example\compare\report.md
pause

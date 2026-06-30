@echo off
setlocal

echo Stonebranch Dependency Tool v0.3 - compare Stonebranch JSON vs AutoSys JIL
echo.

set /p SB_PATH=Stonebranch PROD folder path: 
if "%SB_PATH%"=="" (
  echo Stonebranch path is required.
  pause
  exit /b 1
)

set /p JIL_PATH=JIL folder path: 
if "%JIL_PATH%"=="" (
  echo JIL path is required.
  pause
  exit /b 1
)

set /p ENV_NAME=Environment name [PROD]: 
if "%ENV_NAME%"=="" set ENV_NAME=PROD

set /p OUTPUT_PATH=Output folder [out-compare]: 
if "%OUTPUT_PATH%"=="" set OUTPUT_PATH=out-compare

py -3 -m stonebranch_graph.cli compare --stonebranch "%SB_PATH%" --jil "%JIL_PATH%" --env "%ENV_NAME%" -o "%OUTPUT_PATH%"

echo.
echo Done. Open:
echo   %OUTPUT_PATH%\compare\report.md
echo   %OUTPUT_PATH%\compare\comparison.json
echo   %OUTPUT_PATH%\stonebranch\graph.json
echo   %OUTPUT_PATH%\jil\graph.json
echo.
pause

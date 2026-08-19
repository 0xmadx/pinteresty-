@echo off
REM Daily entry point for Windows Task Scheduler.
REM
REM Runs whatever is DUE and exits -- no daemon. Due-ness is measured from the last
REM successful run and persisted in config/scheduler_state.json, so a missed day runs
REM late rather than being skipped. That distinction is the whole point: a scheduler
REM firing "every 24h from now" silently loses every window it was asleep for, and the
REM gap is invisible afterwards because the rows simply are not there.
REM
REM Register it (no admin needed, runs as the logged-in user):
REM   schtasks /Create /TN "EtsyScrapperDaily" /TR "\"%~f0\"" /SC DAILY /ST 07:00 /F
REM
REM Check on it:
REM   schtasks /Query /TN "EtsyScrapperDaily" /V /FO LIST
REM   .venv\Scripts\python.exe -m core.runlog

cd /d "%~dp0"
if not exist "etsy\data\logs" mkdir "etsy\data\logs"

REM Append, never overwrite: the log IS the record of whether the clock kept running.
echo. >> "etsy\data\logs\scheduler.log"
echo ==== %DATE% %TIME% ==== >> "etsy\data\logs\scheduler.log"
".venv\Scripts\python.exe" -m core.scheduler --once >> "etsy\data\logs\scheduler.log" 2>&1
echo exit=%ERRORLEVEL% >> "etsy\data\logs\scheduler.log"
exit /b %ERRORLEVEL%

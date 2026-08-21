@echo off
REM The optional read server — the interactive app, live from the database, plus
REM on-demand analysis of a keyword you type. NOT required: the batch scheduler and
REM the static files (etsy\data\ui\*.html) work with no server at all. Run this only
REM when you want live data or access from another device.
REM
REM   http://127.0.0.1:8100/          the interactive app
REM   http://127.0.0.1:8100/api/docs  the API (Swagger)
REM
REM Bind to the LAN (reach it from your phone) by setting HOST — but it exposes your
REM private market data with NO auth, so only on a network you trust:
REM   set HOST=0.0.0.0 && run_server.cmd

cd /d "%~dp0"
".venv\Scripts\python.exe" -m etsy.server.app

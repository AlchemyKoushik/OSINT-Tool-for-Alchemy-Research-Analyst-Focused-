@echo off
setlocal EnableExtensions
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_client.ps1"
pause

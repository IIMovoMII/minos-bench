@echo off
chcp 65001 >nul
set /p EXECUTION_ID=请输入本次唯一执行编号（例如 scientific-v2-20260804-a）: 
if "%EXECUTION_ID%"=="" (
  echo 执行编号不能为空。
  pause
  exit /b 2
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_scientific_v2.ps1" -ExecutionId "%EXECUTION_ID%"
pause

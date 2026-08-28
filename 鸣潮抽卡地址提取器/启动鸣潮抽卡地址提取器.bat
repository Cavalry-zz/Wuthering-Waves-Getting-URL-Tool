@echo off
chcp 65001 >nul
cd /d "%~dp0"
pythonw wuwa_link_extractor.py
if errorlevel 1 (
  echo 启动失败，请确认已经安装 Python 3.10 或更高版本。
  pause
)

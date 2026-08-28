@echo off
chcp 65001 >nul
cd /d "%~dp0"
python wuwa_link_extractor.py --once
pause

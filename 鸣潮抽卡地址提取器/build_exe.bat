@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "鸣潮抽卡地址提取器" wuwa_link_extractor.py
echo.
echo 构建完成：dist\鸣潮抽卡地址提取器.exe
pause

# 鸣潮抽卡记录地址提取器

Windows 本地小工具。运行后，在《鸣潮》里打开“唤取 → 唤取记录”，程序会自动从 `Client.log` 中提取当前账号的抽卡记录地址，并复制到剪贴板。

## 直接使用

优先运行打包好的：

```text
dist\鸣潮抽卡地址提取器.exe
```

如果尚未构建 EXE，电脑安装了 Python 3.10+ 时，可双击：

```text
启动鸣潮抽卡地址提取器.bat
```

使用步骤：

1. 启动鸣潮并进入游戏。
2. 打开本工具，让它保持运行。
3. 在游戏内打开“唤取 → 唤取记录”。
4. 工具检测到地址后会自动复制；可粘贴到支持鸣潮记录导入的分析工具。

如果自动定位失败，点击“手动选择 Client.log”。常见位置：

```text
游戏安装目录\Wuthering Waves Game\Client\Saved\Logs\Client.log
```

## 特性

- 纯本地运行，不上传日志或账号信息。
- 自动从游戏进程、注册表和常见安装目录寻找日志。
- 同时支持国服/国际服链接。
- 支持新版异或编码日志和旧版明文日志。
- 支持 JSON 转义形式的 WebView 日志内容。
- 记住手动选择过的日志路径。

## 命令行

提取日志中最近的一条地址：

```powershell
python wuwa_link_extractor.py --once
```

手动指定日志：

```powershell
python wuwa_link_extractor.py --once --log "D:\Wuthering Waves\Wuthering Waves Game\Client\Saved\Logs\Client.log"
```

## 构建 EXE

双击 `build_exe.bat`，或执行：

```powershell
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "鸣潮抽卡地址提取器" wuwa_link_extractor.py
```

## 隐私与安全

抽卡记录地址包含有时效的临时身份参数。请不要把完整地址发到群聊、论坛或公开仓库。地址失效后，在游戏里重新打开一次“唤取记录”即可生成新地址。

本工具仅用于读取玩家本人电脑上的游戏日志，不修改游戏文件，不注入游戏进程。

## 参考

日志位置与新版编码兼容思路参考了以下 MIT 开源项目，并在本工具中重新实现：

- <https://github.com/Anubhav1603/Wuthering-Waves-Convene-URL-Extractor>
- <https://github.com/SugarRainbow/wuwa-gacha-url-extractor>

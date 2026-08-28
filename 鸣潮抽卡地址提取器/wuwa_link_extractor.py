from __future__ import annotations

import argparse
import ctypes
import html
import json
import os
import queue
import re
import sys
import threading
import time
import webbrowser
from ctypes import wintypes
from pathlib import Path
from typing import Callable, Iterable


APP_NAME = "鸣潮抽卡记录地址提取器"
POLL_SECONDS = 0.8
MAX_TAIL_BYTES = 8 * 1024 * 1024

PROCESS_NAMES = {
    "client-win64-shipping.exe",
    "wuthering waves.exe",
    "wutheringwaves.exe",
    "mingchao.exe",
}

# 新版 Client.log 的部分内容采用按密文字节奇偶选择密钥的异或编码。
DECODE_TABLE = bytes(
    (value ^ 0xA5) if value % 2 == 1 else (value ^ 0xEF)
    for value in range(256)
)

URL_PATTERN = re.compile(r"https?://[^\s\"'\\<>\[\]\x00-\x1f]+", re.IGNORECASE)


def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "WuwaGachaLinkExtractor"


def config_path() -> Path:
    return app_data_dir() / "config.json"


def load_saved_log_path() -> Path | None:
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
        value = data.get("client_log")
        if value:
            return Path(value)
    except (OSError, ValueError, TypeError):
        pass
    return None


def save_log_path(path: Path) -> None:
    try:
        app_data_dir().mkdir(parents=True, exist_ok=True)
        config_path().write_text(
            json.dumps({"client_log": str(path)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def normalize_log_text(text: str) -> str:
    return (
        text.replace("\\/", "/")
        .replace("\\u0026", "&")
        .replace("\\u003d", "=")
        .replace("\\x26", "&")
    )


def clean_url(url: str) -> str:
    value = html.unescape(url.strip())
    value = value.rstrip("),.;:]}>'\"")
    return value


def is_convene_record_url(url: str) -> bool:
    lowered = url.casefold()
    if not lowered.startswith(("http://", "https://")):
        return False

    # 避免把普通公告、资源下载等 URL 当成抽卡链接。
    required_identity = "record_id=" in lowered and (
        "player_id=" in lowered or "role_id=" in lowered
    )
    record_page = (
        "/gacha/" in lowered
        or "#/record" in lowered
        or "gacha_id=" in lowered
    )
    return required_identity and record_page


def extract_convene_urls(text: str) -> list[str]:
    normalized = normalize_log_text(text)
    result: list[str] = []
    seen: set[str] = set()
    for match in URL_PATTERN.finditer(normalized):
        url = clean_url(match.group(0))
        if is_convene_record_url(url) and url not in seen:
            seen.add(url)
            result.append(url)
    return result


def decoded_text_views(raw: bytes) -> Iterable[str]:
    variants = (raw, raw.translate(DECODE_TABLE), raw[3:].translate(DECODE_TABLE))
    for data in variants:
        for encoding in ("utf-8", "gb18030"):
            text = data.decode(encoding, errors="ignore")
            if text:
                yield text


def extract_urls_from_bytes(raw: bytes) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for text in decoded_text_views(raw):
        for url in extract_convene_urls(text):
            if url not in seen:
                seen.add(url)
                result.append(url)
    return result


def read_latest_url(path: Path, max_bytes: int = MAX_TAIL_BYTES) -> str | None:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(max(0, size - max_bytes))
            raw = handle.read()
    except OSError:
        return None
    urls = extract_urls_from_bytes(raw)
    return urls[-1] if urls else None


def possible_log_files(base: Path) -> Iterable[Path]:
    relatives = (
        Path("Client") / "Saved" / "Logs" / "Client.log",
        Path("Saved") / "Logs" / "Client.log",
        Path("Wuthering Waves Game") / "Client" / "Saved" / "Logs" / "Client.log",
        Path("Wuthering Waves") / "Wuthering Waves Game" / "Client" / "Saved" / "Logs" / "Client.log",
    )
    yielded: set[str] = set()
    for root in (base, *base.parents):
        for relative in relatives:
            candidate = root / relative
            key = str(candidate).casefold()
            if key not in yielded:
                yielded.add(key)
                yield candidate


def find_log_near_path(path: Path | None) -> Path | None:
    if not path:
        return None
    if path.is_file() and path.name.casefold() == "client.log":
        return path
    base = path.parent if path.is_file() else path
    for candidate in possible_log_files(base):
        if candidate.is_file():
            return candidate
    return None


def iter_process_executables() -> Iterable[Path]:
    if os.name != "nt":
        return

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        return

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.casefold() in PROCESS_NAMES:
                process = kernel32.OpenProcess(0x1000, False, entry.th32ProcessID)
                if process:
                    try:
                        capacity = wintypes.DWORD(32768)
                        buffer = ctypes.create_unicode_buffer(capacity.value)
                        if kernel32.QueryFullProcessImageNameW(
                            process, 0, buffer, ctypes.byref(capacity)
                        ):
                            yield Path(buffer.value)
                    finally:
                        kernel32.CloseHandle(process)
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)


def iter_registry_install_paths() -> Iterable[Path]:
    if os.name != "nt":
        return
    try:
        import winreg
    except ImportError:
        return

    roots = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    for hive, key_name in roots:
        try:
            with winreg.OpenKey(hive, key_name) as root:
                subkey_count = winreg.QueryInfoKey(root)[0]
                for index in range(subkey_count):
                    try:
                        subkey_name = winreg.EnumKey(root, index)
                        with winreg.OpenKey(root, subkey_name) as subkey:
                            display_name = str(winreg.QueryValueEx(subkey, "DisplayName")[0])
                            if not any(word in display_name.casefold() for word in ("wuthering", "鸣潮")):
                                continue
                            for value_name in ("InstallLocation", "InstallPath", "DisplayIcon"):
                                try:
                                    value = str(winreg.QueryValueEx(subkey, value_name)[0]).strip('"')
                                except OSError:
                                    continue
                                if value:
                                    yield Path(value.split(",")[0])
                    except OSError:
                        continue
        except OSError:
            continue


def iter_common_install_paths() -> Iterable[Path]:
    if os.name != "nt":
        return
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    for index in range(26):
        if not mask & (1 << index):
            continue
        drive = f"{chr(65 + index)}:\\"
        for relative in (
            "Wuthering Waves Game",
            r"Wuthering Waves\Wuthering Waves Game",
            r"鸣潮\Wuthering Waves Game",
            r"Program Files\Wuthering Waves\Wuthering Waves Game",
        ):
            yield Path(drive) / relative


def locate_client_log(preferred: Path | None = None) -> Path | None:
    candidates: list[Path | None] = [preferred, load_saved_log_path()]
    candidates.extend(iter_process_executables() or ())
    candidates.extend(iter_registry_install_paths() or ())
    candidates.extend(iter_common_install_paths() or ())

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        key = str(candidate).casefold()
        if key in seen:
            continue
        seen.add(key)
        found = find_log_near_path(candidate)
        if found:
            return found
    return None


class LogMonitor:
    def __init__(
        self,
        on_event: Callable[[str, object], None],
        preferred_path: Path | None = None,
    ) -> None:
        self.on_event = on_event
        self.preferred_path = preferred_path
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def _emit(self, kind: str, value: object) -> None:
        self.on_event(kind, value)

    def _run(self) -> None:
        current: Path | None = None
        last_url: str | None = None
        last_lookup_notice = 0.0
        raw_buffer = b""
        offset = 0

        while not self.stop_event.is_set():
            if not current or not current.is_file():
                current = locate_client_log(self.preferred_path)
                if not current:
                    now = time.monotonic()
                    if now - last_lookup_notice > 4:
                        self._emit("status", "正在寻找鸣潮日志；请先启动游戏。")
                        last_lookup_notice = now
                    self.stop_event.wait(2)
                    continue
                save_log_path(current)
                self._emit("log_path", current)
                self._emit("status", "监听中：请在游戏内打开“唤取 → 唤取记录”。")
                try:
                    size = current.stat().st_size
                    offset = max(0, size - MAX_TAIL_BYTES)
                except OSError:
                    current = None
                    continue
                raw_buffer = b""

            try:
                size = current.stat().st_size
                if size < offset:
                    offset = 0
                    raw_buffer = b""
                if size > offset:
                    with current.open("rb") as handle:
                        handle.seek(offset)
                        chunk = handle.read(size - offset)
                    offset = size
                    raw_buffer = (raw_buffer + chunk)[-MAX_TAIL_BYTES:]
                    urls = extract_urls_from_bytes(raw_buffer)
                    if urls and urls[-1] != last_url:
                        last_url = urls[-1]
                        self._emit("url", last_url)
            except OSError:
                current = None
                self._emit("status", "日志暂时无法读取，正在重新定位。")

            self.stop_event.wait(POLL_SECONDS)


class ExtractorApp:
    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("760x470")
        self.root.minsize(660, 420)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.monitor = LogMonitor(self._post_event)
        self.current_url = ""

        self.status_var = tk.StringVar(value="正在启动监听……")
        self.path_var = tk.StringVar(value="尚未定位日志")
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self._drain_events)
        self.monitor.start()

    def _build_ui(self) -> None:
        tk = self.tk
        ttk = self.ttk
        outer = ttk.Frame(self.root, padding=22)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="鸣潮抽卡记录地址提取器", font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="保持本工具运行，然后在游戏里打开：唤取 → 唤取记录",
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", pady=(6, 18))

        status_box = ttk.LabelFrame(outer, text="状态", padding=12)
        status_box.pack(fill="x")
        ttk.Label(status_box, textvariable=self.status_var, font=("Microsoft YaHei UI", 10)).pack(anchor="w")
        ttk.Label(status_box, textvariable=self.path_var, foreground="#666666", wraplength=690).pack(anchor="w", pady=(6, 0))

        result_box = ttk.LabelFrame(outer, text="提取到的分析地址", padding=12)
        result_box.pack(fill="both", expand=True, pady=(14, 12))
        self.url_text = tk.Text(result_box, height=7, wrap="char", font=("Consolas", 10))
        self.url_text.pack(fill="both", expand=True)
        self.url_text.insert("1.0", "等待打开抽卡记录页面……")
        self.url_text.configure(state="disabled")

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x")
        self.copy_button = ttk.Button(buttons, text="复制地址", command=self.copy_url, state="disabled")
        self.copy_button.pack(side="left")
        self.open_button = ttk.Button(buttons, text="在浏览器打开", command=self.open_url, state="disabled")
        self.open_button.pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="手动选择 Client.log", command=self.choose_log).pack(side="right")

        ttk.Label(
            outer,
            text="隐私提示：程序只在本机读取日志，不会上传数据。链接含临时身份参数，请勿公开分享。",
            foreground="#8a5a00",
            wraplength=710,
        ).pack(anchor="w", pady=(14, 0))

    def _post_event(self, kind: str, value: object) -> None:
        self.events.put((kind, value))

    def _drain_events(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "status":
                    self.status_var.set(str(value))
                elif kind == "log_path":
                    self.path_var.set(f"日志：{value}")
                elif kind == "url":
                    self._show_url(str(value))
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _show_url(self, url: str) -> None:
        self.current_url = url
        self.url_text.configure(state="normal")
        self.url_text.delete("1.0", "end")
        self.url_text.insert("1.0", url)
        self.url_text.configure(state="disabled")
        self.copy_button.configure(state="normal")
        self.open_button.configure(state="normal")
        self.copy_url(silent=True)
        self.status_var.set("提取成功，地址已自动复制到剪贴板。")
        self.root.bell()

    def copy_url(self, silent: bool = False) -> None:
        if not self.current_url:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.current_url)
        self.root.update_idletasks()
        if not silent:
            self.status_var.set("地址已复制到剪贴板。")

    def open_url(self) -> None:
        if self.current_url:
            webbrowser.open(self.current_url)

    def choose_log(self) -> None:
        from tkinter import filedialog

        value = filedialog.askopenfilename(
            title="选择鸣潮 Client.log",
            filetypes=(("Client.log", "Client.log"), ("日志文件", "*.log"), ("所有文件", "*.*")),
        )
        if not value:
            return
        path = Path(value)
        save_log_path(path)
        self.monitor.stop()
        self.monitor = LogMonitor(self._post_event, preferred_path=path)
        self.monitor.start()
        self.path_var.set(f"日志：{path}")
        self.status_var.set("已切换日志，等待打开唤取记录页面。")

    def close(self) -> None:
        self.monitor.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def cli_once(log_path: Path | None) -> int:
    found = locate_client_log(log_path)
    if not found:
        print("没有找到 Client.log。请启动鸣潮，或使用 --log 指定文件。", file=sys.stderr)
        return 1
    print(f"日志：{found}", file=sys.stderr)
    url = read_latest_url(found)
    if not url:
        print("未找到抽卡记录地址。请先在游戏内打开“唤取记录”。", file=sys.stderr)
        return 2
    print(url)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--once", action="store_true", help="从日志中读取一次并输出到终端")
    parser.add_argument("--log", type=Path, help="手动指定 Client.log")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.once:
        return cli_once(args.log)
    app = ExtractorApp()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

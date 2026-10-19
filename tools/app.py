"""Shared player GUI for the font and Chinese NarciBloom installers."""
from __future__ import annotations

import argparse
import importlib
import locale
import os
from pathlib import Path
import queue
import sys
import threading
import traceback
import webbrowser

SOURCE_URL = "https://www.rainlain.com/index.php/2024/11/01/2567/"
ARCHIVE_NAME = "N10 ver1.1补丁.rar"
LANGUAGES = {"日本語": "ja", "English": "en", "简体中文": "zh"}
TEXT = {
    "zh": {
        "title": "NarciBloom · 水仙舒读", "font_mode": "字体补丁", "chinese_mode": "中文整合",
        "preview": "开发预览 · 尚未逐章验证", "language": "界面语言", "location": "Steam 游戏目录",
        "browse": "选择目录…", "scan": "检查目录", "find": "重新查找 Steam", "stories": "选择故事",
        "all": "全选", "none": "全不选", "empty": "找到游戏后，将显示实际已安装的故事。",
        "unknown": "未识别版本，暂不支持", "ja": "日文", "en": "英文", "zh-CN": "简体中文",
        "unrecognized": "语言未识别", "version": "当前补丁：{version}", "not_installed": "尚未安装 NarciBloom",
        "font": "默认字体（可选）", "keep_font": "留空自动选择已装字体", "archive": "原汉化 PC v1.1 RAR",
        "archive_browse": "选择 RAR…", "source": "汉化原发布页", "install": "安装 / 更新", "uninstall": "卸载并恢复",
        "copy": "复制日志", "working": "正在处理，请稍候…", "searching": "正在查找 Steam 并检查游戏…",
        "ready": "已检查目录。请选择故事，然后安装。", "no_game": "没有自动找到游戏，请选择 Steam 十周年合集目录。",
        "no_story": "没有找到可安装的故事。请检查目录与游戏文件；不支持的版本已在上方标出。",
        "close_busy": "任务正在进行，请等待完成后再关闭窗口。", "busy_title": "任务进行中",
        "error_title": "未完成", "error": "操作未完成；详细原因已保留在日志中。", "copied": "日志已复制。",
        "installed": "安装完成。请返回 Steam 启动游戏。", "uninstalled": "卸载完成，已恢复原文件并保留存档。",
        "need_archive": "请先选择原汉化 PC v1.1 RAR；整合包内的同名原包可自动使用。",
        "backend_missing": "安装组件未能加载，请重新解压完整安装包；详细原因见日志。",
        "backend_dev": "开发环境未能加载 installer_app_backend；请检查依赖与日志。",
        "font_scope": "只处理已安装、已识别且勾选的故事；保留当前剧情语言，不下载游戏或 DLC。",
        "chinese_scope": "原汉化 PC v1.1 ＋可调字号；仅处理已安装且支持的故事，需要自有 Steam 游戏。",
        "choose_game": "选择十周年合集游戏根目录", "choose_archive": "选择原汉化 PC v1.1 RAR",
        "log": "进度与日志", "path_changed": "目录已变更，请先检查目录。",
        "recovery": "检测到未完成的操作；安装或卸载会先恢复，发现后续文件变化时会停止。",
    },
    "en": {
        "title": "NarciBloom", "font_mode": "Font patch", "chinese_mode": "Chinese bundle",
        "preview": "Developer preview · Full story playthroughs pending", "language": "Interface language",
        "location": "Steam game folder", "browse": "Browse…", "scan": "Check folder", "find": "Find Steam again",
        "stories": "Choose stories", "all": "Select all", "none": "Clear", "empty": "Installed stories will appear after checking the game folder.",
        "unknown": "Unrecognized version; unsupported", "ja": "Japanese", "en": "English", "zh-CN": "Simplified Chinese",
        "unrecognized": "Language unrecognized", "version": "Installed patch: {version}", "not_installed": "NarciBloom is not installed",
        "font": "Default font (optional)", "keep_font": "Blank: select a local font", "archive": "Original PC v1.1 translation RAR",
        "archive_browse": "Choose RAR…", "source": "Original translation release", "install": "Install / Update", "uninstall": "Uninstall & Restore",
        "copy": "Copy log", "working": "Working, please wait…", "searching": "Finding Steam and checking game files…",
        "ready": "Folder checked. Choose stories, then install.", "no_game": "No game found automatically. Select the Steam anthology folder.",
        "no_story": "No supported installed stories found. Check the folder and game files; unsupported versions are listed above.",
        "close_busy": "An operation is running. Please wait for it to finish before closing.", "busy_title": "Operation running",
        "error_title": "Not completed", "error": "The operation was not completed. The log contains the reason.", "copied": "Log copied.",
        "installed": "Installation complete. Launch the game through Steam.", "uninstalled": "Uninstall complete. Original files restored; saves retained.",
        "need_archive": "Choose the original PC v1.1 translation RAR. The bundle's accompanying archive is detected automatically.",
        "backend_missing": "Installation components could not load. Extract the complete package again; see the log for details.",
        "backend_dev": "Cannot load installer_app_backend in this development environment. Check dependencies and the log.",
        "font_scope": "Only selected, recognized, installed stories are changed. Story language is retained; no game or DLC downloads.",
        "chinese_scope": "PC v1.1 Chinese translation + adjustable font size. Only supported installed stories; requires your Steam game.",
        "choose_game": "Select the anthology's game root folder", "choose_archive": "Choose the original PC v1.1 translation RAR",
        "log": "Progress and log", "path_changed": "Folder changed. Check the folder before installing.",
        "recovery": "An interrupted operation needs recovery. Install or Uninstall will recover first, stopping if files changed afterwards.",
    },
    "ja": {
        "title": "NarciBloom", "font_mode": "フォントパッチ", "chinese_mode": "中国語統合パッケージ",
        "preview": "開発プレビュー・全編の動作確認は未完了", "language": "表示言語", "location": "Steam ゲームフォルダー",
        "browse": "フォルダー選択…", "scan": "フォルダー確認", "find": "Steam を再検索", "stories": "作品を選択",
        "all": "すべて選択", "none": "選択解除", "empty": "ゲームを確認すると、インストール済みの作品が表示されます。",
        "unknown": "未認識のバージョン・未対応", "ja": "日本語", "en": "英語", "zh-CN": "簡体字中国語",
        "unrecognized": "言語未認識", "version": "導入済みパッチ：{version}", "not_installed": "NarciBloom は未導入です",
        "font": "標準フォント（任意）", "keep_font": "空欄：既存フォントを自動選択", "archive": "中国語訳 PC v1.1 の原本 RAR",
        "archive_browse": "RAR を選択…", "source": "中国語訳の公式配布ページ", "install": "インストール / 更新", "uninstall": "削除して元に戻す",
        "copy": "ログをコピー", "working": "処理中です。しばらくお待ちください…", "searching": "Steam を検索し、ゲームを確認中…",
        "ready": "確認しました。作品を選択してインストールしてください。", "no_game": "自動検出できませんでした。Steam 十周年合集のフォルダーを選択してください。",
        "no_story": "対応する作品が見つかりません。フォルダーとゲームファイルを確認してください。未対応の版は上に表示されます。",
        "close_busy": "処理中です。完了してからウィンドウを閉じてください。", "busy_title": "処理中",
        "error_title": "完了できませんでした", "error": "処理は完了していません。詳しい理由はログをご確認ください。", "copied": "ログをコピーしました。",
        "installed": "インストール完了。Steam からゲームを起動してください。", "uninstalled": "削除完了。元のファイルに復元し、セーブは保持しました。",
        "need_archive": "中国語訳 PC v1.1 の原本 RAR を選択してください。同梱された原本は自動検出されます。",
        "backend_missing": "インストール部品を読み込めません。パッケージ全体を再展開し、ログを確認してください。",
        "backend_dev": "開発環境で installer_app_backend を読み込めません。依存関係とログを確認してください。",
        "font_scope": "選択した導入済み・認識済みの作品のみ変更します。本文の言語を保持し、ゲームや DLC はダウンロードしません。",
        "chinese_scope": "中国語訳 PC v1.1 ＋文字サイズ設定。対応する導入済み作品のみ対象。自分の Steam ゲームが必要です。",
        "choose_game": "十周年合集のゲームルートを選択", "choose_archive": "中国語訳 PC v1.1 の原本 RAR を選択",
        "log": "進捗とログ", "path_changed": "フォルダーが変更されました。先に確認してください。",
        "recovery": "未完了の処理があります。導入・削除の前に復元し、後からファイルが変わっていれば停止します。",
    },
}


def default_language(mode="font"):
    if mode == "chinese":
        return "zh"
    try:
        name = locale.getlocale()[0] or ""
    except (ValueError, TypeError):
        name = ""
    language = name.replace("-", "_").split("_")[0].casefold()
    if language.startswith("japanese"):
        language = "ja"
    if language.startswith("chinese"):
        language = "zh"
    return language if language in TEXT else "en"


def default_mode():
    executable = Path(sys.executable if getattr(sys, "frozen", False) else sys.argv[0])
    return "chinese" if "chinese" in executable.name.casefold() else "font"


def companion_archive(directory: Path) -> Path | None:
    exact = directory / ARCHIVE_NAME
    if exact.is_file():
        return exact
    candidates = sorted(path for path in directory.glob("*.rar") if "1.1" in path.name and path.is_file())
    return candidates[0] if len(candidates) == 1 else None


def progress_message(value, *details, **fields):
    if isinstance(value, dict):
        value = value.get("message", value.get("status", str(value)))
    return " ".join(str(item) for item in (value, *details) if item is not None)


def configure_interface_fonts(root):
    """Use an installed sans-serif family in this Tk interpreter only."""
    from tkinter import font
    available = {family.casefold(): family for family in font.families(root)}
    preferred = (["Microsoft YaHei UI", "Segoe UI", "Microsoft YaHei"] if os.name == "nt"
                 else ["Noto Sans CJK SC", "Noto Sans", "Noto Sans CJK JP", "DejaVu Sans"])
    family = next((available[name.casefold()] for name in preferred if name.casefold() in available),
                  font.nametofont("TkDefaultFont", root=root).actual("family"))
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        font.nametofont(name, root=root).configure(family=family)
    return family


class InstallerApp:
    def __init__(self, root, *, mode="font", language="en", game_dir=""):
        import tkinter as tk
        from tkinter import font, ttk
        self.tk, self.ttk, self.root = tk, ttk, root
        self.interface_family = configure_interface_fonts(root)
        self.mode, self.language = mode, language
        self.events = queue.Queue()
        self.busy = False
        self.backend = None
        self.current_scan = None
        self.story_choices = []
        self.controls = []
        self.labels = []
        self.path = tk.StringVar(value=game_dir)
        self.archive = tk.StringVar()
        self.font = tk.StringVar()
        self.status = tk.StringVar()
        self.interface = tk.StringVar(value=next(key for key, value in LANGUAGES.items() if value == language))
        width = min(960, max(780, root.winfo_screenwidth() - 40))
        height = min(720, max(680, root.winfo_screenheight() - 70))
        root.geometry(f"{width}x{height}")
        root.minsize(780, 680)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Up>", lambda event: self.move_focus(event, False), add=True)
        root.bind("<Down>", lambda event: self.move_focus(event, True), add=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(".", font="TkDefaultFont")
        style.configure("Title.TLabel", font=(self.interface_family, 21, "bold"))
        style.configure("Main.TButton", padding=(16, 9))
        style.configure("TButton", padding=(8, 5))
        frame = ttk.Frame(root, padding=(22, 14))
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(7, weight=1)
        heading = ttk.Frame(frame)
        heading.grid(row=0, column=0, sticky="ew")
        heading.columnconfigure(0, weight=1)
        self.heading = ttk.Label(heading, style="Title.TLabel")
        self.heading.grid(row=0, column=0, sticky="w")
        language_box = ttk.Frame(heading)
        language_box.grid(row=0, column=1, sticky="e")
        self.label(language_box, "language").grid(row=0, column=0, padx=(0, 6))
        selector = ttk.Combobox(language_box, textvariable=self.interface, values=list(LANGUAGES), width=10, state="readonly")
        selector.grid(row=0, column=1)
        selector.bind("<<ComboboxSelected>>", self.change_language)
        self.control(selector, "readonly")
        self.preview = self.label(heading, "preview")
        self.preview.grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 8))
        self.scope = ttk.Label(frame, wraplength=900)
        self.scope.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        location = ttk.Frame(frame)
        location.grid(row=2, column=0, sticky="ew")
        location.columnconfigure(0, weight=1)
        self.label(location, "location").grid(row=0, column=0, sticky="w")
        self.game_selector = ttk.Combobox(location, textvariable=self.path)
        self.game_selector.grid(row=1, column=0, sticky="ew", pady=(3, 0))
        self.game_selector.bind("<<ComboboxSelected>>", lambda _: self.scan_selected())
        self.game_selector.bind("<Return>", lambda _: self.scan_selected())
        self.control(self.game_selector)
        self.button(location, "browse", self.choose_game).grid(row=1, column=1, padx=(7, 0))
        self.button(location, "scan", self.scan_selected).grid(row=1, column=2, padx=(7, 0))
        self.button(location, "find", self.discover).grid(row=0, column=1, columnspan=2, sticky="e")
        self.story_frame = ttk.LabelFrame(frame, padding=(10, 3))
        self.story_frame.grid(row=3, column=0, sticky="ew", pady=(10, 7))
        self.story_frame.columnconfigure(0, weight=1)
        self.story_list = ttk.Frame(self.story_frame)
        self.story_list.grid(row=0, column=0, sticky="ew")
        selection = ttk.Frame(self.story_frame)
        selection.grid(row=0, column=1, sticky="ne", padx=(10, 0))
        self.button(selection, "all", lambda: self.select_all(True)).pack(fill="x")
        self.button(selection, "none", lambda: self.select_all(False)).pack(fill="x", pady=(4, 0))
        options = ttk.Frame(frame)
        options.grid(row=4, column=0, sticky="ew")
        options.columnconfigure(1, weight=1)
        self.label(options, "font").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.font_box = ttk.Combobox(options, textvariable=self.font,
                                    values=sorted(set(font.families(root)), key=str.casefold))
        self.font_box.grid(row=0, column=1, sticky="ew")
        self.control(self.font_box)
        self.font_hint = self.label(options, "keep_font")
        self.font_hint.grid(row=0, column=2, sticky="w", padx=(7, 0))
        if mode == "chinese":
            self.label(options, "archive").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=(7, 0))
            archive_entry = ttk.Entry(options, textvariable=self.archive)
            archive_entry.grid(row=1, column=1, sticky="ew", pady=(7, 0))
            self.control(archive_entry)
            self.button(options, "archive_browse", self.choose_archive).grid(row=1, column=2, padx=(7, 0), pady=(7, 0))
            directory = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
            accompanying = companion_archive(directory)
            if accompanying:
                self.archive.set(str(accompanying))
        credits = ttk.Frame(frame)
        credits.grid(row=5, column=0, sticky="ew", pady=(9, 6))
        ttk.Label(credits, text="汉化：风铃汉化组；字体与平台适配：NarciBloom").pack(side="left")
        self.source_link = ttk.Label(credits, foreground="#1767a6", cursor="hand2", takefocus=True)
        self.source_link.pack(side="right", padx=(10, 0))
        self.source_link.bind("<Button-1>", lambda _: webbrowser.open(SOURCE_URL))
        self.source_link.bind("<Return>", lambda _: webbrowser.open(SOURCE_URL))
        actions = ttk.Frame(frame)
        actions.grid(row=6, column=0, sticky="ew")
        actions.columnconfigure(2, weight=1)
        self.install_button = self.button(actions, "install", self.install, style="Main.TButton")
        self.install_button.grid(row=0, column=0, padx=(0, 9))
        self.uninstall_button = self.button(actions, "uninstall", self.uninstall)
        self.uninstall_button.grid(row=0, column=1)
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=120)
        self.progress.grid(row=0, column=2, sticky="ew", padx=(15, 0))
        self.log_frame = ttk.LabelFrame(frame, padding=5)
        self.log_frame.grid(row=7, column=0, sticky="nsew", pady=(8, 5))
        self.log_frame.columnconfigure(0, weight=1)
        self.log_frame.rowconfigure(0, weight=1)
        self.log = tk.Text(self.log_frame, height=5, wrap="word", state="disabled", relief="flat",
                           takefocus=True, font="TkTextFont")
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(self.log_frame, command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)
        self.copy_button = self.button(self.log_frame, "copy", self.copy_log, busy_disable=False)
        self.copy_button.grid(row=1, column=0, columnspan=2, sticky="e", pady=(4, 0))
        self.status_label = ttk.Label(frame, textvariable=self.status, wraplength=900)
        self.status_label.grid(row=8, column=0, sticky="ew")
        frame.bind("<Configure>", lambda event: self.resize_text(event.width))
        self.path.trace_add("write", self.path_changed)
        self.refresh_language()
        self.render_stories()
        try:
            self.backend = importlib.import_module("installer_app_backend")
        except Exception:
            self.append_log(traceback.format_exc())
            self.status.set(self.t("backend_missing" if getattr(sys, "frozen", False) else "backend_dev"))
        self.update_controls()
        root.after(80, self.poll_events)
        if self.backend:
            root.after(120, self.discover)

    def t(self, key):
        return TEXT[self.language][key]

    def resize_text(self, width):
        for widget in (self.scope, self.source_link, self.status_label):
            widget.configure(wraplength=max(300, width))

    def move_focus(self, event, forwards):
        if event.widget.winfo_class() in {"TButton", "TCheckbutton", "TLabel"}:
            target = event.widget.tk_focusNext() if forwards else event.widget.tk_focusPrev()
            if target:
                target.focus_set()
            return "break"

    def label(self, parent, key, **kwargs):
        widget = self.ttk.Label(parent, **kwargs)
        self.labels.append((widget, key))
        return widget

    def control(self, widget, state="normal"):
        self.controls.append((widget, state))
        return widget

    def button(self, parent, key, command, busy_disable=True, **kwargs):
        widget = self.ttk.Button(parent, command=command, **kwargs)
        self.labels.append((widget, key))
        if busy_disable:
            self.control(widget)
        return widget

    def refresh_language(self):
        mode = self.t("chinese_mode" if self.mode == "chinese" else "font_mode")
        self.root.title(f"{self.t('title')} · {mode}")
        self.heading.configure(text=f"{self.t('title')} · {mode}")
        for widget, key in self.labels:
            if widget.winfo_exists():
                widget.configure(text=self.t(key))
        self.story_frame.configure(text=self.t("stories"))
        self.log_frame.configure(text=self.t("log"))
        self.scope.configure(text=self.t("chinese_scope" if self.mode == "chinese" else "font_scope"))
        self.source_link.configure(text=f"{self.t('source')} ↗")

    def change_language(self, _=None):
        self.language = LANGUAGES[self.interface.get()]
        self.refresh_language()
        self.render_stories()
        if not self.busy:
            self.status.set(self.scan_status(self.current_scan) if self.current_scan else self.t("no_game"))

    def render_stories(self):
        previous = {module["id"]: value.get() for module, value, _ in self.story_choices}
        for widget in self.story_list.winfo_children():
            widget.destroy()
        self.story_choices = []
        modules = self.current_scan.get("modules", []) if self.current_scan else []
        if not modules:
            self.ttk.Label(self.story_list, text=self.t("empty"), wraplength=630).pack(anchor="w", pady=6)
        for module in modules:
            variable = self.tk.BooleanVar(value=bool(module.get("supported")) and previous.get(module["id"], True))
            language = self.t(module.get("language")) if module.get("language") in {"ja", "en", "zh-CN"} else self.t("unrecognized")
            description = f"{module.get('title', module['id'])}  ·  {language}"
            if not module.get("supported"):
                description += f"  ·  {self.t('unknown')}"
            choice = self.ttk.Checkbutton(self.story_list, text=description, variable=variable, command=self.update_controls)
            choice.pack(anchor="w")
            self.story_choices.append((module, variable, choice))
        version = self.current_scan.get("installed_version") if self.current_scan else None
        version_text = self.t("version").format(version=version) if version else self.t("not_installed")
        self.story_frame.configure(text=f"{self.t('stories')} · {version_text}")
        self.update_controls()

    def matches_scan(self):
        if not self.current_scan:
            return False
        return os.path.normcase(os.path.abspath(self.path.get().strip())) == os.path.normcase(os.path.abspath(self.current_scan["path"]))

    def update_controls(self):
        for widget, state in self.controls:
            widget.configure(state="disabled" if self.busy else state)
        for module, variable, widget in self.story_choices:
            widget.configure(state="normal" if not self.busy and module.get("supported") else "disabled")
        valid = bool(self.backend) and self.matches_scan() and not self.busy
        selected = any(variable.get() and module.get("supported") for module, variable, _ in self.story_choices)
        self.install_button.configure(state="normal" if valid and selected else "disabled")
        self.uninstall_button.configure(state="normal" if valid else "disabled")

    def path_changed(self, *_):
        self.update_controls()
        if self.current_scan and not self.matches_scan() and not self.busy:
            self.status.set(self.t("path_changed"))

    def select_all(self, value):
        for module, variable, _ in self.story_choices:
            variable.set(value and bool(module.get("supported")))
        self.update_controls()

    def choose_game(self):
        from tkinter import filedialog
        directory = filedialog.askdirectory(parent=self.root, title=self.t("choose_game"), mustexist=True)
        if directory:
            self.path.set(directory)
            self.scan_selected()

    def choose_archive(self):
        from tkinter import filedialog
        archive = filedialog.askopenfilename(parent=self.root, title=self.t("choose_archive"),
                                              filetypes=[("RAR", "*.rar"), ("All files", "*")])
        if archive:
            self.archive.set(archive)

    def append_log(self, message):
        self.log.configure(state="normal")
        self.log.insert("end", str(message).rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def progress_callback(self, value="", *details, **fields):
        self.events.put(("progress", progress_message(value, *details, **fields)))

    def start_task(self, worker, finished, *, searching=False):
        if self.busy or self.backend is None:
            return
        self.busy = True
        self.status.set(self.t("searching" if searching else "working"))
        self.update_controls()
        self.progress.start(12)

        def run():
            try:
                result = worker()
            except Exception as exc:
                self.events.put(("error", (str(exc), traceback.format_exc())))
            else:
                self.events.put(("done", (finished, result)))

        threading.Thread(target=run, name="NarciBloom installer", daemon=True).start()

    def poll_events(self):
        from tkinter import messagebox
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "progress":
                    self.append_log(value)
                elif kind == "error":
                    self.busy = False
                    self.progress.stop()
                    message, details = value
                    self.append_log(details)
                    brief = message.splitlines()[0][:240] if message else self.t("error")
                    self.status.set(self.t("error"))
                    self.update_controls()
                    messagebox.showerror(self.t("error_title"), brief + "\n\n" + self.t("error"), parent=self.root)
                elif kind == "done":
                    self.busy = False
                    self.progress.stop()
                    finished, result = value
                    finished(result)
                    self.update_controls()
        except queue.Empty:
            pass
        self.root.after(80, self.poll_events)

    def apply_scan(self, info):
        previous = self.current_scan
        self.path.set(info["path"])
        if previous and os.path.normcase(previous["path"]) != os.path.normcase(info["path"]):
            self.story_choices = []
        self.current_scan = info
        self.render_stories()
        for module in info.get("modules", []):
            if not module.get("supported"):
                self.append_log(f"{module.get('title', module['id'])}: {module.get('reason', self.t('unknown'))}")
        for warning in info.get("warnings", []):
            self.append_log(warning)
        if info.get("recovery_required"):
            self.append_log(self.t("recovery"))

    def scan_status(self, info):
        if info.get("recovery_required"):
            return self.t("recovery")
        return self.t("ready" if any(module.get("supported") for module in info.get("modules", [])) else "no_story")

    def scan_selected(self):
        directory = self.path.get().strip()
        if not directory or self.backend is None:
            return

        def finished(info):
            self.apply_scan(info)
            self.status.set(self.scan_status(info))

        self.start_task(lambda: self.backend.scan_game(directory), finished, searching=True)

    def discover(self):
        preferred = self.path.get().strip()

        def worker():
            games = self.backend.available_games()
            directory = preferred or (games[0]["path"] if games else "")
            return games, self.backend.scan_game(directory) if directory else None

        def finished(result):
            games, info = result
            self.game_selector.configure(values=[game["path"] for game in games])
            if info:
                self.apply_scan(info)
                self.status.set(self.scan_status(info))
            else:
                self.status.set(self.t("no_game"))

        self.start_task(worker, finished, searching=True)

    def run_operation(self, operation, success):
        directory = self.current_scan["path"]

        def worker():
            result = operation()
            try:
                info = self.backend.scan_game(directory)
            except Exception as exc:
                self.progress_callback(f"Refresh: {exc}")
                info = None
            return result, info

        def finished(result):
            _, info = result
            if info:
                self.apply_scan(info)
            self.status.set(self.t(success))
            self.append_log(self.t(success))

        self.start_task(worker, finished)

    def install(self):
        if not self.matches_scan() or self.backend is None:
            return
        selected = [module["id"] for module, variable, _ in self.story_choices
                    if variable.get() and module.get("supported")]
        if not selected:
            return
        archive = self.archive.get().strip() or None
        if self.mode == "chinese" and not archive:
            self.status.set(self.t("need_archive"))
            self.choose_archive()
            archive = self.archive.get().strip() or None
            if not archive:
                return
        directory, family = self.current_scan["path"], self.font.get().strip() or None
        self.run_operation(lambda: self.backend.run_install(directory, selected, chinese=self.mode == "chinese",
                           progress=self.progress_callback, font_family=family, translation_archive=archive), "installed")

    def uninstall(self):
        if self.matches_scan() and self.backend is not None:
            directory = self.current_scan["path"]
            self.run_operation(lambda: self.backend.run_uninstall(directory, progress=self.progress_callback), "uninstalled")

    def copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log.get("1.0", "end-1c"))
        self.root.update_idletasks()
        if not self.busy:
            self.status.set(self.t("copied"))

    def close(self):
        if self.busy:
            from tkinter import messagebox
            messagebox.showinfo(self.t("busy_title"), self.t("close_busy"), parent=self.root)
        else:
            self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description="NarciBloom graphical installer")
    parser.add_argument("--mode", choices=("font", "chinese"), default=default_mode())
    parser.add_argument("--language", choices=tuple(TEXT))
    parser.add_argument("--game-dir", default="")
    options = parser.parse_args(argv)
    try:
        import tkinter as tk
        root = tk.Tk()
        InstallerApp(root, mode=options.mode, language=options.language or default_language(options.mode),
                     game_dir=options.game_dir)
        root.mainloop()
    except Exception as exc:
        message = f"NarciBloom could not open its window. Please extract the complete package again.\n{exc}"
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "NarciBloom", 0x10)
        else:
            print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

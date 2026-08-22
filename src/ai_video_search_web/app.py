"""應用程式主視窗：組裝全域 Header 與四個頁籤的 Navigation。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import db, theme
from .ui.conversation_tab import ConversationTab
from .ui.header import HeaderFrame
from .ui.library_tab import LibraryTab
from .ui.logs_tab import ProcessingLogTab
from .ui.search_tab import SearchResultsTab
from .ui.video_tab import VideoAnalysisTab


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        db.init_db()

        self.title("AI 影片搜尋")
        self.geometry("1366x768")
        self.minsize(1024, 640)

        style = ttk.Style(self)
        theme.configure_style(style)
        self.configure(background=theme.BG_APP)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._header_stats = db.get_header_stats()
        self.header = HeaderFrame(self, self._header_stats)
        self.header.grid(row=0, column=0, sticky="ew")

        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=theme.SPACE_16, pady=(0, theme.SPACE_16))

        # 建構順序有相依性：video_tab 建構時會立刻觸發 on_stats_changed
        # （載入待分析清單那一刻），而 on_stats_changed 現在也會刷新
        # library_tab，所以 library_tab（連同它依賴的 search_tab）必須
        # 先建好，video_tab 才能最後建立。
        self.search_tab = SearchResultsTab(self.notebook)
        self.library_tab = LibraryTab(
            self.notebook,
            on_search=self._on_search_from_library,
            on_search_in_video=self._on_search_in_video,
            get_recent_queries=self.search_tab.get_recent_queries,
            on_stats_changed=self._on_stats_changed,
        )
        self.video_tab = VideoAnalysisTab(
            self.notebook, on_stats_changed=self._on_stats_changed
        )
        self.conversation_tab = ConversationTab(self.notebook)
        self.logs_tab = ProcessingLogTab(self.notebook)

        self.notebook.add(self.video_tab, text="影片與分析")
        self.notebook.add(self.library_tab, text="影片庫")
        self.notebook.add(self.search_tab, text="搜尋結果")
        self.notebook.add(self.conversation_tab, text="對話搜尋")
        self.notebook.add(self.logs_tab, text="處理紀錄")

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _on_stats_changed(self) -> None:
        self._header_stats = db.get_header_stats()
        self.header.update_stats(self._header_stats)
        # 分析／摘要完成時即時刷新影片庫列表，不用等使用者切換分頁才看得到最新資料
        # （原本只在切到「影片庫」分頁那一刻才 refresh，如果分析是在使用者已經
        # 停留在影片庫分頁時才完成，就永遠不會自動出現，要手動切走再切回來）。
        self.library_tab.refresh()

    def _on_search_from_library(self, query: str) -> None:
        self.search_tab.run_search(query)
        self.notebook.select(self.search_tab)

    def _on_search_in_video(self, video_id: int, video_title: str) -> None:
        self.search_tab.set_scope(video_id, video_title)
        self.notebook.select(self.search_tab)

    def _on_tab_changed(self, _event: object = None) -> None:
        if self.notebook.select() == str(self.library_tab):
            self.library_tab.refresh()

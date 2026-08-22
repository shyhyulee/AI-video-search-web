"""「處理紀錄」頁籤：把整支程式的 logging 輸出即時顯示成可篩選、可匯出的列表。"""
from __future__ import annotations

import csv
import logging
import queue
import tkinter as tk
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from itertools import count
from tkinter import filedialog, ttk

from .. import theme
from .widgets import EmptyState, make_scrollable_treeview, truncate

_MAX_ENTRIES = 1000
_LEVEL_ALL = "全部"
_LEVELS = [_LEVEL_ALL, "INFO", "WARNING", "ERROR"]

_COLUMNS = ("time", "level", "video", "stage", "message")
_HEADINGS = {
    "time": "處理時間", "level": "Log Level", "video": "影片名稱",
    "stage": "Pipeline Stage", "message": "訊息",
}
_WIDTHS = {"time": 150, "level": 90, "video": 200, "stage": 140, "message": 380}
_LEVEL_COLORS = {"ERROR": theme.ERROR, "WARNING": theme.WARNING, "INFO": theme.TEXT_SECONDARY}

_seq_counter = count()


@dataclass
class _LogEntry:
    seq: int
    timestamp: str
    level: str
    video_title: str
    pipeline_stage: str
    message: str  # 單行摘要，Treeview 顯示（會再 truncate）
    detail: str    # 訊息＋完整 traceback（exc_info 有值時），複製／匯出用


class _QueueLogHandler(logging.Handler):
    """emit() 只把 LogRecord 轉成字串塞進 Queue，不能碰任何 Tk 元件——
    可能從背景執行緒（search/summary worker）被呼叫。"""

    def __init__(self, entry_queue: "queue.Queue[_LogEntry]") -> None:
        super().__init__()
        self._queue = entry_queue
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = _LogEntry(
                seq=next(_seq_counter),
                timestamp=datetime.fromtimestamp(record.created).strftime("%Y/%m/%d %H:%M:%S"),
                level=record.levelname,
                video_title=getattr(record, "video_title", ""),
                pipeline_stage=getattr(record, "pipeline_stage", ""),
                message=record.getMessage(),
                detail=self.format(record),
            )
            self._queue.put(entry)
        except Exception:
            self.handleError(record)


class ProcessingLogTab(ttk.Frame):
    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, padding=theme.SPACE_16)
        self._entries: deque[_LogEntry] = deque(maxlen=_MAX_ENTRIES)
        self._entry_queue: "queue.Queue[_LogEntry]" = queue.Queue()
        self._level_filter_var = tk.StringVar(value=_LEVEL_ALL)
        self._filter_buttons: dict[str, ttk.Button] = {}

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self._install_logging()
        self._build_card()
        self._render_filtered()  # 建立當下沒有任何紀錄，確保一開始就顯示 Empty State
        self.after(150, self._poll_log_queue)

    # ------------------------------------------------------------------
    # logging 安裝：整支程式唯一掛 Handler 的地方
    # ------------------------------------------------------------------
    def _install_logging(self) -> None:
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        if not any(isinstance(h, _QueueLogHandler) for h in root_logger.handlers):
            root_logger.addHandler(_QueueLogHandler(self._entry_queue))
        if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
            )
            root_logger.addHandler(stream_handler)

    # ------------------------------------------------------------------
    # 版面
    # ------------------------------------------------------------------
    def _build_card(self) -> None:
        card = ttk.Frame(self, style="Card.TFrame", padding=theme.SPACE_16)
        card.grid(row=0, column=0, sticky="nsew")
        card.columnconfigure(0, weight=1)
        card.rowconfigure(2, weight=1)

        ttk.Label(card, text="處理紀錄", style="CardSection.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, theme.SPACE_16)
        )
        self._build_toolbar(card)
        self._build_table(card)

        self._status_var = tk.StringVar(value="")
        ttk.Label(card, textvariable=self._status_var, style="CardSecondary.TLabel").grid(
            row=3, column=0, sticky="w", pady=(theme.SPACE_8, 0)
        )

    def _build_toolbar(self, parent: tk.Widget) -> None:
        toolbar = ttk.Frame(parent, style="Card.TFrame")
        toolbar.grid(row=1, column=0, sticky="ew", pady=(0, theme.SPACE_16))

        filter_row = ttk.Frame(toolbar, style="Card.TFrame")
        filter_row.pack(side="left")
        ttk.Label(filter_row, text="篩選：", style="CardSecondary.TLabel").pack(side="left")
        for label in _LEVELS:
            btn = ttk.Button(
                filter_row, text=label, style="Secondary.TButton",
                command=lambda label=label: self._on_level_filter_changed(label),
            )
            btn.pack(side="left", padx=(theme.SPACE_8, 0))
            self._filter_buttons[label] = btn
        self._update_filter_button_styles()

        action_row = ttk.Frame(toolbar, style="Card.TFrame")
        action_row.pack(side="right")
        ttk.Button(action_row, text="清除畫面", style="Secondary.TButton",
                   command=self._on_clear_clicked).pack(side="left", padx=(theme.SPACE_8, 0))
        ttk.Button(action_row, text="匯出 Log", style="Secondary.TButton",
                   command=self._on_export_clicked).pack(side="left", padx=(theme.SPACE_8, 0))
        ttk.Button(action_row, text="複製錯誤", style="Secondary.TButton",
                   command=self._on_copy_error_clicked).pack(side="left", padx=(theme.SPACE_8, 0))

    def _build_table(self, parent: tk.Widget) -> None:
        self._tree_container, self._tree = make_scrollable_treeview(
            parent, list(_COLUMNS), _HEADINGS, _WIDTHS, stretch_column="message"
        )
        self._tree_container.grid(row=2, column=0, sticky="nsew")
        for level, color in _LEVEL_COLORS.items():
            self._tree.tag_configure(level, foreground=color)

        self._empty_state = EmptyState(
            parent, "目前沒有處理紀錄",
            ["警告與錯誤發生時會顯示在這裡；套用篩選時也可能是目前沒有符合的紀錄"],
        )
        self._empty_state.grid(row=2, column=0, sticky="nsew")

    # ------------------------------------------------------------------
    # 輪詢／渲染
    # ------------------------------------------------------------------
    def _poll_log_queue(self) -> None:
        drained = False
        try:
            while True:
                self._entries.append(self._entry_queue.get_nowait())
                drained = True
        except queue.Empty:
            pass
        if drained:
            self._render_filtered()
        self.after(150, self._poll_log_queue)

    def _entries_matching_filter(self) -> list[_LogEntry]:
        active = self._level_filter_var.get()
        if active == _LEVEL_ALL:
            return list(self._entries)
        return [e for e in self._entries if e.level == active]

    def _render_filtered(self) -> None:
        filtered = self._entries_matching_filter()

        if filtered:
            self._tree_container.grid()
            self._empty_state.grid_remove()
        else:
            self._tree_container.grid_remove()
            self._empty_state.grid()

        previous_selection = self._tree.selection()
        self._tree.delete(*self._tree.get_children())
        for entry in reversed(filtered):  # 新的在最上面
            self._tree.insert(
                "", "end", iid=str(entry.seq),
                values=(entry.timestamp, entry.level, entry.video_title,
                        entry.pipeline_stage, truncate(entry.message, 120)),
                tags=(entry.level,),
            )
        if previous_selection and self._tree.exists(previous_selection[0]):
            self._tree.selection_set(previous_selection[0])

    def _on_level_filter_changed(self, label: str) -> None:
        self._level_filter_var.set(label)
        self._update_filter_button_styles()
        self._render_filtered()

    def _update_filter_button_styles(self) -> None:
        active = self._level_filter_var.get()
        for label, btn in self._filter_buttons.items():
            btn.configure(style="Primary.TButton" if label == active else "Secondary.TButton")

    # ------------------------------------------------------------------
    # 工具列動作
    # ------------------------------------------------------------------
    def _on_clear_clicked(self) -> None:
        """連記憶體緩衝一起清空（不是只隱藏），不然切換篩選會讓舊紀錄「復活」。"""
        self._entries.clear()
        self._render_filtered()  # 同時處理 Treeview 清空與 Empty State 切換
        self._status_var.set("已清除畫面")

    def _get_selected_entry(self) -> _LogEntry | None:
        selection = self._tree.selection()
        if not selection:
            return None
        seq = int(selection[0])
        return next((e for e in self._entries if e.seq == seq), None)

    def _on_copy_error_clicked(self) -> None:
        entry = self._get_selected_entry()
        if entry is None:
            self._status_var.set("請先選取一列")
            return
        self.clipboard_clear()
        self.clipboard_append(entry.detail)
        self._status_var.set("已複製到剪貼簿")

    def _on_export_clicked(self) -> None:
        entries = self._entries_matching_filter()
        if not entries:
            self._status_var.set("沒有可匯出的紀錄")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile="處理紀錄.csv"
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["處理時間", "Log Level", "影片名稱", "Pipeline Stage", "訊息"])
            for entry in entries:  # 匯出用正序（舊→新），符合一般 log 檔閱讀習慣
                writer.writerow([entry.timestamp, entry.level, entry.video_title,
                                  entry.pipeline_stage, entry.detail])
        self._status_var.set(f"已匯出至 {path}")

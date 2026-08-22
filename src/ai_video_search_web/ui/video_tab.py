"""「影片與分析」頁籤：新增影片（YouTube 下載）、待分析影片列表與開始分析。"""
from __future__ import annotations

import logging
import queue
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from .. import db, downloader, theme
from ..pipeline import analyzer
from ..services import video_service
from .widgets import (
    EmptyState,
    format_analysis_result_note,
    format_datetime_display,
    format_duration,
    make_scrollable_treeview,
)

logger = logging.getLogger(__name__)

_COLUMNS = ("title", "duration", "source", "added_at", "status")
_HEADINGS = {
    "title": "影片名稱",
    "duration": "長度",
    "source": "來源",
    "added_at": "加入時間",
    "status": "狀態",
}
_WIDTHS = {"title": 320, "duration": 80, "source": 90, "added_at": 140, "status": 140}

_SOURCE_DISPLAY = {db.SOURCE_YOUTUBE: "YouTube", db.SOURCE_LOCAL: "本機"}

_LOCAL_VIDEO_FILETYPES = [("影片檔案", "*.mp4 *.mov *.mkv *.webm")]


class VideoAnalysisTab(ttk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        on_stats_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, padding=theme.SPACE_16)
        self._on_stats_changed = on_stats_changed
        self._download_active = False
        self._analysis_active = False
        self._progress_queue: "queue.Queue[object]" = queue.Queue()
        self._analysis_queue: "queue.Queue[object]" = queue.Queue()
        self._analysis_video_ids: list[int] = []
        self._analysis_titles: dict[int, str] = {}
        self._analysis_total_count = 0
        self._analysis_completed_count = 0

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_add_video_card()
        self._build_pending_list_card()

        self._refresh_pending_list()

    # ------------------------------------------------------------------
    # 新增影片卡片
    # ------------------------------------------------------------------
    def _build_add_video_card(self) -> None:
        card = ttk.Frame(self, style="Card.TFrame", padding=theme.SPACE_16)
        card.grid(row=0, column=0, sticky="ew", pady=(0, theme.SPACE_16))
        card.columnconfigure(0, weight=1)

        ttk.Label(card, text="新增影片", style="CardSection.TLabel").grid(
            row=0, column=0, sticky="w"
        )

        ttk.Label(card, text="YouTube 網址", style="CardSecondary.TLabel").grid(
            row=1, column=0, sticky="w", pady=(theme.SPACE_16, theme.SPACE_4)
        )

        url_row = ttk.Frame(card, style="Card.TFrame")
        url_row.grid(row=2, column=0, sticky="ew")
        url_row.columnconfigure(0, weight=1)

        self._url_var = tk.StringVar()
        self._url_entry = ttk.Entry(url_row, textvariable=self._url_var)
        self._url_entry.grid(row=0, column=0, sticky="ew")
        self._url_entry.bind("<Return>", lambda _event: self._on_download_clicked())

        self._download_btn = ttk.Button(
            url_row, text="下載影片", style="Primary.TButton", command=self._on_download_clicked
        )
        self._download_btn.grid(row=0, column=1, padx=(theme.SPACE_8, 0))

        local_row = ttk.Frame(card, style="Card.TFrame")
        local_row.grid(row=3, column=0, sticky="w", pady=(theme.SPACE_16, 0))

        self._local_btn = ttk.Button(
            local_row, text="選擇本機影片", style="Secondary.TButton",
            command=self._on_select_local_clicked,
        )
        self._local_btn.grid(row=0, column=0, sticky="w")
        ttk.Label(
            local_row, text="支援格式：MP4、MOV、MKV、WebM", style="CardSecondary.TLabel"
        ).grid(row=0, column=1, sticky="w", padx=(theme.SPACE_16, 0))

        self._progress_var = tk.DoubleVar(value=0.0)
        self._progress_bar = ttk.Progressbar(
            card,
            style="Primary.Horizontal.TProgressbar",
            orient="horizontal",
            mode="determinate",
            variable=self._progress_var,
            maximum=100,
        )
        self._progress_bar.grid(row=4, column=0, sticky="ew", pady=(theme.SPACE_16, theme.SPACE_8))

        self._status_var = tk.StringVar(value="尚未開始")
        self._status_label = ttk.Label(
            card, textvariable=self._status_var, style="CardSecondary.TLabel"
        )
        self._status_label.grid(row=5, column=0, sticky="w")

    # ------------------------------------------------------------------
    # 待分析影片列表卡片
    # ------------------------------------------------------------------
    def _build_pending_list_card(self) -> None:
        card = ttk.Frame(self, style="Card.TFrame", padding=theme.SPACE_16)
        card.grid(row=1, column=0, sticky="nsew")
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)

        self._count_var = tk.StringVar(value="待分析影片（0）")
        ttk.Label(card, textvariable=self._count_var, style="CardSection.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, theme.SPACE_16)
        )

        self._list_area = ttk.Frame(card, style="Card.TFrame")
        self._list_area.grid(row=1, column=0, sticky="nsew")
        self._list_area.columnconfigure(0, weight=1)
        self._list_area.rowconfigure(0, weight=1)

        self._tree_container, self._tree = make_scrollable_treeview(
            self._list_area,
            list(_COLUMNS),
            _HEADINGS,
            _WIDTHS,
            stretch_column="title",
            selectmode="extended",
        )
        self._tree_container.grid(row=0, column=0, sticky="nsew")

        self._empty_state = EmptyState(
            self._list_area,
            "目前沒有待分析影片",
            ["可貼上 YouTube 網址或選擇本機影片"],
        )
        self._empty_state.grid(row=0, column=0, sticky="nsew")

        toolbar = ttk.Frame(card, style="Card.TFrame")
        toolbar.grid(row=2, column=0, sticky="w", pady=(theme.SPACE_16, 0))

        self._analyze_btn = ttk.Button(
            toolbar, text="開始分析", style="Secondary.TButton", command=self._on_analyze_clicked
        )
        self._analyze_btn.grid(row=0, column=0)
        self._remove_btn = ttk.Button(
            toolbar, text="移除", style="Secondary.TButton", command=self._on_remove_clicked
        )
        self._remove_btn.grid(row=0, column=1, padx=(theme.SPACE_8, 0))

        self._analysis_status_var = tk.StringVar(value="")
        self._analysis_status_label = ttk.Label(
            card, textvariable=self._analysis_status_var, style="CardSecondary.TLabel"
        )
        self._analysis_status_label.grid(row=3, column=0, sticky="w", pady=(theme.SPACE_8, 0))

    # ------------------------------------------------------------------
    # 下載影片
    # ------------------------------------------------------------------
    def _on_download_clicked(self) -> None:
        if self._download_active:
            return
        url = self._url_var.get().strip()
        if not url:
            self._set_status("請輸入 YouTube 網址", "error")
            return
        if not video_service.is_youtube_url(url):
            self._set_status("請輸入有效的 YouTube 網址", "error")
            return
        existing = video_service.find_existing_by_url(url)
        if existing is not None:
            self._set_status(f"此影片已經在庫中（狀態：{existing.status}）", "error")
            return

        self._download_active = True
        self._download_btn.configure(state="disabled")
        self._url_entry.configure(state="disabled")
        self._progress_var.set(0.0)
        self._set_status("準備下載…", "secondary")

        self._progress_queue = queue.Queue()
        downloader.start_download(url, self._progress_queue)
        self.after(150, self._poll_download_progress)

    def _poll_download_progress(self) -> None:
        try:
            while True:
                item = self._progress_queue.get_nowait()
                self._handle_progress_item(item)
        except queue.Empty:
            pass

        if self._download_active:
            self.after(150, self._poll_download_progress)

    def _handle_progress_item(self, item: object) -> None:
        if isinstance(item, downloader.DownloadProgress):
            if item.status == "downloading":
                self._progress_var.set(item.percent)
                label = item.title or "下載中"
                self._set_status(
                    f"{label} 下載中… {item.percent:.0f}%｜{item.speed_text}｜剩餘 {item.eta_text}",
                    "secondary",
                )
            elif item.status == "error":
                self._download_active = False
                self._progress_var.set(0.0)
                self._set_status(f"下載失敗：{item.error_message}", "error")
                self._download_btn.configure(state="normal")
                self._url_entry.configure(state="normal")
        elif isinstance(item, downloader.DownloadResult):
            self._download_active = False
            self._progress_var.set(100.0)
            video_service.register_downloaded_video(
                title=item.title,
                source_url=self._url_var.get().strip(),
                file_path=item.file_path,
                duration_sec=item.duration_sec,
            )
            self._url_var.set("")
            self._download_btn.configure(state="normal")
            self._url_entry.configure(state="normal")
            self._set_status("✓ 影片下載完成，已加入待分析清單", "success")
            self._refresh_pending_list()

    # ------------------------------------------------------------------
    # 選擇本機影片
    # ------------------------------------------------------------------
    def _on_select_local_clicked(self) -> None:
        path_str = filedialog.askopenfilename(title="選擇本機影片", filetypes=_LOCAL_VIDEO_FILETYPES)
        if not path_str:
            return
        path = Path(path_str)
        duration_sec = video_service.probe_local_duration(path)
        video_service.register_local_video(path, duration_sec)
        self._set_status("✓ 已加入待分析清單", "success")
        self._refresh_pending_list()

    def _set_status(self, text: str, kind: str) -> None:
        style = {
            "secondary": "CardSecondary.TLabel",
            "error": "CardError.TLabel",
            "success": "CardSuccess.TLabel",
        }[kind]
        self._status_var.set(text)
        self._status_label.configure(style=style)

    # ------------------------------------------------------------------
    # 待分析影片列表
    # ------------------------------------------------------------------
    def _refresh_pending_list(self) -> None:
        records = video_service.list_pending_videos()
        self._pending_by_id = {record.id: record for record in records}

        self._tree.delete(*self._tree.get_children())
        for record in records:
            self._tree.insert(
                "",
                "end",
                iid=str(record.id),
                values=(
                    record.title,
                    format_duration(record.duration_sec),
                    _SOURCE_DISPLAY.get(record.source, record.source),
                    format_datetime_display(record.created_at),
                    "等待分析",
                ),
            )

        self._count_var.set(f"待分析影片（{len(records)}）")

        if records:
            self._tree_container.grid()
            self._empty_state.grid_remove()
        else:
            self._tree_container.grid_remove()
            self._empty_state.grid()

        if self._on_stats_changed is not None:
            self._on_stats_changed()

    def _on_remove_clicked(self) -> None:
        if self._analysis_active:
            return
        selected_ids = [int(iid) for iid in self._tree.selection()]
        if not selected_ids:
            return

        titles = [self._pending_by_id[vid].title for vid in selected_ids if vid in self._pending_by_id]
        preview = "、".join(titles[:3]) + ("…" if len(titles) > 3 else "")
        confirmed = messagebox.askyesno(
            "移除待分析影片",
            f"確定要移除「{preview}」共 {len(selected_ids)} 支影片，並刪除已下載的檔案嗎？",
        )
        if not confirmed:
            return

        for video_id in selected_ids:
            record, file_error = video_service.delete_video(video_id)
            if record is None:
                continue
            if file_error is not None:
                messagebox.showwarning("刪除檔案失敗", f"「{record.title}」的檔案刪除失敗：{file_error}")

        self._refresh_pending_list()

    # ------------------------------------------------------------------
    # 開始分析
    # ------------------------------------------------------------------
    def _on_analyze_clicked(self) -> None:
        if self._analysis_active:
            return
        selected_ids = [int(iid) for iid in self._tree.selection()]
        if not selected_ids:
            return

        eligible: list[int] = []
        too_long: list[str] = []
        for video_id in selected_ids:
            record = self._pending_by_id.get(video_id)
            if record is None:
                continue
            if video_service.is_within_duration_limit(record.duration_sec):
                eligible.append(video_id)
            else:
                too_long.append(record.title)

        if too_long:
            preview = "、".join(too_long[:3]) + ("…" if len(too_long) > 3 else "")
            limit_min = video_service.max_duration_minutes()
            messagebox.showwarning(
                "影片長度超過限制",
                f"「{preview}」超過 {limit_min} 分鐘，本輪不分析這些影片。",
            )
        if not eligible:
            return

        self._analysis_video_ids = eligible
        self._analysis_titles = {vid: self._pending_by_id[vid].title for vid in eligible}
        self._analysis_total_count = len(eligible)
        self._analysis_completed_count = 0
        self._analysis_active = True
        self._analyze_btn.configure(state="disabled")
        self._remove_btn.configure(state="disabled")
        self._start_next_analysis()

    def _start_next_analysis(self) -> None:
        if not self._analysis_video_ids:
            self._analysis_active = False
            self._analyze_btn.configure(state="normal")
            self._remove_btn.configure(state="normal")
            if self._analysis_total_count:
                self._analysis_status_var.set(
                    f"✓ 已完成 {self._analysis_completed_count}/{self._analysis_total_count} 支影片分析"
                )
            return

        video_id = self._analysis_video_ids.pop(0)
        title = self._analysis_titles.get(video_id, "")
        self._analysis_status_var.set(f"「{title}」準備分析…")
        self._analysis_queue = queue.Queue()
        analyzer.start_analysis(video_id, self._analysis_queue)
        self.after(150, self._poll_analysis_progress, video_id)

    def _poll_analysis_progress(self, video_id: int) -> None:
        try:
            while True:
                item = self._analysis_queue.get_nowait()
                if self._handle_analysis_item(video_id, item):
                    return
        except queue.Empty:
            pass
        self.after(150, self._poll_analysis_progress, video_id)

    def _handle_analysis_item(self, video_id: int, item: object) -> bool:
        """回傳 True 表示這支影片的分析已結束（不論成功或失敗）。"""
        title = self._analysis_titles.get(video_id, "")
        if isinstance(item, analyzer.AnalysisProgress):
            detail = f" {item.detail}" if item.detail else ""
            self._analysis_status_var.set(f"「{title}」{item.stage}{detail}")
            return False
        if isinstance(item, analyzer.AnalysisResult):
            note = format_analysis_result_note(item)
            self._analysis_status_var.set(
                f"✓「{title}」分析完成，共 {item.segment_count} 個片段{note}"
            )
            self._analysis_completed_count += 1
            self._refresh_pending_list()
            self._start_next_analysis()
            return True
        if isinstance(item, analyzer.AnalysisError):
            self._analysis_status_var.set(f"「{title}」分析失敗：{item.message}")
            self._analysis_completed_count += 1
            self._refresh_pending_list()
            self._start_next_analysis()
            return True
        return False

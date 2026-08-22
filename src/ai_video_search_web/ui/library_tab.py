"""「影片庫」頁籤：搜尋入口、可排序／篩選的影片列表、詳細資訊與摘要。"""
from __future__ import annotations

import logging
import os
import queue
import subprocess
import tempfile
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

from .. import db, theme
from ..pipeline import analyzer
from ..pipeline import summary as summary_pipeline
from ..pipeline.openai_client import get_client
from .widgets import (
    Badge,
    EmptyState,
    format_analysis_result_note,
    format_cost,
    format_datetime_display,
    format_duration,
    make_scrollable_frame,
    make_scrollable_treeview,
)

logger = logging.getLogger(__name__)

_FILTER_ALL = "全部"
_FILTER_ANALYZED = "分析完成"
_FILTER_FAILED = "分析失敗"
_FILTER_NO_SUBTITLE = "無字幕"
_FILTER_VISUAL_ONLY = "純畫面"
_FILTERS = [_FILTER_ALL, _FILTER_ANALYZED, _FILTER_FAILED, _FILTER_NO_SUBTITLE, _FILTER_VISUAL_ONLY]

_STATUS_DISPLAY = {db.STATUS_ANALYZED: "分析完成", db.STATUS_FAILED: "分析失敗"}

_COLUMNS = ("title", "duration", "segment_count", "status", "cost", "analyzed_at")
_HEADINGS = {
    "title": "影片名稱",
    "duration": "長度",
    "segment_count": "片段數",
    "status": "分析狀態",
    "cost": "成本",
    "analyzed_at": "分析日期",
}
_WIDTHS = {"title": 300, "duration": 70, "segment_count": 70, "status": 90, "cost": 90, "analyzed_at": 140}
_SORTABLE_COLUMNS = {"title", "segment_count", "cost", "analyzed_at"}

_THUMBNAIL_SIZE = (320, 180)


@dataclass
class _LibraryRow:
    video: db.VideoRecord
    has_transcript: bool
    has_visual: bool
    has_ocr: bool


class LibraryTab(ttk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        on_search: Callable[[str], None],
        on_search_in_video: Callable[[int, str], None],
        get_recent_queries: Callable[[], list[str]],
        on_stats_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, padding=theme.SPACE_16)
        self._on_search = on_search
        self._on_search_in_video = on_search_in_video
        self._get_recent_queries = get_recent_queries
        self._on_stats_changed = on_stats_changed

        self._rows: list[_LibraryRow] = []
        self._rows_by_id: dict[str, _LibraryRow] = {}
        self._selected_video_id: int | None = None
        self._sort_column = "analyzed_at"
        self._sort_reverse = True
        self._summary_active = False
        self._reanalysis_active = False
        self._thumbnail_image: tk.PhotoImage | None = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_search_bar()
        self._build_main_area()

        self.refresh()

    # ------------------------------------------------------------------
    # 搜尋列
    # ------------------------------------------------------------------
    def _build_search_bar(self) -> None:
        card = ttk.Frame(self, style="Card.TFrame", padding=theme.SPACE_16)
        card.grid(row=0, column=0, sticky="ew", pady=(0, theme.SPACE_16))
        card.columnconfigure(0, weight=1)

        query_row = ttk.Frame(card, style="Card.TFrame")
        query_row.grid(row=0, column=0, sticky="ew")
        query_row.columnconfigure(0, weight=1)

        self._query_var = tk.StringVar()
        self._query_entry = ttk.Entry(query_row, textvariable=self._query_var)
        self._query_entry.grid(row=0, column=0, sticky="ew")
        self._query_entry.bind("<Return>", lambda _event: self._on_search_clicked())

        ttk.Button(
            query_row, text="搜尋", style="Primary.TButton", command=self._on_search_clicked
        ).grid(row=0, column=1, padx=(theme.SPACE_8, 0))

        ttk.Label(
            card, text="描述想尋找的事件、人物、動作或教學內容", style="CardSecondary.TLabel"
        ).grid(row=1, column=0, sticky="w", pady=(theme.SPACE_8, 0))

        self._recent_row = ttk.Frame(card, style="Card.TFrame")
        self._recent_row.grid(row=2, column=0, sticky="w", pady=(theme.SPACE_8, 0))

    def _refresh_recent_queries(self) -> None:
        for child in self._recent_row.winfo_children():
            child.destroy()

        recent = self._get_recent_queries()
        if not recent:
            return

        ttk.Label(self._recent_row, text="最近搜尋：", style="CardSecondary.TLabel").pack(side="left")
        for query in recent:
            ttk.Button(
                self._recent_row, text=query, style="Link.TButton",
                command=lambda q=query: self._on_search(q),
            ).pack(side="left", padx=(theme.SPACE_4, 0))

    def _on_search_clicked(self) -> None:
        query = self._query_var.get().strip()
        if not query:
            return
        self._on_search(query)

    # ------------------------------------------------------------------
    # 主要區域（左：影片列表，右：詳細資訊）
    # ------------------------------------------------------------------
    def _build_main_area(self) -> None:
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.grid(row=1, column=0, sticky="nsew")

        left = ttk.Frame(paned, style="Card.TFrame", padding=theme.SPACE_16)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)
        paned.add(left, weight=3)

        self._count_var = tk.StringVar(value="影片庫（0）")
        ttk.Label(left, textvariable=self._count_var, style="CardSection.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, theme.SPACE_8)
        )

        filter_row = ttk.Frame(left, style="Card.TFrame")
        filter_row.grid(row=1, column=0, sticky="w", pady=(0, theme.SPACE_16))
        self._filter_var = tk.StringVar(value=_FILTER_ALL)
        self._filter_buttons: dict[str, ttk.Button] = {}
        for i, label in enumerate(_FILTERS):
            btn = ttk.Button(
                filter_row, text=label, style="Secondary.TButton",
                command=lambda label=label: self._on_filter_changed(label),
            )
            btn.grid(row=0, column=i, padx=(0 if i == 0 else theme.SPACE_8, 0))
            self._filter_buttons[label] = btn
        self._update_filter_button_styles()

        self._list_area = ttk.Frame(left, style="Card.TFrame")
        self._list_area.grid(row=2, column=0, sticky="nsew")
        self._list_area.columnconfigure(0, weight=1)
        self._list_area.rowconfigure(0, weight=1)

        self._tree_container, self._tree = make_scrollable_treeview(
            self._list_area, list(_COLUMNS), _HEADINGS, _WIDTHS, stretch_column="title"
        )
        self._tree_container.grid(row=0, column=0, sticky="nsew")
        self._tree.bind("<<TreeviewSelect>>", self._on_row_selected)
        for col in _SORTABLE_COLUMNS:
            self._tree.heading(col, text=_HEADINGS[col], command=lambda c=col: self._on_sort(c))

        self._empty_state: EmptyState | None = None
        self._empty_state_holder = ttk.Frame(self._list_area, style="Card.TFrame")
        self._empty_state_holder.grid(row=0, column=0, sticky="nsew")
        self._empty_state_holder.columnconfigure(0, weight=1)
        self._empty_state_holder.rowconfigure(0, weight=1)

        right = ttk.Frame(paned, style="Card.TFrame")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        paned.add(right, weight=2)

        # 摘要、字幕長度都不固定，內容可能超過可視高度，用可捲動容器包住，
        # 確保底部的「重新產生摘要」「在此影片內搜尋」按鈕一定滑得到、不會被擋住。
        scroll_outer, scroll_inner = make_scrollable_frame(right)
        scroll_outer.grid(row=0, column=0, sticky="nsew")
        scroll_inner.configure(padding=theme.SPACE_16)
        self._build_detail_panel(scroll_inner)

    def _build_detail_panel(self, parent: tk.Widget) -> None:
        # tk.Label 的 width/height 在還沒有圖片時是以「文字字元數」而非像素計算，
        # 320/180 會被當成 320 個字元寬，把整個 Frame 撐得極寬，導致要橫向捲動
        # 才看得到內容。用一個鎖定像素尺寸的 Frame 包住 Label 來避免這個問題。
        thumbnail_holder = tk.Frame(
            parent, width=_THUMBNAIL_SIZE[0], height=_THUMBNAIL_SIZE[1], background=theme.BORDER
        )
        thumbnail_holder.grid(row=0, column=0, sticky="w", pady=(0, theme.SPACE_16))
        thumbnail_holder.grid_propagate(False)

        self._thumbnail_label = tk.Label(thumbnail_holder, background=theme.BORDER)
        self._thumbnail_label.place(relx=0.5, rely=0.5, anchor="center")

        self._detail_title_var = tk.StringVar(value="尚未選取影片")
        ttk.Label(
            parent, textvariable=self._detail_title_var, style="CardSection.TLabel", wraplength=320
        ).grid(row=1, column=0, sticky="w")

        self._detail_meta_var = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self._detail_meta_var, style="CardSecondary.TLabel").grid(
            row=2, column=0, sticky="w", pady=(theme.SPACE_4, theme.SPACE_8)
        )

        self._flags_row = ttk.Frame(parent, style="Card.TFrame")
        self._flags_row.grid(row=3, column=0, sticky="w", pady=(0, theme.SPACE_16))

        ttk.Label(parent, text="摘要", style="CardSection.TLabel").grid(
            row=4, column=0, sticky="w", pady=(0, theme.SPACE_8)
        )
        self._summary_var = tk.StringVar(value="尚未選取影片")
        ttk.Label(
            parent, textvariable=self._summary_var, style="Card.TLabel", wraplength=320
        ).grid(row=5, column=0, sticky="w")

        self._summary_status_var = tk.StringVar(value="")
        ttk.Label(
            parent, textvariable=self._summary_status_var, style="CardSecondary.TLabel"
        ).grid(row=6, column=0, sticky="w", pady=(theme.SPACE_4, 0))

        button_row = ttk.Frame(parent, style="Card.TFrame")
        button_row.grid(row=7, column=0, sticky="w", pady=(theme.SPACE_16, 0))
        self._regenerate_btn = ttk.Button(
            button_row, text="重新產生摘要", style="Secondary.TButton",
            command=self._on_regenerate_summary_clicked, state="disabled",
        )
        self._regenerate_btn.grid(row=0, column=0)
        self._search_in_video_btn = ttk.Button(
            button_row, text="在此影片內搜尋", style="Secondary.TButton",
            command=self._on_search_in_video_clicked, state="disabled",
        )
        self._search_in_video_btn.grid(row=0, column=1, padx=(theme.SPACE_8, 0))
        self._reanalyze_btn = ttk.Button(
            button_row, text="重新分析", style="Secondary.TButton",
            command=self._on_reanalyze_clicked, state="disabled",
        )
        self._reanalyze_btn.grid(row=0, column=2, padx=(theme.SPACE_8, 0))

        self._reanalysis_status_var = tk.StringVar(value="")
        ttk.Label(
            parent, textvariable=self._reanalysis_status_var, style="CardSecondary.TLabel", wraplength=320
        ).grid(row=8, column=0, sticky="w", pady=(theme.SPACE_8, 0))

    # ------------------------------------------------------------------
    # 篩選／排序
    # ------------------------------------------------------------------
    def _on_filter_changed(self, label: str) -> None:
        self._filter_var.set(label)
        self._update_filter_button_styles()
        self._populate_list()

    def _update_filter_button_styles(self) -> None:
        active = self._filter_var.get()
        for label, btn in self._filter_buttons.items():
            btn.configure(style="Primary.TButton" if label == active else "Secondary.TButton")

    def _on_sort(self, column: str) -> None:
        if self._sort_column == column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column
            self._sort_reverse = False
        self._populate_list()

    def _filtered_sorted_rows(self) -> list[_LibraryRow]:
        active = self._filter_var.get()
        if active == _FILTER_ANALYZED:
            rows = [r for r in self._rows if r.video.status == db.STATUS_ANALYZED]
        elif active == _FILTER_FAILED:
            rows = [r for r in self._rows if r.video.status == db.STATUS_FAILED]
        elif active == _FILTER_NO_SUBTITLE:
            rows = [r for r in self._rows if r.video.status == db.STATUS_ANALYZED and not r.has_transcript]
        elif active == _FILTER_VISUAL_ONLY:
            rows = [
                r for r in self._rows
                if r.video.status == db.STATUS_ANALYZED and not r.has_transcript and not r.has_ocr
            ]
        else:
            rows = list(self._rows)

        key_funcs = {
            "title": lambda r: r.video.title,
            "segment_count": lambda r: r.video.segment_count or 0,
            "cost": lambda r: r.video.cost_usd or 0.0,
            "analyzed_at": lambda r: r.video.analyzed_at or r.video.created_at,
        }
        key_func = key_funcs.get(self._sort_column, key_funcs["analyzed_at"])
        rows.sort(key=key_func, reverse=self._sort_reverse)
        return rows

    # ------------------------------------------------------------------
    # 列表載入與顯示
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """重新從 DB 載入影片列表與最近搜尋，供外部（例如切換到此分頁時）呼叫。"""
        if self._reanalysis_active:
            # 重新分析中的影片狀態是 pending/analyzing，list_library_videos() 撈不到，
            # 這時候重新整理會讓該影片從列表暫時消失；忽略外部觸發的 refresh，
            # 等重新分析結束（_handle_reanalysis_item）自己呼叫 refresh() 再更新。
            return
        self._rows = [self._build_row(video) for video in db.list_library_videos()]
        self._rows_by_id = {str(r.video.id): r for r in self._rows}
        self._refresh_recent_queries()
        self._populate_list()

    def _build_row(self, video: db.VideoRecord) -> _LibraryRow:
        segments = db.list_segments_for_video(video.id)
        return _LibraryRow(
            video=video,
            has_transcript=any(s.transcript for s in segments),
            has_visual=any(s.visual_description for s in segments),
            has_ocr=any(s.ocr_text for s in segments),
        )

    def _populate_list(self) -> None:
        previous_selection = self._selected_video_id
        self._tree.delete(*self._tree.get_children())

        rows = self._filtered_sorted_rows()
        self._count_var.set(f"影片庫（{len(rows)}）")

        if not rows:
            self._tree_container.grid_remove()
            if self._empty_state is not None:
                self._empty_state.destroy()
            if self._rows:
                self._empty_state = EmptyState(self._empty_state_holder, "這個篩選條件下沒有影片", ["試試其他篩選"])
            else:
                self._empty_state = EmptyState(
                    self._empty_state_holder, "影片庫還沒有任何影片",
                    ["先在「影片與分析」頁籤下載並分析影片"],
                )
            self._empty_state.grid(row=0, column=0, sticky="nsew")
            self._empty_state_holder.grid()
            self._show_detail(None)
            return

        self._empty_state_holder.grid_remove()
        self._tree_container.grid()

        for row in rows:
            v = row.video
            self._tree.insert(
                "", "end", iid=str(v.id),
                values=(
                    v.title,
                    format_duration(v.duration_sec),
                    v.segment_count if v.segment_count is not None else "--",
                    _STATUS_DISPLAY.get(v.status, v.status),
                    format_cost(v.cost_usd or 0.0),
                    format_datetime_display(v.analyzed_at),
                ),
            )

        if previous_selection is not None and str(previous_selection) in self._rows_by_id:
            iid = str(previous_selection)
            if self._tree.exists(iid):
                self._tree.selection_set(iid)
                self._tree.see(iid)
                return

        self._show_detail(None)

    def _on_row_selected(self, _event: object = None) -> None:
        selection = self._tree.selection()
        row = self._rows_by_id.get(selection[0]) if selection else None
        new_video_id = row.video.id if row is not None else None
        if new_video_id != self._selected_video_id:
            # 只有「使用者真的換了一支影片」才清暫時性訊息；refresh() 為了保留選取
            # 而重新 selection_set 同一列時，不應該把剛顯示的「✓ 摘要已更新」洗掉。
            self._summary_status_var.set("")
        self._show_detail(row)

    # ------------------------------------------------------------------
    # 詳細資訊
    # ------------------------------------------------------------------
    def _show_detail(self, row: _LibraryRow | None) -> None:
        if row is None:
            self._selected_video_id = None
            self._detail_title_var.set("尚未選取影片")
            self._detail_meta_var.set("")
            self._summary_var.set("")
            self._set_thumbnail(None)
            self._render_flags(None)
            self._regenerate_btn.configure(state="disabled")
            self._search_in_video_btn.configure(state="disabled")
            self._reanalyze_btn.configure(state="disabled")
            return

        video = row.video
        self._selected_video_id = video.id
        self._detail_title_var.set(video.title)

        meta_parts = [format_duration(video.duration_sec)]
        if video.segment_count is not None:
            meta_parts.append(f"{video.segment_count} 個片段")
        meta_parts.append(f"分析於 {format_datetime_display(video.analyzed_at)}")
        meta_parts.append(format_cost(video.cost_usd or 0.0))
        self._detail_meta_var.set("｜".join(meta_parts))

        self._render_flags(row)
        if video.summary:
            self._summary_var.set(video.summary)
        elif video.status == db.STATUS_ANALYZED:
            self._summary_var.set("尚未產生摘要，按下方「重新產生摘要」產生。")
        else:
            self._summary_var.set("這支影片分析失敗，沒有片段可以產生摘要。")

        self._regenerate_btn.configure(
            state="normal"
            if (video.status == db.STATUS_ANALYZED and not self._summary_active and not self._reanalysis_active)
            else "disabled"
        )
        self._search_in_video_btn.configure(
            state="normal" if (video.status == db.STATUS_ANALYZED and not self._reanalysis_active) else "disabled"
        )
        self._reanalyze_btn.configure(
            state="normal"
            if (video.status in (db.STATUS_ANALYZED, db.STATUS_FAILED) and not self._reanalysis_active)
            else "disabled"
        )

        self._set_thumbnail(video)

    def _render_flags(self, row: _LibraryRow | None) -> None:
        for child in self._flags_row.winfo_children():
            child.destroy()
        if row is None:
            return
        Badge(self._flags_row, "有字幕" if row.has_transcript else "無字幕",
              "success" if row.has_transcript else "neutral").pack(side="left")
        Badge(self._flags_row, "有畫面描述" if row.has_visual else "無畫面描述",
              "success" if row.has_visual else "neutral").pack(side="left", padx=(theme.SPACE_8, 0))
        Badge(self._flags_row, "有 OCR" if row.has_ocr else "無 OCR",
              "success" if row.has_ocr else "neutral").pack(side="left", padx=(theme.SPACE_8, 0))

    def _set_thumbnail(self, video: db.VideoRecord | None) -> None:
        self._thumbnail_image = None
        self._thumbnail_label.configure(image="", text="", compound="center")

        if video is None or not video.file_path or not Path(video.file_path).exists():
            return

        mid_sec = (video.duration_sec or 0) / 2
        fd, tmp_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        thumb_path = Path(tmp_path)
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-ss", str(max(mid_sec, 0.0)), "-i", video.file_path,
                    "-vf", f"scale={_THUMBNAIL_SIZE[0]}:{_THUMBNAIL_SIZE[1]}",
                    "-frames:v", "1",
                    str(thumb_path),
                ],
                check=True,
                capture_output=True,
                timeout=15,
            )
            self._thumbnail_image = tk.PhotoImage(file=str(thumb_path))
            self._thumbnail_label.configure(image=self._thumbnail_image)
        except (subprocess.SubprocessError, OSError, tk.TclError):
            self._thumbnail_label.configure(text="無法產生縮圖", compound="center")
        finally:
            thumb_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # 重新產生摘要
    # ------------------------------------------------------------------
    def _on_regenerate_summary_clicked(self) -> None:
        if self._summary_active or self._selected_video_id is None:
            return
        video_id = self._selected_video_id
        segments = db.list_segments_for_video(video_id)
        if not segments:
            messagebox.showinfo("無法產生摘要", "這支影片還沒有任何分析片段。")
            return

        self._summary_active = True
        self._regenerate_btn.configure(state="disabled")
        self._summary_status_var.set("產生摘要中…")

        result_queue: "queue.Queue[object]" = queue.Queue()
        threading.Thread(
            target=self._run_summary_worker, args=(video_id, segments, result_queue), daemon=True
        ).start()
        self.after(150, self._poll_summary, video_id, result_queue)

    def _run_summary_worker(
        self, video_id: int, segments: list[db.SegmentRecord], result_queue: "queue.Queue[object]"
    ) -> None:
        try:
            client = get_client()
            result = summary_pipeline.generate_summary(client, segments)
            db.update_video_summary(video_id, result.summary, summary_pipeline.MODEL_NAME, result.cost_usd)
            result_queue.put(result)
        except Exception as exc:  # API/網路錯誤都攔截，避免背景執行緒讓程式崩潰
            video = db.get_video(video_id)
            title = video.title if video else str(video_id)
            logger.error(
                f"「{title}」產生摘要失敗：{exc}",
                exc_info=True,
                extra={"video_title": title, "pipeline_stage": "產生摘要"},
            )
            result_queue.put(exc)

    def _poll_summary(self, video_id: int, result_queue: "queue.Queue[object]") -> None:
        try:
            item = result_queue.get_nowait()
        except queue.Empty:
            self.after(150, self._poll_summary, video_id, result_queue)
            return

        self._summary_active = False

        if isinstance(item, Exception):
            self._summary_status_var.set(f"產生摘要失敗：{item}")
            self._regenerate_btn.configure(state="normal")
            return

        self.refresh()
        self._summary_status_var.set("✓ 摘要已更新")
        if self._on_stats_changed is not None:
            self._on_stats_changed()

    # ------------------------------------------------------------------
    # 在此影片內搜尋
    # ------------------------------------------------------------------
    def _on_search_in_video_clicked(self) -> None:
        if self._selected_video_id is None:
            return
        row = self._rows_by_id.get(str(self._selected_video_id))
        if row is None:
            return
        self._on_search_in_video(row.video.id, row.video.title)

    # ------------------------------------------------------------------
    # 重新分析
    # ------------------------------------------------------------------
    def _on_reanalyze_clicked(self) -> None:
        if self._reanalysis_active or self._selected_video_id is None:
            return
        row = self._rows_by_id.get(str(self._selected_video_id))
        if row is None:
            return
        video_id = row.video.id
        title = row.video.title

        confirmed = messagebox.askyesno(
            "重新分析",
            f"確定要重新分析「{title}」嗎？\n\n"
            "這支影片現有的分析資料（片段、字幕、畫面描述、OCR、摘要）將會先被清除，"
            "再重新執行一次完整的分析流程。",
        )
        if not confirmed:
            return

        db.reset_to_pending(video_id)

        self._reanalysis_active = True
        self._regenerate_btn.configure(state="disabled")
        self._search_in_video_btn.configure(state="disabled")
        self._reanalyze_btn.configure(state="disabled")
        self._summary_status_var.set("")
        self._reanalysis_status_var.set(f"「{title}」重新分析中…")

        result_queue: "queue.Queue[object]" = queue.Queue()
        analyzer.start_analysis(video_id, result_queue)
        self.after(150, self._poll_reanalysis, title, result_queue)

    def _poll_reanalysis(self, title: str, result_queue: "queue.Queue[object]") -> None:
        try:
            while True:
                item = result_queue.get_nowait()
                if self._handle_reanalysis_item(title, item):
                    return
        except queue.Empty:
            pass
        self.after(150, self._poll_reanalysis, title, result_queue)

    def _handle_reanalysis_item(self, title: str, item: object) -> bool:
        """回傳 True 表示這支影片的重新分析已結束（不論成功或失敗）。"""
        if isinstance(item, analyzer.AnalysisProgress):
            detail = f" {item.detail}" if item.detail else ""
            self._reanalysis_status_var.set(f"「{title}」{item.stage}{detail}")
            return False

        self._reanalysis_active = False
        if isinstance(item, analyzer.AnalysisResult):
            note = format_analysis_result_note(item)
            self.refresh()
            self._reanalysis_status_var.set(f"✓「{title}」重新分析完成，共 {item.segment_count} 個片段{note}")
        elif isinstance(item, analyzer.AnalysisError):
            self.refresh()
            self._reanalysis_status_var.set(f"「{title}」重新分析失敗：{item.message}")

        if self._on_stats_changed is not None:
            self._on_stats_changed()
        return True

"""「搜尋結果」頁籤：語意搜尋輸入、結果列表、詳細分數與片段播放。"""
from __future__ import annotations

import csv
import logging
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk

from .. import theme
from ..pipeline import search as search_pipeline
from .playback import play_segment
from .widgets import (
    EmptyState,
    SimilarityBar,
    format_percent,
    format_time_range,
    make_scrollable_treeview,
    truncate,
)

logger = logging.getLogger(__name__)

_COLUMNS = ("rank", "video", "time_range", "similarity", "fusion_score", "hit_source", "description")
_HEADINGS = {
    "rank": "排名",
    "video": "影片名稱",
    "time_range": "時間範圍",
    "similarity": "相似度",
    "fusion_score": "融合分數",
    "hit_source": "命中來源",
    "description": "片段描述",
}
_WIDTHS = {
    "rank": 50, "video": 220, "time_range": 110, "similarity": 70, "fusion_score": 80,
    "hit_source": 90, "description": 320,
}

_SCORE_NA = "N/A"


class SearchResultsTab(ttk.Frame):
    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, padding=theme.SPACE_16)
        self._search_active = False
        self._search_queue: "queue.Queue[object]" = queue.Queue()
        self._results: list[search_pipeline.SearchResult] = []
        self._results_by_id: dict[str, search_pipeline.SearchResult] = {}
        self._scope_video_id: int | None = None
        self._scope_video_title: str | None = None
        self._recent_queries: list[str] = []

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_search_bar()
        self._build_results_area()

        self._show_initial_state()

    # ------------------------------------------------------------------
    # 搜尋列
    # ------------------------------------------------------------------
    def _build_search_bar(self) -> None:
        card = ttk.Frame(self, style="Card.TFrame", padding=theme.SPACE_16)
        card.grid(row=0, column=0, sticky="ew", pady=(0, theme.SPACE_16))
        card.columnconfigure(0, weight=1)

        self._scope_row = ttk.Frame(card, style="Card.TFrame")
        self._scope_row.grid(row=0, column=0, sticky="w", pady=(0, theme.SPACE_8))
        self._scope_label_var = tk.StringVar(value="")
        ttk.Label(
            self._scope_row, textvariable=self._scope_label_var, style="CardSecondary.TLabel"
        ).pack(side="left")
        ttk.Button(
            self._scope_row, text="清除範圍，改為全部影片", style="Link.TButton",
            command=self._clear_scope,
        ).pack(side="left", padx=(theme.SPACE_8, 0))
        self._scope_row.grid_remove()

        query_row = ttk.Frame(card, style="Card.TFrame")
        query_row.grid(row=1, column=0, sticky="ew")
        query_row.columnconfigure(0, weight=1)

        self._query_var = tk.StringVar()
        self._query_entry = ttk.Entry(query_row, textvariable=self._query_var)
        self._query_entry.grid(row=0, column=0, sticky="ew")
        self._query_entry.bind("<Return>", lambda _event: self._on_search_clicked())

        self._search_btn = ttk.Button(
            query_row, text="搜尋", style="Primary.TButton", command=self._on_search_clicked
        )
        self._search_btn.grid(row=0, column=1, padx=(theme.SPACE_8, 0))

        self._export_btn = ttk.Button(
            query_row, text="匯出 CSV", style="Secondary.TButton", command=self._on_export_clicked,
            state="disabled",
        )
        self._export_btn.grid(row=0, column=2, padx=(theme.SPACE_8, 0))

        self._status_var = tk.StringVar(value="描述想尋找的事件、人物、動作或教學內容")
        self._status_label = ttk.Label(card, textvariable=self._status_var, style="CardSecondary.TLabel")
        self._status_label.grid(row=2, column=0, columnspan=3, sticky="w", pady=(theme.SPACE_8, 0))

    # ------------------------------------------------------------------
    # 結果區（左：列表，右：詳細資訊）
    # ------------------------------------------------------------------
    def _build_results_area(self) -> None:
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.grid(row=1, column=0, sticky="nsew")

        left = ttk.Frame(paned, style="Card.TFrame", padding=theme.SPACE_16)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        paned.add(left, weight=3)

        self._list_area = ttk.Frame(left, style="Card.TFrame")
        self._list_area.grid(row=0, column=0, sticky="nsew")
        self._list_area.columnconfigure(0, weight=1)
        self._list_area.rowconfigure(0, weight=1)

        self._tree_container, self._tree = make_scrollable_treeview(
            self._list_area, list(_COLUMNS), _HEADINGS, _WIDTHS, stretch_column="description"
        )
        self._tree_container.grid(row=0, column=0, sticky="nsew")
        self._tree.bind("<<TreeviewSelect>>", self._on_row_selected)
        self._tree.bind("<Double-1>", lambda _event: self._play_selected())
        self._tree.bind("<Return>", lambda _event: self._play_selected())

        self._empty_state_holder = ttk.Frame(self._list_area, style="Card.TFrame")
        self._empty_state_holder.grid(row=0, column=0, sticky="nsew")
        self._empty_state_holder.columnconfigure(0, weight=1)
        self._empty_state_holder.rowconfigure(0, weight=1)
        self._empty_state: EmptyState | None = None

        toolbar = ttk.Frame(left, style="Card.TFrame")
        toolbar.grid(row=1, column=0, sticky="w", pady=(theme.SPACE_16, 0))
        ttk.Button(toolbar, text="播放片段", style="Secondary.TButton", command=self._play_selected).grid(
            row=0, column=0
        )
        ttk.Button(
            toolbar, text="查看詳細", style="Secondary.TButton", command=self._show_selected_detail
        ).grid(row=0, column=1, padx=(theme.SPACE_8, 0))
        ttk.Label(
            toolbar, text="單擊看詳細內容；雙擊或按 Enter 播放片段", style="CardSecondary.TLabel"
        ).grid(row=0, column=2, padx=(theme.SPACE_16, 0))

        right = ttk.Frame(paned, style="Card.TFrame", padding=theme.SPACE_16)
        right.columnconfigure(0, weight=1)
        paned.add(right, weight=2)
        self._build_detail_panel(right)

    def _build_detail_panel(self, parent: tk.Widget) -> None:
        ttk.Label(parent, text="詳細資訊", style="CardSection.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, theme.SPACE_16)
        )

        self._detail_title_var = tk.StringVar(value="尚未選取片段")
        ttk.Label(
            parent, textvariable=self._detail_title_var, style="Card.TLabel", wraplength=320
        ).grid(row=1, column=0, sticky="w")

        self._detail_time_var = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self._detail_time_var, style="CardSecondary.TLabel").grid(
            row=2, column=0, sticky="w", pady=(theme.SPACE_4, theme.SPACE_16)
        )

        self._similarity_row = ttk.Frame(parent, style="Card.TFrame")
        self._similarity_row.grid(row=3, column=0, sticky="w")
        ttk.Label(self._similarity_row, text="最終相似度：", style="CardSecondary.TLabel").pack(side="left")
        self._similarity_bar_holder = ttk.Frame(self._similarity_row, style="Card.TFrame")
        self._similarity_bar_holder.pack(side="left")

        self._score_vars = {
            "subtitle": tk.StringVar(value="字幕分數：--"),
            "visual": tk.StringVar(value="畫面分數：--"),
            "ocr": tk.StringVar(value="OCR 分數：--"),
            "fusion_score": tk.StringVar(value="融合分數：--"),
            "fusion": tk.StringVar(value="命中策略：--"),
        }
        for i, key in enumerate(("subtitle", "visual", "ocr", "fusion_score", "fusion")):
            ttk.Label(parent, textvariable=self._score_vars[key], style="CardSecondary.TLabel").grid(
                row=4 + i, column=0, sticky="w", pady=(theme.SPACE_4, 0)
            )

        ttk.Label(parent, text="片段描述", style="CardSection.TLabel").grid(
            row=9, column=0, sticky="w", pady=(theme.SPACE_16, theme.SPACE_8)
        )
        self._detail_description_var = tk.StringVar(value="")
        ttk.Label(
            parent, textvariable=self._detail_description_var, style="Card.TLabel", wraplength=320
        ).grid(row=10, column=0, sticky="w")

        ttk.Label(parent, text="字幕內容", style="CardSection.TLabel").grid(
            row=11, column=0, sticky="w", pady=(theme.SPACE_16, theme.SPACE_8)
        )
        self._detail_transcript_var = tk.StringVar(value="")
        ttk.Label(
            parent, textvariable=self._detail_transcript_var, style="CardSecondary.TLabel", wraplength=320
        ).grid(row=12, column=0, sticky="w")

    # ------------------------------------------------------------------
    # 搜尋
    # ------------------------------------------------------------------
    def run_search(self, query: str, video_id: int | None = None, video_title: str | None = None) -> None:
        """供其他頁籤呼叫（例如「影片庫」的「在此影片內搜尋」）：帶查詢字串與可選的範圍限定啟動搜尋。"""
        self._scope_video_id = video_id
        self._scope_video_title = video_title
        self._update_scope_display()
        self._query_var.set(query)
        self._on_search_clicked()

    def set_scope(self, video_id: int, video_title: str) -> None:
        """只設定範圍、不立刻搜尋（例如從「影片庫」按「在此影片內搜尋」，讓使用者自己輸入查詢）。"""
        self._scope_video_id = video_id
        self._scope_video_title = video_title
        self._update_scope_display()
        self._query_var.set("")
        self._query_entry.focus_set()
        if not self._results:
            self._status_var.set(f"在《{video_title}》中搜尋：描述想尋找的事件、人物、動作或教學內容")

    def get_recent_queries(self, limit: int = 5) -> list[str]:
        return self._recent_queries[:limit]

    def _clear_scope(self) -> None:
        self._scope_video_id = None
        self._scope_video_title = None
        self._update_scope_display()

    def _update_scope_display(self) -> None:
        if self._scope_video_id is not None:
            self._scope_label_var.set(f"在《{self._scope_video_title}》中搜尋")
            self._scope_row.grid()
        else:
            self._scope_row.grid_remove()

    def _on_search_clicked(self) -> None:
        if self._search_active:
            return
        query = self._query_var.get().strip()
        if not query:
            self._status_var.set("請輸入想搜尋的內容")
            return

        if query in self._recent_queries:
            self._recent_queries.remove(query)
        self._recent_queries.insert(0, query)
        del self._recent_queries[5:]

        self._search_active = True
        self._search_btn.configure(state="disabled")
        self._search_start_time = time.time()
        self._status_var.set("搜尋中…")

        self._search_queue = queue.Queue()
        threading.Thread(
            target=self._run_search_worker,
            args=(query, self._scope_video_id, self._search_queue),
            daemon=True,
        ).start()
        self.after(150, self._poll_search)

    def _run_search_worker(
        self, query: str, video_id: int | None, result_queue: "queue.Queue[object]"
    ) -> None:
        try:
            response = search_pipeline.search(query, video_id=video_id)
            result_queue.put(response)
        except Exception as exc:  # API/網路錯誤都攔截，避免背景執行緒讓程式崩潰
            logger.error(f"搜尋失敗：{query}｜{exc}", exc_info=True, extra={"pipeline_stage": "搜尋"})
            result_queue.put(exc)

    def _poll_search(self) -> None:
        try:
            item = self._search_queue.get_nowait()
        except queue.Empty:
            self.after(150, self._poll_search)
            return

        elapsed = time.time() - self._search_start_time
        self._search_active = False
        self._search_btn.configure(state="normal")

        if isinstance(item, Exception):
            self._status_var.set(f"搜尋失敗：{item}")
            self._show_empty_state(
                "搜尋時發生錯誤",
                [str(item)],
            )
            self._export_btn.configure(state="disabled")
            return

        self._results = item.results
        self._results_by_id = {str(i): r for i, r in enumerate(self._results)}
        self._populate_results()
        self._status_var.set(
            f"找到 {len(self._results)} 個相關片段｜搜尋時間 {elapsed:.2f} 秒｜花費 ${item.cost_usd:.4f}"
        )
        self._export_btn.configure(state="normal" if self._results else "disabled")

    # ------------------------------------------------------------------
    # 結果列表
    # ------------------------------------------------------------------
    def _show_initial_state(self) -> None:
        self._show_empty_state(
            "輸入描述以搜尋影片內容",
            ["例如：找出工廠中有人出現的片段", "例如：找出全壘打畫面"],
        )

    def _show_empty_state(self, title: str, hint_lines: list[str]) -> None:
        self._tree_container.grid_remove()
        if self._empty_state is not None:
            self._empty_state.destroy()
        self._empty_state = EmptyState(self._empty_state_holder, title, hint_lines)
        self._empty_state.grid(row=0, column=0, sticky="nsew")
        self._empty_state_holder.grid()
        self._clear_detail()

    def _populate_results(self) -> None:
        self._tree.delete(*self._tree.get_children())

        if not self._results:
            self._show_empty_state(
                "沒有找到足夠相關的片段",
                ["建議：", "• 使用較簡短的描述", "• 改用人物、動作或物件名稱", "• 降低最低相似度"],
            )
            return

        self._empty_state_holder.grid_remove()
        self._tree_container.grid()

        for index, result in enumerate(self._results):
            self._tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    index + 1,
                    result.video_title,
                    format_time_range(int(result.start_sec), int(result.end_sec)),
                    format_percent(result.similarity),
                    f"{result.fusion_score:.3f}",
                    result.hit_source,
                    truncate(result.description, 80),
                ),
            )
        self._clear_detail()

    def _on_row_selected(self, _event: object = None) -> None:
        self._show_selected_detail()

    def _get_selected_result(self) -> search_pipeline.SearchResult | None:
        selection = self._tree.selection()
        if not selection:
            return None
        return self._results_by_id.get(selection[0])

    def _show_selected_detail(self) -> None:
        result = self._get_selected_result()
        if result is None:
            return

        self._detail_title_var.set(result.video_title)
        self._detail_time_var.set(format_time_range(int(result.start_sec), int(result.end_sec)))

        for child in self._similarity_bar_holder.winfo_children():
            child.destroy()
        SimilarityBar(self._similarity_bar_holder, result.similarity).pack(side="left")

        self._score_vars["subtitle"].set(f"字幕分數：{_format_score(result.transcript_score)}")
        self._score_vars["visual"].set(f"畫面分數：{_format_score(result.visual_score)}")
        self._score_vars["ocr"].set(f"OCR 分數：{_format_score(result.ocr_score)}")
        self._score_vars["fusion_score"].set(f"融合分數：{result.fusion_score:.3f}（排序依據）")
        self._score_vars["fusion"].set(f"命中策略：{result.fusion_strategy}")

        self._detail_description_var.set(result.description or "（無畫面描述）")
        self._detail_transcript_var.set(result.transcript or "（此片段無字幕）")

    def _clear_detail(self) -> None:
        self._detail_title_var.set("尚未選取片段")
        self._detail_time_var.set("")
        for child in self._similarity_bar_holder.winfo_children():
            child.destroy()
        for key in self._score_vars:
            label = {
                "subtitle": "字幕分數", "visual": "畫面分數", "ocr": "OCR 分數",
                "fusion_score": "融合分數", "fusion": "命中策略",
            }[key]
            self._score_vars[key].set(f"{label}：--")
        self._detail_description_var.set("")
        self._detail_transcript_var.set("")

    # ------------------------------------------------------------------
    # 播放與匯出
    # ------------------------------------------------------------------
    def _play_selected(self) -> None:
        result = self._get_selected_result()
        if result is None:
            return
        play_segment(result.video_id, result.video_title, result.start_sec, result.end_sec)

    def _on_export_clicked(self) -> None:
        if not self._results:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile="搜尋結果.csv",
        )
        if not path:
            return

        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["排名", "影片名稱", "時間範圍", "相似度", "融合分數", "命中來源", "片段描述"])
            for index, result in enumerate(self._results):
                writer.writerow(
                    [
                        index + 1,
                        result.video_title,
                        format_time_range(int(result.start_sec), int(result.end_sec)),
                        format_percent(result.similarity),
                        f"{result.fusion_score:.3f}",
                        result.hit_source,
                        result.description,
                    ]
                )
        self._status_var.set(f"已匯出至 {path}")


def _format_score(score: float | None) -> str:
    return _SCORE_NA if score is None else f"{score:.2f}"

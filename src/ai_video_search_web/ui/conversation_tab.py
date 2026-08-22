"""「對話搜尋」頁籤：多輪對話式影片搜尋，見
docs/Claude_Code_Conversational_Video_Search_Prompt.md 與
pipeline/conversation.py。這是新增的獨立入口，不改動既有「搜尋結果」頁籤
（ui/search_tab.py）的單次關鍵字搜尋行為；兩者共用 pipeline/search.py 與
播放邏輯（ui/playback.py），不重複實作。

沿用 search_tab.py 既有的「背景執行緒 + queue + after(150, poll)」模式呼叫
LLM／搜尋，避免卡住 Tkinter 主執行緒。
"""
from __future__ import annotations

import logging
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

from .. import theme
from ..pipeline import conversation as conversation_pipeline
from ..pipeline.search import SearchResult
from .playback import play_segment
from .widgets import EmptyState, format_percent, format_time_range, make_scrollable_treeview, truncate

logger = logging.getLogger(__name__)

_COLUMNS = ("rank", "video", "time_range", "similarity", "fusion_score", "hit_source", "description")
_HEADINGS = {
    "rank": "編號",
    "video": "影片名稱",
    "time_range": "時間範圍",
    "similarity": "相似度",
    "fusion_score": "融合分數",
    "hit_source": "命中來源",
    "description": "片段描述",
}
_WIDTHS = {
    "rank": 50, "video": 200, "time_range": 100, "similarity": 70, "fusion_score": 80,
    "hit_source": 90, "description": 320,
}

_GREETING = "你好，跟我說說想找的影片內容，例如「找出有人進入生產線的畫面」。之後可以接著說「只看穿紅色衣服的人」或「播放第二段」。"


class ConversationTab(ttk.Frame):
    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, padding=theme.SPACE_16)
        self._state = conversation_pipeline.ConversationState()
        self._turn_active = False
        self._turn_queue: "queue.Queue[object]" = queue.Queue()
        self._turn_start_time = 0.0
        self._results: list[SearchResult] = []
        self._results_by_id: dict[str, SearchResult] = {}

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        paned = ttk.PanedWindow(self, orient="vertical")
        paned.grid(row=0, column=0, sticky="nsew")

        chat_frame = ttk.Frame(paned, style="Card.TFrame", padding=theme.SPACE_16)
        chat_frame.columnconfigure(0, weight=1)
        chat_frame.rowconfigure(0, weight=1)
        paned.add(chat_frame, weight=3)
        self._build_chat_area(chat_frame)

        results_frame = ttk.Frame(paned, style="Card.TFrame", padding=theme.SPACE_16)
        results_frame.columnconfigure(0, weight=1)
        paned.add(results_frame, weight=2)
        self._build_results_area(results_frame)

        self._append_transcript("助理", _GREETING)

    # ------------------------------------------------------------------
    # 對話區（訊息串 + 輸入框）
    # ------------------------------------------------------------------
    def _build_chat_area(self, parent: tk.Widget) -> None:
        text_container = ttk.Frame(parent)
        text_container.grid(row=0, column=0, sticky="nsew", pady=(0, theme.SPACE_8))
        text_container.columnconfigure(0, weight=1)
        text_container.rowconfigure(0, weight=1)

        self._transcript = tk.Text(
            text_container,
            wrap="word",
            state="disabled",
            height=10,
            background=theme.BG_CARD,
            foreground=theme.TEXT_PRIMARY,
            font=theme.font_body(),
            relief="flat",
            borderwidth=0,
            padx=theme.SPACE_8,
            pady=theme.SPACE_8,
        )
        self._transcript.tag_configure("user", font=theme.font_body(bold=True))
        self._transcript.tag_configure("assistant", foreground=theme.TEXT_SECONDARY)
        self._transcript.grid(row=0, column=0, sticky="nsew")

        vsb = ttk.Scrollbar(text_container, orient="vertical", command=self._transcript.yview)
        self._transcript.configure(yscrollcommand=vsb.set)
        vsb.grid(row=0, column=1, sticky="ns")

        input_row = ttk.Frame(parent, style="Card.TFrame")
        input_row.grid(row=1, column=0, sticky="ew")
        input_row.columnconfigure(0, weight=1)

        self._input_var = tk.StringVar()
        self._input_entry = ttk.Entry(input_row, textvariable=self._input_var)
        self._input_entry.grid(row=0, column=0, sticky="ew")
        self._input_entry.bind("<Return>", lambda _event: self._on_send_clicked())

        self._send_btn = ttk.Button(
            input_row, text="送出", style="Primary.TButton", command=self._on_send_clicked
        )
        self._send_btn.grid(row=0, column=1, padx=(theme.SPACE_8, 0))

        self._status_var = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self._status_var, style="CardSecondary.TLabel").grid(
            row=2, column=0, sticky="w", pady=(theme.SPACE_8, 0)
        )

    # ------------------------------------------------------------------
    # 結果區（這一輪的相關片段）
    # ------------------------------------------------------------------
    def _build_results_area(self, parent: tk.Widget) -> None:
        parent.rowconfigure(1, weight=1)
        ttk.Label(parent, text="這一輪的相關片段", style="CardSection.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, theme.SPACE_8)
        )

        self._list_holder = ttk.Frame(parent, style="Card.TFrame")
        self._list_holder.grid(row=1, column=0, sticky="nsew")
        self._list_holder.columnconfigure(0, weight=1)
        self._list_holder.rowconfigure(0, weight=1)

        self._tree_container, self._tree = make_scrollable_treeview(
            self._list_holder, list(_COLUMNS), _HEADINGS, _WIDTHS, stretch_column="description"
        )
        self._tree_container.grid(row=0, column=0, sticky="nsew")
        self._tree.bind("<Double-1>", lambda _event: self._play_selected())
        self._tree.bind("<Return>", lambda _event: self._play_selected())

        self._empty_holder = ttk.Frame(self._list_holder, style="Card.TFrame")
        self._empty_holder.grid(row=0, column=0, sticky="nsew")
        self._empty_holder.columnconfigure(0, weight=1)
        self._empty_holder.rowconfigure(0, weight=1)
        self._empty_state: EmptyState | None = None
        self._show_empty_state("尚無結果", ["在上方輸入想找的內容開始對話"])

        toolbar = ttk.Frame(parent, style="Card.TFrame")
        toolbar.grid(row=2, column=0, sticky="w", pady=(theme.SPACE_8, 0))
        ttk.Button(
            toolbar, text="播放片段", style="Secondary.TButton", command=self._play_selected
        ).grid(row=0, column=0)
        ttk.Label(
            toolbar, text="雙擊或按 Enter 播放片段", style="CardSecondary.TLabel"
        ).grid(row=0, column=1, padx=(theme.SPACE_16, 0))

    # ------------------------------------------------------------------
    # 送出一輪對話
    # ------------------------------------------------------------------
    def _on_send_clicked(self) -> None:
        if self._turn_active:
            return
        message = self._input_var.get().strip()
        if not message:
            return
        self._input_var.set("")
        self._append_transcript("你", message)

        self._turn_active = True
        self._send_btn.configure(state="disabled")
        self._status_var.set("思考中…")
        self._turn_start_time = time.time()

        self._turn_queue = queue.Queue()
        threading.Thread(
            target=self._run_turn_worker,
            args=(message, self._state, self._turn_queue),
            daemon=True,
        ).start()
        self.after(150, self._poll_turn)

    def _run_turn_worker(
        self,
        message: str,
        state: conversation_pipeline.ConversationState,
        result_queue: "queue.Queue[object]",
    ) -> None:
        try:
            result = conversation_pipeline.handle_turn(state, message)
            result_queue.put(result)
        except Exception as exc:  # API/網路錯誤都攔截，避免背景執行緒讓程式崩潰
            logger.error(
                f"對話處理失敗：{message}｜{exc}", exc_info=True, extra={"pipeline_stage": "對話搜尋"}
            )
            result_queue.put(exc)

    def _poll_turn(self) -> None:
        try:
            item = self._turn_queue.get_nowait()
        except queue.Empty:
            self.after(150, self._poll_turn)
            return

        elapsed = time.time() - self._turn_start_time
        self._turn_active = False
        self._send_btn.configure(state="normal")

        if isinstance(item, Exception):
            self._append_transcript("助理", f"處理時發生錯誤：{item}")
            self._status_var.set("發生錯誤")
            return

        self._state = item.new_state
        self._append_transcript("助理", item.reply_text)
        self._results = item.results
        self._results_by_id = {str(i): r for i, r in enumerate(self._results)}
        self._populate_results()
        self._status_var.set(f"回應時間 {elapsed:.2f} 秒｜花費 ${item.cost_usd:.4f}")

    # ------------------------------------------------------------------
    # 訊息串與結果列表顯示
    # ------------------------------------------------------------------
    def _append_transcript(self, speaker: str, text: str) -> None:
        self._transcript.configure(state="normal")
        tag = "user" if speaker == "你" else "assistant"
        self._transcript.insert("end", f"{speaker}：", (tag,))
        self._transcript.insert("end", f"{text}\n\n")
        self._transcript.configure(state="disabled")
        self._transcript.see("end")

    def _show_empty_state(self, title: str, hint_lines: list[str]) -> None:
        self._tree_container.grid_remove()
        if self._empty_state is not None:
            self._empty_state.destroy()
        self._empty_state = EmptyState(self._empty_holder, title, hint_lines)
        self._empty_state.grid(row=0, column=0, sticky="nsew")
        self._empty_holder.grid()

    def _populate_results(self) -> None:
        self._tree.delete(*self._tree.get_children())
        if not self._results:
            self._show_empty_state("這一輪沒有相關片段", ["可以換個描述方式再試試"])
            return

        self._empty_holder.grid_remove()
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

    def _play_selected(self) -> None:
        selection = self._tree.selection()
        if not selection:
            return
        result = self._results_by_id.get(selection[0])
        if result is None:
            return
        play_segment(result.video_id, result.video_title, result.start_sec, result.end_sec)

"""跨頁籤共用的小型元件與格式化函式。"""
from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import ttk

from .. import theme
from ..pipeline import analyzer


def format_analysis_result_note(item: analyzer.AnalysisResult) -> str:
    """把分析結果裡「預算截斷」跟「場景畫面分析失敗」兩種各自獨立的原因組成
    附註文字，兩者可能同時發生；不能共用同一句文字，不然使用者會看到誤導
    的原因（例如明明是內容審查拒絕，卻顯示「已達預算上限」），見
    docs/analysis-pipeline-flow.md。video_tab.py／library_tab.py 共用。"""
    notes = []
    if item.partial:
        notes.append("已達預算上限，僅完成部分片段")
    if item.vlm_failed_count:
        notes.append(f"{item.vlm_failed_count} 個場景畫面分析失敗，已略過")
    return f"（{'；'.join(notes)}）" if notes else ""


def format_duration(seconds: int | None) -> str:
    if not seconds:
        return "--:--"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_datetime_display(iso_str: str | None) -> str:
    if not iso_str:
        return "--"
    try:
        dt = datetime.fromisoformat(iso_str)
    except ValueError:
        return iso_str
    return dt.strftime("%Y/%m/%d %H:%M")


def format_time_range(start_sec: int, end_sec: int) -> str:
    def mmss(sec: int) -> str:
        m, s = divmod(int(sec), 60)
        return f"{m:02d}:{s:02d}"

    return f"{mmss(start_sec)}–{mmss(end_sec)}"


def format_cost(usd: float) -> str:
    return f"US${usd:,.2f}"


def format_percent(ratio: float) -> str:
    return f"{round(ratio * 100)}%"


def truncate(text: str, limit: int) -> str:
    text = text.replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


class StatCard(ttk.Frame):
    """Header 右側的精簡指標卡：標籤字小、數值字大。"""

    def __init__(self, parent: tk.Widget, label: str, value: str) -> None:
        super().__init__(parent)
        self._value_var = tk.StringVar(value=value)
        self._label_var = tk.StringVar(value=label)

        value_lbl = ttk.Label(self, textvariable=self._value_var, style="StatValue.TLabel")
        value_lbl.grid(row=0, column=0, sticky="w")
        label_lbl = ttk.Label(self, textvariable=self._label_var, style="StatLabel.TLabel")
        label_lbl.grid(row=1, column=0, sticky="w")

    def set_value(self, value: str) -> None:
        self._value_var.set(value)


class EmptyState(ttk.Frame):
    """取代空表格的提示區塊：標題 + 多行提示文字。"""

    def __init__(self, parent: tk.Widget, title: str, hint_lines: list[str] | None = None) -> None:
        super().__init__(parent, style="Card.TFrame")
        container = ttk.Frame(self, style="Card.TFrame")
        container.place(relx=0.5, rely=0.5, anchor="center")

        ttk.Label(container, text=title, style="CardSection.TLabel").pack(pady=(0, theme.SPACE_8))
        for line in hint_lines or []:
            ttk.Label(container, text=line, style="CardSecondary.TLabel").pack(anchor="center")


class Badge(ttk.Frame):
    """小型狀態標籤，用底色 + 文字辨識，不只靠顏色。"""

    def __init__(self, parent: tk.Widget, text: str, kind: str = "neutral") -> None:
        super().__init__(parent)
        bg = theme.BADGE_BG.get(kind, theme.BADGE_BG["neutral"])
        fg = theme.BADGE_FG.get(kind, theme.BADGE_FG["neutral"])
        label = tk.Label(
            self,
            text=text,
            bg=bg,
            fg=fg,
            font=theme.font_caption(bold=True),
            padx=theme.SPACE_8,
            pady=2,
        )
        label.pack()


class SimilarityBar(ttk.Frame):
    """相似度小色條 + 百分比文字，避免只用顏色傳達分數。"""

    def __init__(self, parent: tk.Widget, ratio: float, width: int = 60) -> None:
        super().__init__(parent)
        ratio = max(0.0, min(1.0, ratio))
        canvas = tk.Canvas(self, width=width, height=8, highlightthickness=0, bd=0, bg=theme.BG_CARD)
        canvas.pack(side="left")
        canvas.create_rectangle(0, 0, width, 8, fill="#E4E7EC", outline="")
        canvas.create_rectangle(0, 0, int(width * ratio), 8, fill=theme.PRIMARY, outline="")
        ttk.Label(self, text=format_percent(ratio), style="Card.TLabel").pack(side="left", padx=(theme.SPACE_8, 0))


def make_scrollable_treeview(
    parent: tk.Widget,
    columns: list[str],
    headings: dict[str, str],
    widths: dict[str, int] | None = None,
    stretch_column: str | None = None,
    selectmode: str = "browse",
) -> tuple[ttk.Frame, ttk.Treeview]:
    """建立帶垂直捲軸的 Treeview，回傳 (容器 Frame, Treeview)。容器需自行 grid 到 parent。"""
    container = ttk.Frame(parent)
    container.columnconfigure(0, weight=1)
    container.rowconfigure(0, weight=1)

    tree = ttk.Treeview(container, columns=columns, show="headings", selectmode=selectmode)
    widths = widths or {}
    for col in columns:
        tree.heading(col, text=headings.get(col, col))
        tree.column(
            col,
            width=widths.get(col, 120),
            anchor="w",
            stretch=(col == stretch_column),
        )

    vsb = ttk.Scrollbar(container, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=vsb.set)

    tree.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")

    return container, tree


def make_scrollable_frame(parent: tk.Widget) -> tuple[ttk.Frame, ttk.Frame]:
    """建立可垂直捲動的容器，用於內容高度不固定、可能超過可視範圍的面板
    （例如詳細資訊面板：摘要、字幕長度都不固定，底部按鈕不能被擋住）。
    回傳 (外層容器，要 grid 到 parent；內層 Frame，實際內容放這裡)。
    """
    outer = ttk.Frame(parent)
    outer.columnconfigure(0, weight=1)
    outer.rowconfigure(0, weight=1)

    canvas = tk.Canvas(outer, background=theme.BG_CARD, highlightthickness=0, bd=0)
    vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")

    inner = ttk.Frame(canvas, style="Card.TFrame")
    inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

    def _on_inner_configure(_event: object = None) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))

    def _on_canvas_configure(event: tk.Event) -> None:
        canvas.itemconfigure(inner_id, width=event.width)

    inner.bind("<Configure>", _on_inner_configure)
    canvas.bind("<Configure>", _on_canvas_configure)

    def _scroll(delta: int) -> None:
        canvas.yview_scroll(delta, "units")

    def _bind_mousewheel(_event: object = None) -> None:
        canvas.bind_all("<MouseWheel>", lambda e: _scroll(-1 if e.delta > 0 else 1))
        canvas.bind_all("<Button-4>", lambda _e: _scroll(-1))
        canvas.bind_all("<Button-5>", lambda _e: _scroll(1))

    def _unbind_mousewheel(_event: object = None) -> None:
        canvas.unbind_all("<MouseWheel>")
        canvas.unbind_all("<Button-4>")
        canvas.unbind_all("<Button-5>")

    canvas.bind("<Enter>", _bind_mousewheel)
    canvas.bind("<Leave>", _unbind_mousewheel)

    return outer, inner

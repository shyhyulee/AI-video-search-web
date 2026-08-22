"""全域 Header：左側標題副標，右側四個精簡指標卡。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import db, theme
from .widgets import StatCard, format_cost


class HeaderFrame(ttk.Frame):
    def __init__(self, parent: tk.Widget, stats: db.HeaderStatsData) -> None:
        super().__init__(parent, padding=(theme.SPACE_24, theme.SPACE_16))
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)

        title_box = ttk.Frame(self)
        title_box.grid(row=0, column=0, sticky="w")
        ttk.Label(title_box, text="AI 影片語意搜尋", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            title_box,
            text="快速找到影片中的關鍵時刻",
            style="Secondary.TLabel",
        ).pack(anchor="w", pady=(theme.SPACE_4, 0))

        stats_box = ttk.Frame(self)
        stats_box.grid(row=0, column=1, sticky="e")

        self.pending_card = StatCard(stats_box, "待分析", f"{stats.pending_count} 支")
        self.analyzed_card = StatCard(stats_box, "已分析", f"{stats.analyzed_count} 支")
        self.segment_card = StatCard(stats_box, "影片片段", f"{stats.segment_count:,}")
        self.cost_card = StatCard(stats_box, "累計成本", format_cost(stats.total_cost_usd))

        for i, card in enumerate(
            (self.pending_card, self.analyzed_card, self.segment_card, self.cost_card)
        ):
            card.grid(row=0, column=i, padx=(0 if i == 0 else theme.SPACE_24, 0), sticky="e")

    def update_stats(self, stats: db.HeaderStatsData) -> None:
        self.pending_card.set_value(f"{stats.pending_count} 支")
        self.analyzed_card.set_value(f"{stats.analyzed_count} 支")
        self.segment_card.set_value(f"{stats.segment_count:,}")
        self.cost_card.set_value(format_cost(stats.total_cost_usd))

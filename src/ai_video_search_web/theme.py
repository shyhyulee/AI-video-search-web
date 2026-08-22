"""集中管理顏色、字型、間距與 ttk.Style 設定。

所有 Widget 只引用這裡定義的 style name / 常數，
不在個別檔案中分散設定顏色，方便未來整體調整視覺風格。
"""
from __future__ import annotations

import platform
import tkinter.font as tkfont
from tkinter import ttk

# ---------------------------------------------------------------------------
# 顏色
# ---------------------------------------------------------------------------
BG_APP = "#F5F7FA"
BG_CARD = "#FFFFFF"
TEXT_PRIMARY = "#172033"
TEXT_SECONDARY = "#667085"
PRIMARY = "#2563EB"
PRIMARY_HOVER = "#1D4ED8"
PRIMARY_TEXT = "#FFFFFF"
SUCCESS = "#16A34A"
WARNING = "#D97706"
ERROR = "#DC2626"
BORDER = "#D0D5DD"
ROW_SELECTED = "#E8F1FF"

# Badge 底色（淺色底 + 深色字，避免只靠色相辨識）
BADGE_BG = {
    "success": "#DCFCE7",
    "warning": "#FEF3C7",
    "error": "#FEE2E2",
    "neutral": "#EEF2F6",
    "primary": "#DBEAFE",
}
BADGE_FG = {
    "success": SUCCESS,
    "warning": WARNING,
    "error": ERROR,
    "neutral": TEXT_SECONDARY,
    "primary": PRIMARY,
}

# ---------------------------------------------------------------------------
# 間距（8px 系統）
# ---------------------------------------------------------------------------
SPACE_4 = 4
SPACE_8 = 8
SPACE_16 = 16
SPACE_24 = 24
SPACE_32 = 32

# ---------------------------------------------------------------------------
# 字型
# ---------------------------------------------------------------------------
def _resolve_font_family() -> str:
    """依作業系統挑選中文字型，找不到就退回系統預設無襯線字型。"""
    preferred = "Microsoft JhengHei UI" if platform.system() == "Windows" else "Noto Sans CJK TC"
    try:
        available = set(tkfont.families())
    except Exception:
        return preferred
    if preferred in available:
        return preferred
    for fallback in ("Noto Sans CJK TC", "Microsoft JhengHei", "PingFang TC", "sans-serif"):
        if fallback in available:
            return fallback
    return "TkDefaultFont"


FONT_FAMILY = None  # 由 configure_style() 於 root 建立後填入

FONT_TITLE_SIZE = 20
FONT_SECTION_SIZE = 15
FONT_BODY_SIZE = 11
FONT_CAPTION_SIZE = 10


def font_title(bold: bool = True) -> tuple:
    return (FONT_FAMILY, FONT_TITLE_SIZE, "bold" if bold else "normal")


def font_section(bold: bool = True) -> tuple:
    return (FONT_FAMILY, FONT_SECTION_SIZE, "bold" if bold else "normal")


def font_body(bold: bool = False) -> tuple:
    return (FONT_FAMILY, FONT_BODY_SIZE, "bold" if bold else "normal")


def font_caption(bold: bool = False) -> tuple:
    return (FONT_FAMILY, FONT_CAPTION_SIZE, "bold" if bold else "normal")


# ---------------------------------------------------------------------------
# ttk.Style 設定
# ---------------------------------------------------------------------------
def configure_style(style: ttk.Style) -> None:
    """在 root Tk 建立後呼叫一次，統一設定所有 ttk 元件樣式。"""
    global FONT_FAMILY
    FONT_FAMILY = _resolve_font_family()

    style.theme_use("clam")

    style.configure(".", background=BG_APP, foreground=TEXT_PRIMARY, font=font_body())

    # 一般容器 / 標籤
    style.configure("TFrame", background=BG_APP)
    style.configure("Card.TFrame", background=BG_CARD, relief="flat", borderwidth=1)
    style.configure("TLabel", background=BG_APP, foreground=TEXT_PRIMARY, font=font_body())
    style.configure("Card.TLabel", background=BG_CARD, foreground=TEXT_PRIMARY, font=font_body())
    style.configure("Secondary.TLabel", background=BG_APP, foreground=TEXT_SECONDARY, font=font_body())
    style.configure("CardSecondary.TLabel", background=BG_CARD, foreground=TEXT_SECONDARY, font=font_body())
    style.configure("Error.TLabel", background=BG_APP, foreground=ERROR, font=font_body())
    style.configure("CardError.TLabel", background=BG_CARD, foreground=ERROR, font=font_body())
    style.configure("Success.TLabel", background=BG_APP, foreground=SUCCESS, font=font_body())
    style.configure("CardSuccess.TLabel", background=BG_CARD, foreground=SUCCESS, font=font_body())
    style.configure("Title.TLabel", background=BG_APP, foreground=TEXT_PRIMARY, font=font_title())
    style.configure("Section.TLabel", background=BG_APP, foreground=TEXT_PRIMARY, font=font_section())
    style.configure("CardSection.TLabel", background=BG_CARD, foreground=TEXT_PRIMARY, font=font_section())
    style.configure("StatValue.TLabel", background=BG_APP, foreground=TEXT_PRIMARY, font=(FONT_FAMILY, 18, "bold"))
    style.configure("StatLabel.TLabel", background=BG_APP, foreground=TEXT_SECONDARY, font=font_caption())

    # 按鈕：Primary 全應用程式只用一種樣式，Secondary 為次要操作
    style.configure(
        "Primary.TButton",
        background=PRIMARY,
        foreground=PRIMARY_TEXT,
        font=font_body(bold=True),
        padding=(SPACE_16, SPACE_8),
        borderwidth=0,
        focusthickness=0,
    )
    style.map(
        "Primary.TButton",
        background=[("disabled", "#93B4F5"), ("pressed", PRIMARY_HOVER), ("active", PRIMARY_HOVER)],
        foreground=[("disabled", "#F0F4FF")],
    )

    style.configure(
        "Secondary.TButton",
        background=BG_CARD,
        foreground=TEXT_PRIMARY,
        font=font_body(),
        padding=(SPACE_16, SPACE_8),
        borderwidth=1,
        bordercolor=BORDER,
        focusthickness=0,
    )
    style.map(
        "Secondary.TButton",
        background=[("disabled", BG_APP), ("pressed", "#EAECF0"), ("active", "#EAECF0")],
        foreground=[("disabled", TEXT_SECONDARY)],
    )

    style.configure(
        "Link.TButton",
        background=BG_CARD,
        foreground=PRIMARY,
        font=font_body(),
        padding=(SPACE_4, SPACE_4),
        borderwidth=0,
    )
    style.map("Link.TButton", foreground=[("pressed", PRIMARY_HOVER), ("active", PRIMARY_HOVER)])

    # Entry / Combobox
    style.configure(
        "TEntry",
        fieldbackground=BG_CARD,
        foreground=TEXT_PRIMARY,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        padding=(SPACE_8, SPACE_8),
    )
    style.map("TEntry", bordercolor=[("focus", PRIMARY)])

    style.configure(
        "TCombobox",
        fieldbackground=BG_CARD,
        foreground=TEXT_PRIMARY,
        background=BG_CARD,
        bordercolor=BORDER,
        padding=(SPACE_8, SPACE_4),
    )

    # Notebook / Tab
    style.configure("TNotebook", background=BG_APP, borderwidth=0, tabmargins=(0, SPACE_8, 0, 0))
    style.configure(
        "TNotebook.Tab",
        background=BG_APP,
        foreground=TEXT_SECONDARY,
        font=font_body(bold=True),
        padding=(SPACE_16, SPACE_8),
        borderwidth=0,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", BG_CARD)],
        foreground=[("selected", PRIMARY)],
        expand=[("selected", (1, 1, 1, 0))],
    )

    # Treeview
    style.configure(
        "Treeview",
        background=BG_CARD,
        fieldbackground=BG_CARD,
        foreground=TEXT_PRIMARY,
        font=font_body(),
        rowheight=30,
        borderwidth=0,
    )
    style.configure(
        "Treeview.Heading",
        background="#F0F2F5",
        foreground=TEXT_SECONDARY,
        font=font_caption(bold=True),
        relief="flat",
        padding=(SPACE_8, SPACE_8),
    )
    style.map(
        "Treeview.Heading",
        background=[("active", "#E4E7EC")],
    )
    style.map(
        "Treeview",
        background=[("selected", ROW_SELECTED)],
        foreground=[("selected", TEXT_PRIMARY)],
    )

    # PanedWindow
    style.configure("TPanedwindow", background=BG_APP)

    # Progressbar
    style.configure(
        "Primary.Horizontal.TProgressbar",
        troughcolor="#E4E7EC",
        background=PRIMARY,
        borderwidth=0,
        thickness=8,
    )

    # Scrollbar
    style.configure(
        "Vertical.TScrollbar",
        background="#E4E7EC",
        troughcolor=BG_APP,
        bordercolor=BG_APP,
        arrowcolor=TEXT_SECONDARY,
    )

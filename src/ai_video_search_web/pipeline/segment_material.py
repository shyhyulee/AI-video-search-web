"""把片段攤成餵給 LLM 的逐行素材：`[MM:SS｜N 秒] 畫面：…；字幕：…；畫面文字：…`。

summary.py（影片摘要）與 document.py（結構化文件）本來各有一份幾乎相同的實作，
連 `_format_timestamp()` 都是逐字重複的。兩者的 prompt 目的不同，但「素材長什麼
樣子」是同一個決定——時間戳格式、欄位標籤、分隔符號、沒有任何內容的片段要略過
——改其中一邊而忘了另一邊，兩個功能餵給模型的素材就會悄悄長得不一樣。

只留一個開關 `include_ocr`：文件會帶畫面文字、摘要不帶。這是實測逼出來的差異
（1,076/1,156 個片段有畫面文字，對流程類影片特別有價值，摘要用不到但 SOP 用得
到），不是可有可無的選項。

**素材品質過濾在這裡**：整欄都是幻覺的字幕、整支重複的浮水印 OCR，在攤成素材時
就丟掉。放這裡而不是各自的呼叫端，是因為它跟「素材長什麼樣子」是同一個決定——
摘要與文件餵到的都是同一批髒資料，兩邊都該被擋。判斷方式見 `_dominant_share()`。

**截斷不在這裡**：summary.py 只取前 200 段（prompt 長度控制），document.py 刻意
不截斷（SOP 少掉尾段等於少掉最後幾個製程步驟，比直接失敗更糟）。這是兩邊各自的
決定，留在各自的呼叫端才看得見。
"""
from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..db import SegmentRecord

# VLM 偶爾會把「沒有畫面文字」寫成字面字串而不是 JSON null（實測全庫 1,156 個
# 片段裡有 21 個這樣），不濾掉就會餵一堆 "null" 給 LLM 當畫面文字。
_PLACEHOLDER_TEXTS = {"null", "none", "n/a", "na", "無", "-"}

# 幻覺字幕與浮水印 OCR 的偵測門檻，見 _dominant_share() 與 build_material()。
# 數字來自全庫 23 支影片的實測分布，不是拍腦袋定的。
_JUNK_TRANSCRIPT_SHARE = 0.4
_WATERMARK_OCR_SHARE = 0.15

# 樣本太少時不做這個判斷：整支只有 3 句字幕的影片，其中 2 句剛好一樣就會湊出
# 67%，那是樣本雜訊不是幻覺訊號。實測真實語音影片的重複率最高只有 26%
# （video 1，39 句），而 8 句以上還能同一句佔 40% 的，資料裡全都是幻覺。
_MIN_SAMPLES_FOR_JUNK_CHECK = 8


def _dominant_share(texts: list[str]) -> float:
    """最常出現的那一句佔全部的比例；樣本數不足時回 0（等於不判定）。

    **這是影片層級的統計，不是逐片段的信心分數**——這點是走過冤枉路才確定的。
    `asr.py` 已經有一個逐片段的幻覺判斷（`no_speech_prob > 0.7`），一度以為文件
    端只要接上它就好，但拿全庫量過之後發現它在這裡不管用：BMW 那支它抓到
    76/97，但同樣整欄是幻覺的 Intel（`... ... ...` 佔 65%）只抓到 2/108、
    video 6（佔 74%）只抓到 1/82；反過來線性代數那支是真實講課，卻有 16 段被它
    標記。信心分數看的是「這一段像不像人聲」，而幻覺字幕的特徵是「整支影片一直
    重複同一句」——後者只有把整支影片放在一起看才看得出來。
    """
    if len(texts) < _MIN_SAMPLES_FOR_JUNK_CHECK:
        return 0.0
    return max(Counter(texts).values()) / len(texts)


def is_transcript_column_junk(texts: "list[str | None]") -> bool:
    """整支影片的字幕欄位是不是整欄都是幻覺（最常出現的那一句佔比超過門檻）。

    公開的（而不是 `_` 開頭）是為了讓它能被直接測到——門檻與樣本下限都是拿全庫
    23 支影片校準出來的，`build_material()` 的整合測試蓋不到邊界條件。

    曾經有第二個呼叫端：analyzer 用它決定要不要對這支影片加密畫面取樣。2026-08-31
    的 P4 把取樣統一成一律三幀之後那個判斷就沒有了，現在只剩這個模組自己在用。
    """
    cleaned = [t for t in (_clean(text) for text in texts) if t]
    return _dominant_share(cleaned) > _JUNK_TRANSCRIPT_SHARE


def format_timestamp(sec: float) -> str:
    """秒數轉成 `MM:SS`。超過 60 分鐘不會進位成 HH:MM:SS——分析長度上限是
    1 小時（見 analyzer.MAX_DURATION_SEC），所以 MM 最多兩位數。"""
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


def build_material(segments: "list[SegmentRecord]", *, include_ocr: bool = False) -> str:
    """把片段依時間順序攤成逐行素材；三個欄位都是空的片段整行略過。

    **時間戳同時給 `MM:SS` 與總秒數**，這不是裝飾。`VideoDocument` 的欄位叫
    `timestamp_sec`（秒），但素材原本只給 `MM:SS`，等於逼模型自己換算——實測它
    常常不換算，直接把 `[03:18]` 的 `18` 抄進去。2026-08-30 用三支影片各跑一次
    只改這個格式：BMW 的步驟時間戳從「全部塌在 00:56 以內」變成散佈到 08:42、
    Intel 超出影片長度的步驟從 1 個變 0 個、Python 的步驟順序從章節間倒退變成
    單調遞增，步驟數也分別多了 38%／33%／100%。詳見
    docs/05-known-limitations-and-open-items.md。

    **整欄都是幻覺的欄位會被丟掉**。純環境音／純配樂的影片，Whisper 會整支輸出
    同一句罐頭台詞（BMW 那支 97 句字幕裡 70 句是 `Thank you for watching.`，
    佔 72%），而字幕欄一旦是噪音，它還會把真正有訊號的欄位稀釋掉——BMW 的
    `ocr_text` 有 67 句各自不同的製程旁白（`Once the BIW REACHES THE COMPONENT
    ASSEMBLY LINE…`），模型卻只寫出 7 個步驟。

    字幕與 OCR 的處理方式**刻意不同**：
    - 字幕整欄丟。一句佔到 72% 時，剩下的 28% 實測也是同一類垃圾（BMW 的 9 個
      unique 全是 thanks-for-watching 的變體），留著沒有意義。
    - OCR 只丟重複的那個字串本身。重複的通常是頻道浮水印（BMW／Intel 都是
      `FRAME`，各佔 30%／34%），但同一欄的其他內容正是主要訊號，不能整欄丟。
    """
    drop_transcripts = is_transcript_column_junk([s.transcript for s in segments])

    watermarks: set[str] = set()
    if include_ocr:
        ocr_texts = [t for t in (_clean(s.ocr_text) for s in segments) if t]
        if len(ocr_texts) >= _MIN_SAMPLES_FOR_JUNK_CHECK:
            watermarks = {
                text
                for text, count in Counter(ocr_texts).items()
                if count / len(ocr_texts) > _WATERMARK_OCR_SHARE
            }

    lines = []
    for seg in segments:
        parts = []
        if _clean(seg.visual_description):
            parts.append(f"畫面：{_clean(seg.visual_description)}")
        if not drop_transcripts and _clean(seg.transcript):
            parts.append(f"字幕：{_clean(seg.transcript)}")
        if include_ocr and _clean(seg.ocr_text) and _clean(seg.ocr_text) not in watermarks:
            parts.append(f"畫面文字：{_clean(seg.ocr_text)}")
        if parts:
            stamp = f"[{format_timestamp(seg.start_sec)}｜{int(seg.start_sec)} 秒]"
            lines.append(f"{stamp} " + "；".join(parts))
    return "\n".join(lines)


def _clean(text: str | None) -> str:
    """去掉前後空白、把內部換行壓成空白，並把 VLM 偶爾產生的字面佔位字串當成空值。

    壓掉換行是必要的：prompt 開頭就宣告「每行是一個片段」，但 VLM 抓到的畫面
    文字與字幕本身可能帶換行，那些行會沒有時間戳前綴、模型無從得知它們屬於
    哪個片段。實測**每一支影片都有這個問題**，比例 28%～88%（線性代數那支
    461/526 行沒有時間戳）。壓成空白之後那句宣告才是真的。
    """
    stripped = " ".join((text or "").split())
    return "" if stripped.lower() in _PLACEHOLDER_TEXTS else stripped

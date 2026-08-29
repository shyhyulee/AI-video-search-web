"""查詢字串處理：泛用詞清理、候選關鍵字抽取、否定句切分。

這個模組是純字串邏輯——不碰資料庫、不呼叫任何 API，所有規則都是「粗糙但夠用」
的取捨（不引入 jieba 之類的斷詞依賴），各自的校準依據見下方常數旁的說明。
"""
from __future__ import annotations

import re

# 中文虛詞表，用來把查詢字串切成候選關鍵字（不是真正斷詞，純規則）；
# 兩輪 spike（見 docs/02-technical-decisions.md#搜尋）驗證過這個粗糙作法
# 「夠用」：唯一的失敗模式剛好都落在 dense 已經排第一的查詢上，融合後
# 不影響整體結果，所以沒有為此再引入 jieba 之類的斷詞依賴。「要」是後來
# 補的：「要真人的畫面」原本會被黏成查不到任何片段的複合詞「要真人」，
# 見 docs/02-technical-decisions.md「否定句查詢的疊加案例」。
_STOPWORDS = set("的了在是這那個有跟和與上中一準備出現連續喊著地正要")
_ENGLISH_RE = re.compile(r"[A-Za-z0-9]+")

# 否定詞清單：偵測到這些詞，後面到下一個標點符號（或字串結尾）之前的內容
# 視為「使用者不想要」的範圍，見 split_negated_query()。只用
# docs/05-known-limitations-and-open-items.md 待辦事項裡已經列出的四個，
# 不預先擴充；之後有真實案例顯示需要更多否定詞，再照這個模式新增。
_NEGATION_MARKERS = ("不要", "沒有", "不是", "並非")
_CLAUSE_PUNCTUATION = "，。！？、"

# 泛用描述詞：使用者常見的「畫面」「段落」是描述影片單位本身的詞（想找的
# 是內容，不是「這是一個畫面／段落」這件事），不是有鑑別力的內容詞。Sparse
# channel 已經靠 _SHORT_TERM_MAX_MATCH_RATIO 間接濾掉「畫面」（見 sparse.py
# 註解的實測 77.4% 比例），但那是統計上剛好被濾掉，dense channel（embedding）
# 完全沒有對應機制——整句原文（含這兩個詞）直接拿去 embed，VLM 視覺描述模板常以
# 「畫面中…」開頭，幾乎每個片段的 embedding 都帶有這個詞的語意重量，稀釋掉
# 真正有鑑別力的內容詞。直接在 search() 入口用子字串移除清理，兩個 channel
# 都吃到清理後的查詢字串，不用個別修 sparse／dense 兩套邏輯。只挑字面出現
# 的這兩個詞刪除，不是真正斷詞，跟 _STOPWORDS／_NEGATION_MARKERS 同樣「粗糙
# 但夠用」的取捨——極端情況（詞組剛好包住這兩個字，例如「壁畫面積」）會被
# 誤刪，但這個 app 的查詢型態（人物／動作／物件描述）機率很低，先不處理。
_GENERIC_DESCRIPTIVE_TERMS = ("畫面", "段落")


def strip_generic_terms(query: str) -> str:
    """移除查詢字串裡的泛用描述詞（見 _GENERIC_DESCRIPTIVE_TERMS 旁的說明），
    回傳清理後的字串供 dense／sparse 兩個 channel 共用。清理後整句變空字串
    （例如使用者只打「畫面」兩個字）就退回用原始查詢——安全網，跟
    dense.get_query_vectors() 翻譯失敗、dense.relevant_video_ids() 判斷失敗
    時的退回邏輯一致，不讓清理把整個查詢清空。
    """
    cleaned = query
    for term in _GENERIC_DESCRIPTIVE_TERMS:
        cleaned = cleaned.replace(term, "")
    cleaned = cleaned.strip()
    return cleaned if cleaned else query


def extract_terms(query: str) -> list[str]:
    """把查詢字串拆成候選關鍵字：英文／數字直接當一個詞；中文用虛詞表切開，
    剩下的連續中文片段整段當一個候選詞（不是真正斷詞，見 _STOPWORDS 旁的說明）。
    長度 <2 的片段丟棄，太短沒有鑑別力。"""
    english = [w for w in _ENGLISH_RE.findall(query) if len(w) >= 2]
    remainder = _ENGLISH_RE.sub(" ", query)
    chunks: list[str] = []
    current = ""
    for ch in remainder:
        if ch in _STOPWORDS or ch.isspace() or ch in "，。！？、":
            if len(current) >= 2:
                chunks.append(current)
            current = ""
        else:
            current += ch
    if len(current) >= 2:
        chunks.append(current)
    return list(dict.fromkeys(english + chunks))  # 去重，保留順序


def split_negated_query(query: str) -> tuple[str, str]:
    """把查詢依 _NEGATION_MARKERS 切成 (positive_text, negative_text)。否定詞
    出現後、到下一個標點符號（_CLAUSE_PUNCTUATION）或字串結尾之前的內容算
    否定範圍；可能有多段否定，全部否定範圍合併成一段 negative_text（用空白
    分隔）。positive_text 是把否定範圍（含否定詞本身）挖空成空白後剩下的
    文字。沒有偵測到否定詞時回傳 (query, "")。

    刻意用標點當否定範圍邊界，不用 _STOPWORDS 當邊界——虛詞是結構助詞
    （的／在...），會把否定範圍切太短，見 _STOPWORDS 旁「要真人」案例的
    教訓。
    """
    negative_contents: list[str] = []
    blanked = list(query)
    idx = 0
    while idx < len(query):
        marker = next((m for m in _NEGATION_MARKERS if query.startswith(m, idx)), None)
        if marker is None:
            idx += 1
            continue
        content_start = idx + len(marker)
        content_end = content_start
        while content_end < len(query) and query[content_end] not in _CLAUSE_PUNCTUATION:
            content_end += 1
        negative_contents.append(query[content_start:content_end])
        for i in range(idx, content_end):
            blanked[i] = " "
        idx = content_end

    if not negative_contents:
        return query, ""
    return "".join(blanked), " ".join(negative_contents)

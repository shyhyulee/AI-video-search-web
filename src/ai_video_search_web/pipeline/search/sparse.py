"""Sparse channel：BM25 關鍵字檢索（>=3 字元）＋ LIKE fallback（<3 字元），
以及靠同一套取詞規則實作的否定句排除。

跟 dense channel 的分工：這裡完全不看語意，只看字面命中；兩邊的排名最後由
fusion.py 的 RRF 融合。
"""
from __future__ import annotations

from ... import db
from .query import _extract_terms, _split_negated_query

# <3 字元的關鍵字用 LIKE 找到時給的哨兵分數：FTS5 trigram tokenizer 對
# 這種短詞完全查不到（見 db/segments.py create_table 的說明），這裡直接
# 讓它們排在所有真正 bm25 分數（實測落在 -2~-10 之間）前面，模擬「精確
# 關鍵字命中應該最優先」——沒有嚴謹校準過，只是 spike 驗證過方向正確。
#
# 只在片段還沒有真正 bm25 分數時才套用這個哨兵分數（見 _sparse_scores()）：
# 實測「找出全壘打的畫面」這類查詢會同時拆出一個罕見長詞（「全壘打」，
# 10 個片段命中，真實 bm25）跟一個常見短詞（「畫面」，同一支 app.db 裡
# 527 個片段都命中），如果短詞哨兵分數無條件覆寫，會讓 527 個只是剛好
# 提到「畫面」、跟查詢語意無關的片段並列蓋過真正命中「全壘打」的片段，
# 排序整個跑掉；保留真正 bm25 分數，哨兵分數只補「完全沒被 bm25 找到」
# 的片段，兩者才不會互相蓋過。
_SHORT_TERM_SPARSE_SCORE = -1e6

# 短詞如果比對到「太大比例」的候選片段，代表它不是精確關鍵字、比較像
# 「畫面」這種描述性泛用詞，不是「汽車」「工廠」這種有鑑別力的內容詞；
# 這種短詞套用哨兵分數只會製造大量並列的雜訊、把真正精確的長詞 bm25
# 命中擠到排名後面，直接跳過、不當作 sparse 訊號比較安全。用比例（不是
# 絕對筆數）判斷，這樣不管是全域搜尋或限定單一影片搜尋，候選片段池大小
# 不同時都適用。門檻沒有嚴謹校準過，只用同一支 app.db 的幾個詞驗證過方向
# 正確：汽車 11.6%／工廠 14.4%（有鑑別力，該保留）vs 畫面 77.4%（沒有
# 鑑別力，該跳過），0.2 這個門檻剛好能把兩種情況分開。
_SHORT_TERM_MAX_MATCH_RATIO = 0.2


def _sparse_scores(query: str, valid_ids: set[int]) -> dict[int, float]:
    """BM25 關鍵字檢索分數，只回傳 valid_ids 範圍內、真的被找到的片段；
    數字越小（越負）代表越相關。>=3 字元的詞用 FTS5 bm25()（真正的 IDF
    加權），<3 字元的詞用 LIKE fallback（trigram tokenizer 查不到，見
    db/segments.py create_table 的說明）。長詞的真實 bm25 分數優先：短詞
    哨兵分數只補「這個片段完全沒被任何長詞 bm25 找到」的情況，不會覆寫
    已經算出來的真實 bm25 分數；比對到過大比例候選片段的短詞（沒有鑑別
    力，見 _SHORT_TERM_MAX_MATCH_RATIO）整個跳過，不當作 sparse 訊號。"""
    terms = _extract_terms(query)
    long_terms = [t for t in terms if len(t) >= 3]
    short_terms = [t for t in terms if len(t) < 3]

    scores: dict[int, float] = {}
    if long_terms:
        for seg_id, bm25_score in db.fts_bm25_search(long_terms):
            if seg_id in valid_ids:
                scores[seg_id] = bm25_score

    max_matches = len(valid_ids) * _SHORT_TERM_MAX_MATCH_RATIO
    for term in short_terms:
        matched_ids = [seg_id for seg_id in db.fts_like_search(term) if seg_id in valid_ids]
        if valid_ids and len(matched_ids) > max_matches:
            continue  # 太常見，不是精確關鍵字，跳過這個短詞
        for seg_id in matched_ids:
            scores.setdefault(seg_id, _SHORT_TERM_SPARSE_SCORE)
    return scores


def _negated_segment_ids(query: str, valid_ids: set[int]) -> set[int]:
    """回傳因為命中否定關鍵字而該被排除的 segment id 集合（見 service.search()
    的使用方式）。直接重用 _sparse_scores()——它已經有長詞 bm25／短詞 LIKE＋
    _SHORT_TERM_MAX_MATCH_RATIO 比例門檻防呆，對否定範圍的文字跑一次一樣
    的取詞與比對，避免否定詞剛好是「畫面」這種泛用詞時，誤刪掉大部分候選
    片段。"""
    _, negative_text = _split_negated_query(query)
    if not negative_text.strip():
        return set()
    return set(_sparse_scores(negative_text, valid_ids).keys())

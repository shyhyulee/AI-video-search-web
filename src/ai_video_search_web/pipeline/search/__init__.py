"""搜尋：dense（embedding cosine 相似度）+ sparse（BM25 關鍵字）hybrid 召回，
用 RRF 融合排名，取代 V0 純 dense 排序。見 docs/02-technical-decisions.md#搜尋
的 spike 過程與決策依據；reranker 還沒做，是後續 Phase 2 的範圍。

模組分工（原本是單一檔案 pipeline/search.py，內容成長到 522 行、一個 search()
函式同時做六件事之後拆開，對外介面完全不變）：

- `results.py`：SearchResult／SearchResponse 的形狀與「命中來源」文字。
- `query.py`：純字串處理——泛用詞清理、候選關鍵字抽取、否定句切分。
- `sparse.py`：BM25／LIKE 關鍵字通道，以及靠同一套取詞規則做的否定句排除。
- `dense.py`：查詢向量（含中英文翻譯）、片段模態分數、影片層級篩選。
- `fusion.py`：RRF 融合與回傳結果的品質門檻。
- `service.py`：`search()` 對外入口，只負責編排。

`SearchResponse.is_confident`：判斷 top1 結果是否可信（取代 V0 借用
MIN_RELEVANCE 當無答案門檻的暫時作法）。訊號是「top1 是否同時被 sparse
（BM25/LIKE 關鍵字）channel 印證」——單純 dense 相似度分不開 answerable／
no_answer 兩組（golden set 實測 no_answer 四題 top1 dense 相似度落在
0.41~0.74，跟 answerable 題目重疊），RRF 融合分數與 top1/top2 分數差距
也一樣分不開；只有「兩個 channel 是否都同意」這個布林訊號能把兩組分開
（golden set 實測 no_answer_f1 從 0 提升到 0.667）。已知限制：無法處理
否定句（例如「工廠裡沒有機器人」，BM25 照樣會命中「機器人」字面關鍵字，
這是語意理解問題不是門檻問題）；只在 17 題小樣本驗證過。

查詢會先翻譯成中英文兩個版本各自 embed，每個模態的分數取兩者較高分，
處理內容跟查詢語言不一致的情況（例如英文影片被中文查詢、或反過來）；
翻譯失敗則優雅退回只用原始查詢，不讓翻譯失敗擋住搜尋功能。

全域搜尋（沒有指定 video_id）會先依影片摘要（沒有摘要退回標題）判斷
查詢跟哪些影片相關，只在相關影片的片段內比對，減少不相關影片的雜訊；
判斷不出明顯相關影片時（安全網）不篩選，維持原本全部影片都搜尋的行為，
避免誤判排除掉真正相關的內容。「在此影片內搜尋」（已指定 video_id）
不套用這層篩選。

每次搜尋的實際花費（翻譯＋embedding 呼叫）會記錄進 search_log 表，並
包在回傳的 SearchResponse 裡。
"""
from __future__ import annotations

from .results import FUSION_STRATEGY, SearchResponse, SearchResult
from .service import search

__all__ = ["search", "SearchResult", "SearchResponse", "FUSION_STRATEGY"]

"""一次分析共用的東西與預算常數。

`_AnalysisContext` 是三個橫切關注點的載體（固定輸入、進度回報、累計花費與預算
判斷），六個 phase 都靠它。`BUDGET_USD` 住在這裡而不是套件門面：讀它的是
`over_budget`，常數跟判斷放在一起，測試也只要 patch 一個位址
（`analyzer.context.BUDGET_USD`）。
"""
from __future__ import annotations

import queue
import threading
from pathlib import Path

from openai import OpenAI

from ... import db
from .events import AnalysisProgress

# 預算演進：$0.20 →（VLM 條件式多幀）$0.30 →（長度上限放寬到 1 小時）$0.80 →
# （**每個片段一律三幀**，見 FRAME_FRACTIONS）**$1.50**，2026-08-31 由使用者拍板。
#
# $1.50 的依據，用 v28／v33／v36 實跑反推的每片段費率（幾乎全部是 VLM 的圖片
# token——embedding 與文件攤到每個片段趨近於零）：
#
#   1 幀 $0.00056／段、3 幀 $0.00144／段（實測倍率 2.57，兩支影片一致）
#   文件另記的最高觀測費率是 $0.0009／段（1 幀），×2.57 = $0.00232／段
#
#   情境（密度用結構上限 7.5 段/分）        總計    $1.50 的餘裕
#   52 分（ASR 的實際上限）· 實測費率        $0.87      42%
#   52 分 · 最壞費率                        $1.22      19%
#   60 分（理論上限）· 最壞費率              $1.40       7%
#   60 分 · 最壞費率 · 無音軌（不花 ASR）    $1.04      31%
#
# 60 分鐘那一列的 7% 看起來很緊，但它碰不到——asr._extract_audio() 的 64kbps
# 換算 Whisper 25MB 上限約 52~55 分鐘，超過就先卡在 ASR（見 MAX_DURATION_SEC）。
# 實務上限那一列的餘裕是 19%。
BUDGET_USD = 1.50


class _AnalysisContext:
    """一次分析從頭到尾共用的東西：固定的輸入（video_id／video_path／video_title／
    client），加上兩個橫切關注點——進度回報與累計花費／預算判斷。

    抽出來的理由：這兩件事原本靠參數手工穿過每個 phase 函式（`progress_queue`
    一路往下傳、`total_cost` 進出每個簽名），新增或調整一個 phase 就要同時記得
    三件事——更新 videos.pipeline_stage、送出 AnalysisProgress、累加並回傳花費
    ——漏掉任何一件都不會報錯，只會安靜地少一個進度或少算一筆錢。
    """

    def __init__(
        self,
        video_id: int,
        video_path: Path,
        client: OpenAI,
        progress_queue: "queue.Queue[object]",
        video_title: str = "",
        initial_cost: float = 0.0,
    ) -> None:
        self.video_id = video_id
        self.video_path = video_path
        # Phase F 整理文件時要把影片標題放進 prompt（`document.generate_document()`
        # 的必要輸入）。放進 context 而不是一路傳參數，理由跟 video_path 一樣：
        # 它是「這次分析的固定輸入」，不是某個 phase 算出來的中間結果。
        self.video_title = video_title
        self.client = client
        self._progress_queue = progress_queue
        self._initial_cost = initial_cost
        self._cost = initial_cost
        # 好幾個 phase 是在背景執行緒裡累加花費（音訊轉錄、本地 OCR），用鎖
        # 讓 spend() 本身就是安全的，呼叫端不用各自想同步問題。
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 花費與預算
    # ------------------------------------------------------------------
    @property
    def total_cost(self) -> float:
        with self._lock:
            return self._cost

    @property
    def spent(self) -> float:
        """這個 context 自己花掉的金額（不含起始基準），給 merge_branch() 用。"""
        with self._lock:
            return self._cost - self._initial_cost

    def spend(self, amount: float) -> None:
        with self._lock:
            self._cost += amount

    @property
    def over_budget(self) -> bool:
        return self.total_cost > BUDGET_USD

    # ------------------------------------------------------------------
    # 進度回報
    # ------------------------------------------------------------------
    def enter_stage(self, stage: str) -> None:
        """階段切換：同時寫進 videos.pipeline_stage（重新整理頁面也看得到目前
        跑到哪）與送出 AnalysisProgress 事件（Job Manager 的 pump thread 會把它
        寫進 jobs 表）。兩者用同一段文字。"""
        db.update_video_status(self.video_id, db.STATUS_ANALYZING, stage)
        self._progress_queue.put(AnalysisProgress(stage=stage))

    def report_progress(self, stage: str, detail: str, *, persist_as: str | None = None) -> None:
        """階段內的百分比回報。預設只送事件、不寫 DB——這種事件很密集（場景
        切分／音訊轉錄／本地 OCR 都是），沒必要每次都寫一次資料庫。

        Phase B（畫面分析）是唯一會順便更新 pipeline_stage 的，而且兩邊的文字
        格式本來就不一樣（DB 寫「畫面分析 40%」一整串，事件是 stage／detail
        分開兩欄），所以用 persist_as 明確指定要寫進 DB 的字串，不假設兩者相同。
        """
        if persist_as is not None:
            db.update_video_status(self.video_id, db.STATUS_ANALYZING, persist_as)
        self._progress_queue.put(AnalysisProgress(stage=stage, detail=detail))

    # ------------------------------------------------------------------
    # 平行分支
    # ------------------------------------------------------------------
    def budget_branch(self) -> "_AnalysisContext":
        """給「互相平行、而且各自都要判斷預算」的 phase 用：回傳一個從目前金額
        起算、獨立累加的 context。兩個分支互相看不到對方的花費——這正是
        _run_local_ocr_and_document() 既有的取捨（兩者合計可能比 BUDGET_USD 多出
        一點點），用 budget_branch() 把它變成明講的機制而不是靠傳參數傳出來的
        副作用。跑完用 merge_branch() 把增量併回主帳。
        """
        return _AnalysisContext(
            video_id=self.video_id,
            video_path=self.video_path,
            client=self.client,
            progress_queue=self._progress_queue,
            video_title=self.video_title,
            initial_cost=self.total_cost,
        )

    def merge_branch(self, branch: "_AnalysisContext") -> None:
        """把分支自己花掉的增量併回主帳（不是把分支的總額覆蓋上來）。"""
        self.spend(branch.spent)

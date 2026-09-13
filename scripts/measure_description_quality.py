"""量化 `segments.visual_description` 的「具體程度」，當作改 VLM prompt 的回歸基準。

**為什麼需要這支腳本**：畫面描述的品質原本完全沒有量化方式（跟文件整理一樣，見
docs/04-known-limitations-and-open-items.md），只能人眼看。這代表改 VLM prompt
沒有任何東西擋得住退步。這個專案已經因為 n=1 觀察錯誤歸因兩次（見
docs/01-development-timeline.md 那兩節），所以動 prompt 之前先把「現在有多糟」
釘成數字。

**這裡的指標是代理指標，不是真值**。三個詞表都是人工挑的，不可能涵蓋所有講法，
所以：
- 絕對值沒有意義（「籠統率 73%」不等於「73% 的描述是壞的」）。
- **改動前後的差值才有意義**，而且必須是同一批片段、同一份詞表。
- 指標好轉不代表描述真的變好，只代表「沒有明顯退步」。真的要確認品質仍然要人眼
  抽看，這支腳本只負責把該抽看的地方指出來。

純讀資料庫，不呼叫任何 API、不寫任何表。

用法：
    uv run python scripts/measure_description_quality.py
    uv run python scripts/measure_description_quality.py --videos 4,28,32,34
    uv run python scripts/measure_description_quality.py --samples 5
"""
from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime
from pathlib import Path

from ai_video_search_web import db

EVAL_RUNS_DIR = db.PROJECT_ROOT / "docs" / "eval-runs"

# 「籠統詞」：出現這些字代表描述停在場景／氛圍層級，沒有講出具體在做什麼。
# 從全庫 1,354 個既有描述的高頻詞挑出來的，前五名是 顯示(37%)／正在(30%)／
# 進行(19%)／設備(12%)／環境(11%)。
#
# 注意「正在」「可能」「似乎」不是壞詞本身——「正在搬箱子」是好描述。它們被列進來
# 是因為實測高度伴隨籠統句型出現（「正在進行作業」）。所以這個指標要跟
# CONCRETE_ACTION_WORDS 一起看：兩個都高代表描述變長且具體，只有籠統高才是問題。
VAGUE_WORDS = (
    "工作", "操作", "進行", "作業", "活動", "忙碌", "設備", "機器", "儀器", "裝置",
    "處理", "運作", "使用", "顯示", "場景", "環境", "專注", "似乎", "可能", "正在",
)

# 「具體動作動詞」：能讓人重現動作的及物動詞。這是使用者要的東西——
# 「人在產線工作」→「人在產線搬箱子」的差別就在這一類詞有沒有出現。
CONCRETE_ACTION_WORDS = (
    "搬", "抬", "舉", "拿起", "放下", "推", "拉", "轉動", "按下", "插入", "焊接",
    "切割", "倒入", "攪拌", "擦拭", "彎腰", "蹲", "伸手", "遞", "堆疊", "裝入",
    "取出", "扭", "敲", "撕", "貼",
)

# 「幀間比較措辭」：多幀 prompt 的副作用偵測。多幀本來是要給模型時間維度、
# 讓它講得出動作，但 vlm._MULTI_FRAME_PROMPT_TEMPLATE 說「簡短點出變化」，
# 模型就把輸出預算花在描述兩張圖的差異上，而不是描述這段在做什麼。
#
# 實測基準（2026-08-31，改 prompt 前）：多幀片段 61.0% 命中、單幀 0.6%。
# 這個 61% 是 P1 要壓下去的數字。
META_COMPARISON_WORDS = (
    "第一", "第二", "接著顯示", "隨著", "逐漸", "變化", "略有", "前後", "兩張",
    "轉為", "然後在",
)


def _hit(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)


def _rates(descriptions: list[str]) -> dict:
    """一組描述的四個指標；空清單回傳 None 值而不是 0，避免「沒有資料」被讀成「零命中」。"""
    if not descriptions:
        return {"n": 0, "avg_length": None, "vague_rate": None, "concrete_rate": None, "meta_rate": None}
    n = len(descriptions)
    return {
        "n": n,
        "avg_length": round(statistics.mean(len(d) for d in descriptions), 1),
        "vague_rate": round(sum(_hit(d, VAGUE_WORDS) for d in descriptions) / n, 4),
        "concrete_rate": round(sum(_hit(d, CONCRETE_ACTION_WORDS) for d in descriptions) / n, 4),
        "meta_rate": round(sum(_hit(d, META_COMPARISON_WORDS) for d in descriptions) / n, 4),
    }


def _fetch(video_ids: list[int] | None) -> list[dict]:
    sql = """
        SELECT s.video_id, s.start_sec, s.visual_description, s.vlm_frame_count, v.title
        FROM segments s JOIN videos v ON v.id = s.video_id
        WHERE s.visual_description IS NOT NULL AND s.visual_description <> ''
    """
    params: list = []
    if video_ids:
        sql += " AND s.video_id = ANY(%s)"
        params.append(video_ids)
    sql += " ORDER BY s.video_id, s.start_sec"
    with db.get_connection() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _pct(value: float | None) -> str:
    return "  —  " if value is None else f"{value:6.1%}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--videos", type=str, default=None, help="只量這幾支，逗號分隔的 video_id")
    parser.add_argument("--samples", type=int, default=0, help="每支影片印幾筆描述原文供人眼抽看")
    parser.add_argument("--output", type=Path, default=None, help="覆寫預設的 docs/eval-runs/ 輸出路徑")
    parser.add_argument("--no-write", action="store_true", help="只印出，不寫檔")
    args = parser.parse_args()

    video_ids = [int(x) for x in args.videos.split(",")] if args.videos else None
    rows = _fetch(video_ids)
    if not rows:
        print("沒有任何有畫面描述的片段——確認影片已經分析過，或 --videos 給對了嗎？")
        return

    overall = _rates([r["visual_description"] for r in rows])
    print(f"=== 全體（{overall['n']} 個片段）===")
    print(f"平均長度 {overall['avg_length']} 字｜籠統 {_pct(overall['vague_rate'])}"
          f"｜具體動作 {_pct(overall['concrete_rate'])}｜幀間比較 {_pct(overall['meta_rate'])}")

    # 依 vlm_frame_count 分組：這是資料庫裡現成的對照組，能看出多幀有沒有把
    # 描述帶得更具體。注意這是觀察性比較不是隨機實驗——多幀的觸發條件
    # （source_raw_duration > 20s）集中在特定影片類型，兩組的內容組成本來就不同，
    # 差值不能直接當成多幀的因果效果。
    print("\n=== 依 VLM 幀數分組（觀察性比較，有選擇偏誤，不是因果證據）===")
    print(f"{'幀數':<8}{'n':>6}{'平均長度':>10}{'籠統':>10}{'具體動作':>10}{'幀間比較':>10}")
    by_frame: dict = {}
    for row in rows:
        by_frame.setdefault(row["vlm_frame_count"], []).append(row["visual_description"])
    for fc in sorted(by_frame, key=lambda x: (x is None, x)):
        m = _rates(by_frame[fc])
        label = "未記錄" if fc is None else str(fc)
        print(f"{label:<8}{m['n']:>6}{m['avg_length']:>10}{_pct(m['vague_rate']):>10}"
              f"{_pct(m['concrete_rate']):>10}{_pct(m['meta_rate']):>10}")

    print("\n=== 逐支影片 ===")
    print(f"{'id':>4} {'標題':<34}{'n':>5}{'長度':>7}{'籠統':>9}{'具體':>9}{'幀間比較':>9}")
    per_video = {}
    by_video: dict = {}
    for row in rows:
        by_video.setdefault(row["video_id"], []).append(row)
    for vid, group in sorted(by_video.items()):
        m = _rates([g["visual_description"] for g in group])
        per_video[vid] = {"title": group[0]["title"], **m}
        title = group[0]["title"][:32]
        print(f"{vid:>4} {title:<34}{m['n']:>5}{m['avg_length']:>7}{_pct(m['vague_rate']):>9}"
              f"{_pct(m['concrete_rate']):>9}{_pct(m['meta_rate']):>9}")

        if args.samples:
            for g in group[: args.samples]:
                print(f"       [{g['start_sec']:6.0f}s fc={g['vlm_frame_count']}] {g['visual_description']}")

    if args.no_write:
        return
    EVAL_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    # 檔名加 desc- 前綴，跟同資料夾的 Golden Set 搜尋評測結果分開。
    path = args.output or EVAL_RUNS_DIR / f"desc-{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(
        json.dumps(
            {
                "measured_at": datetime.now().isoformat(timespec="seconds"),
                "video_filter": video_ids,
                "overall": overall,
                "by_frame_count": {str(k): _rates(v) for k, v in by_frame.items()},
                "by_video": per_video,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n已寫入 {path.relative_to(db.PROJECT_ROOT)}")


if __name__ == "__main__":
    main()

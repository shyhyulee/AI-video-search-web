"""手動執行 Golden Set 評分，對照 docs/golden-set.csv 量化目前 search.py
的品質，見 src/ai_video_search_web/pipeline/evaluation.py 的評分邏輯。

會呼叫真實 OpenAI API（翻譯＋embedding，跟一般搜尋一樣），對 18 題全部跑一
輪的費用是分毫等級（跟單次搜尋同量級），並會依 search() 既有行為寫入
app.db 的 search_log 表。跑在目前這台機器設定好的 app.db 上——golden set
引用的 video_id 必須已經分析過，不然那幾題會被當成完全沒有候選結果。

每次執行會把結果存成 docs/eval-runs/<timestamp>.json，方便之後比較不同
實驗（Phase 1 改 hybrid 召回／RRF／門檻時）跟這次 baseline 的差異，見規劃
文件 Phase 0 步驟6「建立固定 baseline；後續所有實驗必須使用同一版本的
資料集」。

用法：
    uv run python scripts/run_golden_set_eval.py
    uv run python scripts/run_golden_set_eval.py --top-k 10
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from ai_video_search_web import db
from ai_video_search_web.pipeline import evaluation as ev

EVAL_RUNS_DIR = db.PROJECT_ROOT / "docs" / "eval-runs"


def _fmt(value: float | None, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden-set", type=Path, default=ev.DEFAULT_GOLDEN_SET_PATH)
    parser.add_argument("--top-k", type=int, default=ev.DEFAULT_TOP_K)
    parser.add_argument("--output", type=Path, default=None, help="覆寫預設的 docs/eval-runs/ 輸出路徑")
    args = parser.parse_args()

    db.init_db()  # 冪等：確保 schema／migration（含 segments_fts）是最新的，不用先手動跑過 app 才能執行這支腳本
    print(f"讀取 {args.golden_set}，top_k={args.top_k}")
    print("（無答案判斷用 search.SearchResponse.is_confident：top1 是否同時被 sparse channel 印證）\n")

    def on_query_done(result: ev.QueryEvalResult) -> None:
        marker = "✓" if (result.recall_at_1 or (result.is_answerable is False and not result.predicted_answerable)) else "·"
        print(f"  {marker} {result.id:8s} [{result.query_type:15s}] {result.query}")

    report = ev.run_evaluation(
        golden_set_path=args.golden_set,
        top_k=args.top_k,
        on_query_done=on_query_done,
    )

    print("\n=== 彙總指標（僅 is_answerable=TRUE 的題目計入 Recall/MRR/nDCG） ===")
    print(f"Recall@1        : {_fmt(report.recall_at_1)}")
    print(f"Recall@5        : {_fmt(report.recall_at_5)}")
    print(f"MRR             : {_fmt(report.mrr)}")
    print(f"nDCG@5          : {_fmt(report.ndcg_at_5)}")
    print(f"Mean Timestamp IoU（僅命中的題目）: {_fmt(report.mean_timestamp_iou)}")
    print(f"No-answer Precision : {_fmt(report.no_answer_precision)}")
    print(f"No-answer Recall    : {_fmt(report.no_answer_recall)}")
    print(f"No-answer F1        : {_fmt(report.no_answer_f1)}")
    print(f"總花費 (USD)     : {report.total_cost_usd:.5f}")

    misses = [r for r in report.query_results if r.is_answerable and not r.recall_at_5]
    if misses:
        print("\n=== Recall@5 沒命中的題目（見 notes 判讀是否為預期內的已知差距） ===")
        for r in misses:
            print(f"  {r.id} [{r.query_type}] {r.query}")
            print(f"      notes: {r.notes}")

    EVAL_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = args.output or (EVAL_RUNS_DIR / f"{timestamp}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(asdict(report), f, ensure_ascii=False, indent=2)
    print(f"\n報告已存至 {output_path}")


if __name__ == "__main__":
    main()

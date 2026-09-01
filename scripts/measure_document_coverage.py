"""量化「整理成文件」的時間戳涵蓋率與對位情況，當作改文件 prompt 的回歸基準。

**為什麼需要這支腳本**：文件品質原本完全沒有量化方式（見
docs/05-known-limitations-and-open-items.md），只能人眼看，代表改 prompt 沒有任何
東西擋得住退步。2026-09-01 追一份「停在 05:15」的 SOP 時發現，其中三項其實純讀
資料庫就算得出來，而且那一輪的 A/B 就是靠它們才分得出訊號的。這支腳本把當時臨時
寫的查詢固定下來。

分三類：

**「寫到哪裡為止」**（2026-09-01 那條覆蓋規則要動的東西）
- `coverage`：`max(timestamp_sec) / duration_sec`，文件寫到影片的百分之幾。
- `material_coverage`：分母改成素材最後一行的秒數。這才是公允的分母——素材本來就
  到不了片尾（最後一個場景的長度就是差距），拿片長當分母會系統性低估。
- `second_half` / `tail_20`：後半段與最後 20% 各有幾個步驟。

**「中間有沒有跳過」**（涵蓋率被繞過去之後補的，見 GAP_LIMIT_SEC）
- `max_gap_sec` / `gaps_over_limit` / `skipped_share`：最大的空白有多長、超過門檻的
  空白有幾個、有多少比例的素材落在那些空白裡。
- **為什麼涵蓋率不夠**：它只看最遠的那一點，所以「寫幾步開頭、跳到片尾補兩步」就能
  拿到 97.8%——v37 實測就是這樣，中間空了 514 秒、62 行素材有 77% 沒被寫到。
- `backwards`：照文件排列順序讀下來，時間往回跳了幾次。會誤報（章節依主題分、時間
  軸上允許重疊），只在同一份文件的改動前後比較才有意義。

**「這個時間戳是不是真的」**（防虛構）
- `over_length`：超出影片長度的步驟數。2026-08-30 素材改成同時給總秒數之後應該
  恆為 0，這裡當守門員。
- `off_grid`：**對不上任何一行素材的步驟數**。prompt 要求「直接填素材方括號裡的
  秒數」，所以正確答案永遠等於某一行的行首秒數；對不上就代表那個數字不是抄來的，
  是模型自己生的。實測全庫 212 個步驟裡有 22 個對不上，集中在 Intel（8/16）與
  太極（5/20），是有鑑別力的。

  **試過但沒有用的版本**：一開始寫成「時間戳有沒有落在某個片段的
  `[start_sec, end_sec]` 區間內」，量出來全庫恆為 0——場景是從 0 連續鋪到片長的，
  中間沒有任何空隙，所以任何合法秒數都必然落在某個片段裡。要抓的是「有沒有抄」，
  不是「在不在範圍內」。

  注意它**抓不到往前塌**（`[05:10｜310 秒]` 被寫成 `10`）：塌出來的 `10` 剛好也是
  某一行的行首秒數，完全合法。那一類目前只有把步驟內容對回素材才看得出來。

**這些是代理指標，不是真值。** 它們回答「文件寫到多遠、時間戳指不指得到東西」，
**不回答「步驟寫的內容跟那個時間點是不是同一件事」**——實測有步驟時間戳完全合法、
內容卻是另一段的事（`04:34 定子浸入油漆`，真值 `05:10`）。docs/18 §6.2 的教訓是
代理指標擋得住退步、擋不住幻覺，所以 `--samples` 會把尾段步驟連同該時間點的素材
原文印出來，讓人眼去看那一段——腳本只負責把該抽看的地方指出來。

純讀資料庫，不呼叫任何 API、不寫任何表。

用法：
    uv run python scripts/measure_document_coverage.py
    uv run python scripts/measure_document_coverage.py --videos 7,37
    uv run python scripts/measure_document_coverage.py --videos 37 --samples 3
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from ai_video_search_web import db
from ai_video_search_web.db import segments as segments_db
from ai_video_search_web.pipeline import segment_material

EVAL_RUNS_DIR = db.PROJECT_ROOT / "docs" / "eval-runs"

# 「空隙」的門檻：相鄰兩個步驟之間跳過超過這麼多秒，就算漏掉了一段內容。
#
# 60 秒是使用者定的驗收線，不是量出來的最佳值。它的意義很具體：v37 的文件從
# 03:40 直接跳到 09:40，中間 34 行素材全是不同的製程（浸漆、車削、切管、鑽孔、
# 轉子組裝），那不是重複畫面，是真的被漏掉的環節。
GAP_LIMIT_SEC = 60


@dataclass
class CoverageMetrics:
    steps: int
    max_timestamp_sec: float
    material_end_sec: float
    coverage: float | None
    material_coverage: float | None
    second_half: int
    tail_20: int
    over_length: int
    off_grid: int
    uncovered_items: int
    max_gap_sec: float
    gaps_over_limit: int
    skipped_share: float | None
    backwards: int


def steps_of(document: dict) -> list[dict]:
    """把文件攤平成步驟清單。章節結構在這裡沒有意義——所有指標問的都是
    「時間軸上有沒有東西」，而章節是依主題分的，時間軸上本來就會互相重疊。"""
    return [step for section in document.get("sections", []) for step in section.get("steps", [])]


def measure(
    document: dict, segments: list, duration_sec: float | None, gap_limit_sec: int = GAP_LIMIT_SEC
) -> CoverageMetrics:
    """算一份文件的八項指標。

    `document` 是 `VideoDocument` 的 dict（資料庫裡的 `document_json` 解出來的，
    或實驗跑出來的 `model_dump()`）——刻意收 dict 而不是 `VideoDocument`，這樣
    A/B 實驗腳本可以直接餵剛跑完的結果，不用先寫回資料庫。
    """
    steps = steps_of(document)
    stamps = [float(s["timestamp_sec"]) for s in steps]
    peak = max(stamps, default=0.0)

    lines = material_lines(segments)
    material_end = max(lines, default=0)
    gaps = _gaps(stamps, lines)
    skipped = sum(
        1 for sec in lines if any(a < sec < b for a, b in gaps if b - a > gap_limit_sec)
    )

    return CoverageMetrics(
        steps=len(steps),
        max_timestamp_sec=round(peak, 1),
        material_end_sec=float(material_end),
        coverage=round(peak / duration_sec, 4) if duration_sec else None,
        material_coverage=round(peak / material_end, 4) if material_end else None,
        second_half=sum(1 for t in stamps if duration_sec and t > duration_sec / 2),
        tail_20=sum(1 for t in stamps if duration_sec and t > duration_sec * 0.8),
        over_length=sum(1 for t in stamps if duration_sec and t > duration_sec),
        off_grid=sum(1 for t in stamps if int(t) not in lines),
        uncovered_items=len(document.get("uncovered", [])),
        max_gap_sec=round(max((b - a for a, b in gaps), default=0.0), 1),
        gaps_over_limit=sum(1 for a, b in gaps if b - a > gap_limit_sec),
        skipped_share=round(skipped / len(lines), 4) if lines else None,
        backwards=_backwards(steps),
    )


def _backwards(steps: list[dict]) -> int:
    """照文件的排列順序讀下來，時間往回跳了幾次。

    **這個指標會誤報，不能單獨看**：章節是依主題分的，時間軸上允許互相重疊
    （`docs/05` 記過 Intel 那份「自動化生產線 02:09~15:30」與「測試與品檢
    11:45~18:01」），跨章節的回跳是正當的。它有用的地方是**同一份文件改動前後
    比較**——補寫的步驟一度自成一節接在文件末尾，讓時間軸從 615 秒跳回 140 秒，
    就是靠這個數字看出來的。
    """
    times = [float(s["timestamp_sec"]) for s in steps]
    return sum(1 for a, b in zip(times, times[1:]) if b < a)


def _gaps(stamps: list[float], lines: dict[int, str]) -> list[tuple[float, float]]:
    """相鄰步驟之間的空白區間，兩端補上素材的頭與尾。

    頭尾要補：一份從 03:40 才開始寫的文件，前面那三分半也是漏掉的內容，不能因為
    「第一步之前沒有前一步」就不算。邊界用**素材**的頭尾而不是 0 與片長——素材本
    來就到不了片尾，拿片長當邊界會把一個必然存在的差距算成漏寫。
    """
    if not stamps or not lines:
        return []
    edges = [float(min(lines))] + sorted(stamps) + [float(max(lines))]
    return [(a, b) for a, b in zip(edges, edges[1:]) if b > a]


def material_lines(segments: list) -> dict[int, str]:
    """模型實際看到的素材，key 是每一行行首的那個秒數。

    刻意組整支影片的素材再拆行，而不是逐片段呼叫 `build_material()`：幻覺字幕的
    偵測是**影片層級**的統計（見 `segment_material._dominant_share()`），一次只餵
    一個片段會讓那道過濾失效，量出來的素材就不是模型真的看到的那份。
    """
    return segment_material.material_lines(
        segment_material.build_material(segments, include_ocr=True)
    )


def _fetch_documents(video_ids: list[int] | None) -> list[dict]:
    sql = """
        SELECT id, title, duration_sec, document_type, document_json
        FROM videos WHERE document_json IS NOT NULL
    """
    params: list = []
    if video_ids:
        sql += " AND id = ANY(%s)"
        params.append(video_ids)
    sql += " ORDER BY id"
    with db.get_connection() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _pct(value: float | None) -> str:
    return "   —  " if value is None else f"{value:6.1%}"


def _print_samples(document: dict, segments: list, count: int) -> None:
    """印出最後幾個步驟，以及該時間點的素材原文，供人眼確認內容有沒有對上。

    印尾段而不是開頭，是因為「後半段整片空白」正是這支腳本要盯的失效——逼模型
    寫到片尾之後，尾段步驟如果是硬湊出來的，對照素材原文一眼就看得出來。這是
    這支腳本唯一碰得到「內容對不對」的地方，而且要靠人。
    """
    lines = material_lines(segments)
    for step in sorted(steps_of(document), key=lambda s: s["timestamp_sec"])[-count:]:
        stamp = float(step["timestamp_sec"])
        material = lines.get(int(stamp))
        mark = "" if material else "  ⚠ 對不上任何一行素材"
        print(f"       [{segment_material.format_timestamp(stamp)}｜{stamp:.0f}s]{mark}")
        print(f"         文件：{step['heading']}｜{step['detail'][:60]}")
        print(f"         素材：{(material or '（這個秒數沒有對應的素材行）')[:100]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--videos", type=str, default=None, help="只量這幾支，逗號分隔的 video_id")
    parser.add_argument("--samples", type=int, default=0, help="每支印幾個尾段步驟與對應素材供人眼抽看")
    parser.add_argument("--output", type=Path, default=None, help="覆寫預設的 docs/eval-runs/ 輸出路徑")
    parser.add_argument("--no-write", action="store_true", help="只印出，不寫檔")
    args = parser.parse_args()

    video_ids = [int(x) for x in args.videos.split(",")] if args.videos else None
    rows = _fetch_documents(video_ids)
    if not rows:
        print("沒有任何已整理成文件的影片——確認文件已經產生，或 --videos 給對了嗎？")
        return

    print(f"{'id':>4} {'標題':<24}{'類型':<14}{'步驟':>5}{'步/段':>7}{'對素材':>8}"
          f"{'最大空隙':>9}{'>60s':>6}{'漏掉':>7}{'倒退':>5}{'脫格':>5}{'uncov':>6}")
    per_video = {}
    for row in rows:
        document = json.loads(row["document_json"])
        segments = segments_db.list_segments_for_video(row["id"])
        metrics = measure(document, segments, row["duration_sec"])
        per_video[row["id"]] = {"title": row["title"], "doc_type": row["document_type"], **asdict(metrics)}

        # 警示線兩條：涵蓋率（對素材）90%、以及沒有超過門檻的空隙。前者是
        # 2026-09-01 那輪的驗收線，後者是同一天稍晚訂的——一份寫到片尾但中間
        # 空了六分鐘的文件，涵蓋率漂亮，內容照樣是漏的。
        lines = len(material_lines(segments))
        flag = " " if metrics.gaps_over_limit == 0 and (metrics.material_coverage or 0) >= 0.9 else "<"
        print(f"{row['id']:>4} {row['title'][:22]:<24}{str(row['document_type']):<14}"
              f"{metrics.steps:>5}{metrics.steps / lines if lines else 0:>7.2f}"
              f"{_pct(metrics.material_coverage):>8}{metrics.max_gap_sec:>9.0f}"
              f"{metrics.gaps_over_limit:>6}{_pct(metrics.skipped_share):>7}"
              f"{metrics.backwards:>5}{metrics.off_grid:>5}{metrics.uncovered_items:>6} {flag}")

        if args.samples:
            _print_samples(document, segments, args.samples)

    passing = sum(1 for m in per_video.values() if (m["material_coverage"] or 0) >= 0.9)
    no_holes = sum(1 for m in per_video.values() if m["gaps_over_limit"] == 0)
    print(f"\n涵蓋率（對素材）達 90% 的：{passing}/{len(per_video)} 支")
    print(f"沒有超過 {GAP_LIMIT_SEC} 秒空隙的：{no_holes}/{len(per_video)} 支")
    print(f"時間戳超出片長的步驟總數：{sum(m['over_length'] for m in per_video.values())}")
    print(f"對不上任何一行素材的步驟總數：{sum(m['off_grid'] for m in per_video.values())}"
          f"／{sum(m['steps'] for m in per_video.values())}")
    print("\n注意：以上都是代理指標，不保證「步驟內容跟那個時間點是同一件事」，"
          "那一項只有人眼看得出來（用 --samples）。")

    if args.no_write:
        return
    EVAL_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    # 檔名加 doccov- 前綴，跟同資料夾的搜尋評測（無前綴）與描述品質（desc-）分開。
    path = args.output or EVAL_RUNS_DIR / f"doccov-{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(
        json.dumps(
            {
                "measured_at": datetime.now().isoformat(timespec="seconds"),
                "video_filter": video_ids,
                "by_video": per_video,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    # 相對路徑：`--output` 可以指到專案外面，`Path.relative_to()` 對那種情況會丟錯，
    # 而這只是一行提示訊息，不值得讓整支腳本在寫完檔之後才失敗。
    print(f"已寫入 {os.path.relpath(path.resolve(), db.PROJECT_ROOT)}")


if __name__ == "__main__":
    main()

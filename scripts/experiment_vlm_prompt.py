"""單變數實驗台：對同一組畫面同時跑多個 VLM prompt，比較描述品質。

**怎麼用**：把要比的 prompt 填進 `ARMS`，跑起來。每個片段只抽一次畫面，同一組
base64 圖片餵給每個 arm，唯一的變數就是那段文字。

**為什麼不能拿資料庫既有描述當對照組**：同一個 prompt 跑兩次，模型輸出本來就
不一樣。實測同一個 prompt 重跑三次，籠統率範圍 5pt、具體動作 7.6pt、元描述
11.3pt——**任何小於這個幅度的差異都是雜訊**。所以對照組必須跟候選在同一輪執行。

**唯讀**：不寫任何資料庫欄位。這是這個專案做 prompt 實驗的既有模式（見
docs/01-development-timeline.md 追查時間戳那三次單變數實驗）。

**指標是代理指標，擋得住退步、擋不住幻覺**。這一點是實測撞出來的：候選 B 的三個
指標全面勝出，人眼一看才發現它在沒有真人的影片上 10/10 段編出「作業員」。所以
`PERSON_WORDS` 那個診斷欄要搭配「這支影片畫面裡到底有沒有人」一起讀，而且每輪
實驗都要真的把描述印出來看。

**已跑完的兩輪（2026-08-31）**，完整數據見 vlm.py 兩個 prompt 常數上方的註解，
原始輸出在 docs/eval-runs/desc-exp-*.json：
- 多幀（v32＋v34，80 段）：候選 C 勝出 → `vlm._MULTI_FRAME_PROMPT_TEMPLATE`。
- 單幀（v28＋v33＋v32，90 段）：候選 S2 勝出 → `vlm._PROMPT`。

用法：
    uv run python scripts/experiment_vlm_prompt.py --mode multi  --videos 32,34 --dry-run
    uv run python scripts/experiment_vlm_prompt.py --mode single --videos 28,33,32 --limit 40
"""
from __future__ import annotations

import argparse
import base64
import json
from datetime import datetime
from pathlib import Path

import measure_description_quality as mdq  # 同一個 scripts/ 目錄，共用詞表與指標

from ai_video_search_web import db
from ai_video_search_web.pipeline import analyzer, frames, vlm
from ai_video_search_web.pipeline.openai_client import chat_completion_cost, get_client

EVAL_RUNS_DIR = db.PROJECT_ROOT / "docs" / "eval-runs"

# 候選 A：只移除「點出變化」，不給替代任務。長度要求仍是「一到兩句話」。
#
# **實測失敗（2026-08-31，80 段）**：元描述確實清掉了（68.8% → 3.8%），但描述整體
# 退步——長度 61.5 → 45.3 字、籠統 73.8% → 90.0%、具體動作 23.8% → 8.8%。原因是
# 「點出變化」雖然把輸出導去講差異，但它至少逼模型去看細節（角度、顏色、哪個部件）；
# 單純拿掉而不給替代任務，模型就直接縮短輸出。保留這個 arm 當對照組，證明
# 「移除舊指令」與「給新指令」必須一起做。
CANDIDATE_A_MULTI_FRAME_PROMPT = (
    "以下 {n} 張畫面是同一個約 {duration:.1f} 秒片段的連續取樣，依時間順序排列。"
    "這幾張是同一段過程的前後時刻，不是要你比較的幾張圖——請把它們合起來看，回答兩件事："
    "1. description：一到兩句話描述這段時間裡發生了什麼事（不要加開頭語）。"
    "**不要描述畫面之間的差異**：不要寫「第一張」「第二張」「畫面逐漸變化」「略有不同」"
    "這類句子，讀者看不到這些畫面，只想知道發生了什麼。如果這幾張其實是同一個靜止狀態，"
    "就直接描述那個狀態，不要硬說有變化。"
    "2. on_screen_text：畫面上實際出現的文字逐字列出（涵蓋所有畫面出現過的文字，"
    "不要重複列同一段文字），維持原本語言，不要翻譯；如果所有畫面都沒有任何文字，"
    "這欄位填 null，不要自己編造。"
)

# 候選 B：移除「點出變化」**並且**給替代任務——講出「誰、對什麼、做了什麼」，
# 動詞要具體到能重現，物件要指名。長度放寬到三句，因為候選 A 證明了單純收緊會讓
# 模型直接縮短輸出。這是 P1 與 P2 合併後的版本。
CANDIDATE_B_MULTI_FRAME_PROMPT = (
    "以下 {n} 張畫面是同一個約 {duration:.1f} 秒片段的連續取樣，依時間順序排列。"
    "這幾張是同一段過程的前後時刻，不是要你比較的幾張圖——請把它們合起來看，回答兩件事："
    "1. description：一到三句話講出這段時間裡「誰、對什麼東西、做了什麼」（不要加開頭語）。"
    "動詞要具體到讀者能照著重現：要寫「作業員雙手抱起紙箱放上輸送帶」，"
    "不要寫「人在產線工作」「進行作業」「操作設備」這種看不出實際在做什麼的句子。"
    "看得到的物件要指名（紙箱、螺絲、扳手、料架、電路板），不要只說「零件」「設備」「物件」。"
    "**不要描述畫面之間的差異**：不要寫「第一張」「第二張」「畫面逐漸變化」「略有不同」"
    "這類句子，讀者看不到這些畫面。如果這幾張其實是同一個靜止狀態，就描述那個狀態裡"
    "看得到的東西與正在發生的動作。"
    "2. on_screen_text：畫面上實際出現的文字逐字列出（涵蓋所有畫面出現過的文字，"
    "不要重複列同一段文字），維持原本語言，不要翻譯；如果所有畫面都沒有任何文字，"
    "這欄位填 null，不要自己編造。"
)


# 候選 C：候選 B **加上「只寫看得到的東西」護欄**。
#
# **候選 B 為什麼需要修**（實測 2026-08-31，80 段）：B 的三個指標全面勝過現行版
# （籠統 78.8%→65.0%、具體動作 18.8%→36.2%、幀間比較 62.5%→12.5%），但人眼抽看
# 發現那是靠幻覺換來的——v32 是一支沒有任何真人的 3D 動畫組裝 SOP，B 卻在
# **10/10 段**都寫出「作業員」「技術人員」，還編出「用手擰緊固定螺絲」。
#
# 根因是句型：「講出誰、對什麼東西、做了什麼」預設了畫面裡有一個施動者，沒人的
# 時候模型就發明一個。護欄照 pipeline/document.py 既有的寫法——先講「只寫看得到
# 的」「寧可少寫不要補完」，再講「有人的時候要多具體」。
CANDIDATE_C_MULTI_FRAME_PROMPT = (
    "以下 {n} 張畫面是同一個約 {duration:.1f} 秒片段的連續取樣，依時間順序排列。"
    "這幾張是同一段過程的前後時刻，不是要你比較的幾張圖——請把它們合起來看，回答兩件事："
    "1. description：一到三句話講出這段時間裡發生了什麼（不要加開頭語）。"
    "**只寫畫面上真的看得到的東西**：畫面裡沒有人就不要寫人；看到的是 3D 模型、"
    "示意圖或動畫，就照實說那是模型或示意圖，不要腦補出操作它的人；看不出來的動作"
    "就不要寫，寧可少寫也不要補完。"
    "畫面上真的有人在動作時，動詞要具體到讀者能照著重現：要寫「作業員雙手抱起紙箱"
    "放上輸送帶」，不要寫「人在產線工作」「進行作業」「操作設備」這種看不出實際在"
    "做什麼的句子。看得到的物件要指名（紙箱、螺絲、扳手、料架、電路板），不要只說"
    "「零件」「設備」「物件」。"
    "**不要描述畫面之間的差異**：不要寫「第一張」「第二張」「畫面逐漸變化」「略有不同」"
    "這類句子，讀者看不到這些畫面。"
    "2. on_screen_text：畫面上實際出現的文字逐字列出（涵蓋所有畫面出現過的文字，"
    "不要重複列同一段文字），維持原本語言，不要翻譯；如果所有畫面都沒有任何文字，"
    "這欄位填 null，不要自己編造。"
)

# ── 單幀 prompt 的候選（`vlm._PROMPT`）────────────────────────────────────
#
# 單幀跟多幀的差別不只是張數：**一張靜止畫面在物理上看不出動作的方向**。一個人
# 彎腰、雙手扶在紙箱兩側，可能是搬起、放下、或只是扶著。多幀那套「動詞要具體到
# 能重現」直接套過來，可能反而逼模型猜——而候選 B 已經證明這個模型被逼就會編。
# 所以這一輪比的是兩種設計，不是一種。

# 候選 S1：把多幀那套（具體動詞要求＋幻覺護欄）原封不動移植過來。
CANDIDATE_S1_PROMPT = (
    "請分析這張畫面，用繁體中文回答兩件事："
    "1. description：一到三句話講出畫面裡發生了什麼（不要加開頭語）。"
    "**只寫畫面上真的看得到的東西**：畫面裡沒有人就不要寫人；看到的是 3D 模型、"
    "示意圖或動畫，就照實說那是模型或示意圖，不要腦補出操作它的人；看不出來的動作"
    "就不要寫，寧可少寫也不要補完。"
    "畫面上真的有人在動作時，動詞要具體到讀者能照著重現：要寫「作業員雙手抱起紙箱"
    "放上輸送帶」，不要寫「人在產線工作」「進行作業」「操作設備」這種看不出實際在"
    "做什麼的句子。看得到的物件要指名（紙箱、螺絲、扳手、料架、電路板），不要只說"
    "「零件」「設備」「物件」。"
    "2. on_screen_text：畫面上實際出現的文字逐字列出（字幕、標題、標語、招牌、螢幕顯示文字等），"
    "維持原本語言，不要翻譯；如果畫面上沒有任何文字，這欄位填 null，不要自己編造。"
)

# 候選 S2：**承認單幀看不出動作方向**，改要求描述「看得到的姿勢與接觸關係」，
# 明講不要猜意圖。物件指名的要求跟 S1 一樣，差別只在動作那一段。
CANDIDATE_S2_PROMPT = (
    "請分析這張畫面，用繁體中文回答兩件事："
    "1. description：一到三句話講出畫面裡看得到什麼（不要加開頭語）。"
    "**這是一張靜止畫面，你看不到動作的前後**，所以描述姿勢與接觸關係，不要猜動作的意圖："
    "要寫「作業員彎腰、雙手扶在紙箱兩側，紙箱放在輸送帶邊緣」，不要寫「作業員正在搬起"
    "紙箱」——你分不出他是搬起還是放下。"
    "**只寫真的看得到的東西**：畫面裡沒有人就不要寫人；看到的是 3D 模型、示意圖或動畫，"
    "就照實說那是模型或示意圖；看不出來的就不要寫，寧可少寫也不要補完。"
    "看得到的物件要指名（紙箱、螺絲、扳手、料架、電路板），不要只說「零件」「設備」"
    "「物件」，也不要寫「進行作業」「操作設備」這種看不出實際狀況的句子。"
    "2. on_screen_text：畫面上實際出現的文字逐字列出（字幕、標題、標語、招牌、螢幕顯示文字等），"
    "維持原本語言，不要翻譯；如果畫面上沒有任何文字，這欄位填 null，不要自己編造。"
)

# 「提到人物」偵測詞：不是品質指標，是**幻覺診斷欄**。對已知畫面裡沒有真人的影片
# （例如 v32 這支 3D 動畫 SOP），這一欄的正確值是 0%，任何非零都是編造。
PERSON_WORDS = (
    "作業員", "技術人員", "工人", "操作員", "員工", "工程師", "師傅",
    "男子", "女子", "一名", "一位", "人員",
)

# 「姿勢／接觸」偵測詞：候選 S2 刻意避開動作動詞，`CONCRETE_ACTION_WORDS` 會低估
# 它。兩欄要一起讀——S1 應該在動作那欄高，S2 應該在這欄高，兩欄都低才是真的沒講
# 出東西。
POSTURE_WORDS = (
    "彎腰", "蹲", "站", "坐", "伸手", "扶", "握", "抓", "靠", "面向", "背對",
    "低頭", "抬頭", "雙手", "單手", "手持", "手指", "手臂", "膝", "肩",
)

# 這一輪要跑的 arm，依 --mode 選一組。**下一個實驗就是改這裡**——把候選 prompt
# 加進來，跑完看指標與人眼抽看，勝出的才寫進 vlm.py。
#
# multi 現在只留 `current`：候選 C 已經採用、就是 vlm 模組裡的那一版，所以跑它等於
# 重新量一次正式 prompt（換模型或改別的參數之後想確認有沒有退步時有用）。上面的
# CANDIDATE_A／B 常數保留成歷史紀錄，證明「移除舊指令」「補新指令」「加幻覺護欄」
# 三步缺一不可，不要之後又把其中一步當成多餘的拿掉。
ARMS_BY_MODE = {
    "multi": {
        "current": lambda: vlm._MULTI_FRAME_PROMPT_TEMPLATE,
    },
    # single 同樣只留 current：候選 S2 已經採用、就是 vlm._PROMPT。S1 保留成常數
    # 是為了記住「直接把多幀那套搬過來沒有用」這個結果。
    "single": {
        "current": lambda: vlm._PROMPT,
    },
}
ARM_LABELS = {
    "current": "現行", "candidate_a": "候選A", "candidate_b": "候選B", "candidate_c": "候選C",
    "candidate_s1": "候選S1", "candidate_s2": "候選S2",
}


def _image_blocks(video_path: Path, start_sec: float, end_sec: float, fractions: tuple[float, ...]) -> list[dict]:
    """抽一次畫面、編碼一次，兩個 arm 共用。參數與 vlm.describe_segment() 一致
    （`detail: "low"`），確保實驗跟正式流程餵給模型的圖片完全相同。"""
    duration = end_sec - start_sec
    blocks = []
    for fraction in fractions:
        frame_path = frames.extract_frame(video_path, start_sec + fraction * duration)
        try:
            b64 = base64.b64encode(frame_path.read_bytes()).decode("ascii")
        finally:
            frame_path.unlink(missing_ok=True)
        blocks.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"}})
    return blocks


def _describe(client, image_blocks: list[dict], prompt: str) -> tuple[str, float]:
    """照 vlm.describe_segment() 的呼叫方式送出，只是 prompt 由外面指定。"""
    response = client.chat.completions.parse(
        model=vlm.MODEL_NAME,
        messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, *image_blocks]}],
        response_format=vlm._SceneAnalysis,
        max_completion_tokens=300,
    )
    parsed = response.choices[0].message.parsed
    description = (parsed.description if parsed else "").strip()
    cost = chat_completion_cost(response.usage, vlm.PRICE_INPUT_PER_TOKEN_USD, vlm.PRICE_OUTPUT_PER_TOKEN_USD)
    return description, cost


def _load_segments(video_ids: list[int], mode: str) -> list[dict]:
    """multi 模式只挑多幀片段（單幀片段跑了也不會有差別）；single 模式全部都要。

    **single 模式刻意不管片段原本是幾幀**：這裡要比的是單幀 prompt，抽幀方式由
    實驗這邊決定（一律取中點一張），所以任何片段都可以當素材。這讓 v32 那支
    3D 動畫也能進來當幻覺對照組——它在正式流程裡全都是多幀片段。
    """
    where = "s.video_id = ANY(%s)" + (" AND s.vlm_frame_count >= 2" if mode == "multi" else "")
    with db.get_connection() as conn:
        return [
            dict(r)
            for r in conn.execute(
                f"""
                SELECT s.video_id, s.start_sec, s.end_sec, s.visual_description, v.title, v.file_path
                FROM segments s JOIN videos v ON v.id = s.video_id
                WHERE {where} AND s.visual_description IS NOT NULL AND s.visual_description <> ''
                ORDER BY s.video_id, s.start_sec
                """,
                [video_ids],
            ).fetchall()
        ]


def _summarise(label: str, descriptions: list[str]) -> dict:
    m = mdq._rates(descriptions)
    if descriptions:
        n = len(descriptions)
        m["person_rate"] = round(sum(any(w in d for w in PERSON_WORDS) for d in descriptions) / n, 4)
        m["posture_rate"] = round(sum(any(w in d for w in POSTURE_WORDS) for d in descriptions) / n, 4)
    print(f"  {label:<12} n={m['n']:<4} 長度 {m['avg_length']:>5}  籠統 {m['vague_rate']:6.1%}"
          f"  具體動作 {m['concrete_rate']:6.1%}  姿勢接觸 {m.get('posture_rate', 0):6.1%}"
          f"  幀間比較 {m['meta_rate']:6.1%}  提到人物 {m.get('person_rate', 0):6.1%}")
    return m


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("single", "multi"), default="multi", help="要比單幀還是多幀 prompt")
    parser.add_argument("--videos", type=str, default="32,34", help="逗號分隔的 video_id")
    parser.add_argument("--limit", type=int, default=0, help="每支影片最多跑幾段（0＝全部）")
    parser.add_argument("--dry-run", action="store_true", help="不呼叫 API，只列出會跑幾段與估價")
    parser.add_argument("--samples", type=int, default=6, help="印幾組新舊描述對照")
    args = parser.parse_args()

    arms = {name: build() for name, build in ARMS_BY_MODE[args.mode].items()}
    fractions = vlm.DEFAULT_FRAME_FRACTIONS if args.mode == "single" else analyzer.MULTI_FRAME_FRACTIONS

    video_ids = [int(x) for x in args.videos.split(",")]
    segments = _load_segments(video_ids, args.mode)
    if args.limit:
        kept: dict[int, int] = {}
        picked = []
        for s in segments:
            if kept.get(s["video_id"], 0) < args.limit:
                picked.append(s)
                kept[s["video_id"]] = kept.get(s["video_id"], 0) + 1
        segments = picked

    if not segments:
        print("這幾支影片沒有可用的片段，沒有東西可以比。")
        return

    calls = len(segments) * len(arms)
    # 依既有實測：單幀呼叫的 prompt tokens 約 2,960，多幀約 1.9 倍。
    unit = 0.0005 if args.mode == "single" else 0.0009
    print(f"{args.mode} 模式：{len(segments)} 段 × {len(arms)} 個 arm"
          f"（{'／'.join(ARM_LABELS[a] for a in arms)}）＝ {calls} 次 VLM 呼叫")
    print(f"預估花費：約 US${calls * unit:.3f}（粗估，實際以回報為準）")
    if args.dry_run:
        for vid in sorted({s["video_id"] for s in segments}):
            group = [s for s in segments if s["video_id"] == vid]
            print(f"  v{vid:<3} {group[0]['title'][:34]:<36} {len(group)} 段")
        return

    client = get_client()
    rows, total_cost = [], 0.0
    for i, seg in enumerate(segments, 1):
        video_path = Path(seg["file_path"])
        if not video_path.exists():
            print(f"  ! 跳過 v{seg['video_id']} [{seg['start_sec']:.0f}s]：找不到影片檔 {video_path}")
            continue
        blocks = _image_blocks(video_path, seg["start_sec"], seg["end_sec"], fractions)
        fmt = {"n": len(blocks), "duration": seg["end_sec"] - seg["start_sec"]}
        row = {"video_id": seg["video_id"], "start_sec": seg["start_sec"], "stored": seg["visual_description"]}
        for arm, template in arms.items():
            row[arm], cost = _describe(client, blocks, template.format(**fmt))
            total_cost += cost
        rows.append(row)
        print(f"  [{i}/{len(segments)}] v{seg['video_id']} {seg['start_sec']:6.0f}s  ${total_cost:.4f}")

    print(f"\n=== 指標對照（同一組畫面、同一輪執行，唯一變數是 prompt）===")
    metrics = {"stored": _summarise("資料庫既有", [r["stored"] for r in rows if r["stored"]])}
    for arm in arms:
        metrics[arm] = _summarise(ARM_LABELS[arm], [r[arm] for r in rows])

    # 逐支分解是必要的，不是附加資訊：「提到人物」這一欄只有對照「這支影片畫面裡
    # 到底有沒有人」才讀得出意義，混在一起看不出幻覺。
    per_video: dict = {}
    for vid in sorted({r["video_id"] for r in rows}):
        vid_rows = [r for r in rows if r["video_id"] == vid]
        print(f"\n  ── v{vid}（n={len(vid_rows)}）──")
        per_video[str(vid)] = {
            "stored": _summarise("　資料庫既有", [r["stored"] for r in vid_rows if r["stored"]]),
            **{arm: _summarise("　" + ARM_LABELS[arm], [r[arm] for r in vid_rows]) for arm in arms},
        }
    print(f"\n=== 逐段對照（前 {args.samples} 組）===")
    for r in rows[: args.samples]:
        print(f"\n  v{r['video_id']} [{r['start_sec']:.0f}s]")
        for arm in arms:
            print(f"    {ARM_LABELS[arm]}：{r[arm]}")

    EVAL_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = EVAL_RUNS_DIR / f"desc-exp-{args.mode}-{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps({
        "measured_at": datetime.now().isoformat(timespec="seconds"),
        "video_ids": video_ids,
        "segment_count": len(rows),
        "cost_usd": round(total_cost, 5),
        "mode": args.mode,
        "prompts": dict(arms),
        "metrics": metrics,
        "by_video": per_video,
        "rows": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n實際花費 US${total_cost:.4f}｜已寫入 {path.relative_to(db.PROJECT_ROOT)}")


if __name__ == "__main__":
    main()

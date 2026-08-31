"""VLM：畫面描述。V0 只接 OpenAI GPT-4o-mini，對外只暴露 provider 無關的介面，
之後要加其他供應商，在這個模組內部加實作分支即可，不用動呼叫端。
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI
from pydantic import BaseModel

from . import frames
from .openai_client import chat_completion_cost

MODEL_NAME = "gpt-4o-mini"
PRICE_INPUT_PER_TOKEN_USD = 0.15 / 1_000_000
PRICE_OUTPUT_PER_TOKEN_USD = 0.60 / 1_000_000

# 預設只取片段中點一張畫面。場景偵測器完全沒抓到切點、被 scene_detect.py
# 的 _split_long_scenes() 機械式均分出來的場景（source_raw_duration 明顯
# 超過自己的長度），中點單幀常常漏看場景內其實塞了好幾段不同內容（見
# docs/02-technical-decisions.md「VLM 條件式多幀取樣」的 gs-002 案例）；
# pipeline/analyzer.py 的 Phase B 會依 source_raw_duration 決定要不要改傳
# MULTI_FRAME_FRACTIONS 觸發多幀。
DEFAULT_FRAME_FRACTIONS = (0.5,)

# 單幀版 prompt。**「描述姿勢與接觸關係、不要猜動作意圖」這個框架是實測選出來的**
# （2026-08-31，v28 Intel／v33 PCB 工廠／v32 3D 動畫共 90 段，見
# scripts/experiment_vlm_prompt.py --mode single）：
#
# 單幀跟多幀的差別不只是張數——**一張靜止畫面在物理上看不出動作的方向**。一個人
# 彎腰、雙手扶在紙箱兩側，可能是搬起、放下、或只是扶著。所以比了兩種設計：
#
# | arm | 具體動作 | 姿勢接觸 |
# |---|---|---|
# | 舊版（「越具體越好」） | 4.4% | 14.4% |
# | 候選 S1：直接移植多幀那套「動詞要具體到能重現」 | 6.7% | 17.8% |
# | 候選 S2（就是這版）：改問姿勢與接觸關係 | **11.1%** | **25.6%** |
#
# **S1 幾乎沒有效果**，只是把描述寫長；逼模型對單張靜止畫面講出動作動詞，它給不出
# 比原本多的東西。S2 在 v28 那支的姿勢接觸率是 22.5% → 45.0%。
#
# 注意 S2 對「具體動作」的 +6.7pt **落在雜訊範圍內**（同一個 prompt 重跑的變異是
# ±7.6pt），真正站得住的是 S1 與 S2 之間的差距——兩者同輪執行、都是新 prompt，
# 差別只在動作那一段的框架。
#
# 幻覺護欄（「沒有人就不要寫人」「看到 3D 模型就說是模型」「寧可少寫不要補完」）
# 跟多幀版是同一套，理由見 _MULTI_FRAME_PROMPT_TEMPLATE 上方候選 B 的教訓。三個
# arm 在 v32（純 3D 動畫、畫面裡沒有真人）的人物提及率都是 0%，護欄有效。
#
# **已知副作用**：描述平均長度 52.2 → 74.8 字（+43%）。`segments.content` 是
# generated column、BM25 會做文件長度正規化，所以重新分析過的影片在搜尋端的
# 分數分佈會跟舊影片不同，見 docs/05-known-limitations-and-open-items.md。
_PROMPT = (
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

# 多幀版 prompt：{n}/{duration} 由 describe_segment() 依實際幀數／片段長度
# 填入。跟單幀版分開維護，不是共用同一句話中間插值——單幀版沒有「依時間
# 順序」「綜合所有畫面」這些多幀才需要的措辭，硬共用反而會讓單幀情境的
# prompt 多出不必要的文字。
#
# **三段措辭都是實測換來的**（2026-08-31，v32＋v34 共 80 個多幀片段，同一組畫面
# 同一輪執行跑多個 prompt arm，見 scripts/experiment_vlm_prompt.py）：
#
# 1. **「不要描述畫面之間的差異」取代原本的「簡短點出變化」**。舊措辭把輸出預算
#    導去比較兩張圖：多幀片段 61.0% 的描述含「第一／第二／逐漸／略有變化」，單幀
#    只有 0.6%。一支叫「組裝 SOP」的影片（v32）10 段描述全是「部件位置略有變化」，
#    沒有一句講出裝了什麼。
# 2. **但光拿掉舊指令會退步**，必須同時給替代任務。只移除不補的版本（實驗的候選 A）
#    元描述確實清掉了（→3.8%），描述卻縮短 26%、籠統率反升到 90%、具體動作腰斬——
#    「點出變化」雖然導錯方向，至少逼模型去看細節。
# 3. **「只寫真的看得到的東西」這道護欄不能省**。只加具體動詞要求、沒加護欄的版本
#    （候選 B）指標全面變好，但那是幻覺換來的：v32 是純 3D 動畫、畫面裡沒有任何
#    真人，B 卻在 **10/10 段**寫出「作業員」「技術人員」，還編出「用手擰緊固定
#    螺絲」。加上護欄後（就是現在這版）v32 的人物提及率回到 0%，v34（真的有人）
#    的具體動作率仍從 14.3% 拉到 35.7%、元描述從 52.9% 降到 4.3%。
#
# 雜訊校準：同一個 prompt 重跑三次，籠統率範圍 5pt、具體動作 7.6pt、元描述 11.3pt。
# 上面引用的改善幅度都明顯超過這個範圍。
_MULTI_FRAME_PROMPT_TEMPLATE = (
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


class _SceneAnalysis(BaseModel):
    description: str
    on_screen_text: str | None


@dataclass
class DescribeResult:
    description: str
    ocr_text: str | None
    cost_usd: float
    frame_count: int


def describe_segment(
    client: OpenAI,
    video_path: Path,
    start_sec: float,
    end_sec: float,
    frame_fractions: tuple[float, ...] = DEFAULT_FRAME_FRACTIONS,
) -> DescribeResult:
    """取片段內 `frame_fractions`（相對於片段起訖的比例，例如 0.5 是中點）
    指定的時間點各抽一張畫面，同一次 VLM 呼叫取得畫面描述與畫面上的文字
    （OCR）。預設只取中點一張（`DEFAULT_FRAME_FRACTIONS`），呼叫端要觸發
    多幀時傳入例如 `(0.3, 0.7)`。
    """
    duration = end_sec - start_sec
    timestamps = [start_sec + fraction * duration for fraction in frame_fractions]

    image_blocks = []
    for at_sec in timestamps:
        frame_path = frames.extract_frame(video_path, at_sec)
        try:
            image_b64 = base64.b64encode(frame_path.read_bytes()).decode("ascii")
        finally:
            frame_path.unlink(missing_ok=True)
        image_blocks.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}", "detail": "low"},
        })

    prompt = _PROMPT if len(frame_fractions) == 1 else _MULTI_FRAME_PROMPT_TEMPLATE.format(
        n=len(frame_fractions), duration=duration,
    )

    response = client.chat.completions.parse(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, *image_blocks]}],
        response_format=_SceneAnalysis,
        max_completion_tokens=300,
    )
    parsed = response.choices[0].message.parsed
    description = (parsed.description if parsed else "").strip()
    ocr_text = parsed.on_screen_text.strip() if parsed and parsed.on_screen_text else None

    cost_usd = chat_completion_cost(response.usage, PRICE_INPUT_PER_TOKEN_USD, PRICE_OUTPUT_PER_TOKEN_USD)
    return DescribeResult(
        description=description, ocr_text=ocr_text, cost_usd=cost_usd, frame_count=len(frame_fractions),
    )

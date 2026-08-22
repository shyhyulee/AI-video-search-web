# AI 影片搜尋（AI Video Search POC II）

本機執行的 Tkinter 桌面應用：下載或匯入影片後自動分析（場景切分、語音辨識、畫面描述、畫面文字辨識），讓使用者用自然語言描述（人物、動作、物件、教學內容）搜尋影片中的關鍵時刻，取代人工逐格瀏覽。

## 功能

- **影片與分析**：貼上 YouTube 網址下載，或選擇本機影片檔案，加入待分析清單後一鍵開始分析。
- **影片庫**：已分析影片列表（可依名稱／片段數／成本／日期排序與篩選）、自動摘要、縮圖、詳細資訊、快速跳轉搜尋。
- **搜尋結果**：自然語言查詢、結果列表（時間範圍／相似度／融合分數／命中來源）、詳細分數面板、片段播放、CSV 匯出。
- **處理紀錄**：即時 log 顯示，可依等級篩選、複製錯誤內容、匯出。

## 系統需求

- Python ≥ 3.11（開發環境固定用系統 Python 3.14，見 `.python-version`；**不要用 `uv` 自動下載的 standalone Python**——它在部分環境〔例如 WSL2 + WSLg〕的 Tk 找不到 CJK 字型，中文會顯示空白，`pyproject.toml` 已設定 `python-preference = "only-system"` 避免這個問題）。
- [uv](https://docs.astral.sh/uv/)
- 系統套件：`ffmpeg`（含 `ffplay`，播放片段用）、`node`（YouTube 下載解簽章挑戰用）
- OpenAI API 金鑰（分析與搜尋都需要呼叫 Whisper／GPT-4o-mini／text-embedding-3-small）

## 安裝

```bash
uv sync
```

## 設定

在專案根目錄建立 `.env`（已加入 `.gitignore`，不會進版控）：

```
OPENAI_API_KEY=sk-...
```

## 執行

```bash
uv run ai-video-search-web
```

第一次執行會自動在專案根目錄建立 `app.db`（SQLite 資料庫）與 `video/`（下載的影片檔案），兩者都已加入 `.gitignore`。

## 測試

```bash
uv run pytest                  # 一般測試，純邏輯／mock，不呼叫真實 API
uv run pytest -m integration   # 整合測試，呼叫真實 OpenAI API，有極小額費用
```

## Golden Set 評測

用固定的 17 題查詢集量化搜尋品質（Recall@K／MRR／nDCG@K／Timestamp IoU／No-answer F1）：

```bash
uv run python scripts/run_golden_set_eval.py
```

會呼叫真實 OpenAI API（費用是分毫等級），並把結果存成 `docs/eval-runs/<timestamp>.json`。

## 專案結構

```text
src/ai_video_search_web/
  app.py           # 主視窗組裝：Header + 四個頁籤
  db/              # SQLite 存取層（videos／segments／ocr_events／search_log）
  downloader.py    # YouTube 下載（yt-dlp）
  theme.py         # 全域顏色／間距／字型／ttk.Style
  pipeline/        # 分析與搜尋 pipeline（以下列主要模組，其餘見原始碼）
    analyzer.py        #   orchestrator：串起場景切分→ASR→VLM→embedding→索引
    scene_detect.py     #   場景切分（PySceneDetect）
    asr.py               #   語音轉文字（Whisper）＋幻覺字幕過濾
    vlm.py                #   畫面描述＋畫面文字（GPT-4o-mini）
    ocr_service.py        #   本地 OCR 掃描（EasyOCR，補 VLM 漏掉的文字）
    embedding.py           #   文字向量化
    search.py               #   Hybrid（Dense+BM25）+ RRF 融合搜尋
    evaluation.py            #   Golden Set 評分
  ui/              # Tkinter 頁籤（video_tab／library_tab／search_tab／logs_tab）
tests/             # pytest 測試（單元測試 + integration marker）
scripts/           # 手動執行的工具腳本（Golden Set 評測）
docs/              # 開發文件、規劃記錄與 Golden Set
  organize-docs/   #   整理過的專案總覽，建議從這裡開始讀
```

## 成本與限制

- 每支影片分析花費硬上限 **US$0.20**，只分析 **20 分鐘以內**的影片（超過會在 UI 層擋下，不會嘗試分析後才中止）。
- 目前只接 OpenAI（Whisper／GPT-4o-mini／`text-embedding-3-small`），供應商邏輯以介面隔離，之後可擴充其他供應商。
- 搜尋每次呼叫都會記錄花費，但目前沒有上限或警示機制。

## 深入文件

專案的完整背景、架構、開發歷程與技術決策整理在 [`docs/organize-docs/`](docs/organize-docs/00-overview.md)：

- [`00-overview.md`](docs/organize-docs/00-overview.md) — 專案背景需求、系統現況、資料流（建議從這裡開始）
- [`01-development-timeline.md`](docs/organize-docs/01-development-timeline.md) — 依日期彙整的開發歷程
- [`02-technical-decisions.md`](docs/organize-docs/02-technical-decisions.md) — 技術決策的背景、比較與實測數據
- [`03-excluded-approaches.md`](docs/organize-docs/03-excluded-approaches.md) — 已嘗試但放棄的方案
- [`04-testing-and-evaluation.md`](docs/organize-docs/04-testing-and-evaluation.md) — 測試套件、Golden Set、評測 baseline
- [`05-known-limitations-and-open-items.md`](docs/organize-docs/05-known-limitations-and-open-items.md) — 已知限制、待辦、待確認事項

`docs/` 底下其餘檔案是各功能主題的原始規劃文件與逐日開發紀錄，仍會持續被程式碼註解引用，保留原樣不動。

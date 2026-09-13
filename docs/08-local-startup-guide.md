# 本機啟動指南

> **類型**：現況參考｜**狀態**：維護中，跟著程式碼更新
> 分類說明與完整索引見 [`README.md`](README.md)。

## 1. 文件目的

記錄「從開機到能在瀏覽器操作」的完整啟動順序、驗證方式與卡點排查。

README 的〈執行〉節只給三行指令（給已經熟悉環境的人），這份文件補的是它沒寫的部分：
一次性的環境前置（Docker Desktop／WSL integration）、每一步的驗證指令與預期輸出、
以及實際遇過的錯誤訊息對應的處理方式。

本文所有指令與輸出都在 2026-08-28 於此機器實測過。

## 2. 系統需求

| 項目 | 版本／說明 | 本機實測 |
|---|---|---|
| Python | ≥ 3.11，開發環境固定用系統 Python（見 `.python-version`） | ✅ |
| [uv](https://docs.astral.sh/uv/) | 後端套件管理與執行 | ✅ `~/.local/bin/uv` |
| Node.js / npm | ≥ 18；前端建置與 yt-dlp 解 YouTube 簽章挑戰共用同一份 | ✅ v22.22.1 |
| ffmpeg / ffprobe | 場景抽幀、縮圖、探測本機影片長度 | ✅ `/usr/bin/` |
| Docker | 跑 PostgreSQL 容器，見 `docker-compose.yml` | 需先啟動，見 §4 Step 0 |
| OpenAI API 金鑰 | 分析與搜尋都要（Whisper／GPT-4o-mini／text-embedding-3-small） | 寫在 `.env` |

## 3. 一次性安裝與設定

只有第一次 clone 或相依變動時要做，日常啟動可直接跳到 §4。

```bash
uv sync                       # 後端相依（產生 .venv/）
cd frontend && npm install    # 前端相依（產生 frontend/node_modules/）
```

設定檔複製 `.env.example` 成 `.env`（`.env` 在 `.gitignore` 裡，不會進版控）：

```
OPENAI_API_KEY=sk-...
DATABASE_URL=postgresql://avs:avs_local_dev@localhost:5433/avs
```

`DATABASE_URL` 不設也能跑——`src/ai_video_search_web/db/__init__.py:49` 的預設值就是上面那一行，
跟 `docker-compose.yml` 對齊。`db/__init__.py` 自己會 `load_dotenv()`，不依賴呼叫端先載，
所以 uvicorn／pytest／`scripts/` 底下的工具都讀得到。

## 4. 啟動步驟

四個步驟，兩個常駐終端機。

### Step 0：確認 Docker 可用

這是唯一需要離開終端機、動到 Windows GUI 的步驟。

1. 啟動 **Docker Desktop**（Windows 端）。
2. Settings → Resources → **WSL Integration**，勾選目前這個 distro。

驗證：

```bash
docker compose ps
```

沒設定好會得到（實測訊息）：

```text
The command 'docker' could not be found in this WSL 2 distro.
We recommend to activate the WSL integration in Docker Desktop settings.
```

背景見 `docs/archive/14-postgresql-migration-plan.md` §2.3——Windows 端另外裝的 PostgreSQL 17
服務是 Manual 啟動且本專案不使用，`postgresql-x64-17` 不需要開。

### Step 1：啟動 PostgreSQL

```bash
docker compose up -d          # pgvector/pgvector:pg17，對外 port 5433
docker compose ps             # 等 STATUS 出現 (healthy)
```

預期輸出：

```text
NAME           IMAGE                    SERVICE   STATUS                   PORTS
avs-postgres   pgvector/pgvector:pg17   db        Up 6 minutes (healthy)   0.0.0.0:5433->5432/tcp
```

- 容器是 `restart: unless-stopped`，做過一次之後往後會隨 Docker Desktop 自己起來，
  日常開機通常只要確認 Docker Desktop 有開即可。
- 資料放在 named volume `avs_pgdata`，容器砍掉重建資料還在。
- port 用 5433 而不是預設 5432，是為了避開機器上另外裝的那套 PostgreSQL。

### Step 2：終端機 1 — 後端 API

```bash
uv run ai-video-search-web    # http://127.0.0.1:8000
```

進入點 `main()` → `api/main.py` 的 `run()`，內容是
`uvicorn.run(app, host="127.0.0.1", port=8000, workers=1)`。

FastAPI lifespan 啟動時會做兩件事（`api/main.py:50`）：

1. `db.init_db()`——建立資料表與索引，**冪等**，每次啟動都會跑，不需要手動 migrate。
2. `job_manager.reconcile_stale_jobs()`——把上次關機時卡在「執行中」的背景工作標記為失敗，並把連帶卡在「分析中」的影片還原：已經分析成功過的回到「已分析」（舊結果原封不動），第一次分析就被中斷的回到「待分析」（順便清掉部分寫入的殘骸）。少了後面這半，影片會一直停在中斷當下的進度（例如「畫面分析 14%」）。

看到 `Application startup complete.` 就代表 DB 連得上、表也備好了。

### Step 3：終端機 2 — 前端 dev server

```bash
cd frontend && npm run dev    # http://127.0.0.1:5173
```

Vite proxy 會把 `/api` 轉給 `http://127.0.0.1:8000`（`frontend/vite.config.ts`），
所以**瀏覽器一律開 5173**，不要開 8000。

### Step 4：驗證

打開 `http://127.0.0.1:5173`，Header 統計出現數字就代表前端 → 後端 → PostgreSQL 整條通了。

想在終端機確認可以用這三個指令：

```bash
# DB：連得上、資料在
uv run python -c "
from ai_video_search_web import db
with db.get_connection() as c:
    print(c.execute('select version()').fetchone()['version'][:40])
    print(c.execute('select count(*) n from videos').fetchone())
"

# 後端與前端：各自回 200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/v1/stats
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5173/
```

2026-08-28 實測結果：`PostgreSQL 17.10 (Debian 17.10-1.pgdg12+1)`、`{'n': 22}`、兩個 `200`。

## 5. 常見問題排查

### 5.1 `docker: command not found`

```text
The command 'docker' could not be found in this WSL 2 distro.
```

→ **原因**：Docker Desktop 沒開，或這個 WSL distro 的 integration 沒勾。
→ **解法**：見 §4 Step 0，需要 GUI 操作一次。

### 5.2 後端起不來、或連 DB 失敗

先確認 5433 有沒有在聽：

```bash
ss -ltn | grep 5433
```

沒有任何輸出代表 PostgreSQL 沒跑（實測連線錯誤是 `[Errno 111] Connection refused`）
→ 回到 §4 Step 1 執行 `docker compose up -d`。

### 5.3 `address already in use`（port 8000）

```text
ERROR: [Errno 98] error while attempting to bind on address ('127.0.0.1', 8000): address already in use
```

→ **原因**：已經有一個後端在跑了（不是錯誤設定）。
→ **解法**：確認是不是自己開的另一個終端機；要找出是誰：

```bash
ss -ltnp | grep -E '8000|5173'
```

前端 5173 同理。

### 5.4 畫面空白／API 都 404

→ 檢查是不是直接開了 `http://127.0.0.1:8000`。後端只提供 `/api/v1/*`，
沒有掛前端靜態檔，開發時一律走 5173 的 Vite dev server。

## 6. 用 pgAdmin 看資料庫內容

pgAdmin 4 已經隨 Windows 端的 PostgreSQL 17 裝好
（`C:\Program Files\PostgreSQL\17\pgAdmin 4\runtime\pgAdmin4.exe`），直接拿來連 Docker 容器即可，
不需要另外安裝——兩邊都是 PG 17，版本對得上。這也是 `docs/archive/14-postgresql-migration-plan.md` D1
決策裡選 pg17 的理由之一。

前提是 §4 Step 1 的容器在跑（`docker compose ps` 顯示 `(healthy)`）。

### 6.1 註冊連線

1. Windows 開始選單開 **pgAdmin 4**。第一次會要求設定 master password，那是 pgAdmin
   自己用來保存連線密碼的，跟資料庫帳號無關。
2. 左側 **Servers** 右鍵 → **Register** → **Server…**
3. **General** 頁籤 → Name 填 `AVS Docker (5433)`（用來跟 Windows 本機那套 PG 區分）。
4. **Connection** 頁籤：

   | 欄位 | 值 |
   |---|---|
   | Host name/address | `localhost` |
   | Port | **`5433`**（不是 5432） |
   | Maintenance database | `avs` |
   | Username | `avs` |
   | Password | `avs_local_dev` |
   | Save password | 勾起來 |

5. **Save** → 展開 `Servers → AVS Docker → Databases → avs → Schemas → public → Tables`。

⚠️ Databases 底下還有一個 **`avs_test`**——那是測試用資料庫，`uv run pytest` 每個測試前都會清空它。
看資料請認明 **`avs`**。

### 6.2 資料表一覽（2026-08-28 實測）

| 表 | 筆數 | 總大小 | 內容 |
|---|---|---|---|
| `segments` | 931 | 18 MB | 片段：時間範圍、逐字稿、畫面描述、OCR 文字、3 個 embedding |
| `search_log` | 630 | 128 kB | 每次搜尋的 query 與花費 |
| `conversations` | 167 | 192 kB | 對話搜尋狀態（`state_json`） |
| `ocr_events` | 95 | 648 kB | 本地 OCR 掃描結果 |
| `jobs` | 32 | 64 kB | 背景工作與進度 |
| `videos` | 22 | 72 kB | 影片主檔 |

### 6.3 不要對 `segments` 用 View/Edit Data

`segments` 有三個 `bytea` 欄位（`transcript_embedding`／`visual_embedding`／`ocr_embedding`），
佔掉那 18 MB 的絕大部分。表格右鍵 **View/Edit Data → All Rows** 會連二進位資料一起撈，
既慢又讀不出東西。

改用 **Query Tool**（表格右鍵 → Query Tool）明確指定欄位：

```sql
-- 影片清單
select id, title, status, duration_sec, segment_count, cost_usd, analyzed_at
from videos order by id;

-- 某支影片的片段內容（排除 embedding）
select id, start_sec, end_sec, transcript, visual_description, ocr_text
from segments where video_id = 3 order by start_sec;

-- 最近的搜尋紀錄
select id, query, cost_usd, created_at from search_log order by id desc limit 50;

-- 背景工作與失敗原因
select id, job_type, video_id, status, stage, progress_percent, error_message, created_at
from jobs order by id desc limit 30;

-- 花費排行
select id, title, segment_count, round(cost_usd::numeric, 4) as cost
from videos order by cost_usd desc nulls last;
```

### 6.4 時間欄位是 text 不是 timestamp

`created_at`／`analyzed_at` 這類欄位的型別是 **text**，內容是 ISO 字串
（例如 `2026-08-18T21:36:37`）——從 SQLite 搬過來時保留原型別，見
`docs/archive/14-postgresql-migration-plan.md`。

字串排序剛好等於時間排序，所以 `order by created_at` 可以直接用；
但要做日期運算或比較區間，得先轉型：

```sql
select * from search_log
where created_at::timestamp >= now() - interval '7 days'
order by created_at desc;
```

### 6.5 不開 pgAdmin 的替代方式

WSL 終端機直接進 psql：

```bash
docker compose exec db psql -U avs -d avs
```

常用 meta command：`\dt` 列出資料表、`\d segments` 看結構、`\q` 離開。

## 7. 關閉

```bash
# 兩個終端機各按 Ctrl+C 停掉後端與前端

docker compose stop           # 停容器、保留資料
docker compose down           # 移除容器，資料仍在 volume avs_pgdata
```

`docker compose down -v` 會**連 volume 一起刪掉**（22 支影片的分析結果會消失），一般不要用。

## 8. 其他常用指令

```bash
# 後端測試（需要 §4 Step 1 的 DB 在跑）
uv run pytest                  # 一般測試，純邏輯／mock，不呼叫真實 API
uv run pytest -m integration   # 整合測試，呼叫真實 OpenAI API，有極小額費用

# 前端檢查
cd frontend
npx tsc -b --noEmit            # 型別檢查
npx oxlint                     # lint
npm run build                  # production build

# Golden Set 評測（呼叫真實 OpenAI API，結果存到 docs/eval-runs/）
uv run python scripts/run_golden_set_eval.py
```

測試會自動建立並使用獨立的 `avs_test` 資料庫，每個測試前清空，**不會碰到正式資料庫**——
`tests/conftest.py` 會檢查目標資料庫名稱以 `_test` 結尾才動手。

## 9. 待確認事項

- [ ] `.env.example` 註解說 `GEMINI_API_KEY` 是「YouTube 搜尋功能用」，但 `src/` 底下
      grep 不到任何 `GEMINI`／`gemini` 的引用；`services/youtube_search_service.py`
      實際用的是 yt-dlp 的 `ytsearch{n}:`，而且該檔註解明講「刻意不引入 YouTube Data API v3
      ⋯⋯不需要申請與保管 API 金鑰」。這個變數看起來已經沒有作用，待確認是否要從
      `.env.example` 移除。
- [ ] 專案根目錄的 `app.db`／`app.db-shm`／`app.db-wal` 是遷移前的 SQLite 舊檔，
      遷移完成後已無程式讀取（見 `docs/archive/14-postgresql-migration-plan.md`）。
      待確認保留為備份到什麼時候。

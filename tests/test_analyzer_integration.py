"""analyzer.py 端到端特徵測試：真的跑一次 _analyze_worker()，鎖住目前的
Phase 順序與完成後的資料庫狀態，做為之後拆分 _analyze_worker()（重構
Step 8）的安全網。

需要真實 OpenAI API 呼叫（ASR／VLM／embedding／摘要；本地 OCR 是純本機
運算不花錢），單次執行成本約 US$0.002，執行時間約數十秒。預設 `pytest`
不會執行這個測試（見 pyproject.toml 的 addopts），要手動執行：

    uv run pytest -m integration tests/test_analyzer_integration.py -v

測試影片用 ffmpeg 現場產生（純色背景＋靜音音軌），不提交大型影片檔案
進 git，也不依賴任何個人路徑或字型檔案。
"""
from __future__ import annotations

import queue
import subprocess
from pathlib import Path

import pytest

from ai_video_search_web import db
from ai_video_search_web.pipeline import analyzer

pytestmark = pytest.mark.integration


@pytest.fixture
def synthetic_video(tmp_path) -> Path:
    """產生一支 6 秒的合成測試影片（純色背景＋靜音音軌），足夠讓完整分析
    流程跑過一輪。"""
    video_path = tmp_path / "synthetic_test_video.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=navy:s=640x360:d=6:r=10",
            "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(video_path),
        ],
        check=True, capture_output=True, timeout=30,
    )
    return video_path


def test_analyze_worker_full_pipeline(temp_db, synthetic_video):
    video_id = db.insert_video(
        title="Step6 特徵測試影片", source=db.SOURCE_LOCAL, source_url=None,
        file_path=str(synthetic_video), duration_sec=6,
    )

    progress_queue: "queue.Queue[object]" = queue.Queue()
    analyzer._analyze_worker(video_id, progress_queue)

    stages: list[str] = []
    final: object = None
    while not progress_queue.empty():
        item = progress_queue.get()
        if isinstance(item, analyzer.AnalysisProgress):
            stages.append(item.stage)
        if isinstance(item, (analyzer.AnalysisResult, analyzer.AnalysisError)):
            final = item

    # 鎖住目前的 Phase 順序（依序出現一次，不含重複的百分比更新）
    expected_stage_order = [
        "場景切分中", "音訊轉錄中", "音訊轉錄完成", "畫面分析",
        "建立向量中", "寫入索引", "本地 OCR 掃描中", "產生摘要中",
    ]
    assert list(dict.fromkeys(stages)) == expected_stage_order

    assert isinstance(final, analyzer.AnalysisResult), f"分析失敗：{final}"
    assert final.video_id == video_id
    assert final.partial is False
    assert 0 < final.cost_usd < analyzer.BUDGET_USD

    video = db.get_video(video_id)
    assert video.status == db.STATUS_ANALYZED
    assert video.segment_count == final.segment_count
    assert video.summary, "Phase F 應該自動產生摘要"
    assert video.summary_model == "gpt-4o-mini"

    segments = db.list_segments_for_video(video_id)
    assert len(segments) == final.segment_count
    assert all(seg.visual_description for seg in segments), "每個片段都應該有 VLM 畫面描述"

"""五個 ffmpeg／ffprobe 呼叫端產生的命令列，逐字鎖住。

這些參數是實測校準過的（音訊 64kbps 單聲道 16kHz 對應 Whisper 的 25MB 上限、
抽幀 `-ss` 放在 `-i` 之前才是快速 seek、縮圖固定 320x180…），改動任何一個都
會安靜地改變分析結果或成本，而不是讓測試轉紅——所以在把這些呼叫收進
pipeline/media.py 之前，先把命令列本身變成有測試看著的契約。

patch 的是**共用的 `subprocess` 模組**而不是各呼叫端模組裡的 `subprocess`
名稱：五個呼叫端都是 `import subprocess` 後在呼叫當下才查 `subprocess.run`，
所以不管這一行實際住在 frames.py 還是搬進 media.py，這裡都攔得到。測試因此
不綁定目前的模組結構，重構前後同一份測試都該是綠的。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ai_video_search_web.pipeline import asr, frames, media, scene_detect
from ai_video_search_web.services import video_service


class _RunSpy:
    """攔下 subprocess.run，記錄每次呼叫的 argv 與關鍵字參數。

    `stdout` 給 ffprobe 呼叫端用；`creates_output` 讓 ffmpeg 呼叫端拿得到一個
    真的存在、有內容的產出檔（呼叫端會讀它或回傳它的路徑）。
    """

    def __init__(self, stdout: str = "", creates_output: bytes | None = None) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self._stdout = stdout
        self._creates_output = creates_output

    def __call__(self, args, **kwargs):
        self.calls.append((list(args), kwargs))
        if self._creates_output is not None:
            Path(args[-1]).write_bytes(self._creates_output)
        return subprocess.CompletedProcess(args, 0, self._stdout, "")

    @property
    def argv(self) -> list[str]:
        assert len(self.calls) == 1, f"預期剛好一次子行程呼叫，實際 {len(self.calls)} 次"
        return self.calls[0][0]

    @property
    def kwargs(self) -> dict:
        assert len(self.calls) == 1
        return self.calls[0][1]


@pytest.fixture
def spy(monkeypatch):
    def _install(stdout: str = "", creates_output: bytes | None = None) -> _RunSpy:
        s = _RunSpy(stdout=stdout, creates_output=creates_output)
        monkeypatch.setattr(subprocess, "run", s)
        return s

    return _install


# ----------------------------------------------------------------------
# ffmpeg：抽幀（VLM 與本地 OCR 共用）
# ----------------------------------------------------------------------
def test_extract_frame_command_line(spy):
    s = spy(creates_output=b"\xff\xd8jpeg")

    path = frames.extract_frame(Path("/videos/x.mp4"), 12.5)

    assert s.argv[:-1] == [
        "ffmpeg", "-y",
        # -ss 在 -i 之前＝快速 seek（先跳再解碼）。調換順序會慢好幾個數量級。
        "-ss", "12.5",
        "-i", "/videos/x.mp4",
        "-frames:v", "1",
        "-q:v", "3",
    ]
    assert Path(s.argv[-1]) == path
    assert path.suffix == ".jpg"
    assert path.read_bytes() == b"\xff\xd8jpeg"
    assert s.kwargs["check"] is True
    assert s.kwargs["capture_output"] is True
    path.unlink(missing_ok=True)


def test_extract_frame_clamps_negative_timestamp_to_zero(spy):
    s = spy(creates_output=b"jpeg")
    path = frames.extract_frame(Path("/videos/x.mp4"), -3.0)
    assert s.argv[3] == "0.0"
    path.unlink(missing_ok=True)


# ----------------------------------------------------------------------
# ffmpeg：抽音訊（Whisper 上傳用）
# ----------------------------------------------------------------------
def test_extract_audio_command_line(spy):
    s = spy(creates_output=b"mp3")

    path = asr._extract_audio(Path("/videos/x.mp4"))

    assert s.argv[:-1] == [
        "ffmpeg", "-y",
        "-i", "/videos/x.mp4",
        # -vn 去掉視訊；單聲道 16kHz 64kbps 是為了讓 60 分鐘影片仍落在
        # Whisper 的 25MB 上傳上限內，見 analyzer.MAX_DURATION_SEC 的說明。
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k",
    ]
    assert Path(s.argv[-1]) == path
    assert path.suffix == ".mp3"
    assert s.kwargs["check"] is True
    assert s.kwargs["capture_output"] is True
    path.unlink(missing_ok=True)


# ----------------------------------------------------------------------
# ffmpeg：縮圖
# ----------------------------------------------------------------------
def _analyzed_video(tmp_path: Path, duration_sec: int = 100):
    video_file = tmp_path / "movie.mp4"
    video_file.write_bytes(b"not really a video")
    return video_service.VideoRecord(
        id=1, title="t", source="local", source_url=None, file_path=str(video_file),
        duration_sec=duration_sec, status="analyzed", pipeline_stage=None,
        created_at="2026-01-01T00:00:00", analyzed_at=None, segment_count=None, cost_usd=None,
        asr_model=None, vlm_model=None, embedding_model=None, summary=None, summary_model=None,
        document_json=None, document_type=None, document_model=None,
    )


def test_generate_thumbnail_command_line(spy, tmp_path):
    s = spy(creates_output=b"\x89PNG-bytes")
    video = _analyzed_video(tmp_path, duration_sec=100)

    thumbnail = video_service.generate_thumbnail(video)

    assert s.argv[:-1] == [
        "ffmpeg", "-y",
        "-ss", "50.0",  # 影片時間中點
        "-i", video.file_path,
        "-vf", "scale=320:180",
        "-frames:v", "1",
    ]
    assert thumbnail == b"\x89PNG-bytes"
    assert s.kwargs["check"] is True
    assert s.kwargs["capture_output"] is True
    assert s.kwargs["timeout"] == 15
    # 暫存檔讀完就刪掉，不留在磁碟上
    assert not Path(s.argv[-1]).exists()


def test_generate_thumbnail_returns_none_when_the_file_is_gone(spy, tmp_path):
    s = spy(creates_output=b"png")
    video = _analyzed_video(tmp_path)
    Path(video.file_path).unlink()

    assert video_service.generate_thumbnail(video) is None
    assert s.calls == [], "檔案不存在時不該啟動 ffmpeg"


def test_generate_thumbnail_returns_none_when_ffmpeg_fails(monkeypatch, tmp_path):
    def boom(args, **kwargs):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(subprocess, "run", boom)
    assert video_service.generate_thumbnail(_analyzed_video(tmp_path)) is None


# ----------------------------------------------------------------------
# ffprobe：影片長度與編碼判斷
# ----------------------------------------------------------------------
def test_probe_local_duration_command_line(spy):
    s = spy(stdout="123.456\n")

    duration = video_service.probe_local_duration(Path("/videos/x.mp4"))

    assert s.argv == [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        "/videos/x.mp4",
    ]
    assert duration == 123  # 四捨五入成整數秒
    assert s.kwargs["capture_output"] is True
    assert s.kwargs["text"] is True
    assert s.kwargs["timeout"] == 10
    assert s.kwargs["check"] is True


def test_probe_local_duration_returns_none_when_output_is_not_a_number(spy):
    spy(stdout="N/A\n")
    assert video_service.probe_local_duration(Path("/videos/x.mp4")) is None


def test_is_av1_command_line(spy):
    s = spy(stdout="av1\n")

    assert scene_detect._is_av1(Path("/videos/x.mp4")) is True
    assert s.argv == [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name",
        "-of", "default=noprint_wrappers=1:nokey=1",
        "/videos/x.mp4",
    ]
    assert s.kwargs["capture_output"] is True
    assert s.kwargs["text"] is True
    assert s.kwargs["timeout"] == 10
    assert s.kwargs["check"] is True


def test_is_av1_false_for_other_codecs(spy):
    spy(stdout="h264\n")
    assert scene_detect._is_av1(Path("/videos/x.mp4")) is False


def test_is_av1_false_when_ffprobe_is_unavailable(monkeypatch):
    def boom(args, **kwargs):
        raise FileNotFoundError("ffprobe not installed")

    monkeypatch.setattr(subprocess, "run", boom)
    # 讀不到編碼就當作不是 AV1（走 opencv backend），不讓整支分析失敗
    assert scene_detect._is_av1(Path("/videos/x.mp4")) is False


# ----------------------------------------------------------------------
# 每個子行程呼叫都有 timeout
#
# 這是刻意的行為變更，不是純結構重構：抽幀與抽音訊原本沒有 timeout，ffmpeg
# 卡住時分析執行緒會無限期停住、送不出終端事件，job_manager 的分析 slot 就
# 永遠不會釋放（跟第三輪 C0 修掉的是同一條失敗路徑）。
# ----------------------------------------------------------------------
def test_every_ffmpeg_and_ffprobe_call_sets_a_timeout(spy, tmp_path):
    """五個呼叫端**都**要有 timeout，一個都不能漏。"""
    cases = [
        ("抽幀", lambda: frames.extract_frame(Path("/videos/x.mp4"), 1.0), b"jpeg"),
        ("抽音訊", lambda: asr._extract_audio(Path("/videos/x.mp4")), b"mp3"),
        ("縮圖", lambda: video_service.generate_thumbnail(_analyzed_video(tmp_path)), b"png"),
        ("影片長度", lambda: video_service.probe_local_duration(Path("/videos/x.mp4")), None),
        ("編碼判斷", lambda: scene_detect._is_av1(Path("/videos/x.mp4")), None),
    ]
    for label, call, output in cases:
        s = spy(stdout="1.0", creates_output=output)
        result = call()
        timeout = s.kwargs.get("timeout")
        assert timeout is not None and timeout > 0, f"{label} 沒有設 timeout"
        if isinstance(result, Path):
            result.unlink(missing_ok=True)


def test_frame_extraction_and_audio_extraction_use_their_own_timeouts(spy):
    """抽一張畫面（快速 seek，次秒級）跟讀完整支影片的音訊（上限 1 小時）
    差了一個數量級，不共用同一個值。"""
    s = spy(creates_output=b"jpeg")
    frames.extract_frame(Path("/videos/x.mp4"), 1.0).unlink(missing_ok=True)
    assert s.kwargs["timeout"] == media.FRAME_TIMEOUT_SEC

    s = spy(creates_output=b"mp3")
    asr._extract_audio(Path("/videos/x.mp4")).unlink(missing_ok=True)
    assert s.kwargs["timeout"] == media.AUDIO_TIMEOUT_SEC

    assert media.AUDIO_TIMEOUT_SEC > media.FRAME_TIMEOUT_SEC


def test_a_hung_ffmpeg_surfaces_as_an_exception_instead_of_blocking(monkeypatch):
    """超時的抽幀／抽音訊要往外拋，讓 analyzer 把這支影片標記失敗——而不是
    整條執行緒停在那裡、把分析 slot 一起帶走。"""
    def hang(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs.get("timeout", 0))

    monkeypatch.setattr(subprocess, "run", hang)

    with pytest.raises(subprocess.TimeoutExpired):
        frames.extract_frame(Path("/videos/x.mp4"), 1.0)
    with pytest.raises(subprocess.TimeoutExpired):
        asr._extract_audio(Path("/videos/x.mp4"))


def test_a_hung_ffmpeg_is_swallowed_where_the_caller_already_swallowed_failures(
    monkeypatch, tmp_path
):
    """縮圖與兩個 ffprobe 呼叫本來就吞例外回退；TimeoutExpired 是
    SubprocessError 的子類別，所以既有的 except 照樣接得住，超時的語意跟
    「ffmpeg 執行失敗」一致，不需要各呼叫端再多寫一個 except。"""
    def hang(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs.get("timeout", 0))

    monkeypatch.setattr(subprocess, "run", hang)

    assert video_service.generate_thumbnail(_analyzed_video(tmp_path)) is None
    assert video_service.probe_local_duration(Path("/videos/x.mp4")) is None
    assert scene_detect._is_av1(Path("/videos/x.mp4")) is False


# ----------------------------------------------------------------------
# media.py 本身
# ----------------------------------------------------------------------
def test_run_ffmpeg_prepends_the_shared_prefix(spy):
    s = spy()
    media.run_ffmpeg(["-i", "in.mp4", "out.mp4"], timeout=1.0)
    # -y（覆寫輸出檔）是所有呼叫端共用的決定，收在這裡而不是各寫一次
    assert s.argv == ["ffmpeg", "-y", "-i", "in.mp4", "out.mp4"]


def test_run_ffprobe_prepends_the_prefix_and_strips_the_output(spy):
    s = spy(stdout="  h264 \n")
    assert media.run_ffprobe(["-show_entries", "x"]) == "h264"
    assert s.argv == ["ffprobe", "-v", "error", "-show_entries", "x"]


def test_new_temp_path_creates_an_empty_file_the_caller_owns():
    path = media.new_temp_path(".jpg")
    try:
        assert path.exists()
        assert path.suffix == ".jpg"
        assert path.read_bytes() == b""
    finally:
        path.unlink(missing_ok=True)


# ----------------------------------------------------------------------
# has_audio_stream()：決定要不要跳過 ASR，見 analyzer._run_transcription()
# ----------------------------------------------------------------------


def test_has_audio_stream_command_line(spy):
    s = spy(stdout="audio\n")

    assert media.has_audio_stream(Path("/videos/x.mp4")) is True
    assert s.argv == [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_type",
        "-of", "default=noprint_wrappers=1:nokey=1",
        "/videos/x.mp4",
    ]
    assert s.kwargs["timeout"] == 10


def test_has_audio_stream_false_when_output_is_empty(spy):
    # 沒有音軌時 ffprobe 選不到 a:0，標準輸出是空的
    spy(stdout="")
    assert media.has_audio_stream(Path("/videos/x.mp4")) is False


def test_has_audio_stream_true_when_ffprobe_is_unavailable(monkeypatch):
    def boom(args, **kwargs):
        raise FileNotFoundError("ffprobe not installed")

    monkeypatch.setattr(subprocess, "run", boom)
    # 猜錯的代價不對稱：當成沒有音軌會讓有旁白的影片整支失去字幕，
    # 當成有音軌最多白花一次 ASR 的錢，所以讀不到一律回 True
    assert media.has_audio_stream(Path("/videos/x.mp4")) is True

"""asr.py 的幻覺字幕偵測測試：
- is_hallucinated_transcript()（模式 A）：用真實 app.db 資料校準過的
  no_speech_prob 門檻（0.7）判斷字幕是不是背景音樂被誤判成重複亂碼的幻覺。
- find_repetitive_transcript_indices()（模式 B）：用真實資料校準過的
  「連續場景被同一個詞主導」判斷整段被誤判成單字重複（例如「Music Music」）
  的幻覺，見 docs/whisper-hallucination-filter-plan.md。
"""
from __future__ import annotations

from ai_video_search_web.pipeline.asr import (
    SegmentScores,
    _dominant_word_ratio,
    find_repetitive_transcript_indices,
    is_hallucinated_transcript,
)


def _scores(no_speech_prob: float | None) -> SegmentScores:
    return SegmentScores(no_speech_prob=no_speech_prob, avg_logprob=-0.5, compression_ratio=1.0)


def test_is_hallucinated_transcript_true_above_threshold():
    assert is_hallucinated_transcript(_scores(0.8)) is True


def test_is_hallucinated_transcript_false_at_or_below_threshold():
    assert is_hallucinated_transcript(_scores(0.7)) is False
    assert is_hallucinated_transcript(_scores(0.487)) is False  # 真實 NBA 對白影片的實測最高值


def test_is_hallucinated_transcript_false_when_no_speech_prob_is_none():
    """範圍內沒有 Whisper 片段時（no_speech_prob 是 None）不算可疑，不能因為
    沒資料就當作幻覺。"""
    assert is_hallucinated_transcript(_scores(None)) is False


def test_dominant_word_ratio_basic():
    assert _dominant_word_ratio("Music Music Music") == ("music", 1.0)
    assert _dominant_word_ratio("Music Music") == ("music", 1.0)
    assert _dominant_word_ratio("這是一段真實的對白內容") == ("這是一段真實的對白內容", 1.0)


def test_dominant_word_ratio_empty_string_returns_none():
    assert _dominant_word_ratio("") == (None, 0.0)
    assert _dominant_word_ratio("   ") == (None, 0.0)


def test_find_repetitive_transcript_indices_flags_long_run_of_same_dominant_word():
    transcripts = ["Music", "Music Music", "Music Music Music", "Music"]
    assert find_repetitive_transcript_indices(transcripts) == {0, 1, 2, 3}


def test_find_repetitive_transcript_indices_ignores_short_run_below_threshold():
    """真實資料：短促但變化的內容（例如動物教學）連續相同主導詞最多只到 2，
    低於門檻（3）不該被標記——這是實測過會被單獨用「主導詞佔比」誤殺的案例。"""
    transcripts = ["大象", "大象", "獅子", "老虎"]
    assert find_repetitive_transcript_indices(transcripts) == set()


def test_find_repetitive_transcript_indices_ignores_varying_real_content():
    """真實資料：NBA 對白裡連續 7 個場景的「主導詞」都是 the，但因為是長句、
    the 只占少數詞，不該被標記——這是實測過會被單獨用「連續同一主導詞」
    誤殺的案例。"""
    transcripts = [
        "He's in! Stopped in on Harper, out to MJ for the 3! It's short!",
        "Kornicek kicking it ahead to the Russell, gets back to pick it off!",
        "Rodman! Offensive foul on the Dennis! And that's 5!",
        "Now Isaiah, jumping out off the screen and make Michael Jordan a passer!",
    ]
    assert find_repetitive_transcript_indices(transcripts) == set()


def test_find_repetitive_transcript_indices_two_independent_runs():
    """中間插入一段不同內容應該把連續段打斷，前後兩段各自獨立判斷。"""
    transcripts = [
        "Music", "Music", "Music",
        "這是真的對白內容跟音樂完全無關",
        "Kiss", "Kiss", "Kiss",
    ]
    assert find_repetitive_transcript_indices(transcripts) == {0, 1, 2, 4, 5, 6}


def test_find_repetitive_transcript_indices_empty_list():
    assert find_repetitive_transcript_indices([]) == set()

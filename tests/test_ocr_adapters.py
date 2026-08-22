"""EasyOcrEngine adapter 測試：用假的 reader 物件，不下載真實 EasyOCR 模型
（get_easyocr_engine() 才會真的 import easyocr／載入模型，這裡刻意繞過它，
直接建構 EasyOcrEngine 測試轉換邏輯）。
"""
from __future__ import annotations

from ai_video_search_web.pipeline.ocr_adapters import ENGINE_EASYOCR, EasyOcrEngine


class _FakeReader:
    """模擬 easyocr.Reader.readtext() 的回傳格式：list[(bbox, text, confidence)]。"""

    def __init__(self, results):
        self._results = results

    def readtext(self, image_path):
        return self._results


def test_recognize_converts_easyocr_tuples_to_candidates():
    bbox = [[0, 0], [10, 0], [10, 10], [0, 10]]
    engine = EasyOcrEngine(_FakeReader([(bbox, "ABC-1234", 0.87)]))

    candidates = engine.recognize("fake/path.jpg")

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.text == "ABC-1234"
    assert candidate.confidence == 0.87
    assert candidate.bbox == [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def test_recognize_strips_whitespace_and_drops_blank_text():
    engine = EasyOcrEngine(
        _FakeReader(
            [
                ([[0, 0]], "  hello  ", 0.5),
                ([[0, 0]], "   ", 0.9),  # 空白文字應該被捨棄
            ]
        )
    )

    candidates = engine.recognize("fake/path.jpg")

    assert len(candidates) == 1
    assert candidates[0].text == "hello"


def test_recognize_empty_results():
    engine = EasyOcrEngine(_FakeReader([]))
    assert engine.recognize("fake/path.jpg") == []


def test_engine_name_constant():
    assert EasyOcrEngine.name == ENGINE_EASYOCR

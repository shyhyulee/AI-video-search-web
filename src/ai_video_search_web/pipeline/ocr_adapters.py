"""本地 OCR 引擎 adapter：把 EasyOCR（Phase 2 之後會加 Tesseract）包成統一介面，
ocr_service.py 不直接依賴特定 OCR SDK，之後要加 Tesseract 只需要在這個模組內
多一個實作類別，不用動 ocr_service.py 的邏輯。

Engine（含底層模型）只建立一次並重複使用——模型載入很慢，比照
openai_client.get_client() 的 lru_cache 單例模式。easyocr 套件本身在
get_easyocr_engine() 內才 import，避免這個模組本身的 import 也連帶拖慢
（或在 easyocr 尚未安裝妥當時失敗）。
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

ENGINE_EASYOCR = "easyocr"

# 正體中文＋英文；EasyOCR 不允許 ch_tra 跟 ch_sim 同時使用，但可以跟 en 混用。
LANGUAGES = ["ch_tra", "en"]


@dataclass
class OcrCandidate:
    text: str
    confidence: float
    bbox: list[tuple[float, float]]  # 四點座標（像素），EasyOCR 原生回傳格式


class OcrEngine(Protocol):
    name: str

    def recognize(self, image_path: Path) -> list[OcrCandidate]: ...


class EasyOcrEngine:
    """包住一個已初始化的 easyocr.Reader；不要自己 new，一律透過 get_easyocr_engine()。"""

    name = ENGINE_EASYOCR

    def __init__(self, reader) -> None:
        self._reader = reader

    def recognize(self, image_path: Path) -> list[OcrCandidate]:
        raw_results = self._reader.readtext(str(image_path))
        return [
            OcrCandidate(
                text=text.strip(),
                confidence=float(confidence),
                bbox=[(float(x), float(y)) for x, y in bbox],
            )
            for bbox, text, confidence in raw_results
            if text.strip()
        ]


@lru_cache(maxsize=1)
def get_easyocr_engine() -> EasyOcrEngine:
    """建立並快取全域唯一的 EasyOCR engine。gpu=False：這台機器沒有確認過 GPU
    可用性，先固定用 CPU（見 docs/02-technical-decisions.md#vlm-與-ocr）。
    """
    import easyocr

    reader = easyocr.Reader(LANGUAGES, gpu=False)
    return EasyOcrEngine(reader)

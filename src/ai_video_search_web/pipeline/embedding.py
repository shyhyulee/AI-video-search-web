"""Embedding：文字向量化與相似度計算。V0 只接 OpenAI text-embedding-3-small，
對外只暴露 provider 無關的介面，之後要加其他供應商，在這個模組內部加實作分支即可。

注意：不同 embedding 模型的向量空間不可混用比較，同一批可比較的向量必須來自同一個模型。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from openai import OpenAI

MODEL_NAME = "text-embedding-3-small"
PRICE_PER_TOKEN_USD = 0.02 / 1_000_000

# text-embedding-3-small 原生輸出 1536 維，用 API 的 dimensions 參數截短到 1024 維
# （模型訓練時就支援這種截短，品質損失很小），統一全部 embedding 欄位的維度。
DIMENSIONS = 1024


@dataclass
class EmbedResult:
    vector: list[float]
    cost_usd: float


def embed_text(client: OpenAI, text: str) -> EmbedResult:
    response = client.embeddings.create(input=text, model=MODEL_NAME, dimensions=DIMENSIONS)
    usage = response.usage
    cost_usd = usage.prompt_tokens * PRICE_PER_TOKEN_USD if usage else 0.0
    return EmbedResult(vector=response.data[0].embedding, cost_usd=cost_usd)


def encode_embedding(vector: list[float]) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def decode_embedding(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)

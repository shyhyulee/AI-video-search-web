"""API 統一錯誤回應格式，沿用 docs/08-web-ui-migration-design.md 第 6 節的
Error Schema。
"""
from __future__ import annotations

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail

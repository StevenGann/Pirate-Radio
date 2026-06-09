"""The control-API response envelope (Phase 6, D4) — `{success, data, error}`.

A single consistent shape for every endpoint (the global API rule + D4). ``data`` carries the
payload on success; ``error`` a typed `{code, message}` on failure. The data-XOR-error invariant is
in the model (``error`` present IFF ``not success``; an error response carries no data), so a route
can never accidentally ship a malformed envelope. NO ``Generic[T]`` (fights mypy for no gain on
hand-written routes) and NO ``meta`` (nothing paginates) — Old Man's Rev-2 trims.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


class ApiError(BaseModel):
    model_config = ConfigDict(frozen=True)
    code: str
    message: str


class ApiResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    success: bool
    data: Any = None
    error: ApiError | None = None

    @model_validator(mode="after")
    def _data_xor_error(self) -> ApiResponse:
        if self.success and self.error is not None:
            raise ValueError("a success response must not carry an error")
        if not self.success and self.error is None:
            raise ValueError("an error response must carry an error")
        if not self.success and self.data is not None:
            raise ValueError("an error response must not carry data")
        return self


def ok(data: Any = None) -> ApiResponse:
    """A success envelope wrapping ``data`` (``None`` is valid — e.g. an accepted skip)."""
    return ApiResponse(success=True, data=data, error=None)


def fail(code: str, message: str) -> ApiResponse:
    """An error envelope carrying a typed ``{code, message}`` and no data."""
    return ApiResponse(success=False, data=None, error=ApiError(code=code, message=message))

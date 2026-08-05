"""Nguồn thời gian và ID có thể thay thế được trong test.

Toàn bộ hệ thống lấy thời gian qua :func:`now_utc` và sinh ID qua
:func:`new_run_id` để test có thể cố định kết quả (deterministic).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from itertools import count


def now_utc() -> datetime:
    """Thời điểm hiện tại, luôn kèm timezone UTC."""
    return datetime.now(tz=UTC)


def new_run_id() -> str:
    """ID ngắn cho một lần render."""
    return uuid.uuid4().hex[:12]


class FixedClock:
    """Đồng hồ cố định dùng trong test."""

    def __init__(self, moment: datetime, run_id_prefix: str = "run") -> None:
        self._moment = moment
        self._counter: Iterator[int] = count(1)
        self._prefix = run_id_prefix

    def now_utc(self) -> datetime:
        return self._moment

    def new_run_id(self) -> str:
        return f"{self._prefix}{next(self._counter):04d}"

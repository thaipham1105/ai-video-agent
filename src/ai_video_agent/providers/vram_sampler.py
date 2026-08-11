"""Lấy mẫu VRAM ở luồng nền trong lúc một lượt render đang chạy.

Khác hẳn ``resource_budget``: ở đó là **chặn trước** (máy có đủ không), ở đây là
**ghi nhận trong lúc chạy** (thực tế đã dùng bao nhiêu). Không đo cái sau thì
không bao giờ biết ước lượng của cái trước sai bao nhiêu — D05-B đã lộ ra Duix
khai 7.004 MiB trong khi thực dùng ~8.031 MiB.

Nguyên tắc: **ghi nhận, không chặn**. Mọi lỗi lấy mẫu đều bị nuốt — một lượt
render vài phút không được hỏng chỉ vì ``nvidia-smi`` bận. Không đo được thì
``peak_used_mib()`` trả ``None``, giữ đúng nghĩa "chưa đo" mà
``AvatarProvenance.peak_vram_mib`` đã định.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

#: Khoảng lấy mẫu mặc định. 1 s là nhịp bake-off D04-G đã dùng — đủ dày để bắt
#: đỉnh của một lượt vài chục giây, đủ thưa để không quấy máy.
VRAM_SAMPLE_INTERVAL_SEC = 1.0


class VramSampler:
    """Context manager: vào thì bắt đầu lấy mẫu, ra thì dừng.

    Đo **phần trống thấp nhất** rồi quy ngược ra phần đã dùng, vì ``nvidia-smi``
    trả phần trống tức thời còn thứ cần ghi vào manifest là đỉnh đã dùng.
    """

    def __init__(
        self,
        sampler: Callable[[], int | None],
        total_probe: Callable[[], int | None],
        interval_sec: float = VRAM_SAMPLE_INTERVAL_SEC,
        *,
        thread_name: str = "aiva-vram",
    ) -> None:
        self._sampler = sampler
        self._total_probe = total_probe
        self._interval_sec = interval_sec
        self._thread_name = thread_name
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._min_free_mib: int | None = None

    def __enter__(self) -> VramSampler:
        self._thread = threading.Thread(target=self._loop, daemon=True, name=self._thread_name)
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval_sec * 3)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                free = self._sampler()
            except Exception:  # noqa: BLE001 - ghi nhận, không được làm hỏng lượt render
                free = None
            if free is not None and (self._min_free_mib is None or free < self._min_free_mib):
                self._min_free_mib = free
            self._stop.wait(self._interval_sec)

    def peak_used_mib(self) -> int | None:
        """Đỉnh VRAM **đã dùng** = tổng trừ đi lượng trống thấp nhất quan sát được.

        Trả về lượng dùng của **cả card**, không riêng backend đang chạy — đúng
        cách bake-off đã đo (``nvidia-smi --query-gpu=memory.used``), nên con số
        này so trực tiếp được với ``ResourceEstimate.vram_mib``.
        """
        if self._min_free_mib is None:
            return None
        try:
            total = self._total_probe()
        except Exception:  # noqa: BLE001 - cùng lý do với vòng lấy mẫu
            total = None
        if total is None or total <= self._min_free_mib:
            return None
        return total - self._min_free_mib

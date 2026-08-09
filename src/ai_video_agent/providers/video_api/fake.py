"""Transport giả cho đường video trả phí — dùng ở D05-C khi paid boundary còn đóng.

Ba điều transport này **không bao giờ** làm, và đó là lý do nó tồn tại:

* không khởi tạo client Gemini thật,
* không đọc ``GEMINI_API_KEY`` hay ``AIVA_VIDEO_API_KEY``,
* không tạo bất kỳ request mạng nào.

Nó đếm số lần gọi để test chứng minh được điều quan trọng nhất: khi cổng đóng,
**số lần gọi provider bằng 0**.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ai_video_agent.errors import ProviderError

#: Vài byte đủ để là một file tồn tại. Không phải video thật.
_STUB_BYTES = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom-FAKE-D05C"


@dataclass
class CallCounter:
    """Đếm từng loại hành động riêng — vì ba loại có ba chính sách khác nhau."""

    submit: int = 0
    poll: int = 0
    download: int = 0

    @property
    def total(self) -> int:
        return self.submit + self.poll + self.download


@dataclass
class FakeVideoTransport:
    """Transport giả, có thể lập trình để mô phỏng lỗi.

    ``poll_done_after`` cho phép mô phỏng operation chạy nền: các lần poll đầu
    báo chưa xong, lần thứ N mới xong — nhờ đó test chứng minh được poll thử lại
    được mà **không** phát sinh submit mới.
    """

    counter: CallCounter = field(default_factory=CallCounter)
    operation_name: str = "fake/operations/d05c-0001"
    poll_done_after: int = 1
    usage_payload: object | None = None
    fail_submit_with: Exception | None = None
    fail_download_times: int = 0

    def submit(self, payload: dict[str, object], idempotency_key: str) -> str:
        del payload, idempotency_key
        self.counter.submit += 1
        if self.fail_submit_with is not None:
            raise self.fail_submit_with
        return self.operation_name

    def poll(self, operation_name: str) -> tuple[bool, dict[str, object] | None]:
        del operation_name
        self.counter.poll += 1
        done = self.counter.poll >= self.poll_done_after
        if not done:
            return False, None
        usage: dict[str, object] = (
            {"raw": self.usage_payload} if self.usage_payload is not None else {}
        )
        return True, usage

    def download(self, operation_name: str, out_path: Path) -> Path:
        del operation_name
        self.counter.download += 1
        if self.counter.download <= self.fail_download_times:
            msg = "tai that bai (gia lap)"
            raise ProviderError(msg)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(_STUB_BYTES)
        return out_path

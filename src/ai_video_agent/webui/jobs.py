"""Một khe job duy nhất cho việc dựng video.

Vì sao chỉ một: Duix chạy **một job tại một thời điểm** (``get_run_flag()`` trả
mã bận), và hàng rào VRAM tính cho một lượt. Cho hai lượt chạy song song thì
lượt thứ hai hoặc bị container từ chối, hoặc cả hai cùng OOM — cả hai kết cục
đều tệ hơn việc nói thẳng "đang bận".

Khe này cũng là lý do việc bắt log bằng ``redirect_stdout`` an toàn: không bao
giờ có hai job cùng ghi vào một ``Console``.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ai_video_agent.clock import now_utc
from ai_video_agent.errors import AivaError

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime


class JobBusyError(AivaError):
    """Đã có job đang chạy. Cố ý là lỗi riêng để tầng trên trả 409, không phải 500."""


@dataclass
class JobState:
    """Ảnh chụp một job. Đọc được từ luồng khác, nên mọi cập nhật đi qua khoá."""

    id: str
    kind: str
    status: str  # running | succeeded | failed
    started_at: datetime
    finished_at: datetime | None = None
    message: str = ""
    log: str = ""
    result: dict[str, Any] = field(default_factory=dict)

    @property
    def running(self) -> bool:
        return self.status == "running"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "message": self.message,
            "log": self.log,
            "result": self.result,
        }


class JobRunner:
    """Chạy nền đúng một job, giữ lại kết quả của job gần nhất để UI hỏi lại."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: JobState | None = None
        self._thread: threading.Thread | None = None

    def start(self, kind: str, fn: Callable[[], dict[str, Any]]) -> JobState:
        """Nhận job mới, hoặc ném :class:`JobBusyError` nếu còn job đang chạy.

        Kiểm tra và đặt chỗ nằm **trong cùng một khoá**: tách ra là mở đúng cái
        cửa sổ đua mà khe này sinh ra để đóng.
        """
        with self._lock:
            if self._state is not None and self._state.running:
                msg = (
                    f"Đang có job {self._state.kind!r} chạy dở "
                    f"(bắt đầu {self._state.started_at.isoformat()}). "
                    "Duix chỉ chạy một lượt tại một thời điểm — đợi xong rồi thử lại."
                )
                raise JobBusyError(msg)
            state = JobState(
                id=uuid.uuid4().hex[:12], kind=kind, status="running", started_at=now_utc()
            )
            self._state = state

        thread = threading.Thread(
            target=self._run, args=(state, fn), daemon=True, name=f"aiva-job-{state.id}"
        )
        self._thread = thread
        thread.start()
        return state

    def _run(self, state: JobState, fn: Callable[[], dict[str, Any]]) -> None:
        try:
            ket_qua = fn()
        except Exception as exc:  # noqa: BLE001 - job hỏng phải thành trạng thái, không giết luồng
            with self._lock:
                state.status = "failed"
                state.message = f"{type(exc).__name__}: {exc}"
                state.finished_at = now_utc()
            return
        with self._lock:
            #: "Hàm chạy xong" **không** đồng nghĩa "việc đã xong". ``run_make``
            #: trả ``ok=False`` khi lượt render thất bại — nếu vẫn báo
            #: ``succeeded`` thì giao diện nói dối về kết quả, và người dùng đi
            #: tìm một file MP4 không tồn tại. Lượt ``09fb9c1e14d3`` của D06-B là
            #: bằng chứng: TTS hỏng, manifest ``failed``, job vẫn xanh.
            thanh_cong = bool(ket_qua.get("ok", True))
            state.status = "succeeded" if thanh_cong else "failed"
            state.result = ket_qua
            state.log = str(ket_qua.pop("log", "") or state.log)
            state.message = str(
                ket_qua.get("message", "") or ("Xong." if thanh_cong else "Lượt dựng thất bại.")
            )
            state.finished_at = now_utc()

    def current(self) -> JobState | None:
        with self._lock:
            return self._state

    def busy(self) -> bool:
        with self._lock:
            return self._state is not None and self._state.running

    def join(self, timeout: float | None = None) -> None:
        """Chờ job hiện tại xong. Chỉ dùng cho test và lúc tắt server."""
        if self._thread is not None:
            self._thread.join(timeout=timeout)

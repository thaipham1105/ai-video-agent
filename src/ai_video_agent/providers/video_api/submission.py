"""Máy trạng thái bảo đảm **gửi đúng một lần** cho provider sinh video trả phí.

Vấn đề cốt lõi: một lần ``submit`` có thể tạo ra một generation **bị tính tiền**,
còn ``poll`` và ``download`` thì không. Gộp cả ba vào một ``max_retries`` chung —
như ``CallPolicy.max_retries = 1`` hiện tại — là cách chắc chắn để trả tiền hai lần.

Thứ tự ghi đĩa là thứ bảo vệ thật, không phải khoá idempotency:

    ghi + flush SUBMITTING  ->  gọi mạng  ->  ghi + flush operation_name

Nếu tiến trình chết giữa bước 1 và bước 3, lần khởi động sau đọc được
``SUBMITTING`` mà không có ``operation_name`` và chuyển sang
:attr:`SubmissionState.SUBMISSION_UNKNOWN` — **không bao giờ tự gửi lại**.

Một điều cố ý **không** khẳng định: rằng ``idempotency_key`` của repo này ngăn
được tính tiền hai lần. Nó chỉ có tác dụng nếu provider nhận và tôn trọng khoá
đó, mà điều ấy chưa được xác minh. Nó ở đây với vai trò khoá truy vết nội bộ.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from ai_video_agent.errors import ProviderError, SubmissionUnknownError
from ai_video_agent.providers.video_api.serialization import normalize, write_usage_safely


class SubmissionState(StrEnum):
    """Các trạng thái của một lần gửi. Xem D05-C §5.1."""

    AUTHORIZED = "AUTHORIZED"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    POLLING = "POLLING"
    DOWNLOADED = "DOWNLOADED"
    QC_PENDING = "QC_PENDING"
    HUMAN_APPROVED = "HUMAN_APPROVED"
    REJECTED = "REJECTED"
    #: Chết giữa chừng, không biết provider đã nhận hay chưa.
    SUBMISSION_UNKNOWN = "SUBMISSION_UNKNOWN"


#: Trạng thái cuối — không đi tiếp được nữa.
TERMINAL_STATES = frozenset(
    {
        SubmissionState.HUMAN_APPROVED,
        SubmissionState.REJECTED,
        SubmissionState.SUBMISSION_UNKNOWN,
    }
)


@dataclass
class SubmissionRecord:
    """Bản ghi bền vững của một lần gửi."""

    submission_id: str
    state: str = SubmissionState.AUTHORIZED.value
    model_id: str = ""
    idempotency_key: str = ""
    #: Bằng chứng provider đã nhận. Có nó thì poll/download an toàn để thử lại.
    operation_name: str | None = None
    submit_attempts: int = 0
    result_path: str | None = None
    #: Ghi thô trước khi chuẩn hoá — chuẩn hoá hỏng vẫn còn dữ liệu tính tiền.
    raw_usage_repr: str | None = None
    usage: dict[str, object] | None = None
    history: list[str] = field(default_factory=list)
    note: str = ""


class SubmissionStore:
    """Lưu bản ghi ra JSON, ghi có ``flush`` + ``fsync``.

    Không dùng ghi bộ đệm thông thường: nếu tiến trình chết trước khi dữ liệu
    chạm đĩa thì toàn bộ cơ chế write-ahead trở nên vô nghĩa.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.is_file()

    def save(self, record: SubmissionRecord) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(record), indent=2, ensure_ascii=False)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(self._path)

    def load(self) -> SubmissionRecord:
        data = json.loads(self._path.read_text(encoding="utf-8"))
        return SubmissionRecord(**data)


@dataclass(frozen=True)
class RetryPolicy:
    """Ba hành động, ba chính sách. Cố ý **không** gộp chung một con số.

    ``submit_attempts = 1`` nghĩa là gửi đúng một lần, không có lần thứ hai.
    """

    submit_attempts: int = 1
    poll_attempts: int = 30
    download_attempts: int = 3

    def __post_init__(self) -> None:
        if self.submit_attempts != 1:
            msg = (
                "submit_attempts phải bằng 1: mỗi lần gửi có thể tạo một generation "
                "bị tính tiền. Muốn thử lại thì phải là quyết định của con người."
            )
            raise ValueError(msg)


class VideoTransport(Protocol):
    """Ranh giới với thế giới bên ngoài.

    Tách ra thành Protocol để toàn bộ máy trạng thái test được bằng transport
    giả, **không cần API key, không chạm mạng**.
    """

    def submit(self, payload: dict[str, object], idempotency_key: str) -> str:
        """Gửi yêu cầu, trả về ``operation_name``."""
        ...

    def poll(self, operation_name: str) -> tuple[bool, dict[str, object] | None]:
        """Trả về ``(đã_xong, usage_thô)``."""
        ...

    def download(self, operation_name: str, out_path: Path) -> Path:
        """Tải kết quả về ``out_path``."""
        ...


def _retry[T](attempts: int, action: Callable[[], T], what: str) -> T:
    """Thử lại một hành động **không** tạo generation mới."""
    last: Exception | None = None
    for _ in range(attempts):
        try:
            return action()
        except Exception as exc:  # noqa: BLE001 - gom lại để báo sau khi hết lượt
            last = exc
    msg = f"{what} thất bại sau {attempts} lần thử: {last}"
    raise ProviderError(msg)


class SubmissionMachine:
    """Điều phối vòng đời một lần gửi, bảo đảm gửi đúng một lần."""

    def __init__(
        self,
        *,
        store: SubmissionStore,
        transport: VideoTransport,
        policy: RetryPolicy | None = None,
    ) -> None:
        self._store = store
        self._transport = transport
        self._policy = policy or RetryPolicy()

    @property
    def policy(self) -> RetryPolicy:
        return self._policy

    # ----- khôi phục sau khi khởi động lại ---------------------------------

    def recover(self) -> SubmissionRecord | None:
        """Đọc bản ghi cũ và quyết định trạng thái sau khi khởi động lại.

        ``SUBMITTING`` mà không có ``operation_name`` nghĩa là tiến trình chết
        đúng lúc không biết provider đã nhận hay chưa ⇒ chuyển
        ``SUBMISSION_UNKNOWN`` và dừng.
        """
        if not self._store.exists():
            return None
        record = self._store.load()
        if record.state == SubmissionState.SUBMITTING.value and not record.operation_name:
            record.state = SubmissionState.SUBMISSION_UNKNOWN.value
            record.note = (
                "Chết sau khi ghi SUBMITTING nhưng trước khi lưu được operation_name. "
                "KHÔNG tự gửi lại. Phải đối chiếu thủ công: bản ghi trên đĩa, hoặc "
                "billing console. Không giả định provider cho liệt kê operations."
            )
            record.history.append(SubmissionState.SUBMISSION_UNKNOWN.value)
            self._store.save(record)
        return record

    @staticmethod
    def assert_can_resubmit(record: SubmissionRecord) -> None:
        """Chặn mọi đường tự gửi lại từ trạng thái không xác định."""
        if record.state == SubmissionState.SUBMISSION_UNKNOWN.value:
            msg = (
                f"Lần gửi {record.submission_id} đang ở SUBMISSION_UNKNOWN. "
                "Không được tự gửi lại — có thể provider đã nhận và đã tính tiền. "
                "Cần con người đối chiếu rồi quyết định."
            )
            raise SubmissionUnknownError(msg)

    # ----- đường đi chính ---------------------------------------------------

    def submit_once(
        self,
        *,
        submission_id: str,
        model_id: str,
        payload: dict[str, object],
        idempotency_key: str,
    ) -> SubmissionRecord:
        """Gửi **đúng một lần**, với write-ahead trước khi chạm mạng."""
        existing = self.recover()
        if existing is not None:
            self.assert_can_resubmit(existing)
            if existing.operation_name:
                return existing

        record = SubmissionRecord(
            submission_id=submission_id,
            model_id=model_id,
            idempotency_key=idempotency_key,
            state=SubmissionState.SUBMITTING.value,
            submit_attempts=1,
            history=[SubmissionState.AUTHORIZED.value, SubmissionState.SUBMITTING.value],
        )
        # WRITE-AHEAD: phải chạm đĩa TRƯỚC khi chạm mạng.
        self._store.save(record)

        try:
            operation_name = self._transport.submit(payload, idempotency_key)
        except Exception as exc:  # mọi lỗi đều fail closed, kể cả lỗi lạ
            record.state = SubmissionState.SUBMISSION_UNKNOWN.value
            record.note = (
                f"Lỗi transport khi gửi: {type(exc).__name__}: {exc}. "
                "Không xác định được provider đã nhận hay chưa ⇒ fail closed, "
                "KHÔNG tự gửi lại."
            )
            record.history.append(SubmissionState.SUBMISSION_UNKNOWN.value)
            self._store.save(record)
            raise SubmissionUnknownError(record.note) from exc

        # Có operation_name thì ghi NGAY, trước mọi thao tác khác.
        record.operation_name = operation_name
        record.state = SubmissionState.SUBMITTED.value
        record.history.append(SubmissionState.SUBMITTED.value)
        self._store.save(record)
        return record

    def poll_until_done(self, record: SubmissionRecord) -> SubmissionRecord:
        """Hỏi trạng thái — được thử lại vì **không tạo generation mới**."""
        if not record.operation_name:
            msg = "Không thể poll khi chưa có operation_name."
            raise SubmissionUnknownError(msg)
        operation_name = record.operation_name

        record.state = SubmissionState.POLLING.value
        record.history.append(SubmissionState.POLLING.value)
        self._store.save(record)

        def _one() -> tuple[bool, dict[str, object] | None]:
            done, usage = self._transport.poll(operation_name)
            if not done:
                msg = "operation chưa xong"
                raise ProviderError(msg)
            return done, usage

        _, usage = _retry(self._policy.poll_attempts, _one, "Poll operation")
        self._persist_usage(record, usage)
        return record

    def _persist_usage(self, record: SubmissionRecord, usage: object) -> None:
        """Lưu usage sao cho **không bước nào** có thể làm mất kết quả đã trả tiền.

        Thứ tự cố định:

        1. ``repr`` thô vào bản ghi, lưu ngay — rẻ, gần như không thể hỏng.
        2. Ghi hai file usage cạnh bản ghi (thô + đã chuẩn hoá).
        3. Chuẩn hoá vào ``record.usage``.

        Mỗi bước sau bước 1 đều được bọc riêng: hỏng thì ghi lý do vào ``note``
        rồi đi tiếp. ``operation_name`` và ``result_path`` **không bao giờ** bị
        đụng tới trong hàm này — đó chính là thứ đã mất ở D05-B khi
        ``json.dumps`` chết vì ``ModalityTokens``.
        """
        try:
            record.raw_usage_repr = repr(usage)
        except Exception as exc:  # noqa: BLE001 - repr của object lạ cũng có thể hỏng
            record.raw_usage_repr = f"<repr hỏng: {type(exc).__name__}>"
        self._store.save(record)

        base = self._store.path.parent
        stem = self._store.path.stem
        try:
            report = write_usage_safely(
                raw_usage=usage,
                raw_path=base / f"{stem}.usage.raw.txt",
                normalized_path=base / f"{stem}.usage.json",
            )
            if report.get("error"):
                record.note = f"{record.note} | ghi usage: {report['error']}".strip(" |")
        except Exception as exc:  # noqa: BLE001 - ghi file hỏng không được làm mất gì
            record.note = f"{record.note} | ghi usage hỏng: {type(exc).__name__}".strip(" |")

        try:
            normalized = normalize(usage)
            record.usage = normalized if isinstance(normalized, dict) else {"value": normalized}
        except Exception as exc:  # noqa: BLE001 - chuẩn hoá hỏng thì vẫn còn repr thô
            record.usage = None
            record.note = f"{record.note} | chuẩn hoá usage hỏng: {type(exc).__name__}".strip(" |")

        self._store.save(record)

    def download(self, record: SubmissionRecord, out_path: Path) -> SubmissionRecord:
        """Tải kết quả — được thử lại từ operation/file đã tồn tại."""
        if not record.operation_name:
            msg = "Không thể tải khi chưa có operation_name."
            raise SubmissionUnknownError(msg)
        operation_name = record.operation_name

        produced = _retry(
            self._policy.download_attempts,
            lambda: self._transport.download(operation_name, out_path),
            "Download ket qua",
        )
        record.result_path = str(produced)
        record.state = SubmissionState.DOWNLOADED.value
        record.history.append(SubmissionState.DOWNLOADED.value)
        self._store.save(record)
        return record

    def mark_qc_pending(self, record: SubmissionRecord) -> SubmissionRecord:
        record.state = SubmissionState.QC_PENDING.value
        record.history.append(SubmissionState.QC_PENDING.value)
        self._store.save(record)
        return record

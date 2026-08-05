"""API sinh video trả phí — mở ở Gate D05, mặc định TẮT.

Brief §D05.3 bắt buộc mỗi lời gọi phải có đủ: estimate, hard cap, phê duyệt rõ
ràng, timeout, giới hạn retry và idempotency. Adapter này khai báo sẵn cả sáu
ràng buộc để D05 chỉ việc nối phần HTTP vào, không phải thiết kế lại chính sách.

Khoá an toàn ở D01, theo thứ tự kiểm tra:

1. Gate D05 chưa mở      -> :class:`GateNotReachedError`
2. Cost guard            -> chặn nếu project chưa APPROVED hoặc vượt trần
3. Không đọc API key     -> adapter chỉ kiểm tra *sự tồn tại* của biến môi trường
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from ai_video_agent import gate_is_open
from ai_video_agent.config import secret_present
from ai_video_agent.domain.enums import ProviderKind, ProviderMode, RenderStage
from ai_video_agent.errors import GateNotReachedError
from ai_video_agent.providers.base import (
    BrollRequest,
    BrollResult,
    CostQuote,
    ProviderInfo,
)
from ai_video_agent.providers.pricing import VIDEO_API_GENERIC

GATE = "D05"

#: Tên biến chứa key. Giá trị KHÔNG BAO GIỜ được đọc trong repo này.
API_KEY_ENV = "AIVA_VIDEO_API_KEY"


@dataclass(frozen=True)
class CallPolicy:
    """Chính sách gọi API bắt buộc theo brief §D05.3."""

    timeout_sec: int = 600
    max_retries: int = 1
    max_usd_per_run: float = 0.0
    require_explicit_approval: bool = True


class VideoApiBrollProvider:
    """Client cho API sinh video tính tiền."""

    def __init__(
        self,
        *,
        provider_name: str = "video-api",
        model: str = "unset",
        policy: CallPolicy | None = None,
    ) -> None:
        self._provider_name = provider_name
        self._model = model
        self._policy = policy or CallPolicy()

    @property
    def policy(self) -> CallPolicy:
        return self._policy

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name=self._provider_name,
            kind=ProviderKind.BROLL,
            model=self._model,
            version="unpinned-until-D05",
            mode=ProviderMode.REAL,
            billable=True,
            gate=GATE,
        )

    def api_key_configured(self) -> bool:
        """Chỉ cho biết key có tồn tại hay không, không đọc nội dung."""
        return secret_present(API_KEY_ENV)

    def idempotency_key(self, request: BrollRequest, project_id: str) -> str:
        """Khoá idempotency ổn định: cùng yêu cầu -> cùng khoá -> không trả tiền hai lần."""
        material = "|".join(
            [
                project_id,
                request.shot_id,
                request.prompt_vi,
                f"{request.duration_sec:.3f}",
                f"{request.width}x{request.height}@{request.fps}",
                str(request.seed),
                self._model,
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]

    def quote(self, request: BrollRequest) -> CostQuote:
        units = round(request.duration_sec, 3)
        return CostQuote(
            stage=RenderStage.BROLL,
            provider=self._provider_name,
            model=self._model,
            unit=VIDEO_API_GENERIC.unit,
            units=units,
            unit_price_usd=VIDEO_API_GENERIC.unit_price_usd,
            estimated_usd=round(units * VIDEO_API_GENERIC.unit_price_usd, 4),
            billable=True,
            assumption=VIDEO_API_GENERIC.assumption,
        )

    def generate(self, request: BrollRequest, out_path: Path) -> BrollResult:
        if not gate_is_open(GATE):
            raise GateNotReachedError(
                "API sinh video trả phí",
                GATE,
                hint=(
                    "Cần estimate + hard cap + phê duyệt rõ ràng của người dùng. "
                    "Giữ AIVA_ALLOW_PAID_APIS=0 cho tới khi D05 được duyệt."
                ),
            )
        raise NotImplementedError  # pragma: no cover - mở ở D05

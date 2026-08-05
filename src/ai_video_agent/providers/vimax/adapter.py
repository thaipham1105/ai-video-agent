"""Adapter ViMax thật — mở ở Gate D05.

Bằng chứng (D00 §4.3): ViMax là dự án Python/uv, chạy qua CLI/module, có Web UI
Node ở ``127.0.0.1:4173``. Nó **bắt buộc API trả phí** ở cả ba lớp (LLM, image,
video) nên đúng định vị trong brief §1.5: mô-đun mở rộng, không phải phụ thuộc
của MVP, và không được thay Duix ở nhiệm vụ avatar nói (brief §D05.2).

Brief §D05.4 còn cấm ViMax tự gọi API khi người dùng đang sửa storyboard —
ràng buộc đó do :mod:`ai_video_agent.orchestrator.costguard` thực thi (chỉ trạng
thái đã APPROVED mới được chạy thật).
"""

from __future__ import annotations

from pathlib import Path

from ai_video_agent import gate_is_open
from ai_video_agent.domain.enums import ProviderKind, ProviderMode, RenderStage
from ai_video_agent.errors import GateNotReachedError
from ai_video_agent.providers.base import (
    BrollRequest,
    BrollResult,
    CostQuote,
    ProviderInfo,
)
from ai_video_agent.providers.pricing import VIMAX_ORCHESTRATED

GATE = "D05"


class ViMaxBrollProvider:
    """Gọi ViMax qua CLI/module để dựng B-roll nhiều cảnh."""

    def __init__(self, *, model: str = "vimax", workdir: Path | None = None) -> None:
        self._model = model
        self._workdir = workdir

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="vimax",
            kind=ProviderKind.BROLL,
            model=self._model,
            version="unpinned-until-D05",
            mode=ProviderMode.REAL,
            billable=True,
            gate=GATE,
        )

    def quote(self, request: BrollRequest) -> CostQuote:
        units = round(request.duration_sec, 3)
        return CostQuote(
            stage=RenderStage.BROLL,
            provider="vimax",
            model=self._model,
            unit=VIMAX_ORCHESTRATED.unit,
            units=units,
            unit_price_usd=VIMAX_ORCHESTRATED.unit_price_usd,
            estimated_usd=round(units * VIMAX_ORCHESTRATED.unit_price_usd, 4),
            billable=True,
            assumption=VIMAX_ORCHESTRATED.assumption,
        )

    def generate(self, request: BrollRequest, out_path: Path) -> BrollResult:
        if not gate_is_open(GATE):
            raise GateNotReachedError(
                "ViMax thật (gọi API LLM/image/video trả phí)",
                GATE,
                hint="MVP không phụ thuộc ViMax. Giữ broll=none cho tới khi D05 được duyệt.",
            )
        raise NotImplementedError  # pragma: no cover - mở ở D05

"""B-roll giả lập, dùng chung cho ViMax lẫn API video.

Mock cố ý **vẫn báo giá như hàng tính tiền** (``billable = True``) để đường đi
của cost guard được kiểm thử thật sự: nếu ai đó nới lỏng luật chặn chi tiêu,
test sẽ đỏ ngay ở chế độ mock chứ không phải chờ tới lúc mất tiền thật.
"""

from __future__ import annotations

from pathlib import Path

from ai_video_agent.domain.enums import ProviderKind, ProviderMode, RenderStage
from ai_video_agent.providers._placeholder import write_placeholder_video
from ai_video_agent.providers.base import (
    BrollRequest,
    BrollResult,
    CostQuote,
    ProviderInfo,
)
from ai_video_agent.providers.pricing import VIMAX_ORCHESTRATED, PriceBook

MOCK_VERSION = "0.1.0"


class MockBrollProvider:
    """Sinh file B-roll đánh dấu và báo giá theo bảng giá giả định."""

    def __init__(
        self,
        *,
        name: str = "vimax",
        model: str = "vimax-mock",
        price: PriceBook = VIMAX_ORCHESTRATED,
    ) -> None:
        self._name = name
        self._model = model
        self._price = price

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name=self._name,
            kind=ProviderKind.BROLL,
            model=self._model,
            version=MOCK_VERSION,
            mode=ProviderMode.MOCK,
            billable=self._price.billable,
            gate="D01",
        )

    def quote(self, request: BrollRequest) -> CostQuote:
        units = round(request.duration_sec, 3)
        return CostQuote(
            stage=RenderStage.BROLL,
            provider=self._name,
            model=self._model,
            unit=self._price.unit,
            units=units,
            unit_price_usd=self._price.unit_price_usd,
            estimated_usd=round(units * self._price.unit_price_usd, 4),
            billable=self._price.billable,
            assumption=self._price.assumption,
        )

    def generate(self, request: BrollRequest, out_path: Path) -> BrollResult:
        write_placeholder_video(
            out_path,
            {
                "provider": self._name,
                "model": self._model,
                "version": MOCK_VERSION,
                "shot_id": request.shot_id,
                "prompt_vi": request.prompt_vi,
                "duration_sec": request.duration_sec,
                "width": request.width,
                "height": request.height,
                "fps": request.fps,
                "seed": request.seed,
                "warning": "File giả do mock sinh ra. KHÔNG gọi API, KHÔNG mất tiền.",
            },
        )
        return BrollResult(
            path=out_path,
            duration_sec=request.duration_sec,
            width=request.width,
            height=request.height,
            fps=request.fps,
            is_placeholder=True,
            #: Mock không tiêu tiền thật, dù báo giá là billable.
            actual_cost_usd=0.0,
        )

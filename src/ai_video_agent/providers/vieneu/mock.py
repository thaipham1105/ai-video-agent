"""VieNeu-TTS giả lập — chạy được toàn bộ đường đi mà không cần model."""

from __future__ import annotations

from pathlib import Path

from ai_video_agent.domain.enums import ProviderKind, ProviderMode, RenderStage
from ai_video_agent.providers._placeholder import write_silent_wav
from ai_video_agent.providers.base import (
    CostQuote,
    ProviderInfo,
    TtsRequest,
    TtsResult,
)
from ai_video_agent.providers.pricing import VIENEU_LOCAL, duration_from_text

MOCK_MODEL = "vieneu-mock"
MOCK_VERSION = "0.1.0"


class MockVieNeuTtsProvider:
    """Sinh WAV im lặng có đúng thời lượng ước tính từ độ dài thoại.

    Thời lượng dùng chung công thức với planner và estimator
    (:func:`~ai_video_agent.providers.pricing.duration_from_text`) nên số giây
    trong storyboard, trong báo giá và trong file WAV luôn khớp nhau.
    """

    def __init__(self, *, sample_rate: int = 48_000, channels: int = 1) -> None:
        self._sample_rate = sample_rate
        self._channels = channels

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="vieneu",
            kind=ProviderKind.TTS,
            model=MOCK_MODEL,
            version=MOCK_VERSION,
            mode=ProviderMode.MOCK,
            billable=False,
            gate="D01",
        )

    def quote(self, request: TtsRequest) -> CostQuote:
        units = float(len(request.text_vi))
        return CostQuote(
            stage=RenderStage.TTS,
            provider="vieneu",
            model=MOCK_MODEL,
            unit=VIENEU_LOCAL.unit,
            units=units,
            unit_price_usd=VIENEU_LOCAL.unit_price_usd,
            estimated_usd=0.0,
            billable=False,
            assumption=VIENEU_LOCAL.assumption,
        )

    def synthesize(self, request: TtsRequest, out_path: Path) -> TtsResult:
        duration = request.target_duration_sec or duration_from_text(request.text_vi)
        sample_rate = request.sample_rate or self._sample_rate
        write_silent_wav(
            out_path,
            duration_sec=duration,
            sample_rate=sample_rate,
            channels=self._channels,
        )
        return TtsResult(
            path=out_path,
            duration_sec=round(duration, 3),
            sample_rate=sample_rate,
            channels=self._channels,
            is_placeholder=True,
            actual_cost_usd=0.0,
        )

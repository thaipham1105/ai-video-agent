"""Duix-Avatar giả lập — không Docker, không GPU, không tải ~70 GB image."""

from __future__ import annotations

from pathlib import Path

from ai_video_agent.domain.enums import ProviderKind, ProviderMode, RenderStage
from ai_video_agent.providers._placeholder import read_wav_duration, write_placeholder_video
from ai_video_agent.providers.base import (
    AvatarRequest,
    AvatarResult,
    CostQuote,
    ProviderInfo,
)
from ai_video_agent.providers.pricing import DUIX_LOCAL

MOCK_MODEL = "duix-avatar-mock"
MOCK_VERSION = "0.1.0"


class MockDuixAvatarProvider:
    """Sinh file đánh dấu có metadata khớp với WAV đầu vào.

    Thời lượng lấy từ **file WAV thật** chứ không từ tham số, nên nếu bước TTS
    sinh sai độ dài thì test đồng bộ audio/video sẽ bắt được ngay.
    """

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="duix",
            kind=ProviderKind.AVATAR,
            model=MOCK_MODEL,
            version=MOCK_VERSION,
            mode=ProviderMode.MOCK,
            billable=False,
            gate="D01",
        )

    def quote(self, request: AvatarRequest) -> CostQuote:
        seconds = request.duration_sec or self._duration_of(request.audio_path)
        return CostQuote(
            stage=RenderStage.AVATAR,
            provider="duix",
            model=MOCK_MODEL,
            unit=DUIX_LOCAL.unit,
            units=seconds,
            unit_price_usd=DUIX_LOCAL.unit_price_usd,
            estimated_usd=0.0,
            billable=False,
            assumption=DUIX_LOCAL.assumption,
        )

    def generate(self, request: AvatarRequest, out_path: Path) -> AvatarResult:
        duration = self._duration_of(request.audio_path)
        write_placeholder_video(
            out_path,
            {
                "provider": "duix",
                "model": MOCK_MODEL,
                "version": MOCK_VERSION,
                "shot_id": request.shot_id,
                "audio_path": request.audio_path.name,
                "avatar_source": (request.avatar_source.name if request.avatar_source else None),
                "duration_sec": duration,
                "width": request.width,
                "height": request.height,
                "fps": request.fps,
                "seed": request.seed,
                "warning": "File giả do mock sinh ra. KHÔNG phải video thật.",
            },
        )
        return AvatarResult(
            path=out_path,
            duration_sec=duration,
            width=request.width,
            height=request.height,
            fps=request.fps,
            is_placeholder=True,
            actual_cost_usd=0.0,
        )

    @staticmethod
    def _duration_of(audio_path: Path) -> float:
        if audio_path.is_file() and audio_path.suffix.lower().endswith("wav"):
            return read_wav_duration(audio_path)
        return 0.0

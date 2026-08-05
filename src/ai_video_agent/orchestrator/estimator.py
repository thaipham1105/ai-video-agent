"""Ước tính chi phí cho một storyboard, **trước** khi chạm vào provider.

Hai nguyên tắc:

* Cộng tiền bằng :class:`~decimal.Decimal` và **làm tròn LÊN** tới 1/100 cent.
  Ước tính thấp hơn thực tế nguy hiểm hơn nhiều so với ước tính cao hơn, vì nó
  có thể lọt qua trần ngân sách.
* Mọi dòng chi phí đều kèm giả định để người dùng đối chiếu, đúng brief §D05.5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

from ai_video_agent.domain.enums import BrollKind, RenderStage
from ai_video_agent.domain.project import Project
from ai_video_agent.domain.render import CostLine
from ai_video_agent.domain.storyboard import Storyboard
from ai_video_agent.providers.base import (
    AvatarRequest,
    BrollRequest,
    CostQuote,
    ProviderSet,
    TtsRequest,
)

_CENT_HUNDREDTH = Decimal("0.0001")


def _ceil_usd(value: Decimal) -> float:
    """Làm tròn lên, không bao giờ báo thấp hơn thực tế."""
    return float(value.quantize(_CENT_HUNDREDTH, rounding=ROUND_CEILING))


@dataclass(frozen=True)
class Estimate:
    """Bảng chi phí dự kiến của một lần render."""

    project_id: str
    lines: list[CostLine] = field(default_factory=list)
    total_usd: float = 0.0
    billable_usd: float = 0.0
    total_duration_sec: float = 0.0
    warnings: list[str] = field(default_factory=list)

    @property
    def billable_lines(self) -> list[CostLine]:
        return [line for line in self.lines if line.billable]

    @property
    def has_billable(self) -> bool:
        return bool(self.billable_lines)


def _line_from_quote(quote: CostQuote) -> CostLine:
    return CostLine(
        stage=quote.stage,
        provider=quote.provider,
        model=quote.model,
        unit=quote.unit,
        units=round(quote.units, 3),
        unit_price_usd=quote.unit_price_usd,
        estimated_usd=quote.estimated_usd,
        billable=quote.billable,
        assumption=quote.assumption,
    )


def estimate_storyboard(
    project: Project,
    storyboard: Storyboard,
    providers: ProviderSet,
) -> Estimate:
    """Gộp báo giá của mọi shot thành một bảng chi phí duy nhất."""
    width, height = project.aspect_ratio.size
    lines: list[CostLine] = []
    warnings: list[str] = []

    for shot in storyboard.shots:
        lines.append(
            _line_from_quote(
                providers.tts.quote(
                    TtsRequest(
                        shot_id=shot.id,
                        text_vi=shot.narration_vi,
                        target_duration_sec=shot.duration_sec,
                    )
                )
            )
        )
        lines.append(
            _line_from_quote(
                providers.avatar.quote(
                    AvatarRequest(
                        shot_id=shot.id,
                        # Ước tính chạy trước khi có WAV; ``duration_sec`` bên dưới
                        # mới là thứ quyết định báo giá.
                        audio_path=Path(f"{shot.id}.wav"),
                        avatar_source=None,
                        width=width,
                        height=height,
                        fps=project.fps,
                        duration_sec=shot.duration_sec,
                    )
                )
            )
        )
        if shot.broll.kind in {BrollKind.VIMAX, BrollKind.VIDEO_API}:
            if providers.broll is None:
                warnings.append(
                    f"Shot {shot.id} yêu cầu B-roll '{shot.broll.kind.value}' nhưng project "
                    "đang đặt providers.broll = none — shot sẽ bị bỏ qua."
                )
            else:
                lines.append(
                    _line_from_quote(
                        providers.broll.quote(
                            BrollRequest(
                                shot_id=shot.id,
                                prompt_vi=shot.broll.prompt_vi or shot.narration_vi,
                                duration_sec=shot.duration_sec,
                                width=width,
                                height=height,
                                fps=project.fps,
                            )
                        )
                    )
                )

    lines.append(
        CostLine(
            stage=RenderStage.COMPOSE,
            provider="ffmpeg",
            model="local",
            unit="second",
            units=storyboard.total_duration_sec,
            unit_price_usd=0.0,
            estimated_usd=0.0,
            billable=False,
            assumption="FFmpeg chạy local. Chi phí = thời gian CPU, không phải hoá đơn API.",
        )
    )

    total = sum((Decimal(str(line.estimated_usd)) for line in lines), Decimal(0))
    billable = sum(
        (Decimal(str(line.estimated_usd)) for line in lines if line.billable), Decimal(0)
    )

    if billable > 0 and project.budget.cap_usd <= 0:
        warnings.append(
            "Storyboard có bước tính tiền nhưng budget.cap_usd = 0 — render thật sẽ bị chặn."
        )

    return Estimate(
        project_id=project.id,
        lines=lines,
        total_usd=_ceil_usd(total),
        billable_usd=_ceil_usd(billable),
        total_duration_sec=storyboard.total_duration_sec,
        warnings=warnings,
    )

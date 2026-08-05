"""Giao diện chung cho mọi provider.

Mỗi provider phải trả lời được ba câu hỏi trước khi làm bất cứ việc gì:

1. ``info()``  — tôi là ai, model/version nào, mock hay thật, có tính tiền không.
2. ``quote()`` — việc này tốn bao nhiêu, dựa trên giả định gì.
3. hàm chạy    — thực thi và trả về artifact đã ghi ra đĩa.

Nhờ ``quote()`` tách khỏi hàm chạy, ``aiva estimate`` và ``aiva render --dry-run``
lấy được toàn bộ bảng chi phí mà **không** chạm vào provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from ai_video_agent.domain.enums import ProviderKind, ProviderMode, RenderStage


@dataclass(frozen=True)
class ProviderInfo:
    """Danh tính provider, ghi thẳng vào ``render-manifest.json``."""

    name: str
    kind: ProviderKind
    model: str
    version: str
    mode: ProviderMode
    #: ``True`` nếu provider gọi API tính tiền. Cost guard chặn dựa vào cờ này.
    billable: bool = False
    #: Gate mở tính năng thật của provider (``D02``/``D03``/``D05``).
    gate: str = "D01"


@dataclass(frozen=True)
class CostQuote:
    """Báo giá cho một đơn vị công việc, kèm giả định để người dùng kiểm chứng."""

    stage: RenderStage
    provider: str
    model: str
    unit: str
    units: float
    unit_price_usd: float
    estimated_usd: float
    billable: bool
    assumption: str = ""


@dataclass(frozen=True)
class TtsRequest:
    """Yêu cầu tổng hợp giọng nói."""

    shot_id: str
    text_vi: str
    #: Giọng dựng sẵn, hoặc ``None`` nếu dùng ``ref_audio``.
    voice: str | None = None
    #: Đường dẫn mẫu giọng đã có đồng ý sử dụng (chỉ mở từ D02).
    ref_audio: Path | None = None
    sample_rate: int = 48_000
    speed: float = 1.0
    target_duration_sec: float | None = None


@dataclass(frozen=True)
class TtsResult:
    """Kết quả WAV đã ghi ra đĩa."""

    path: Path
    duration_sec: float
    sample_rate: int
    channels: int = 1
    is_placeholder: bool = False
    actual_cost_usd: float | None = None


@dataclass(frozen=True)
class AvatarRequest:
    """Yêu cầu sinh video người đại diện nói."""

    shot_id: str
    audio_path: Path
    #: Video/ảnh nguồn của avatar — bắt buộc đã có ``consent = granted``.
    avatar_source: Path | None
    width: int
    height: int
    fps: int = 30
    seed: int | None = None
    #: Thời lượng dự kiến, để ``quote()`` chạy được khi file WAV chưa tồn tại
    #: (trường hợp ``estimate`` và ``render --dry-run``).
    duration_sec: float = 0.0


@dataclass(frozen=True)
class AvatarResult:
    path: Path
    duration_sec: float
    width: int
    height: int
    fps: int
    is_placeholder: bool = False
    actual_cost_usd: float | None = None


@dataclass(frozen=True)
class BrollRequest:
    """Yêu cầu sinh cảnh minh hoạ (ViMax hoặc API video, chỉ từ D05)."""

    shot_id: str
    prompt_vi: str
    duration_sec: float
    width: int
    height: int
    fps: int = 30
    seed: int | None = None


@dataclass(frozen=True)
class BrollResult:
    path: Path
    duration_sec: float
    width: int
    height: int
    fps: int
    is_placeholder: bool = False
    actual_cost_usd: float | None = None


@runtime_checkable
class TtsProvider(Protocol):
    """Provider sinh giọng đọc tiếng Việt."""

    def info(self) -> ProviderInfo: ...

    def quote(self, request: TtsRequest) -> CostQuote: ...

    def synthesize(self, request: TtsRequest, out_path: Path) -> TtsResult: ...


@runtime_checkable
class AvatarProvider(Protocol):
    """Provider sinh video người nói từ WAV + tài sản avatar."""

    def info(self) -> ProviderInfo: ...

    def quote(self, request: AvatarRequest) -> CostQuote: ...

    def generate(self, request: AvatarRequest, out_path: Path) -> AvatarResult: ...


@runtime_checkable
class BrollProvider(Protocol):
    """Provider sinh B-roll / cảnh nhiều shot."""

    def info(self) -> ProviderInfo: ...

    def quote(self, request: BrollRequest) -> CostQuote: ...

    def generate(self, request: BrollRequest, out_path: Path) -> BrollResult: ...


@dataclass
class ProviderSet:
    """Bộ provider đã chọn cho một lần chạy."""

    tts: TtsProvider
    avatar: AvatarProvider
    broll: BrollProvider | None = None
    notes: list[str] = field(default_factory=list)

    def infos(self) -> list[ProviderInfo]:
        found = [self.tts.info(), self.avatar.info()]
        if self.broll is not None:
            found.append(self.broll.info())
        return found

    @property
    def any_billable(self) -> bool:
        return any(info.billable for info in self.infos())

"""Duix-Avatar giả lập — không Docker, không GPU, không tải ~70 GB image."""

from __future__ import annotations

from pathlib import Path

from ai_video_agent.domain.enums import ProviderKind, ProviderMode, RenderStage
from ai_video_agent.providers._placeholder import read_wav_duration, write_placeholder_video
from ai_video_agent.providers.base import (
    AvatarCapability,
    AvatarProvenance,
    AvatarRequest,
    AvatarResult,
    CostQuote,
    ProviderInfo,
    ResourceEstimate,
    fingerprint_file,
)
from ai_video_agent.providers.duix.capability import DUIX_CAPABILITY
from ai_video_agent.providers.pricing import DUIX_LOCAL

MOCK_MODEL = "duix-avatar-mock"
MOCK_VERSION = "0.1.0"

#: Mock không nạp model nên tài nguyên gần như bằng 0 — nhưng vẫn phải khai
#: **thật**, không mượn số của adapter thật. Khai nhầm số của bản thật sẽ khiến
#: hàng rào VRAM chặn nhầm cả đường mock.
MOCK_RESOURCES = ResourceEstimate(
    vram_mib=0,
    ram_mib=64,
    storage_mib=1,
    deterministic_local=True,
    measured=True,
    measured_on="2026-08-07",
)


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

    def capability(self) -> AvatarCapability:
        """Cùng ràng buộc hình/tiếng với bản thật, chỉ khác danh tính và tài nguyên.

        Nếu mock khai năng lực rộng hơn bản thật, test sẽ xanh trên đường mock
        rồi vỡ khi chạy thật — đúng loại lỗi mock sinh ra để tránh.
        """
        real = DUIX_CAPABILITY
        return AvatarCapability(
            backend_id=real.backend_id,
            backend_version=MOCK_VERSION,
            native_fps=real.native_fps,
            supported_fps=real.supported_fps,
            max_width=real.max_width,
            max_height=real.max_height,
            audio_sample_rate_hz=real.audio_sample_rate_hz,
            audio_channels=real.audio_channels,
            audio_encoder=real.audio_encoder,
            languages_verified=real.languages_verified,
            accepts_image_source=real.accepts_image_source,
            accepts_video_source=real.accepts_video_source,
            requires_gate="D01",
            resources=MOCK_RESOURCES,
            source_url=real.source_url,
        )

    def estimate_resources(self, request: AvatarRequest) -> ResourceEstimate:
        del request
        return MOCK_RESOURCES

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
            provenance=self._provenance(request),
        )

    def _provenance(self, request: AvatarRequest) -> AvatarProvenance:
        """Mock cũng khai provenance — nhưng khai *sự thật về mock*.

        Nếu mock trả về ``None`` thì code đọc provenance sẽ chỉ được kiểm trên
        đường thật, tức là chỉ vỡ khi đã tốn GPU. Nếu mock chép danh tính của
        bản thật thì một file giả sẽ trông y hệt file thật trong manifest — nguy
        hiểm hơn nhiều. Nên: đúng hình dạng, đúng vân tay đầu vào, danh tính mock.
        """
        cap = self.capability()
        return AvatarProvenance(
            backend_id=cap.backend_id,
            backend_version=cap.backend_version,
            model=MOCK_MODEL,
            model_version=MOCK_VERSION,
            audio_encoder=cap.audio_encoder,
            source_fps=request.fps,
            audio_sha256=fingerprint_file(request.audio_path),
            source_asset_sha256=fingerprint_file(request.avatar_source),
            checkpoint_sha256="",
            image_digest="",
            params={"mode": "mock"},
            #: Mock không dựng gì; một con số thời gian ở đây sẽ bị đọc nhầm
            #: thành tốc độ render thật.
            render_seconds=None,
            peak_vram_mib=MOCK_RESOURCES.vram_mib,
        )

    @staticmethod
    def _duration_of(audio_path: Path) -> float:
        if audio_path.is_file() and audio_path.suffix.lower().endswith("wav"):
            return read_wav_duration(audio_path)
        return 0.0

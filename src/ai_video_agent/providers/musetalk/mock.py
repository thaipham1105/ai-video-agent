"""MuseTalk giả lập — không WSL, không GPU, không mạng, không ~15 GB weights."""

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
from ai_video_agent.providers.musetalk.capability import (
    MUSETALK_CAPABILITY,
    MUSETALK_LOCAL,
    REPO_COMMIT,
    UNET_SHA256,
)

MOCK_MODEL = "musetalk-v15-mock"
MOCK_VERSION = "0.1.0"

#: Mock không nạp model nên tài nguyên gần như bằng 0 — nhưng vẫn khai **thật**,
#: không mượn số 9.798 MiB của bản thật. Mượn số thật sẽ khiến hàng rào tài
#: nguyên chặn nhầm cả đường mock trên máy VRAM nhỏ.
MOCK_RESOURCES = ResourceEstimate(
    vram_mib=0,
    ram_mib=64,
    storage_mib=1,
    deterministic_local=True,
    measured=True,
    measured_on="2026-08-10",
)


class MockMuseTalkProvider:
    """Sinh file đánh dấu có metadata khớp WAV đầu vào.

    Thời lượng lấy từ **file WAV thật** chứ không từ tham số, nên nếu bước TTS
    sinh sai độ dài thì test đồng bộ audio/video sẽ bắt được ngay.
    """

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="musetalk",
            kind=ProviderKind.AVATAR,
            model=MOCK_MODEL,
            version=MOCK_VERSION,
            mode=ProviderMode.MOCK,
            billable=False,
            #: Mock chạy được từ D01 — nó không chạm WSL, GPU hay weights nào.
            gate="D01",
        )

    def capability(self) -> AvatarCapability:
        """Cùng ràng buộc hình/tiếng với bản thật, chỉ khác danh tính và tài nguyên.

        Mock khai năng lực **rộng hơn** bản thật là kiểu lỗi khiến test xanh trên
        đường mock rồi vỡ khi chạy thật — đúng loại lỗi mock sinh ra để tránh.
        """
        real = MUSETALK_CAPABILITY
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
            provider="musetalk",
            model=MOCK_MODEL,
            unit=MUSETALK_LOCAL.unit,
            units=seconds,
            unit_price_usd=MUSETALK_LOCAL.unit_price_usd,
            estimated_usd=0.0,
            billable=False,
            assumption=MUSETALK_LOCAL.assumption,
        )

    def generate(self, request: AvatarRequest, out_path: Path) -> AvatarResult:
        duration = self._duration_of(request.audio_path)
        write_placeholder_video(
            out_path,
            {
                "provider": "musetalk",
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
        """Khai **sự thật về mock**: đúng hình dạng, đúng vân tay đầu vào, danh tính mock.

        Trả ``None`` sẽ khiến code đọc provenance chỉ được kiểm trên đường thật —
        tức chỉ vỡ khi đã tốn GPU. Chép danh tính bản thật còn nguy hiểm hơn: một
        file giả sẽ trông y hệt file thật trong manifest.
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
            #: Mock KHÔNG khai băm checkpoint thật — nó chưa từng đọc file nào.
            checkpoint_sha256="",
            image_digest="",
            #: Tên khoá cố ý dài dòng: một công cụ grep commit hash **không được**
            #: hiểu nhầm manifest mock là bằng chứng đã chạy thật. "declares_target"
            #: nói rõ đây là bản mà mock ĐỨNG THAY, không phải bản đã nạp.
            params={
                "mode": "mock",
                "mock_declares_target_commit": REPO_COMMIT[:8],
                "mock_declares_target_unet_sha256": UNET_SHA256[:8],
            },
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

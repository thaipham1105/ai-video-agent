"""Năng lực đã xác minh của từng model sinh video, khoá theo **model ID chính xác**.

Nguyên tắc nền của module này, rút ra từ D05-C §1:

    **SDK có field KHÔNG chứng minh model hỗ trợ.**

``google.genai.types.GenerateVideosConfig`` có cả ``generate_audio`` lẫn ``fps``,
nhưng tài liệu model nói Veo 3.1 luôn xuất audio và cố định 24 fps. SDK phục vụ
nhiều model; sự tồn tại của một field không nói gì về model cụ thể. Vì vậy bảng
dưới đây lấy từ **tài liệu model**, không phải từ introspection SDK.

Nguồn: https://ai.google.dev/gemini-api/docs/veo (kiểm tra 2026-08-06)

Mọi cấu hình không tương thích phải chết ở đây — **trước** provider boundary —
để không bao giờ biến thành một lần gọi có thể bị tính tiền.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ai_video_agent.errors import CapabilityError

#: Nguồn duy nhất cho mọi số liệu năng lực trong file này.
CAPABILITY_SOURCE_URL = "https://ai.google.dev/gemini-api/docs/veo"
CAPABILITY_VERIFIED_ON = "2026-08-06"

VEO_STANDARD = "veo-3.1-generate-preview"
VEO_FAST = "veo-3.1-fast-generate-preview"
VEO_LITE = "veo-3.1-lite-generate-preview"

#: Pipeline này luôn xin đúng một video mỗi lần gọi.
PIPELINE_NUMBER_OF_VIDEOS = 1


@dataclass(frozen=True)
class ModelCapability:
    """Năng lực của một model, khoá theo model ID chính xác."""

    model_id: str
    #: ``always_on`` nghĩa là không bao giờ được gửi ``generate_audio=False``.
    audio_mode: str
    #: FPS model xuất ra. Cố định — không phải thứ gọi được bằng tham số.
    source_fps: int
    supported_resolutions: frozenset[str]
    supported_aspect_ratios: frozenset[str]
    #: ``resolution`` -> tập thời lượng (giây) được phép ở độ phân giải đó.
    duration_constraint: dict[str, frozenset[int]]
    supports_reference_images: bool
    max_reference_images: int
    supports_initial_image: bool
    source_url: str = CAPABILITY_SOURCE_URL
    verified_on: str = CAPABILITY_VERIFIED_ON
    notes: tuple[str, ...] = field(default_factory=tuple)


_COMMON_RES = frozenset({"720p", "1080p"})
_COMMON_RATIO = frozenset({"9:16", "16:9"})
#: 1080p bắt buộc đúng 8 giây (D05C §1.5).
_COMMON_DURATION = {"720p": frozenset({4, 6, 8}), "1080p": frozenset({8})}


CAPABILITIES: dict[str, ModelCapability] = {
    VEO_STANDARD: ModelCapability(
        model_id=VEO_STANDARD,
        audio_mode="always_on",
        source_fps=24,
        supported_resolutions=_COMMON_RES,
        supported_aspect_ratios=_COMMON_RATIO,
        duration_constraint=_COMMON_DURATION,
        supports_reference_images=True,
        max_reference_images=3,
        supports_initial_image=True,
        notes=("Ứng viên chất lượng production — CHƯA phải winner, chờ A/B.",),
    ),
    VEO_FAST: ModelCapability(
        model_id=VEO_FAST,
        audio_mode="always_on",
        source_fps=24,
        supported_resolutions=_COMMON_RES,
        supported_aspect_ratios=_COMMON_RATIO,
        duration_constraint=_COMMON_DURATION,
        supports_reference_images=True,
        max_reference_images=3,
        supports_initial_image=True,
    ),
    VEO_LITE: ModelCapability(
        model_id=VEO_LITE,
        audio_mode="always_on",
        source_fps=24,
        supported_resolutions=_COMMON_RES,
        supported_aspect_ratios=_COMMON_RATIO,
        duration_constraint=_COMMON_DURATION,
        #: Lite KHÔNG nhận reference_images…
        supports_reference_images=False,
        max_reference_images=0,
        #: …nhưng vẫn nhận một ảnh khởi tạo qua tham số ``image=`` của
        #: ``generate_videos()``. Hai đường hoàn toàn khác nhau.
        supports_initial_image=True,
        notes=("Không hỗ trợ reference_images; vẫn hỗ trợ initial image-to-video.",),
    ),
}


@dataclass(frozen=True)
class VideoRequestConfig:
    """Cấu hình một lần sinh video, trước khi chạm provider."""

    model_id: str
    resolution: str
    aspect_ratio: str
    duration_seconds: int
    number_of_videos: int = PIPELINE_NUMBER_OF_VIDEOS
    reference_image_count: int = 0
    has_initial_image: bool = False
    #: ``True`` khi người gọi muốn video **không có tiếng**.
    want_silent: bool = False
    #: Đặt khi người gọi muốn ép FPS khác FPS gốc của model.
    requested_fps: int | None = None


def get_capability(model_id: str) -> ModelCapability:
    """Tra năng lực theo model ID chính xác. Không đoán, không khớp mờ."""
    cap = CAPABILITIES.get(model_id)
    if cap is None:
        known = ", ".join(sorted(CAPABILITIES))
        msg = (
            f"Không có bản ghi năng lực cho model {model_id!r}. "
            f"Model đã xác minh: {known}. "
            "Không suy năng lực từ việc SDK có field tương ứng."
        )
        raise CapabilityError(msg)
    return cap


def check_config(config: VideoRequestConfig) -> ModelCapability:
    """Kiểm tra cấu hình trước provider boundary.

    Ném :class:`CapabilityError` ngay khi thấy điểm không khớp. Trả về năng lực
    đã tra được nếu mọi thứ hợp lệ.
    """
    cap = get_capability(config.model_id)

    if config.number_of_videos != PIPELINE_NUMBER_OF_VIDEOS:
        msg = (
            f"Pipeline này chỉ sinh đúng {PIPELINE_NUMBER_OF_VIDEOS} video mỗi lần gọi, "
            f"nhận được number_of_videos={config.number_of_videos}."
        )
        raise CapabilityError(msg)

    if config.resolution not in cap.supported_resolutions:
        msg = (
            f"{cap.model_id} không hỗ trợ độ phân giải {config.resolution!r}. "
            f"Hỗ trợ: {sorted(cap.supported_resolutions)}."
        )
        raise CapabilityError(msg)

    if config.aspect_ratio not in cap.supported_aspect_ratios:
        msg = (
            f"{cap.model_id} không hỗ trợ tỉ lệ {config.aspect_ratio!r}. "
            f"Hỗ trợ: {sorted(cap.supported_aspect_ratios)}."
        )
        raise CapabilityError(msg)

    allowed = cap.duration_constraint.get(config.resolution, frozenset())
    if config.duration_seconds not in allowed:
        msg = (
            f"{cap.model_id} ở {config.resolution} chỉ nhận thời lượng "
            f"{sorted(allowed)} giây, nhận được {config.duration_seconds}."
        )
        raise CapabilityError(msg)

    if config.reference_image_count > 0 and not cap.supports_reference_images:
        msg = (
            f"{cap.model_id} KHÔNG hỗ trợ reference_images "
            f"(yêu cầu {config.reference_image_count} ảnh). "
            "Dùng ảnh khởi tạo image-to-video, hoặc đổi sang model Standard/Fast."
        )
        raise CapabilityError(msg)

    if config.reference_image_count > cap.max_reference_images:
        msg = (
            f"{cap.model_id} nhận tối đa {cap.max_reference_images} reference_images, "
            f"yêu cầu {config.reference_image_count}."
        )
        raise CapabilityError(msg)

    if config.has_initial_image and not cap.supports_initial_image:
        msg = f"{cap.model_id} không hỗ trợ ảnh khởi tạo."
        raise CapabilityError(msg)

    if config.want_silent and cap.audio_mode == "always_on":
        msg = (
            f"{cap.model_id} luôn xuất video kèm audio (audio_mode=always_on) nên không "
            "nhận yêu cầu sinh video câm. KHÔNG gửi generate_audio=False. "
            "Composer được phép bỏ audio sau khi tải, nhưng giá vẫn tính như có audio."
        )
        raise CapabilityError(msg)

    if config.requested_fps is not None and config.requested_fps != cap.source_fps:
        msg = (
            f"{cap.model_id} xuất cố định {cap.source_fps} fps, không nhận "
            f"fps={config.requested_fps}. Việc đổi khung hình do composer làm."
        )
        raise CapabilityError(msg)

    return cap


def build_provider_payload(config: VideoRequestConfig) -> dict[str, object]:
    """Dựng payload gửi provider, **sau khi** cấu hình đã qua :func:`check_config`.

    Cố tình **không bao giờ** đặt ``generate_audio`` hay ``fps``: hai field đó có
    trong SDK nhưng không thuộc năng lực Veo, gửi đi chỉ tạo ảo giác điều khiển
    được thứ mình không điều khiển được.
    """
    cap = check_config(config)
    payload: dict[str, object] = {
        "model": cap.model_id,
        "aspect_ratio": config.aspect_ratio,
        "resolution": config.resolution,
        "duration_seconds": config.duration_seconds,
        "number_of_videos": config.number_of_videos,
    }
    return payload

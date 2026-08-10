"""Kiểm tương thích yêu cầu avatar với năng lực backend — **trước** khi chạm GPU.

Cùng triết lý với :mod:`ai_video_agent.providers.video_api.capability` đã dùng ở
D05-C: một cấu hình sai phải chết ở đây, không phải sau khi model đã nạp xong và
GPU đã chạy được nửa đường.

Khác biệt duy nhất: avatar chạy local nên cái đắt không phải tiền mà là **thời
gian GPU và VRAM**. Duix mất 22 s cho 7,6 s video, MuseTalk mất 211 s — hỏng ở
phút cuối vì một tham số sai là mất từng ấy thời gian.
"""

from __future__ import annotations

from ai_video_agent.errors import CapabilityError
from ai_video_agent.providers.base import AvatarCapability, AvatarRequest


def check_avatar_request(
    capability: AvatarCapability,
    request: AvatarRequest,
    *,
    available_vram_mib: int | None = None,
    source_is_image: bool | None = None,
) -> None:
    """Ném :class:`CapabilityError` ngay khi thấy điểm không khớp.

    ``available_vram_mib`` để ``None`` nghĩa là bỏ qua kiểm VRAM — dùng cho
    đường mock và cho lúc chưa đo được GPU. Cố ý **không** đoán một giá trị mặc
    định: đoán thừa thì chặn nhầm, đoán thiếu thì để lọt.
    """
    if request.fps not in capability.supported_fps:
        msg = (
            f"{capability.backend_id} không xuất được {request.fps} fps. "
            f"Hỗ trợ: {sorted(capability.supported_fps)} (gốc {capability.native_fps}). "
            "Việc đổi khung hình là của composer, không phải của backend."
        )
        raise CapabilityError(msg)

    if request.width > capability.max_width or request.height > capability.max_height:
        msg = (
            f"{capability.backend_id} tối đa "
            f"{capability.max_width}x{capability.max_height}, "
            f"yêu cầu {request.width}x{request.height}."
        )
        raise CapabilityError(msg)

    if request.width <= 0 or request.height <= 0:
        msg = f"Kích thước không hợp lệ: {request.width}x{request.height}."
        raise CapabilityError(msg)

    if source_is_image is True and not capability.accepts_image_source:
        msg = (
            f"{capability.backend_id} không nhận ảnh tĩnh làm nguồn avatar, "
            "chỉ nhận video."
        )
        raise CapabilityError(msg)
    if source_is_image is False and not capability.accepts_video_source:
        msg = f"{capability.backend_id} không nhận video làm nguồn avatar, chỉ nhận ảnh."
        raise CapabilityError(msg)

    if available_vram_mib is not None:
        need = capability.resources.vram_mib
        if need > available_vram_mib:
            source = "đo thật" if capability.resources.measured else "ước tính"
            msg = (
                f"{capability.backend_id} cần {need} MiB VRAM ({source}), "
                f"máy còn {available_vram_mib} MiB. Không nạp model."
            )
            raise CapabilityError(msg)


def language_is_verified(capability: AvatarCapability, language: str) -> bool:
    """Ngôn ngữ này đã được kiểm chứng trên backend chưa.

    Tách khỏi :func:`describe_language_fit` vì nơi gọi cần **quyết định** (có
    cảnh báo hay không) chứ không phải một câu văn để dò chuỗi. Dò chuỗi tiếng
    Việt trong logic điều kiện là thứ hỏng ngay lần đầu ai đó sửa lời văn.
    """
    verified = capability.languages_verified
    return "multi" in verified or language in verified


def describe_language_fit(capability: AvatarCapability, language: str) -> str:
    """Câu mô tả ngắn về mức phù hợp ngôn ngữ, để ghi vào cảnh báo/manifest.

    Không ném lỗi: dùng model ngoài ngôn ngữ đã kiểm chứng là **lựa chọn có ý
    thức của người dùng**, không phải lỗi cấu hình. Nhưng phải nói ra — trần
    khẩu hình tiếng Việt của Duix chính là hệ quả của việc này.
    """
    if language_is_verified(capability, language):
        return f"{capability.backend_id}: {capability.audio_encoder} có phủ {language!r}."
    return (
        f"{capability.backend_id}: bộ mã hoá {capability.audio_encoder} mới kiểm chứng "
        f"cho {sorted(capability.languages_verified)}, KHÔNG gồm {language!r}. Khẩu hình "
        "có thể đúng thời điểm nhưng sai hình âm."
    )

"""Các kiểu liệt kê dùng chung cho toàn bộ hợp đồng dữ liệu."""

from __future__ import annotations

from enum import StrEnum


class ProjectState(StrEnum):
    """State machine của project (brief §D01.4)."""

    DRAFT = "DRAFT"
    PLANNED = "PLANNED"
    APPROVED = "APPROVED"
    RENDERING = "RENDERING"
    COMPOSED = "COMPOSED"
    DONE = "DONE"
    FAILED = "FAILED"


class AspectRatio(StrEnum):
    """Tỷ lệ khung hình. MVP ưu tiên 9:16 (brief §D04.3)."""

    VERTICAL = "9:16"
    HORIZONTAL = "16:9"
    SQUARE = "1:1"

    @property
    def size(self) -> tuple[int, int]:
        """Kích thước pixel chuẩn tương ứng."""
        return {
            AspectRatio.VERTICAL: (1080, 1920),
            AspectRatio.HORIZONTAL: (1920, 1080),
            AspectRatio.SQUARE: (1080, 1080),
        }[self]


class SceneRole(StrEnum):
    """Vai trò của scene trong cấu trúc video ngắn."""

    HOOK = "hook"
    BODY = "body"
    PROOF = "proof"
    CTA = "cta"


class AssetKind(StrEnum):
    """Loại tài sản khai báo trong asset-manifest.json."""

    VOICE_SAMPLE = "voice_sample"
    AVATAR_SOURCE = "avatar_source"
    IMAGE = "image"
    BROLL = "broll"
    LOGO = "logo"
    MUSIC = "music"
    FONT = "font"


class ConsentStatus(StrEnum):
    """Trạng thái đồng ý sử dụng tài sản (brief §4, §7)."""

    GRANTED = "granted"
    PENDING = "pending"
    DENIED = "denied"
    #: Dùng cho tài sản do chính dự án tạo ra, không cần xin phép ai.
    NOT_REQUIRED = "not_required"

    @property
    def usable(self) -> bool:
        return self in {ConsentStatus.GRANTED, ConsentStatus.NOT_REQUIRED}


class ProviderKind(StrEnum):
    """Nhóm chức năng của provider."""

    TTS = "tts"
    AVATAR = "avatar"
    BROLL = "broll"
    COMPOSER = "composer"


class ProviderMode(StrEnum):
    """Mock hay thật. Mặc định toàn hệ thống là ``mock``."""

    MOCK = "mock"
    REAL = "real"


class RenderStage(StrEnum):
    """Các bước trong một lần render."""

    TTS = "tts"
    AVATAR = "avatar"
    BROLL = "broll"
    SUBTITLE = "subtitle"
    COMPOSE = "compose"


class StageStatus(StrEnum):
    """Kết quả của một bước render."""

    #: Dry-run: đã lên kế hoạch nhưng cố ý không thực thi.
    PLANNED = "planned"
    SUCCEEDED = "succeeded"
    #: Bỏ qua vì đã có artifact cache còn hợp lệ.
    REUSED = "reused"
    SKIPPED = "skipped"
    FAILED = "failed"


class OnScreenTextKind(StrEnum):
    """Loại chữ hiển thị. Các loại ``exact`` bắt buộc do composer chèn."""

    PHONE = "phone"
    PRICE = "price"
    LEGAL = "legal"
    CTA = "cta"
    GENERIC = "generic"


class BrollKind(StrEnum):
    """Nguồn hình minh hoạ cho một shot."""

    NONE = "none"
    LOCAL_ASSET = "local_asset"
    VIMAX = "vimax"
    VIDEO_API = "video_api"

"""Cây lỗi của AI-VIDEO-AGENT.

Mọi lỗi nghiệp vụ đều kế thừa :class:`AivaError` để CLI có thể bắt gọn và in ra
thông điệp tiếng Việt thay vì traceback.
"""

from __future__ import annotations


class AivaError(Exception):
    """Lỗi gốc của hệ thống."""


class ConfigError(AivaError):
    """Cấu hình môi trường sai hoặc thiếu."""


class ProjectNotFoundError(AivaError):
    """Không tìm thấy project trong thư mục runtime."""


class ValidationError(AivaError):
    """Dữ liệu không khớp JSON Schema hoặc model."""


class InvalidTransitionError(AivaError):
    """Chuyển trạng thái không hợp lệ trong state machine."""


class ApprovalRequiredError(AivaError):
    """Hành động cần project ở trạng thái APPROVED nhưng chưa được duyệt."""


class ApprovalStaleError(AivaError):
    """Storyboard đã đổi sau khi duyệt; phải duyệt lại trước khi render thật."""


class BudgetExceededError(AivaError):
    """Chi phí ước tính vượt trần ngân sách của project."""


class PaidApiNotAllowedError(AivaError):
    """Provider tính tiền bị chặn vì thiếu cờ cho phép rõ ràng."""


class ConsentMissingError(AivaError):
    """Tài sản (giọng/hình/video) chưa có trạng thái đồng ý sử dụng."""


class GateNotReachedError(AivaError):
    """Chức năng thuộc gate chưa được duyệt.

    Đây là hàng rào chính giữ cho D01 không vô tình chạy model thật, pull image
    hay gọi API mất tiền.
    """

    def __init__(self, feature: str, gate: str, hint: str = "") -> None:
        message = f"'{feature}' chỉ được bật ở Gate {gate}. Gate hiện tại chưa mở tính năng này."
        if hint:
            message = f"{message} {hint}"
        super().__init__(message)
        self.feature = feature
        self.gate = gate


class ProviderError(AivaError):
    """Provider chạy thất bại."""


class ComposeError(AivaError):
    """Bước ghép video thất bại."""

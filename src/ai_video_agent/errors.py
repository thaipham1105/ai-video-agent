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


class CapabilityError(AivaError):
    """Cấu hình không khớp năng lực đã xác minh của model.

    Ném ra **trước** khi chạm tới provider, để một cấu hình sai không bao giờ
    biến thành một lần gọi có thể bị tính tiền (D05C §4.2).
    """


class PriceUnverifiedError(AivaError):
    """Bảng giá thiếu nguồn, quá hạn kiểm chứng hoặc không khớp khoá.

    Cổng giá chạy theo nguyên tắc *fail-closed*: thà dừng còn hơn đoán một con
    số rồi tiêu tiền dựa trên nó (D05C §6.2).
    """


class SubmissionUnknownError(AivaError):
    """Không biết provider đã nhận yêu cầu hay chưa.

    Xảy ra khi tiến trình chết sau khi ghi ``SUBMITTING`` nhưng trước khi lưu
    được ``operation_name``. **Tuyệt đối không tự gửi lại** — phải đối chiếu thủ
    công (D05C §5.2, §5.4).
    """


class BrollQcFailedError(AivaError):
    """Clip B-roll trượt kiểm tra QC tự động nên không được vào composer."""


class HumanApprovalRequiredError(AivaError):
    """Shot chưa có người duyệt.

    QC tự động chỉ có quyền TỪ CHỐI, không bao giờ có quyền chấp nhận thay
    người (D05C §7.5).
    """

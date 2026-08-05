"""Hàng rào an toàn chi phí và quyền riêng tư trước mỗi lần render.

Đây là nơi duy nhất quyết định "có được chạy thật không". Mọi luật trong brief
§4, §5 và §D05.3 được gom về đây để chỉ cần đọc một file là kiểm chứng được:

1. **Dry-run** không bao giờ bị chặn — nhưng cũng không bao giờ chạy provider.
2. Chạy thật đòi project ở trạng thái đã duyệt (``APPROVED``/``COMPOSED``/``DONE``).
3. Phê duyệt phải còn khớp với storyboard hiện tại; sửa kịch bản là mất hiệu lực.
4. Provider tính tiền cần cờ ``--allow-paid`` **rõ ràng**.
5. Tổng ước tính không được vượt ``budget.cap_usd`` còn lại.
6. Mọi tài sản đưa vào render thật phải có ``consent`` hợp lệ.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ai_video_agent.domain.assets import AssetManifest
from ai_video_agent.domain.enums import ProviderMode
from ai_video_agent.domain.project import Project
from ai_video_agent.domain.state import EXECUTABLE_STATES
from ai_video_agent.domain.storyboard import Storyboard
from ai_video_agent.errors import (
    ApprovalRequiredError,
    ApprovalStaleError,
    BudgetExceededError,
    ConsentMissingError,
    PaidApiNotAllowedError,
)
from ai_video_agent.orchestrator.estimator import Estimate


@dataclass(frozen=True)
class GuardDecision:
    """Kết quả thẩm định, kèm lý do đọc được cho người dùng."""

    allowed: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.allowed:
            return "Cho phép chạy."
        return " | ".join(self.reasons)


def evaluate(
    project: Project,
    storyboard: Storyboard,
    assets: AssetManifest,
    estimate: Estimate,
    *,
    execute: bool,
    provider_mode: ProviderMode,
    allow_paid: bool,
) -> GuardDecision:
    """Thẩm định một lần render mà **không** ném lỗi — dùng để hiển thị."""
    reasons: list[str] = []
    warnings: list[str] = []

    if not execute:
        warnings.append("Dry-run: không provider nào được gọi, không có chi phí phát sinh.")
        if estimate.has_billable:
            warnings.append(
                f"Nếu chạy thật sẽ tốn khoảng {estimate.billable_usd:.4f} USD "
                f"(trần còn lại {project.budget.remaining_usd:.4f} USD)."
            )
        return GuardDecision(allowed=True, reasons=[], warnings=warnings)

    if project.state not in EXECUTABLE_STATES:
        allowed_names = ", ".join(sorted(s.value for s in EXECUTABLE_STATES))
        reasons.append(
            f"Project đang ở trạng thái {project.state.value}; chỉ {allowed_names} "
            "mới được render. Chạy 'aiva approve' trước."
        )
    elif not project.approval_matches(storyboard.sha256()):
        reasons.append(
            "Storyboard đã thay đổi sau khi duyệt. Phải xem lại và duyệt lại "
            "trước khi render (aiva approve)."
        )

    if estimate.has_billable:
        if not allow_paid:
            billable_names = sorted({line.provider for line in estimate.billable_lines})
            reasons.append(
                f"Có provider tính tiền ({', '.join(billable_names)}) nhưng thiếu cờ "
                "--allow-paid. Mặc định hệ thống chặn mọi chi tiêu."
            )
        if estimate.billable_usd > project.budget.remaining_usd:
            reasons.append(
                f"Ước tính {estimate.billable_usd:.4f} USD vượt trần còn lại "
                f"{project.budget.remaining_usd:.4f} USD (cap {project.budget.cap_usd:.4f})."
            )

    if provider_mode is ProviderMode.REAL:
        blocked = assets.blocking()
        if blocked:
            names = ", ".join(f"{a.id}({a.consent.status.value})" for a in blocked)
            reasons.append(
                f"Tài sản chưa được phép sử dụng: {names}. "
                "Phải có consent=granted trước khi render thật."
            )
    else:
        warnings.append("Provider mock: output là file đánh dấu, không phải media thật.")

    return GuardDecision(allowed=not reasons, reasons=reasons, warnings=warnings)


def enforce(
    project: Project,
    storyboard: Storyboard,
    assets: AssetManifest,
    estimate: Estimate,
    *,
    execute: bool,
    provider_mode: ProviderMode,
    allow_paid: bool,
) -> GuardDecision:
    """Như :func:`evaluate` nhưng ném lỗi cụ thể nếu bị chặn.

    Loại lỗi được chọn theo lý do *nghiêm trọng nhất*, để CLI in đúng cách khắc
    phục thay vì một thông báo chung chung.
    """
    decision = evaluate(
        project,
        storyboard,
        assets,
        estimate,
        execute=execute,
        provider_mode=provider_mode,
        allow_paid=allow_paid,
    )
    if decision.allowed:
        return decision

    joined = " | ".join(decision.reasons)
    if any("chưa được phép sử dụng" in reason for reason in decision.reasons):
        raise ConsentMissingError(joined)
    if any("vượt trần" in reason for reason in decision.reasons):
        raise BudgetExceededError(joined)
    if any("--allow-paid" in reason for reason in decision.reasons):
        raise PaidApiNotAllowedError(joined)
    if any("duyệt lại" in reason for reason in decision.reasons):
        raise ApprovalStaleError(joined)
    raise ApprovalRequiredError(joined)

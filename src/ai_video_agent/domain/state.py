"""State machine của project.

Sơ đồ bắt buộc theo brief §D01.4::

    DRAFT -> PLANNED -> APPROVED -> RENDERING -> COMPOSED -> DONE / FAILED

Các cạnh bổ sung (đều là hệ quả trực tiếp của yêu cầu trong brief):

* ``PLANNED -> PLANNED``  — lập lại kế hoạch khi sửa brief.
* ``APPROVED -> PLANNED`` — sửa storyboard làm mất hiệu lực phê duyệt (§9:
  "Người dùng có thể duyệt trước render").
* ``COMPOSED/DONE -> RENDERING`` — render lại **một** shot rồi ghép lại, không
  render lại toàn bộ (§D04.5, §9).
* ``FAILED -> PLANNED/RENDERING`` — thử lại sau khi sửa lỗi.
"""

from __future__ import annotations

from collections.abc import Mapping

from ai_video_agent.domain.enums import ProjectState
from ai_video_agent.errors import InvalidTransitionError

S = ProjectState

ALLOWED_TRANSITIONS: Mapping[ProjectState, frozenset[ProjectState]] = {
    S.DRAFT: frozenset({S.PLANNED, S.FAILED}),
    S.PLANNED: frozenset({S.PLANNED, S.APPROVED, S.FAILED}),
    S.APPROVED: frozenset({S.PLANNED, S.RENDERING, S.FAILED}),
    # RENDERING -> APPROVED là cạnh "tạm dừng chờ người duyệt": B-roll trả phí đã
    # sinh xong và qua QC, nhưng chưa ai duyệt bằng mắt. Đó là điểm dừng có chủ
    # đích, KHÔNG phải lỗi provider, nên không được đẩy project sang FAILED.
    S.RENDERING: frozenset({S.COMPOSED, S.APPROVED, S.FAILED}),
    S.COMPOSED: frozenset({S.DONE, S.RENDERING, S.FAILED}),
    S.DONE: frozenset({S.RENDERING, S.PLANNED}),
    S.FAILED: frozenset({S.PLANNED, S.RENDERING}),
}

#: Trạng thái cho phép chạy provider thật (đã qua bước duyệt của người dùng).
EXECUTABLE_STATES: frozenset[ProjectState] = frozenset({S.APPROVED, S.COMPOSED, S.DONE})

#: Trạng thái kết thúc, không còn cạnh bắt buộc phải đi tiếp.
TERMINAL_STATES: frozenset[ProjectState] = frozenset({S.DONE})


def next_states(current: ProjectState) -> frozenset[ProjectState]:
    """Tập trạng thái hợp lệ có thể chuyển tới từ ``current``."""
    return ALLOWED_TRANSITIONS.get(current, frozenset())


def can_transition(current: ProjectState, target: ProjectState) -> bool:
    """``True`` nếu cạnh ``current -> target`` hợp lệ."""
    return target in next_states(current)


def assert_transition(current: ProjectState, target: ProjectState) -> None:
    """Ném :class:`InvalidTransitionError` nếu cạnh không hợp lệ."""
    if not can_transition(current, target):
        allowed = ", ".join(sorted(s.value for s in next_states(current))) or "(không có)"
        raise InvalidTransitionError(
            f"Không thể chuyển {current.value} -> {target.value}. "
            f"Từ {current.value} chỉ được phép: {allowed}."
        )

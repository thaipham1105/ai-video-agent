"""State machine DRAFT -> PLANNED -> APPROVED -> RENDERING -> COMPOSED -> DONE/FAILED."""

from __future__ import annotations

from itertools import pairwise

import pytest

from ai_video_agent.domain.enums import ProjectState as S
from ai_video_agent.domain.project import Project
from ai_video_agent.domain.state import (
    EXECUTABLE_STATES,
    assert_transition,
    can_transition,
    next_states,
)
from ai_video_agent.errors import InvalidTransitionError


def test_duong_di_chinh_theo_brief() -> None:
    """Chuỗi bắt buộc trong brief §D01.4 phải đi được trọn vẹn."""
    happy_path = [S.DRAFT, S.PLANNED, S.APPROVED, S.RENDERING, S.COMPOSED, S.DONE]
    for current, target in pairwise(happy_path):
        assert can_transition(current, target), f"{current} -> {target} phải hợp lệ"


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.DRAFT, S.APPROVED),  # không được bỏ qua bước lập kế hoạch
        (S.DRAFT, S.RENDERING),  # không được render khi chưa có kịch bản
        (S.PLANNED, S.RENDERING),  # không được render khi chưa duyệt
        (S.PLANNED, S.DONE),
        (S.APPROVED, S.DONE),  # không được nhảy thẳng tới hoàn tất
        (S.RENDERING, S.DONE),  # phải qua COMPOSED
        (S.DONE, S.DONE),
    ],
)
def test_chan_cac_buoc_nhay_coc(current: S, target: S) -> None:
    assert not can_transition(current, target)
    with pytest.raises(InvalidTransitionError):
        assert_transition(current, target)


def test_moi_trang_thai_deu_co_duong_ra_tru_done() -> None:
    for state in S:
        if state is S.DONE:
            continue
        assert next_states(state), f"{state} bị kẹt, không có cạnh đi tiếp"


def test_render_lai_mot_shot_tu_trang_thai_da_xong() -> None:
    """Brief §D04.5: sửa một cảnh rồi ghép lại, không phải làm lại từ đầu."""
    assert can_transition(S.DONE, S.RENDERING)
    assert can_transition(S.COMPOSED, S.RENDERING)


def test_chi_trang_thai_da_duyet_moi_duoc_chay_that() -> None:
    assert S.DRAFT not in EXECUTABLE_STATES
    assert S.PLANNED not in EXECUTABLE_STATES
    assert S.APPROVED in EXECUTABLE_STATES


def test_transition_ghi_lai_lich_su(project: Project) -> None:
    project.transition_to(S.PLANNED, reason="lập kế hoạch")
    project.transition_to(S.APPROVED, reason="chủ máy duyệt")

    assert project.state is S.APPROVED
    assert [record.to_state for record in project.history] == [S.PLANNED, S.APPROVED]
    assert project.history[-1].reason == "chủ máy duyệt"
    assert project.history[0].from_state is S.DRAFT


def test_transition_sai_khong_lam_ban_trang_thai(project: Project) -> None:
    """Chuyển sai phải để nguyên project, không được sửa dở dang."""
    with pytest.raises(InvalidTransitionError):
        project.transition_to(S.DONE)

    assert project.state is S.DRAFT
    assert project.history == []

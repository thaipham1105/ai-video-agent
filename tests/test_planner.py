"""Planner: brief tiếng Việt -> storyboard hợp lệ."""

from __future__ import annotations

import pytest

from ai_video_agent.domain.enums import AspectRatio, OnScreenTextKind, SceneRole
from ai_video_agent.domain.storyboard import Storyboard
from ai_video_agent.errors import ValidationError
from ai_video_agent.jsonschemas import SchemaName, validate
from ai_video_agent.orchestrator.planner import MAX_SHOT_SEC, MIN_SHOT_SEC, RuleBasedPlanner


def plan_of(brief: str, duration: float = 45.0) -> Storyboard:
    return RuleBasedPlanner().plan(
        project_id="demo-bds",
        brief_vi=brief,
        target_duration_sec=duration,
        aspect_ratio=AspectRatio.VERTICAL,
    )


def test_storyboard_sinh_ra_khop_schema(storyboard: Storyboard) -> None:
    """Tiêu chí MVP §9: một lệnh tiếng Việt tạo storyboard có schema hợp lệ."""
    validate(SchemaName.STORYBOARD, storyboard.model_dump(mode="json"))


def test_ket_qua_tat_dinh(sample_brief: str) -> None:
    """Cùng đầu vào phải cho cùng kết quả, để phê duyệt neo được vào hash."""
    assert plan_of(sample_brief).sha256() == plan_of(sample_brief).sha256()


def test_tong_thoi_luong_bam_muc_tieu(sample_brief: str) -> None:
    assert plan_of(sample_brief, duration=45.0).total_duration_sec == pytest.approx(45.0, abs=0.5)


def test_moi_shot_nam_trong_khoang_cho_phep(storyboard: Storyboard) -> None:
    for shot in storyboard.shots:
        assert MIN_SHOT_SEC <= shot.duration_sec <= MAX_SHOT_SEC


def test_cau_truc_hook_body_cta(storyboard: Storyboard) -> None:
    assert [scene.role for scene in storyboard.scenes] == [
        SceneRole.HOOK,
        SceneRole.BODY,
        SceneRole.CTA,
    ]


def test_shot_duoc_danh_so_lien_tuc(storyboard: Storyboard) -> None:
    shots = storyboard.shots
    assert [shot.order for shot in shots] == list(range(len(shots)))
    assert len({shot.id for shot in shots}) == len(shots)


def test_chu_chinh_xac_duoc_gan_vao_shot_chua_no(storyboard: Storyboard) -> None:
    """Brief §D04.2: số điện thoại/giá/pháp lý phải thành lớp chữ do composer chèn."""
    kinds = {text.kind for shot in storyboard.shots for text in shot.on_screen_text}
    assert OnScreenTextKind.PHONE in kinds
    assert OnScreenTextKind.PRICE in kinds
    assert OnScreenTextKind.LEGAL in kinds


def test_moi_chu_chinh_xac_deu_danh_dau_exact(storyboard: Storyboard) -> None:
    for shot in storyboard.shots:
        for text in shot.on_screen_text:
            assert text.exact, f"{text.text} phải do composer chèn, không giao model vẽ"


def test_so_dien_thoai_giu_nguyen_tung_chu_so(storyboard: Storyboard) -> None:
    phones = [
        text.text
        for shot in storyboard.shots
        for text in shot.on_screen_text
        if text.kind is OnScreenTextKind.PHONE
    ]
    assert phones == ["0909123456"]


def test_shot_cuoi_luon_co_loi_keu_goi(storyboard: Storyboard) -> None:
    last = storyboard.shots[-1]
    assert any(text.kind is OnScreenTextKind.CTA for text in last.on_screen_text)


def test_brief_ngan_van_ra_storyboard_hop_le() -> None:
    storyboard = plan_of("Bán đất Biên Hoà giá tốt.", duration=10.0)
    validate(SchemaName.STORYBOARD, storyboard.model_dump(mode="json"))
    assert storyboard.shots


def test_brief_rong_bi_tu_choi() -> None:
    with pytest.raises(ValidationError):
        plan_of("   ")


def test_doi_thoai_lam_doi_hash_storyboard(sample_brief: str) -> None:
    """Sửa kịch bản phải đổi hash, đó là cơ sở để huỷ hiệu lực phê duyệt."""
    before = plan_of(sample_brief)
    after = plan_of(sample_brief + " Tặng thêm chi phí sang tên.")
    assert before.sha256() != after.sha256()

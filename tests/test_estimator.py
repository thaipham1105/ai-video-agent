"""Ước tính chi phí: làm tròn lên, tách phần tính tiền, nêu giả định."""

from __future__ import annotations

from ai_video_agent.config import Config
from ai_video_agent.domain.enums import BrollKind, ProviderMode, RenderStage
from ai_video_agent.domain.project import Project, ProviderSelection
from ai_video_agent.domain.storyboard import Storyboard
from ai_video_agent.orchestrator.estimator import estimate_storyboard
from ai_video_agent.providers.pricing import VIDEO_API_GENERIC, duration_from_text
from ai_video_agent.providers.registry import build_provider_set


def _estimate(project: Project, storyboard: Storyboard, config: Config, broll: str = "none"):
    providers = build_provider_set(
        ProviderSelection(broll=broll), mode=ProviderMode.MOCK, config=config
    )
    return estimate_storyboard(project, storyboard, providers)


def test_pipeline_local_khong_ton_tien(
    project: Project, storyboard: Storyboard, config: Config
) -> None:
    """VieNeu + Duix + FFmpeg đều chạy local: 0 USD hoá đơn API."""
    estimate = _estimate(project, storyboard, config)

    assert estimate.total_usd == 0.0
    assert estimate.billable_usd == 0.0
    assert not estimate.has_billable


def test_broll_api_lam_phat_sinh_chi_phi(
    project: Project, storyboard: Storyboard, config: Config
) -> None:
    for shot in storyboard.shots:
        shot.broll.kind = BrollKind.VIDEO_API

    estimate = _estimate(project, storyboard, config, broll="video_api")

    assert estimate.has_billable
    assert estimate.billable_usd > 0
    assert all(line.assumption for line in estimate.billable_lines)


def test_uoc_tinh_lam_tron_len_khong_bao_thap(
    project: Project, storyboard: Storyboard, config: Config
) -> None:
    """Báo thấp hơn thực tế nguy hiểm hơn báo cao, nên luôn làm tròn lên."""
    for shot in storyboard.shots:
        shot.broll.kind = BrollKind.VIDEO_API
    estimate = _estimate(project, storyboard, config, broll="video_api")

    tong_tho = sum(line.estimated_usd for line in estimate.lines)
    assert estimate.total_usd >= tong_tho - 1e-9


def test_gia_api_khai_bao_ro_la_gia_dinh_chua_kiem_chung() -> None:
    """Bảng giá của provider tính tiền phải tự nói rõ nó chưa được xác nhận."""
    assert "CHƯA KIỂM CHỨNG" in VIDEO_API_GENERIC.assumption
    assert VIDEO_API_GENERIC.billable is True


def test_canh_bao_khi_co_buoc_tinh_tien_ma_tran_bang_khong(
    project: Project, storyboard: Storyboard, config: Config
) -> None:
    for shot in storyboard.shots:
        shot.broll.kind = BrollKind.VIDEO_API
    project.budget.cap_usd = 0.0

    estimate = _estimate(project, storyboard, config, broll="video_api")

    assert any("cap_usd" in warning for warning in estimate.warnings)


def test_canh_bao_khi_shot_can_broll_ma_project_tat_broll(
    project: Project, storyboard: Storyboard, config: Config
) -> None:
    storyboard.shots[0].broll.kind = BrollKind.VIMAX

    estimate = _estimate(project, storyboard, config, broll="none")

    assert any("broll = none" in warning for warning in estimate.warnings)


def test_luon_co_dong_chi_phi_cho_buoc_ghep(
    project: Project, storyboard: Storyboard, config: Config
) -> None:
    estimate = _estimate(project, storyboard, config)
    compose = [line for line in estimate.lines if line.stage is RenderStage.COMPOSE]

    assert len(compose) == 1
    assert compose[0].billable is False


def test_quy_doi_thoai_ra_giay_nhat_quan() -> None:
    """Planner, mock TTS và estimator phải dùng chung một công thức."""
    assert duration_from_text("x" * 150) == 10.0
    assert duration_from_text("") >= 1.0

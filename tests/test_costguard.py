"""Cost guard — hàng rào chặn chi phí và chặn dùng tài sản chưa được phép."""

from __future__ import annotations

import pytest

from ai_video_agent.clock import now_utc
from ai_video_agent.config import Config
from ai_video_agent.domain.assets import AssetManifest
from ai_video_agent.domain.enums import BrollKind, ProjectState, ProviderMode
from ai_video_agent.domain.project import Approval, Project, ProviderSelection
from ai_video_agent.domain.storyboard import Storyboard
from ai_video_agent.errors import (
    ApprovalRequiredError,
    ApprovalStaleError,
    BudgetExceededError,
    ConsentMissingError,
    PaidApiNotAllowedError,
)
from ai_video_agent.orchestrator import costguard
from ai_video_agent.orchestrator.estimator import estimate_storyboard
from ai_video_agent.providers.registry import build_provider_set


def _approve(project: Project, storyboard: Storyboard) -> None:
    project.transition_to(ProjectState.PLANNED)
    project.approval = Approval(
        approved_by="Chủ máy",
        approved_at=now_utc(),
        storyboard_sha256=storyboard.sha256(),
    )
    project.transition_to(ProjectState.APPROVED)


def _estimate(project: Project, storyboard: Storyboard, config: Config, broll: str = "none"):
    providers = build_provider_set(
        ProviderSelection(broll=broll), mode=ProviderMode.MOCK, config=config
    )
    return estimate_storyboard(project, storyboard, providers)


def _guard(project, storyboard, assets, estimate, **kwargs):
    defaults = {"execute": True, "provider_mode": ProviderMode.MOCK, "allow_paid": False}
    return costguard.evaluate(project, storyboard, assets, estimate, **{**defaults, **kwargs})


# --- dry-run -----------------------------------------------------------------


def test_dry_run_luon_duoc_phep_du_chua_duyet(
    project: Project, storyboard: Storyboard, empty_assets: AssetManifest, config: Config
) -> None:
    """Brief §D01.5: dry-run là mặc định và không bao giờ bị chặn."""
    estimate = _estimate(project, storyboard, config)
    decision = _guard(project, storyboard, empty_assets, estimate, execute=False)

    assert decision.allowed
    assert project.state is ProjectState.DRAFT


def test_dry_run_van_bao_truoc_so_tien_neu_chay_that(
    project: Project, storyboard: Storyboard, empty_assets: AssetManifest, config: Config
) -> None:
    for shot in storyboard.shots:
        shot.broll.kind = BrollKind.VIDEO_API
    estimate = _estimate(project, storyboard, config, broll="video_api")

    decision = _guard(project, storyboard, empty_assets, estimate, execute=False)

    assert decision.allowed
    assert any("USD" in warning for warning in decision.warnings)


# --- phê duyệt ---------------------------------------------------------------


def test_chua_duyet_thi_khong_duoc_chay_that(
    project: Project, storyboard: Storyboard, empty_assets: AssetManifest, config: Config
) -> None:
    estimate = _estimate(project, storyboard, config)

    decision = _guard(project, storyboard, empty_assets, estimate)

    assert not decision.allowed
    with pytest.raises(ApprovalRequiredError):
        costguard.enforce(
            project,
            storyboard,
            empty_assets,
            estimate,
            execute=True,
            provider_mode=ProviderMode.MOCK,
            allow_paid=False,
        )


def test_da_duyet_thi_chay_duoc(
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest, config: Config
) -> None:
    _approve(project, storyboard)
    estimate = _estimate(project, storyboard, config)

    assert _guard(project, storyboard, granted_assets, estimate).allowed


def test_sua_storyboard_lam_mat_hieu_luc_phe_duyet(
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest, config: Config
) -> None:
    """Duyệt xong rồi sửa kịch bản thì phải duyệt lại (brief §9)."""
    _approve(project, storyboard)
    storyboard.scenes[0].shots[0].narration_vi = "Lời thoại đã bị sửa sau khi duyệt"
    estimate = _estimate(project, storyboard, config)

    with pytest.raises(ApprovalStaleError):
        costguard.enforce(
            project,
            storyboard,
            granted_assets,
            estimate,
            execute=True,
            provider_mode=ProviderMode.MOCK,
            allow_paid=False,
        )


# --- chi phí -----------------------------------------------------------------


def test_provider_tinh_tien_bi_chan_khi_thieu_co(
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest, config: Config
) -> None:
    _approve(project, storyboard)
    for shot in storyboard.shots:
        shot.broll.kind = BrollKind.VIDEO_API
    project.approval = Approval(
        approved_by="Chủ máy", approved_at=now_utc(), storyboard_sha256=storyboard.sha256()
    )
    project.budget.cap_usd = 1000.0
    estimate = _estimate(project, storyboard, config, broll="video_api")

    with pytest.raises(PaidApiNotAllowedError):
        costguard.enforce(
            project,
            storyboard,
            granted_assets,
            estimate,
            execute=True,
            provider_mode=ProviderMode.MOCK,
            allow_paid=False,
        )


def test_vuot_tran_ngan_sach_bi_chan_du_da_cho_phep_tra_phi(
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest, config: Config
) -> None:
    _approve(project, storyboard)
    for shot in storyboard.shots:
        shot.broll.kind = BrollKind.VIDEO_API
    project.approval = Approval(
        approved_by="Chủ máy", approved_at=now_utc(), storyboard_sha256=storyboard.sha256()
    )
    project.budget.cap_usd = 0.01
    estimate = _estimate(project, storyboard, config, broll="video_api")

    with pytest.raises(BudgetExceededError):
        costguard.enforce(
            project,
            storyboard,
            granted_assets,
            estimate,
            execute=True,
            provider_mode=ProviderMode.MOCK,
            allow_paid=True,
        )


def test_tran_ngan_sach_du_thi_qua(
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest, config: Config
) -> None:
    _approve(project, storyboard)
    for shot in storyboard.shots:
        shot.broll.kind = BrollKind.VIDEO_API
    project.approval = Approval(
        approved_by="Chủ máy", approved_at=now_utc(), storyboard_sha256=storyboard.sha256()
    )
    project.budget.cap_usd = 10_000.0
    estimate = _estimate(project, storyboard, config, broll="video_api")

    assert _guard(project, storyboard, granted_assets, estimate, allow_paid=True).allowed


# --- đồng ý sử dụng tài sản ---------------------------------------------------


def test_tai_san_chua_dong_y_chan_render_that(
    project: Project, storyboard: Storyboard, pending_assets: AssetManifest, config: Config
) -> None:
    """Brief §4: không dùng hình ảnh/giọng người khác khi chưa có đồng ý."""
    _approve(project, storyboard)
    estimate = _estimate(project, storyboard, config)

    with pytest.raises(ConsentMissingError):
        costguard.enforce(
            project,
            storyboard,
            pending_assets,
            estimate,
            execute=True,
            provider_mode=ProviderMode.REAL,
            allow_paid=False,
        )


def test_che_do_mock_khong_bi_chan_boi_consent_nhung_co_canh_bao(
    project: Project, storyboard: Storyboard, pending_assets: AssetManifest, config: Config
) -> None:
    """Mock không đụng tài sản thật nên không cần consent, nhưng phải nói rõ là giả."""
    _approve(project, storyboard)
    estimate = _estimate(project, storyboard, config)

    decision = _guard(
        project, storyboard, pending_assets, estimate, provider_mode=ProviderMode.MOCK
    )

    assert decision.allowed
    assert any("mock" in warning.lower() for warning in decision.warnings)

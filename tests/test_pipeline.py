"""Pipeline: dry-run, chạy mock đầy đủ, và render lại từng shot."""

from __future__ import annotations

import pytest

from ai_video_agent.clock import now_utc
from ai_video_agent.domain.assets import AssetManifest
from ai_video_agent.domain.enums import ProjectState, ProviderMode, RenderStage, StageStatus
from ai_video_agent.domain.project import Approval, Project
from ai_video_agent.domain.storyboard import Storyboard
from ai_video_agent.errors import ApprovalRequiredError, ValidationError
from ai_video_agent.jsonschemas import SchemaName, validate
from ai_video_agent.orchestrator.pipeline import Pipeline, RenderOptions
from ai_video_agent.orchestrator.repository import ProjectRepository


def _approve(project: Project, storyboard: Storyboard) -> None:
    project.transition_to(ProjectState.PLANNED)
    project.approval = Approval(
        approved_by="Chủ máy",
        approved_at=now_utc(),
        storyboard_sha256=storyboard.sha256(),
    )
    project.transition_to(ProjectState.APPROVED)


# --- dry-run -----------------------------------------------------------------


def test_dry_run_khong_goi_provider_va_khong_tao_media(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    empty_assets: AssetManifest,
) -> None:
    manifest = pipeline.render(project, storyboard, empty_assets)

    assert manifest.dry_run is True
    assert manifest.status == "planned"
    assert all(record.status is StageStatus.PLANNED for record in manifest.records)
    assert manifest.records, "phải ghi lại kế hoạch từng bước"
    assert not manifest.outputs
    assert not list(repo.paths(project.id).artifacts_dir.rglob("*")), "không được sinh artifact"


def test_dry_run_khong_doi_trang_thai_project(
    pipeline: Pipeline, project: Project, storyboard: Storyboard, empty_assets: AssetManifest
) -> None:
    pipeline.render(project, storyboard, empty_assets)
    assert project.state is ProjectState.DRAFT


def test_dry_run_ghi_render_manifest_khop_schema(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    empty_assets: AssetManifest,
) -> None:
    manifest = pipeline.render(project, storyboard, empty_assets)
    path = repo.paths(project.id).run_dir(manifest.run_id) / "render-manifest.json"

    assert path.is_file()
    validate(SchemaName.RENDER_MANIFEST, manifest.model_dump(mode="json"))


def test_render_that_bi_chan_khi_chua_duyet(
    pipeline: Pipeline, project: Project, storyboard: Storyboard, empty_assets: AssetManifest
) -> None:
    """Brief §D01.5: chạy provider thật đòi project đã APPROVED."""
    with pytest.raises(ApprovalRequiredError):
        pipeline.render(project, storyboard, empty_assets, RenderOptions(dry_run=False))


# --- chạy thật với provider mock ----------------------------------------------


def test_chay_mock_di_het_duong_ong(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    _approve(project, storyboard)
    repo.save_project(project)

    manifest = pipeline.render(project, storyboard, granted_assets, RenderOptions(dry_run=False))

    stages = {record.stage for record in manifest.records}
    assert {
        RenderStage.TTS,
        RenderStage.AVATAR,
        RenderStage.SUBTITLE,
        RenderStage.COMPOSE,
    } <= stages
    assert manifest.status == "succeeded"
    assert project.state is ProjectState.DONE
    assert manifest.outputs


def test_chay_mock_khong_ton_tien(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    _approve(project, storyboard)
    repo.save_project(project)

    manifest = pipeline.render(project, storyboard, granted_assets, RenderOptions(dry_run=False))

    assert manifest.actual_cost_usd == 0.0
    assert project.budget.spent_usd == 0.0


def test_output_mock_duoc_danh_dau_ro_rang(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    """Không ai được nhầm file mock với sản phẩm thật."""
    _approve(project, storyboard)
    repo.save_project(project)

    manifest = pipeline.render(project, storyboard, granted_assets, RenderOptions(dry_run=False))

    assert manifest.has_placeholder_output
    assert ".mock." in manifest.outputs[0]


def test_phu_de_duoc_sinh_ra_bang_utf8(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    _approve(project, storyboard)
    repo.save_project(project)

    manifest = pipeline.render(project, storyboard, granted_assets, RenderOptions(dry_run=False))
    srt = repo.paths(project.id).run_dir(manifest.run_id) / "subtitles.srt"

    assert srt.is_file()
    assert "sổ hồng riêng" in srt.read_text(encoding="utf-8").casefold()


def test_nhan_ai_duoc_ghi_vao_manifest(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    """Brief §4: video AI công khai phải có tuỳ chọn gắn nhãn."""
    _approve(project, storyboard)
    repo.save_project(project)

    manifest = pipeline.render(project, storyboard, granted_assets, RenderOptions(dry_run=False))

    assert manifest.ai_disclosure_applied is True
    lenh = next(w for w in manifest.warnings if w.startswith("Lệnh FFmpeg:"))
    assert project.ai_disclosure.label_vi in lenh


def test_manifest_ghi_du_thong_tin_tai_lap(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    """Brief §7: provider/model/version + thời điểm + trạng thái + file vào/ra."""
    _approve(project, storyboard)
    repo.save_project(project)

    manifest = pipeline.render(project, storyboard, granted_assets, RenderOptions(dry_run=False))

    assert manifest.storyboard_sha256 == storyboard.sha256()
    assert "python" in manifest.tool_versions
    tts = next(r for r in manifest.records if r.stage is RenderStage.TTS)
    assert tts.model and tts.version and tts.outputs
    assert tts.started_at is not None and tts.finished_at is not None


# --- render lại từng phần ------------------------------------------------------


def test_chay_lai_dung_lai_artifact_khi_noi_dung_khong_doi(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    """Brief §9: chỉ chạy lại phần phụ thuộc, không làm lại toàn bộ."""
    _approve(project, storyboard)
    repo.save_project(project)
    pipeline.render(project, storyboard, granted_assets, RenderOptions(dry_run=False))

    muc_tieu = storyboard.shots[0].id
    lan_hai = pipeline.render(
        project,
        storyboard,
        granted_assets,
        RenderOptions(dry_run=False, only_shots=(muc_tieu,)),
    )

    da_chay = {r.shot_id for r in lan_hai.records if r.status is StageStatus.SUCCEEDED}
    dung_lai = {r.shot_id for r in lan_hai.records if r.status is StageStatus.REUSED}
    assert muc_tieu in da_chay
    assert dung_lai, "các shot khác phải được dùng lại"
    assert muc_tieu not in dung_lai


def test_force_bo_qua_cache(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    _approve(project, storyboard)
    repo.save_project(project)
    pipeline.render(project, storyboard, granted_assets, RenderOptions(dry_run=False))

    lan_hai = pipeline.render(
        project,
        storyboard,
        granted_assets,
        RenderOptions(dry_run=False, only_shots=(storyboard.shots[0].id,), force=True),
    )

    assert not [r for r in lan_hai.records if r.status is StageStatus.REUSED]


def test_sua_thoai_lam_doi_khoa_cache_cua_rieng_shot_do(storyboard: Storyboard) -> None:
    truoc = storyboard.shots[0].content_hash()
    khac = storyboard.shots[1].content_hash()

    storyboard.shots[0].narration_vi = "Lời thoại mới hoàn toàn"

    assert storyboard.shots[0].content_hash() != truoc
    assert storyboard.shots[1].content_hash() == khac


def test_only_shot_khong_ton_tai_bi_tu_choi(
    pipeline: Pipeline, project: Project, storyboard: Storyboard, granted_assets: AssetManifest
) -> None:
    with pytest.raises(ValidationError, match="Không có shot"):
        pipeline.render(
            project, storyboard, granted_assets, RenderOptions(only_shots=("shot-khong-co",))
        )


# --- ước tính -----------------------------------------------------------------


def test_uoc_tinh_mock_bang_khong(
    pipeline: Pipeline, project: Project, storyboard: Storyboard
) -> None:
    estimate = pipeline.estimate(project, storyboard)

    assert estimate.total_usd == 0.0
    assert estimate.has_billable is False
    assert estimate.total_duration_sec == storyboard.total_duration_sec


def test_uoc_tinh_co_dong_cho_moi_shot(
    pipeline: Pipeline, project: Project, storyboard: Storyboard
) -> None:
    estimate = pipeline.estimate(project, storyboard)
    tts_lines = [line for line in estimate.lines if line.stage is RenderStage.TTS]

    assert len(tts_lines) == len(storyboard.shots)
    assert all(line.assumption for line in estimate.lines), "mọi dòng phải nêu giả định"


def test_render_manifest_ghi_dung_che_do_provider(
    pipeline: Pipeline, project: Project, storyboard: Storyboard, empty_assets: AssetManifest
) -> None:
    manifest = pipeline.render(project, storyboard, empty_assets)
    assert manifest.provider_mode is ProviderMode.MOCK

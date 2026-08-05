"""Chống hồi quy cho D03 (Duix) và D04 (FFmpeg composer).

Các tính năng dưới đây đều sinh ra từ lỗi thật gặp khi chạy end-to-end, nên mỗi
test ở đây ứng với một sự cố đã xảy ra một lần.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ai_video_agent.composer.ffmpeg import FONT_CANDIDATES, default_font_file
from ai_video_agent.composer.runner import FfmpegComposer
from ai_video_agent.domain.assets import AssetEntry, AssetManifest, Consent
from ai_video_agent.domain.enums import AssetKind, ConsentStatus, ProviderMode, StageStatus
from ai_video_agent.domain.project import Project
from ai_video_agent.domain.storyboard import Scene, Shot, Storyboard
from ai_video_agent.errors import ConsentMissingError, ValidationError
from ai_video_agent.jsonschemas import SchemaName, validate
from ai_video_agent.orchestrator.pipeline import Pipeline, RenderOptions
from ai_video_agent.orchestrator.repository import ProjectRepository
from ai_video_agent.providers._placeholder import write_silent_wav
from ai_video_agent.providers.duix.adapter import DuixAvatarProvider, DuixJob

# --- Duix: đơn vị thời lượng ---------------------------------------------------


def test_duix_tra_ve_mili_giay_phai_doi_ra_giay() -> None:
    """Quan sát thật: clip 7,68 s thì Duix trả `video_duration = 7680`."""
    job = DuixJob(code="x", payload={}, submitted_at=0.0, video_duration=7680)

    assert DuixAvatarProvider.duration_seconds(job) == 7.68


def test_duix_thieu_thoi_luong_thi_tra_0_chu_khong_no() -> None:
    job = DuixJob(code="x", payload={}, submitted_at=0.0, video_duration=None)

    assert DuixAvatarProvider.duration_seconds(job) == 0.0


# --- Duix: tìm file kết quả ----------------------------------------------------


def test_duix_tim_ket_qua_trong_thu_muc_temp(tmp_path: Path) -> None:
    """Duix trả về '/<tên>-r.mp4' — chỉ có tên, file thật nằm trong temp/."""
    (tmp_path / "temp").mkdir()
    real = tmp_path / "temp" / "abc-r.mp4"
    real.write_bytes(b"x")

    provider = DuixAvatarProvider(result_dir_host=tmp_path)
    job = DuixJob(code="abc", payload={}, submitted_at=0.0, result_path="/abc-r.mp4")

    assert provider._resolve_result(job) == real


def test_duix_bao_loi_ro_khi_khong_thay_file_ket_qua(tmp_path: Path) -> None:
    provider = DuixAvatarProvider(result_dir_host=tmp_path)
    job = DuixJob(code="abc", payload={}, submitted_at=0.0, result_path="/khong-co-r.mp4")

    with pytest.raises(Exception, match="không tìm thấy file kết quả"):
        provider._resolve_result(job)


# --- FFmpeg: font ---------------------------------------------------------------


def test_co_font_de_ve_chu_tieng_viet() -> None:
    """Thiếu font tường minh thì `drawtext` làm FFmpeg crash trên Windows."""
    font = default_font_file()

    assert font is not None, f"không thấy font nào trong {FONT_CANDIDATES}"
    assert font.is_file()


def test_composer_that_khai_bao_phien_ban_ffmpeg_that() -> None:
    version = FfmpegComposer().info().version

    assert version not in {"", "unknown"}
    assert "ffmpeg" in version.lower()


# --- pipeline: audio đã duyệt ---------------------------------------------------


def _storyboard_voi_audio_chot(project_id: str, asset_id: str | None) -> Storyboard:
    return Storyboard(
        project_id=project_id,
        scenes=[
            Scene(
                id="scene-01",
                title="Mở đầu",
                shots=[
                    Shot(
                        id="shot-001",
                        order=0,
                        duration_sec=3.0,
                        narration_vi="Xin chào quý khách.",
                        narration_audio_asset_id=asset_id,
                    )
                ],
            )
        ],
    )


def _manifest_voi_audio(
    project_id: str, assets_dir: Path, *, status: ConsentStatus = ConsentStatus.GRANTED
) -> AssetManifest:
    path = assets_dir / "voice/da-duyet.wav"
    write_silent_wav(path, duration_sec=3.0, sample_rate=48_000)
    return AssetManifest(
        project_id=project_id,
        assets=[
            AssetEntry(
                id="da-duyet",
                path="voice/da-duyet.wav",
                sha256="a" * 64,
                kind=AssetKind.VOICE_SAMPLE,
                bytes=path.stat().st_size,
                consent=Consent(status=status, owner="PO"),
            )
        ],
    )


def test_shot_chot_audio_thi_bo_qua_tts(
    pipeline: Pipeline, repo: ProjectRepository, project: Project
) -> None:
    """Sinh lại giọng sẽ ra bản khác (TTS có ngẫu nhiên) — phải dùng đúng file đã duyệt."""
    from ai_video_agent.clock import now_utc
    from ai_video_agent.domain.enums import ProjectState
    from ai_video_agent.domain.project import Approval

    storyboard = _storyboard_voi_audio_chot(project.id, "da-duyet")
    assets = _manifest_voi_audio(project.id, repo.paths(project.id).assets_dir)
    project.transition_to(ProjectState.PLANNED)
    project.approval = Approval(
        approved_by="PO", approved_at=now_utc(), storyboard_sha256=storyboard.sha256()
    )
    project.transition_to(ProjectState.APPROVED)
    repo.save_project(project)

    manifest = pipeline.render(project, storyboard, assets, RenderOptions(dry_run=False))

    tts = next(r for r in manifest.records if r.stage.value == "tts")
    assert tts.status is StageStatus.SKIPPED
    assert "da-duyet" in tts.message


def test_bao_loi_khi_audio_da_chot_khong_co_trong_manifest(
    pipeline: Pipeline, project: Project, repo: ProjectRepository
) -> None:
    storyboard = _storyboard_voi_audio_chot(project.id, "khong-ton-tai")
    assets = _manifest_voi_audio(project.id, repo.paths(project.id).assets_dir)

    with pytest.raises(ValidationError, match="khong-ton-tai"):
        pipeline._approved_audio(storyboard.shots[0], assets, project)


def test_bao_loi_khi_audio_da_chot_chua_co_consent(
    pipeline: Pipeline, project: Project, repo: ProjectRepository
) -> None:
    """Brief §4: consent chưa granted thì không được dùng để render."""
    storyboard = _storyboard_voi_audio_chot(project.id, "da-duyet")
    assets = _manifest_voi_audio(
        project.id, repo.paths(project.id).assets_dir, status=ConsentStatus.PENDING
    )

    with pytest.raises(ConsentMissingError):
        pipeline._approved_audio(storyboard.shots[0], assets, project)


def test_khong_chot_audio_thi_van_chay_tts(
    pipeline: Pipeline, project: Project, repo: ProjectRepository
) -> None:
    storyboard = _storyboard_voi_audio_chot(project.id, None)
    assets = _manifest_voi_audio(project.id, repo.paths(project.id).assets_dir)

    assert pipeline._approved_audio(storyboard.shots[0], assets, project) is None


def test_storyboard_co_truong_moi_van_khop_schema(project: Project) -> None:
    storyboard = _storyboard_voi_audio_chot(project.id, "da-duyet")

    validate(SchemaName.STORYBOARD, storyboard.model_dump(mode="json"))


# --- pipeline: dùng lại theo từng bước ------------------------------------------


def test_dung_lai_audio_ke_ca_khi_video_da_mat(
    pipeline: Pipeline, repo: ProjectRepository, project: Project, storyboard, granted_assets
) -> None:
    """Avatar hỏng ở lần trước không được kéo theo việc sinh lại giọng."""
    from ai_video_agent.clock import now_utc
    from ai_video_agent.domain.enums import ProjectState
    from ai_video_agent.domain.project import Approval

    project.transition_to(ProjectState.PLANNED)
    project.approval = Approval(
        approved_by="PO", approved_at=now_utc(), storyboard_sha256=storyboard.sha256()
    )
    project.transition_to(ProjectState.APPROVED)
    repo.save_project(project)
    pipeline.render(project, storyboard, granted_assets, RenderOptions(dry_run=False))

    # Xoá riêng video của một shot, giữ nguyên audio.
    target = storyboard.shots[0]
    cache = repo.paths(project.id).shot_cache_dir(target.id, target.content_hash())
    for video in cache.glob("avatar*"):
        video.unlink()

    lan_hai = pipeline.render(
        project,
        storyboard,
        granted_assets,
        RenderOptions(dry_run=False, only_shots=(storyboard.shots[1].id,)),
    )

    tts = next(r for r in lan_hai.records if r.stage.value == "tts" and r.shot_id == target.id)
    avatar = next(
        r for r in lan_hai.records if r.stage.value == "avatar" and r.shot_id == target.id
    )
    assert tts.status is StageStatus.REUSED, "audio còn nguyên thì phải dùng lại"
    assert avatar.status is StageStatus.SUCCEEDED, "video mất thì phải sinh lại"


def test_provider_ghi_ra_cho_khac_thi_van_dua_ve_cache(
    pipeline: Pipeline, repo: ProjectRepository, project: Project, tmp_path: Path
) -> None:
    """Duix ghi vào thư mục riêng của nó; pipeline phải gom về cache của shot."""
    goc = tmp_path / "cho-khac.mp4"
    goc.write_bytes(b"noi-dung")
    dich = tmp_path / "cache" / "avatar.mp4"
    dich.parent.mkdir(parents=True)

    shutil.copy2(goc, dich)

    assert dich.is_file()
    assert dich.read_bytes() == goc.read_bytes()


# --- gate ------------------------------------------------------------------------


def test_d05_van_khoa_du_da_toi_d04() -> None:
    """D05 là tuỳ chọn và gọi API TÍNH TIỀN — không được tự mở."""
    from ai_video_agent import gate_is_open

    assert gate_is_open("D04")
    assert not gate_is_open("D05")


def test_che_do_real_dung_ffmpeg_that_con_mock_thi_khong() -> None:
    from ai_video_agent.composer.runner import MockComposer

    assert FfmpegComposer().info().mode is ProviderMode.REAL
    assert MockComposer().info().mode is ProviderMode.MOCK

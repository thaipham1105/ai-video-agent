"""D04-D — cảnh báo ngôn ngữ và preflight tài nguyên ở dry-run.

Hai thứ D04-C để lại: `describe_language_fit()` không ai gọi, và preflight chỉ
chạy khi đã `--execute` — tức là chỉ biết mình thiếu VRAM sau khi đã quyết định
chạy thật.

Nguyên tắc phân vai xuyên suốt nhóm test này:

* **Ngôn ngữ chỉ cảnh báo.** Chạy Duix cho tiếng Việt là lựa chọn PO đã cân nhắc
  ở bake-off D04, không phải lỗi cấu hình. Chặn ở đây là chặn sai người.
* **Tài nguyên thì chặn** — nhưng chỉ khi biết chắc là thiếu.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_video_agent.clock import FixedClock, now_utc
from ai_video_agent.composer.runner import MockComposer
from ai_video_agent.config import Config
from ai_video_agent.domain.assets import AssetManifest
from ai_video_agent.domain.enums import ProjectState, ProviderMode
from ai_video_agent.domain.project import Approval, Project, ProviderSelection
from ai_video_agent.domain.storyboard import Storyboard
from ai_video_agent.errors import CapabilityError
from ai_video_agent.orchestrator.pipeline import (
    LANGUAGE_WARNING_PREFIX,
    Pipeline,
    RenderOptions,
)
from ai_video_agent.orchestrator.repository import ProjectRepository
from ai_video_agent.providers.avatar_capability import (
    describe_language_fit,
    language_is_verified,
)
from ai_video_agent.providers.base import (
    AvatarCapability,
    AvatarRequest,
    AvatarResult,
    ResourceEstimate,
)
from ai_video_agent.providers.duix.capability import DUIX_CAPABILITY, DUIX_RESOURCES
from ai_video_agent.providers.duix.mock import MockDuixAvatarProvider
from ai_video_agent.providers.registry import build_provider_set

LANGUAGE_MARKER = LANGUAGE_WARNING_PREFIX
PREFLIGHT_MARKER = "Preflight tài nguyên"


def _approve(project: Project, storyboard: Storyboard, repo: ProjectRepository) -> None:
    project.transition_to(ProjectState.PLANNED)
    project.approval = Approval(
        approved_by="Chủ máy", approved_at=now_utc(), storyboard_sha256=storyboard.sha256()
    )
    project.transition_to(ProjectState.APPROVED)
    repo.save_project(project)


def _pipeline(
    repo: ProjectRepository, config: Config, clock: FixedClock, avatar: object | None = None
) -> Pipeline:
    providers = build_provider_set(ProviderSelection(), mode=ProviderMode.MOCK, config=config)
    if avatar is not None:
        providers.avatar = avatar  # type: ignore[assignment]
    return Pipeline(
        repository=repo,
        providers=providers,
        config=config,
        composer=MockComposer(),
        now=clock.now_utc,
        make_run_id=clock.new_run_id,
    )


def _notes(manifest: object, marker: str) -> list[str]:
    return [w for w in manifest.warnings if marker in w]  # type: ignore[attr-defined]


class _DaKiemChungVi(MockDuixAvatarProvider):
    """Backend giả định đã kiểm chứng tiếng Việt — để bắt cảnh báo báo động giả."""

    def capability(self) -> AvatarCapability:
        base = super().capability()
        return AvatarCapability(
            backend_id=base.backend_id,
            backend_version=base.backend_version,
            native_fps=base.native_fps,
            supported_fps=base.supported_fps,
            max_width=base.max_width,
            max_height=base.max_height,
            audio_sample_rate_hz=base.audio_sample_rate_hz,
            audio_channels=base.audio_channels,
            audio_encoder="whisper",
            languages_verified=frozenset({"vi", "en"}),
            accepts_image_source=base.accepts_image_source,
            accepts_video_source=base.accepts_video_source,
            requires_gate=base.requires_gate,
            resources=base.resources,
        )


# --- language_is_verified: quyết định, không phải dò chuỗi -----------------


def test_duix_khong_kiem_chung_tieng_viet() -> None:
    assert language_is_verified(DUIX_CAPABILITY, "vi") is False
    assert language_is_verified(DUIX_CAPABILITY, "zh") is True


def test_backend_da_ngon_ngu_phu_moi_thu() -> None:
    cap = _DaKiemChungVi().capability()
    assert language_is_verified(cap, "vi") is True

    from dataclasses import replace

    multi = replace(cap, languages_verified=frozenset({"multi"}))
    assert language_is_verified(multi, "vi") is True
    assert language_is_verified(multi, "th") is True


def test_cau_mo_ta_va_quyet_dinh_luon_dong_bo() -> None:
    """Nếu hai hàm lệch nhau thì cảnh báo sẽ nói một đằng, logic làm một nẻo."""
    for language in ("vi", "zh", "en", "multi"):
        verified = language_is_verified(DUIX_CAPABILITY, language)
        note = describe_language_fit(DUIX_CAPABILITY, language)
        assert ("KHÔNG gồm" in note) is not verified


# --- Cảnh báo hiện ra ở manifest (chính là thứ CLI in) ---------------------


def test_dry_run_hien_canh_bao_ngon_ngu_cho_duix_va_vi(
    pipeline: Pipeline,
    project: Project,
    storyboard: Storyboard,
    empty_assets: AssetManifest,
) -> None:
    assert storyboard.language == "vi"

    manifest = pipeline.render(project, storyboard, empty_assets)

    notes = _notes(manifest, LANGUAGE_MARKER)
    assert len(notes) == 1, "phải cảnh báo đúng một lần"


def test_canh_bao_noi_du_provider_backend_va_ngon_ngu_da_kiem_chung(
    pipeline: Pipeline,
    project: Project,
    storyboard: Storyboard,
    empty_assets: AssetManifest,
) -> None:
    """Cảnh báo thiếu tên backend là cảnh báo không hành động được."""
    manifest = pipeline.render(project, storyboard, empty_assets)
    note = _notes(manifest, LANGUAGE_MARKER)[0]

    assert "duix" in note, "phải nói provider nào"
    assert "duix-avatar-mock" in note, "phải nói model/version nào"
    assert "wenet-aishell" in note, "bộ mã hoá là nguyên nhân gốc"
    assert "['zh']" in note, "phải liệt kê languages_verified"
    assert "'vi'" in note, "phải nói ngôn ngữ đang dùng"


def test_canh_bao_ngon_ngu_khong_chan_render(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    """Trần chất lượng đã biết ≠ lỗi. PO đã chọn Duix biết rõ điều này."""
    _approve(project, storyboard, repo)

    manifest = pipeline.render(project, storyboard, granted_assets, RenderOptions(dry_run=False))

    assert manifest.status == "succeeded"
    assert _notes(manifest, LANGUAGE_MARKER), "chạy được nhưng vẫn phải nói"


def test_execute_cung_hien_canh_bao_nhu_dry_run(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    kho = pipeline.render(project, storyboard, granted_assets)
    _approve(project, storyboard, repo)
    that = pipeline.render(project, storyboard, granted_assets, RenderOptions(dry_run=False))

    assert _notes(kho, LANGUAGE_MARKER) == _notes(that, LANGUAGE_MARKER)


def test_ngon_ngu_da_kiem_chung_thi_khong_bao_dong_gia(
    repo: ProjectRepository,
    config: Config,
    clock: FixedClock,
    project: Project,
    storyboard: Storyboard,
    empty_assets: AssetManifest,
) -> None:
    """Cảnh báo cho cả trường hợp đúng sẽ bị người dùng học cách bỏ qua."""
    pipeline = _pipeline(repo, config, clock, avatar=_DaKiemChungVi())

    manifest = pipeline.render(project, storyboard, empty_assets)

    assert not _notes(manifest, LANGUAGE_MARKER)


def test_doi_ngon_ngu_storyboard_thi_canh_bao_doi_theo(
    repo: ProjectRepository,
    config: Config,
    clock: FixedClock,
    project: Project,
    storyboard: Storyboard,
    empty_assets: AssetManifest,
) -> None:
    """Duix kiểm chứng tiếng Trung — dùng đúng ngôn ngữ của nó thì không cảnh báo."""
    storyboard.language = "zh"
    pipeline = _pipeline(repo, config, clock)

    manifest = pipeline.render(project, storyboard, empty_assets)

    assert not _notes(manifest, LANGUAGE_MARKER)


# --- Dry-run chạy đúng preflight của đường execute -------------------------


def test_dry_run_co_chay_preflight_tai_nguyen(
    pipeline: Pipeline,
    project: Project,
    storyboard: Storyboard,
    empty_assets: AssetManifest,
) -> None:
    manifest = pipeline.render(project, storyboard, empty_assets)

    assert manifest.dry_run is True
    assert len(_notes(manifest, PREFLIGHT_MARKER)) == 1


def test_dry_run_thieu_vram_bi_chan_ngay(
    repo: ProjectRepository,
    clock: FixedClock,
    project: Project,
    storyboard: Storyboard,
    empty_assets: AssetManifest,
    tmp_path: Path,
) -> None:
    """Biết chắc không đủ thì nói ngay ở lúc lập kế hoạch, đừng đợi --execute."""
    config = Config(runtime_dir=tmp_path / "runtime", vram_budget_mib=2_048)

    class DoiVramThat(MockDuixAvatarProvider):
        def estimate_resources(self, request: AvatarRequest) -> ResourceEstimate:
            del request
            return DUIX_RESOURCES

    pipeline = _pipeline(repo, config, clock, avatar=DoiVramThat())

    with pytest.raises(CapabilityError) as exc:
        pipeline.render(project, storyboard, empty_assets)

    text = str(exc.value)
    assert "7004" in text and "2048" in text


def test_dry_run_khong_cham_provider_du_da_chay_preflight(
    repo: ProjectRepository,
    config: Config,
    clock: FixedClock,
    project: Project,
    storyboard: Storyboard,
    empty_assets: AssetManifest,
) -> None:
    """Preflight chỉ hỏi khai báo. Chạm generate là chạm GPU/HTTP."""

    class NoTung(MockDuixAvatarProvider):
        def generate(self, request: AvatarRequest, out_path: Path) -> AvatarResult:
            raise AssertionError("Dry-run mà đã gọi generate().")

    pipeline = _pipeline(repo, config, clock, avatar=NoTung())

    manifest = pipeline.render(project, storyboard, empty_assets)
    assert manifest.dry_run is True


def test_dry_run_khong_sinh_artifact_nao(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    empty_assets: AssetManifest,
) -> None:
    """Hồi quy: thêm preflight không được làm dry-run bắt đầu ghi media."""
    pipeline.render(project, storyboard, empty_assets)

    assert not list(repo.paths(project.id).artifacts_dir.rglob("*"))


def test_dry_run_du_ngan_sach_thi_bao_du(
    repo: ProjectRepository,
    clock: FixedClock,
    project: Project,
    storyboard: Storyboard,
    empty_assets: AssetManifest,
    tmp_path: Path,
) -> None:
    config = Config(
        runtime_dir=tmp_path / "runtime",
        vram_budget_mib=12_282,
        ram_budget_mib=32_768,
        storage_budget_mib=500_000,
    )
    pipeline = _pipeline(repo, config, clock)

    manifest = pipeline.render(project, storyboard, empty_assets)

    note = _notes(manifest, PREFLIGHT_MARKER)[0]
    assert "đủ" in note
    assert "chưa xác minh được" not in note


def test_dry_run_khong_xac_minh_duoc_thi_noi_ro_bien_can_khai(
    pipeline: Pipeline,
    project: Project,
    storyboard: Storyboard,
    empty_assets: AssetManifest,
) -> None:
    """Không bịa 0, không bịa 'đủ' — nói thẳng là chưa biết và chỉ cách khai."""
    manifest = pipeline.render(project, storyboard, empty_assets)
    note = _notes(manifest, PREFLIGHT_MARKER)[0]

    assert "chưa xác minh được" in note
    assert "AIVA_VRAM_BUDGET_MIB" in note
    assert "AIVA_RAM_BUDGET_MIB" in note
    assert "AIVA_STORAGE_BUDGET_MIB" in note
    assert "đủ." not in note, "chưa biết mà nói đủ là nói dối"


def test_dry_run_va_execute_ra_cung_ket_luan_preflight(
    repo: ProjectRepository,
    clock: FixedClock,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
    tmp_path: Path,
) -> None:
    """Dry-run mà kết luận khác execute thì nó không còn là preflight."""
    config = Config(runtime_dir=tmp_path / "runtime", vram_budget_mib=12_282)
    pipeline = _pipeline(repo, config, clock)

    kho = pipeline.render(project, storyboard, granted_assets)
    _approve(project, storyboard, repo)
    that = pipeline.render(project, storyboard, granted_assets, RenderOptions(dry_run=False))

    assert _notes(kho, PREFLIGHT_MARKER) == _notes(that, PREFLIGHT_MARKER)


def test_thieu_vram_chan_ca_hai_duong_giong_nhau(
    repo: ProjectRepository,
    clock: FixedClock,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
    tmp_path: Path,
) -> None:
    config = Config(runtime_dir=tmp_path / "runtime", vram_budget_mib=1_024)

    class DoiVramThat(MockDuixAvatarProvider):
        def estimate_resources(self, request: AvatarRequest) -> ResourceEstimate:
            del request
            return DUIX_RESOURCES

        def generate(self, request: AvatarRequest, out_path: Path) -> AvatarResult:
            raise AssertionError("Thiếu VRAM mà vẫn gọi generate().")

    pipeline = _pipeline(repo, config, clock, avatar=DoiVramThat())
    _approve(project, storyboard, repo)

    with pytest.raises(CapabilityError):
        pipeline.render(project, storyboard, granted_assets)
    with pytest.raises(CapabilityError):
        pipeline.render(project, storyboard, granted_assets, RenderOptions(dry_run=False))


# --- Preflight hỏi cho trường hợp nặng nhất -------------------------------


def test_preflight_hoi_theo_shot_dai_nhat(
    repo: ProjectRepository,
    config: Config,
    clock: FixedClock,
    project: Project,
    storyboard: Storyboard,
    empty_assets: AssetManifest,
) -> None:
    """Backend tính VRAM theo thời lượng sẽ OOM nếu preflight hỏi shot ngắn nhất."""
    da_hoi: list[float] = []

    class Ghi(MockDuixAvatarProvider):
        def estimate_resources(self, request: AvatarRequest) -> ResourceEstimate:
            da_hoi.append(request.duration_sec)
            return super().estimate_resources(request)

    pipeline = _pipeline(repo, config, clock, avatar=Ghi())
    dai_nhat = max(shot.duration_sec for shot in storyboard.shots)

    pipeline.render(project, storyboard, empty_assets)

    assert da_hoi == [dai_nhat]


def test_preflight_hoi_dung_kich_thuoc_cua_project(
    repo: ProjectRepository,
    config: Config,
    clock: FixedClock,
    project: Project,
    storyboard: Storyboard,
    empty_assets: AssetManifest,
) -> None:
    """Hỏi sai độ phân giải thì con số VRAM trả về cũng vô nghĩa."""
    da_hoi: list[tuple[int, int, int]] = []

    class Ghi(MockDuixAvatarProvider):
        def estimate_resources(self, request: AvatarRequest) -> ResourceEstimate:
            da_hoi.append((request.width, request.height, request.fps))
            return super().estimate_resources(request)

    pipeline = _pipeline(repo, config, clock, avatar=Ghi())

    pipeline.render(project, storyboard, empty_assets)

    assert da_hoi == [(*project.aspect_ratio.size, project.fps)]

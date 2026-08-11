"""D04-C — provenance vào manifest, preflight tài nguyên vào đường render thật.

D04-B dựng hợp đồng nhưng không ai ở production gọi. Nhóm test này canh đúng chỗ
nối: manifest ghi thật, preflight chặn thật.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_video_agent.clock import now_utc
from ai_video_agent.config import Config
from ai_video_agent.domain.assets import AssetManifest
from ai_video_agent.domain.enums import ProjectState, RenderStage
from ai_video_agent.domain.project import Approval, Project
from ai_video_agent.domain.render import RenderManifest, RenderRecord, ResourceUsage
from ai_video_agent.domain.storyboard import Storyboard
from ai_video_agent.errors import CapabilityError, ProviderError
from ai_video_agent.jsonschemas import SchemaName, iter_errors, validate
from ai_video_agent.orchestrator.pipeline import Pipeline, RenderOptions
from ai_video_agent.orchestrator.repository import ProjectRepository
from ai_video_agent.providers.base import AvatarRequest, AvatarResult, ResourceEstimate
from ai_video_agent.providers.duix.capability import DUIX_RESOURCES
from ai_video_agent.providers.duix.mock import MockDuixAvatarProvider
from ai_video_agent.providers.resource_budget import (
    ResourceBudget,
    check_resources,
    probe_free_storage_mib,
    probe_free_vram_mib,
)


def _approve(project: Project, storyboard: Storyboard, repo: ProjectRepository) -> None:
    project.transition_to(ProjectState.PLANNED)
    project.approval = Approval(
        approved_by="Chủ máy", approved_at=now_utc(), storyboard_sha256=storyboard.sha256()
    )
    project.transition_to(ProjectState.APPROVED)
    repo.save_project(project)


def _render(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    assets: AssetManifest,
) -> RenderManifest:
    _approve(project, storyboard, repo)
    return pipeline.render(project, storyboard, assets, RenderOptions(dry_run=False))


def _avatar_records(manifest: RenderManifest) -> list[RenderRecord]:
    return [r for r in manifest.records if r.stage is RenderStage.AVATAR]


# --- Manifest thật chứa provenance đầy đủ ---------------------------------


def test_manifest_that_co_provenance_cho_moi_shot_avatar(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    manifest = _render(pipeline, repo, project, storyboard, granted_assets)

    records = _avatar_records(manifest)
    assert records, "phải có bước avatar"
    for record in records:
        assert record.avatar_provenance is not None, f"shot {record.shot_id} thiếu provenance"


def test_provenance_trong_manifest_khai_du_danh_tinh_backend(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    manifest = _render(pipeline, repo, project, storyboard, granted_assets)
    prov = _avatar_records(manifest)[0].avatar_provenance
    assert prov is not None

    assert prov.backend_id == "duix"
    assert prov.backend_version
    assert prov.model
    # Đây là thứ giải thích trần khẩu hình tiếng Việt — mất nó là mất lý do.
    assert prov.audio_encoder == "wenet-aishell"
    assert prov.languages_verified == ["zh"]
    assert prov.native_fps == 30


def test_provenance_mang_van_tay_vao_va_ra(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    """Không có băm thì manifest chỉ là lời kể, không phải bằng chứng."""
    manifest = _render(pipeline, repo, project, storyboard, granted_assets)
    prov = _avatar_records(manifest)[0].avatar_provenance
    assert prov is not None

    assert len(prov.audio_sha256) == 64, "audio đã sinh xong thì phải có băm"
    assert len(prov.output_sha256) == 64, "video đã ghi xong thì phải có băm"
    assert prov.audio_sha256 != prov.output_sha256


def test_output_sha256_bam_dung_file_trong_cache(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    """Băm phải khớp file bước ghép sẽ đọc, không phải file provider tự ghi."""
    from ai_video_agent.domain.assets import sha256_file

    manifest = _render(pipeline, repo, project, storyboard, granted_assets)
    record = _avatar_records(manifest)[0]
    prov = record.avatar_provenance
    assert prov is not None

    written = Path(record.outputs[0])
    assert written.is_file()
    assert prov.output_sha256 == sha256_file(written)


def test_provenance_ghi_metadata_dau_ra(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    manifest = _render(pipeline, repo, project, storyboard, granted_assets)
    prov = _avatar_records(manifest)[0].avatar_provenance
    assert prov is not None

    assert (prov.output_width, prov.output_height) == project.aspect_ratio.size
    assert prov.output_fps == project.fps
    assert prov.output_duration_sec > 0


def test_provenance_ghi_ca_uoc_tinh_tai_nguyen(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    manifest = _render(pipeline, repo, project, storyboard, granted_assets)
    prov = _avatar_records(manifest)[0].avatar_provenance
    assert prov is not None and prov.resources is not None

    # Mock khai tài nguyên CỦA MOCK, không mượn số của bản thật.
    assert prov.resources.est_ram_mib == 64
    assert prov.resources.est_vram_mib == 0
    assert prov.resources.estimate_measured is True
    assert prov.resources.estimate_measured_on


def test_manifest_co_provenance_van_ghi_dia_va_doc_lai_duoc(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    """Repository validate theo JSON Schema ở cả lúc ghi lẫn lúc đọc."""
    manifest = _render(pipeline, repo, project, storyboard, granted_assets)

    reloaded = repo.load_render_manifest(project.id, manifest.run_id)
    prov = _avatar_records(reloaded)[0].avatar_provenance
    assert prov is not None
    assert prov.backend_id == "duix"


# --- Bỏ nối provenance thì phải hỏng, không được im lặng -------------------


def test_provider_khong_khai_provenance_thi_render_hong(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    """Ghi null vào manifest sẽ che mất việc ai đó quên nối dây."""
    inner = MockDuixAvatarProvider()

    class Quen(MockDuixAvatarProvider):
        def generate(self, request: AvatarRequest, out_path: Path) -> AvatarResult:
            result = inner.generate(request, out_path)
            return AvatarResult(
                path=result.path,
                duration_sec=result.duration_sec,
                width=result.width,
                height=result.height,
                fps=result.fps,
                is_placeholder=result.is_placeholder,
                actual_cost_usd=result.actual_cost_usd,
                provenance=None,
            )

    pipeline._provider_set.avatar = Quen()  # type: ignore[assignment]
    _approve(project, storyboard, repo)

    with pytest.raises(ProviderError, match="KHÔNG có provenance"):
        pipeline.render(project, storyboard, granted_assets, RenderOptions(dry_run=False))


# --- Schema đối chiếu model ------------------------------------------------


def test_schema_chap_nhan_provenance_day_du(storyboard: Storyboard) -> None:
    manifest = RenderManifest(
        project_id=storyboard.project_id,
        run_id="run0001",
        storyboard_sha256=storyboard.sha256(),
    )
    validate(SchemaName.RENDER_MANIFEST, manifest.model_dump(mode="json"))


def test_schema_chan_ram_bang_0(storyboard: Storyboard) -> None:
    """Model chặn bằng ``gt=0``; schema phải chặn độc lập, không tin model."""
    payload = RenderManifest(
        project_id=storyboard.project_id,
        run_id="run0001",
        storyboard_sha256=storyboard.sha256(),
    ).model_dump(mode="json")
    payload["records"] = [
        {
            "stage": "avatar",
            "provider": "duix",
            "model": "m",
            "version": "1",
            "mode": "mock",
            "status": "succeeded",
            "avatar_provenance": {
                "backend_id": "duix",
                "backend_version": "1",
                "model": "m",
                "audio_encoder": "wenet-aishell",
                "native_fps": 30,
                "source_fps": 30,
                "output_width": 1080,
                "output_height": 1920,
                "output_fps": 30,
                "output_duration_sec": 1.0,
                "resources": {
                    "est_vram_mib": 0,
                    "est_ram_mib": 0,
                    "est_storage_mib": 1,
                },
            },
        }
    ]
    assert iter_errors(SchemaName.RENDER_MANIFEST, payload)


def test_schema_bat_truong_la_trong_provenance(storyboard: Storyboard) -> None:
    payload = RenderManifest(
        project_id=storyboard.project_id,
        run_id="run0001",
        storyboard_sha256=storyboard.sha256(),
    ).model_dump(mode="json")
    payload["records"] = [
        {
            "stage": "avatar",
            "provider": "duix",
            "model": "m",
            "version": "1",
            "mode": "mock",
            "status": "succeeded",
            "avatar_provenance": {
                "backend_id": "duix",
                "backend_version": "1",
                "model": "m",
                "audio_encoder": "wenet-aishell",
                "native_fps": 30,
                "source_fps": 30,
                "output_width": 1080,
                "output_height": 1920,
                "output_fps": 30,
                "output_duration_sec": 1.0,
                "truong_bia_ra": "x",
            },
        }
    ]
    assert iter_errors(SchemaName.RENDER_MANIFEST, payload)


def test_manifest_cu_khong_co_provenance_van_doc_duoc(storyboard: Storyboard) -> None:
    """Tương thích ngược: manifest ghi trước D04-C không có trường này."""
    payload = {
        "schema_version": 1,
        "project_id": storyboard.project_id,
        "run_id": "run-cu",
        "dry_run": False,
        "provider_mode": "mock",
        "storyboard_sha256": storyboard.sha256(),
        "created_at": "2026-08-04T09:30:00+00:00",
        "status": "succeeded",
        "records": [
            {
                "stage": "avatar",
                "shot_id": "shot-001",
                "provider": "duix",
                "model": "duix-avatar-mock",
                "version": "0.1.0",
                "mode": "mock",
                "status": "succeeded",
            }
        ],
        "estimated_cost_usd": 0.0,
        "actual_cost_usd": 0.0,
        "ai_disclosure_applied": False,
    }
    validate(SchemaName.RENDER_MANIFEST, payload)
    restored = RenderManifest.model_validate(payload)
    assert restored.records[0].avatar_provenance is None


def test_peak_vram_null_khac_han_khong_ghi() -> None:
    """``None`` = không quan sát được. Đổi thành 0 là bịa một số đo."""
    usage = ResourceUsage(est_vram_mib=7004, est_ram_mib=4096, est_storage_mib=5120)
    assert usage.peak_vram_mib is None
    with pytest.raises(ValueError, match="est_ram_mib"):
        ResourceUsage(est_vram_mib=0, est_ram_mib=0, est_storage_mib=1)


# --- Preflight: đối chiếu từng chiều --------------------------------------


def _estimate(vram: int = 7_004, ram: int = 4_096, storage: int = 5_120) -> ResourceEstimate:
    return ResourceEstimate(
        vram_mib=vram,
        ram_mib=ram,
        storage_mib=storage,
        deterministic_local=True,
        measured=True,
        measured_on="2026-08-05",
    )


def test_du_tai_nguyen_thi_khong_chan() -> None:
    budget = ResourceBudget(vram_mib=12_282, ram_mib=32_768, storage_mib=500_000)
    report = check_resources("duix", _estimate(), budget)

    assert report.ok
    assert report.fully_verified
    report.raise_if_insufficient()


def test_thieu_vram_thi_chan_va_noi_ro_can_bao_nhieu() -> None:
    budget = ResourceBudget(vram_mib=2_048, ram_mib=32_768, storage_mib=500_000)
    report = check_resources("duix", _estimate(), budget)

    assert not report.ok
    with pytest.raises(CapabilityError) as exc:
        report.raise_if_insufficient()
    text = str(exc.value)
    assert "duix" in text
    assert "7004" in text, "phải nói cần bao nhiêu"
    assert "2048" in text, "phải nói đang có bao nhiêu"
    assert "đo thật" in text, "phải nói con số này đo hay chép tài liệu"


def test_thieu_nhieu_chieu_thi_bao_het_mot_lan() -> None:
    """Báo từng chiều một sẽ bắt người dùng sửa rồi chạy lại nhiều vòng."""
    budget = ResourceBudget(vram_mib=1_024, ram_mib=512, storage_mib=100)
    report = check_resources("duix", _estimate(), budget)

    assert len(report.shortfalls) == 3
    text = report.message()
    assert "VRAM" in text and "RAM" in text and "đĩa" in text


def test_khong_biet_thi_khong_chan_nhung_phai_noi() -> None:
    report = check_resources("duix", _estimate(), ResourceBudget())

    assert report.ok, "không biết thì không được chặn"
    assert not report.fully_verified
    assert set(report.unverified) == {"VRAM", "RAM", "đĩa"}
    assert "chưa xác minh được" in report.warning()


def test_khong_biet_khac_han_bang_0() -> None:
    """Nếu ``None`` bị coi như 0 thì mọi backend đều bị chặn."""
    khong_biet = ResourceBudget()
    bang_khong = ResourceBudget(vram_mib=0, ram_mib=0, storage_mib=0)
    unknown = check_resources("duix", _estimate(), khong_biet)
    zeroed = check_resources("duix", _estimate(), bang_khong)

    assert unknown.ok
    assert not zeroed.ok


def test_chieu_biet_van_duoc_kiem_du_chieu_khac_khong_biet() -> None:
    """Biết một nửa vẫn tốt hơn không kiểm gì."""
    budget = ResourceBudget(vram_mib=1_024)
    report = check_resources("duix", _estimate(), budget)

    assert not report.ok
    assert set(report.unverified) == {"RAM", "đĩa"}


# --- Nguồn của ngân sách ---------------------------------------------------


def test_config_thang_may_do(tmp_path: Path) -> None:
    """Người vận hành khai thấp hơn thực tế để chừa GPU cho việc khác."""
    config = Config(runtime_dir=tmp_path, vram_budget_mib=4_096)

    def probe_khong_duoc_goi() -> int | None:
        raise AssertionError("Đã khai trong config thì không được dò máy nữa.")

    budget = ResourceBudget.detect(config, vram_probe=probe_khong_duoc_goi)
    assert budget.vram_mib == 4_096
    assert "vram=config" in budget.sources


def test_khong_khai_thi_dung_may_do(tmp_path: Path) -> None:
    """Không khai thì dò máy — và ``vram_mib`` là **tổng của card**, không phải trống.

    Nguồn ghi rõ ``(total)`` để sau này đọc manifest còn biết con số ấy là sức
    chứa hay phần rảnh; nhầm hai thứ đó chính là lỗi D05-C đã bắt.
    """
    config = Config(runtime_dir=tmp_path)
    budget = ResourceBudget.detect(
        config,
        vram_probe=lambda: 9_000,
        vram_free_probe=lambda: 3_000,
        storage_probe=lambda _p: 123_456,
    )

    assert budget.vram_mib == 9_000
    assert budget.vram_free_mib == 3_000
    assert budget.storage_mib == 123_456
    assert "vram=nvidia-smi(total)" in budget.sources


def test_may_do_that_bai_thi_de_none_chu_khong_de_0(tmp_path: Path) -> None:
    config = Config(runtime_dir=tmp_path)
    budget = ResourceBudget.detect(config, vram_probe=lambda: None, storage_probe=lambda _p: None)

    assert budget.vram_mib is None
    assert budget.storage_mib is None
    assert "chưa xác minh được" in budget.describe()


def test_ram_khong_co_may_do_nen_phai_khai(tmp_path: Path) -> None:
    """Python không có API chuẩn đọc RAM trống — nói thẳng thay vì đoán."""
    khong_khai = Config(runtime_dir=tmp_path)
    co_khai = Config(runtime_dir=tmp_path, ram_budget_mib=8_192)

    assert ResourceBudget.detect(khong_khai).ram_mib is None
    assert ResourceBudget.detect(co_khai).ram_mib == 8_192


def test_config_bo_qua_gia_tri_rac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIVA_VRAM_BUDGET_MIB", "nhieu lam")
    monkeypatch.setenv("AIVA_RAM_BUDGET_MIB", "-5")
    monkeypatch.setenv("AIVA_STORAGE_BUDGET_MIB", "0")
    config = Config.from_env()

    assert config.vram_budget_mib is None
    assert config.ram_budget_mib is None, "số âm không phải ngưỡng hợp lệ"
    assert config.storage_budget_mib is None, "0 MiB trống là khai nhầm, không phải sự thật"


def test_config_doc_duoc_nguong_hop_le(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIVA_VRAM_BUDGET_MIB", "8192")
    assert Config.from_env().vram_budget_mib == 8_192


# --- Máy dò chỉ đọc, không nạp model --------------------------------------


def test_may_do_vram_chi_tra_None_hoac_so_duong() -> None:
    """Chạy thật trên máy này: không được sập, không được trả số vô lý."""
    value = probe_free_vram_mib()
    assert value is None or value > 0


def test_may_do_dia_chay_duoc_ca_khi_thu_muc_chua_ton_tai(tmp_path: Path) -> None:
    """Runtime dir tạo lúc chạy 'aiva plan' — preflight không được sập trước đó."""
    value = probe_free_storage_mib(tmp_path / "chua" / "ton" / "tai")
    assert value is None or value > 0


# --- Preflight được gọi trong pipeline thật, không chỉ test ----------------


def test_pipeline_chan_render_khi_khong_du_vram(
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
    tmp_path: Path,
    clock: object,
) -> None:
    """Backend đòi 8,5 GB, máy khai còn 2 GB — phải chết trước khi gọi generate()."""
    from ai_video_agent.composer.runner import MockComposer
    from ai_video_agent.domain.enums import ProviderMode
    from ai_video_agent.domain.project import ProviderSelection
    from ai_video_agent.providers.registry import build_provider_set

    config = Config(runtime_dir=tmp_path / "runtime", vram_budget_mib=2_048)
    providers = build_provider_set(ProviderSelection(), mode=ProviderMode.MOCK, config=config)

    class DoiVramThat(MockDuixAvatarProvider):
        """Mock nhưng khai tài nguyên của bản thật, để dựng đúng tình huống thiếu."""

        def estimate_resources(self, request: AvatarRequest) -> ResourceEstimate:
            del request
            return DUIX_RESOURCES

        def generate(self, request: AvatarRequest, out_path: Path) -> AvatarResult:
            raise AssertionError("Đã gọi generate() dù thiếu VRAM — preflight không chặn.")

    providers.avatar = DoiVramThat()  # type: ignore[assignment]
    pipeline = Pipeline(
        repository=repo,
        providers=providers,
        config=config,
        composer=MockComposer(),
        now=clock.now_utc,  # type: ignore[attr-defined]
        make_run_id=clock.new_run_id,  # type: ignore[attr-defined]
    )
    _approve(project, storyboard, repo)

    with pytest.raises(CapabilityError, match=str(DUIX_RESOURCES.vram_mib)):
        pipeline.render(project, storyboard, granted_assets, RenderOptions(dry_run=False))


def test_du_ngan_sach_thi_duong_mock_di_tron(
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
    tmp_path: Path,
    clock: object,
) -> None:
    from ai_video_agent.composer.runner import MockComposer
    from ai_video_agent.domain.enums import ProviderMode
    from ai_video_agent.domain.project import ProviderSelection
    from ai_video_agent.providers.registry import build_provider_set

    config = Config(
        runtime_dir=tmp_path / "runtime",
        vram_budget_mib=12_282,
        ram_budget_mib=32_768,
        storage_budget_mib=500_000,
    )
    providers = build_provider_set(ProviderSelection(), mode=ProviderMode.MOCK, config=config)
    pipeline = Pipeline(
        repository=repo,
        providers=providers,
        config=config,
        composer=MockComposer(),
        now=clock.now_utc,  # type: ignore[attr-defined]
        make_run_id=clock.new_run_id,  # type: ignore[attr-defined]
    )
    _approve(project, storyboard, repo)

    manifest = pipeline.render(project, storyboard, granted_assets, RenderOptions(dry_run=False))

    assert manifest.status == "succeeded"
    note = next(w for w in manifest.warnings if "Preflight tài nguyên" in w)
    assert "đủ" in note


def test_ngan_sach_khong_xac_dinh_van_chay_va_ghi_ro_trang_thai(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    """Máy không có GPU vẫn phải chạy được đường mock — nhưng manifest phải nói rõ."""
    manifest = _render(pipeline, repo, project, storyboard, granted_assets)

    assert manifest.status == "succeeded"
    note = next(w for w in manifest.warnings if "Preflight tài nguyên" in w)
    assert "chưa xác minh được" in note
    assert "AIVA_VRAM_BUDGET_MIB" in note, "phải chỉ cách khai ngưỡng"


def test_canh_bao_preflight_khong_lap_lai_moi_shot(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    manifest = _render(pipeline, repo, project, storyboard, granted_assets)

    notes = [w for w in manifest.warnings if "Preflight tài nguyên" in w]
    assert len(notes) == 1, f"{len(storyboard.shots)} shot nhưng chỉ cần nói một lần"


def test_hoi_tai_nguyen_dung_mot_lan_cho_ca_run(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    """Preflight là câu hỏi của *lần chạy*, không phải của từng shot.

    D04-D chuyển preflight lên cấp run để dry-run và execute dùng chung đúng một
    đường. Hệ quả: số lần hỏi không còn phụ thuộc vào bao nhiêu shot phải render
    lại hay bao nhiêu shot lấy từ cache.
    """
    _render(pipeline, repo, project, storyboard, granted_assets)
    assert len(storyboard.shots) > 1, "test này cần nhiều hơn một shot mới có nghĩa"

    da_hoi: list[str] = []

    class Dem(MockDuixAvatarProvider):
        def estimate_resources(self, request: AvatarRequest) -> ResourceEstimate:
            da_hoi.append(request.shot_id)
            return super().estimate_resources(request)

    pipeline._provider_set.avatar = Dem()  # type: ignore[assignment]

    manifest = pipeline.render(
        project,
        storyboard,
        granted_assets,
        RenderOptions(dry_run=False, only_shots=(storyboard.shots[0].id,)),
    )

    assert manifest.status == "succeeded"
    assert len(da_hoi) == 1, f"hỏi {len(da_hoi)} lần cho một run: {da_hoi}"

"""D05-C — QC B-roll trả phí chạy trong ``Pipeline.render()`` THẬT.

Vì sao nhóm test này tồn tại: audit của PO chỉ ra rằng cổng ở ``_compose`` đã có,
nhưng **không gì trong lifecycle sinh ra ``broll.qc.json``**, nên B-roll trả phí
sẽ luôn bị chặn vì thiếu báo cáo. Test cũ tự tay viết file JSON rồi gọi thẳng
phương thức private — nên không chứng minh được điều cần chứng minh.

Ở đây mọi thứ đi qua ``Pipeline.render(..., dry_run=False)``. Báo cáo QC do
chính pipeline sinh ra, không phải do test dựng sẵn.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ai_video_agent.clock import FixedClock, now_utc
from ai_video_agent.composer.runner import MockComposer
from ai_video_agent.config import Config
from ai_video_agent.domain.assets import AssetManifest
from ai_video_agent.domain.enums import (
    BrollKind,
    ProjectState,
    ProviderKind,
    ProviderMode,
    RenderStage,
)
from ai_video_agent.domain.project import Approval, Project
from ai_video_agent.domain.storyboard import Storyboard
from ai_video_agent.errors import BrollQcFailedError, HumanApprovalRequiredError
from ai_video_agent.orchestrator.pipeline import Pipeline, RenderOptions
from ai_video_agent.orchestrator.repository import ProjectRepository
from ai_video_agent.providers.base import (
    BrollRequest,
    BrollResult,
    CostQuote,
    ProviderInfo,
    ProviderSet,
)
from ai_video_agent.providers.duix.mock import MockDuixAvatarProvider
from ai_video_agent.providers.registry import build_provider_set
from ai_video_agent.providers.vieneu.mock import MockVieNeuTtsProvider
from ai_video_agent.qc.approval import APPROVED, REJECTED, qc_report_path_for

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(
    not FFMPEG or not FFPROBE, reason="cần ffmpeg/ffprobe trên PATH"
)

CLIP_W, CLIP_H, CLIP_FPS, CLIP_SEC = 240, 426, 24, 1.0


@pytest.fixture(scope="module")
def real_clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Một clip thật, giải mã được — QC phải soi được file chứ không phải file rỗng."""
    if not FFMPEG:
        pytest.skip("cần ffmpeg")
    out = tmp_path_factory.mktemp("broll_src") / "src.mp4"
    subprocess.run(  # noqa: S603
        [
            FFMPEG, "-v", "error", "-f", "lavfi",
            "-i", f"testsrc2=size={CLIP_W}x{CLIP_H}:rate={CLIP_FPS}:duration={CLIP_SEC}",
            "-vf", "format=yuv420p", "-y", str(out),
        ],
        check=True,
    )
    return out


class _BillableBrollProvider:
    """B-roll trả phí giả lập.

    Cố ý ghi ra **đường KHÁC** đường pipeline yêu cầu, rồi trả đường thật qua
    ``BrollResult.path``. Đúng hành vi Duix từng có. Nếu pipeline tin vào đường
    yêu cầu thay vì đường trả về, QC sẽ soi nhầm file và test sẽ đổ.
    """

    def __init__(
        self, source: Path, *, billable: bool = True, lie_about_size: bool = False
    ) -> None:
        self._source = source
        self._billable = billable
        #: Khai một đằng, ghi một nẻo — ép QC FAIL thật thay vì bịa verdict.
        self._lie = lie_about_size
        #: Mọi đường đã ghi. Storyboard có nhiều shot ⇒ nhiều B-roll, nhiều báo cáo.
        self.all_written: list[Path] = []

    @property
    def written(self) -> Path | None:
        return self.all_written[-1] if self.all_written else None

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="fake-paid-broll",
            kind=ProviderKind.BROLL,
            model="fake-veo",
            version="test",
            mode=ProviderMode.REAL,
            billable=self._billable,
            gate="D01",
        )

    def quote(self, request: BrollRequest) -> CostQuote:
        return CostQuote(
            stage=RenderStage.BROLL, provider="fake-paid-broll", model="fake-veo",
            unit="second", units=request.duration_sec, unit_price_usd=0.0,
            estimated_usd=0.0, billable=self._billable,
        )

    def generate(self, request: BrollRequest, out_path: Path) -> BrollResult:
        del request
        actual = out_path.parent / f"ACTUAL-{out_path.name}"
        actual.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self._source, actual)
        self.all_written.append(actual)
        w, h = (1080, 1920) if self._lie else (CLIP_W, CLIP_H)
        return BrollResult(
            path=actual, duration_sec=CLIP_SEC, width=w, height=h,
            fps=CLIP_FPS, is_placeholder=False, actual_cost_usd=0.0,
        )


def _pipeline_with(
    repo: ProjectRepository, config: Config, clock: FixedClock, broll: object
) -> Pipeline:
    base = build_provider_set_stub(config)
    return Pipeline(
        repository=repo,
        providers=ProviderSet(tts=base.tts, avatar=base.avatar, broll=broll),  # type: ignore[arg-type]
        config=config,
        composer=MockComposer(),
        now=clock.now_utc,
        make_run_id=clock.new_run_id,
    )


def build_provider_set_stub(config: Config) -> ProviderSet:
    del config
    return ProviderSet(tts=MockVieNeuTtsProvider(), avatar=MockDuixAvatarProvider())


def _enable_broll(storyboard: Storyboard) -> Storyboard:
    for shot in storyboard.shots:
        shot.broll.kind = BrollKind.VIDEO_API
        shot.broll.prompt_vi = "Cảnh flycam khu đất"
    return storyboard


def _set_approval(clip: Path, approval: str, *, verdict: str | None = None) -> Path:
    """Sửa báo cáo QC do PIPELINE sinh ra, giữ nguyên ``clip_sha256``."""
    path = qc_report_path_for(clip)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["human_approval"] = approval
    if verdict is not None:
        data["verdict"] = verdict
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _approve(project: Project, storyboard: Storyboard) -> None:
    project.transition_to(ProjectState.PLANNED)
    project.approval = Approval(
        approved_by="Chủ máy",
        approved_at=now_utc(),
        storyboard_sha256=storyboard.sha256(),
    )
    project.transition_to(ProjectState.APPROVED)


def _render(pipeline: Pipeline, project: Project, storyboard: Storyboard, assets: AssetManifest):
    """Chạy render thật qua đường B-roll tính tiền.

    ``allow_paid=True`` ở đây là cờ **của riêng lần chạy test**, áp lên một
    provider giả chi phí 0,00 USD, không mạng, không key. Nó không đụng tới
    ``CURRENT_GATE``, ``max_usd_per_run`` hay bất kỳ cấu hình production nào —
    mục đích duy nhất là đi được vào nhánh B-roll trả phí để kiểm cổng QC.
    """
    return pipeline.render(
        project, storyboard, assets, RenderOptions(dry_run=False, allow_paid=True)
    )


# =========================================================================
# QC report do CHÍNH pipeline sinh ra
# =========================================================================


@needs_ffmpeg
def test_broll_tra_phi_sinh_qc_report_roi_dung_vi_chua_ai_duyet(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    provider = _BillableBrollProvider(real_clip)
    pipeline = _pipeline_with(repo, config, clock, provider)
    _enable_broll(storyboard)
    _approve(project, storyboard)
    repo.save_project(project)

    with pytest.raises(HumanApprovalRequiredError, match="chưa có người duyệt"):
        _render(pipeline, project, storyboard, granted_assets)

    # Báo cáo QC phải TỒN TẠI — do pipeline ghi, không phải test dựng.
    assert provider.written is not None
    report_path = qc_report_path_for(provider.written)
    assert report_path.is_file(), "pipeline phải ghi broll.qc.json"

    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["verdict"] == "PASS"
    assert data["human_approval"] is None, "QC PASS TUYỆT ĐỐI không được tự duyệt"


@needs_ffmpeg
def test_report_duoc_ghi_theo_duong_provider_thuc_su_ghi(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    """Provider ghi ra đường KHÁC đường yêu cầu — report phải bám đường thật."""
    provider = _BillableBrollProvider(real_clip)
    pipeline = _pipeline_with(repo, config, clock, provider)
    _enable_broll(storyboard)
    _approve(project, storyboard)
    repo.save_project(project)

    with pytest.raises(HumanApprovalRequiredError):
        _render(pipeline, project, storyboard, granted_assets)

    actual = provider.written
    assert actual is not None
    assert actual.name.startswith("ACTUAL-"), "fixture phải ghi ra đường khác"
    assert qc_report_path_for(actual).is_file()
    # và KHÔNG có report nào bám đường yêu cầu
    requested = actual.parent / actual.name.replace("ACTUAL-", "")
    assert not qc_report_path_for(requested).is_file()


@needs_ffmpeg
def test_duyet_roi_thi_composer_duoc_goi(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    provider = _BillableBrollProvider(real_clip)
    pipeline = _pipeline_with(repo, config, clock, provider)
    _enable_broll(storyboard)
    _approve(project, storyboard)
    repo.save_project(project)

    # lượt 1: sinh report rồi bị chặn
    with pytest.raises(HumanApprovalRequiredError):
        _render(pipeline, project, storyboard, granted_assets)

    # người duyệt TỪNG shot — cổng kiểm mọi shot, không chỉ shot cuối
    assert len(provider.all_written) == len(storyboard.shots)
    for clip in provider.all_written:
        _set_approval(clip, APPROVED)

    # lượt 2: đi qua tới composer
    _approve(project, storyboard)
    manifest = _render(pipeline, project, storyboard, granted_assets)
    assert RenderStage.COMPOSE in {r.stage for r in manifest.records}
    assert manifest.status == "succeeded"


@needs_ffmpeg
def test_qc_fail_thi_van_bi_chan_du_da_duyet(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    """Máy có quyền phủ quyết: QC FAIL không bị người ghi đè.

    QC phải FAIL **thật** — provider khai 1080x1920 nhưng ghi ra clip nhỏ hơn.
    Không bịa ``verdict`` trong JSON, vì pipeline tính lại verdict mỗi lần chạy
    (đúng như nó nên làm: verdict là kết quả đo, không phải thứ sửa tay được).
    """
    provider = _BillableBrollProvider(real_clip, lie_about_size=True)
    pipeline = _pipeline_with(repo, config, clock, provider)
    _enable_broll(storyboard)
    _approve(project, storyboard)
    repo.save_project(project)

    # QC FAIL ngay từ lượt đầu ⇒ chặn bằng BrollQcFailedError
    with pytest.raises(BrollQcFailedError):
        _render(pipeline, project, storyboard, granted_assets)

    report = json.loads(
        qc_report_path_for(provider.all_written[0]).read_text(encoding="utf-8")
    )
    assert report["verdict"] == "FAIL"

    # người duyệt vẫn không ghi đè được phán quyết của máy
    for clip in provider.all_written:
        _set_approval(clip, APPROVED)

    _approve(project, storyboard)
    with pytest.raises(BrollQcFailedError):
        _render(pipeline, project, storyboard, granted_assets)


@needs_ffmpeg
def test_bi_tu_choi_thi_bi_chan(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    provider = _BillableBrollProvider(real_clip)
    pipeline = _pipeline_with(repo, config, clock, provider)
    _enable_broll(storyboard)
    _approve(project, storyboard)
    repo.save_project(project)

    with pytest.raises(HumanApprovalRequiredError):
        _render(pipeline, project, storyboard, granted_assets)

    for clip in provider.all_written:
        _set_approval(clip, REJECTED)

    _approve(project, storyboard)
    with pytest.raises(HumanApprovalRequiredError):
        _render(pipeline, project, storyboard, granted_assets)


# =========================================================================
# Đường không tính tiền: D04 giữ nguyên hành vi
# =========================================================================


@needs_ffmpeg
def test_broll_khong_tinh_tien_khong_bi_cong_moi_chan(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    """``billable=False`` ⇒ không QC, không cổng. Duix/VieNeu/mock không đổi."""
    provider = _BillableBrollProvider(real_clip, billable=False)
    pipeline = _pipeline_with(repo, config, clock, provider)
    _enable_broll(storyboard)
    _approve(project, storyboard)
    repo.save_project(project)

    manifest = _render(pipeline, project, storyboard, granted_assets)

    assert manifest.status == "succeeded"
    assert provider.written is not None
    assert not qc_report_path_for(provider.written).is_file(), (
        "provider không tính tiền thì KHÔNG được sinh QC report"
    )


def test_duong_mock_mac_dinh_van_chay_het_nhu_D04(
    pipeline: Pipeline, repo: ProjectRepository, project: Project,
    storyboard: Storyboard, granted_assets: AssetManifest,
) -> None:
    """Hồi quy D04: bộ provider mock mặc định không hề bị cổng mới đụng tới."""
    _approve(project, storyboard)
    repo.save_project(project)
    manifest = pipeline.render(
        project, storyboard, granted_assets, RenderOptions(dry_run=False)
    )
    assert manifest.status == "succeeded"
    assert RenderStage.COMPOSE in {r.stage for r in manifest.records}


def test_registry_khong_bi_doi(config: Config) -> None:
    """Batch này không được đụng registry."""
    from ai_video_agent.domain.project import ProviderSelection

    providers = build_provider_set(ProviderSelection(), mode=ProviderMode.MOCK, config=config)
    assert providers.broll is None or providers.broll.info().billable is False

"""D05-C — đường resume cho B-roll trả phí đã duyệt.

Vấn đề đường resume giải quyết: sau REVIEW FIX 3, người dùng duyệt xong phải chạy
lại ``render``. Nhưng ``render`` sinh lại B-roll — với provider như Veo, đó là một
generation MỚI, một hash mới, một hoá đơn mới, và phê duyệt cũ mất hiệu lực. Người
dùng không bao giờ ghép được, mà mỗi lần thử lại tốn thêm tiền.

``Pipeline.resume()`` ghép từ artifact đã có và **không gọi provider nào**.
Bằng chứng trong mọi test dưới đây: ``provider.generate_calls``.
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
from ai_video_agent.errors import (
    HumanApprovalRequiredError,
    ValidationError,
)
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
from ai_video_agent.providers.vieneu.mock import MockVieNeuTtsProvider
from ai_video_agent.qc.approval import APPROVED, qc_report_path_for

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(
    not FFMPEG or not FFPROBE, reason="cần ffmpeg/ffprobe trên PATH"
)

CLIP_W, CLIP_H, CLIP_FPS, CLIP_SEC = 240, 426, 24, 1.0


@pytest.fixture(scope="module")
def real_clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not FFMPEG:
        pytest.skip("cần ffmpeg")
    out = tmp_path_factory.mktemp("resume_src") / "src.mp4"
    subprocess.run(  # noqa: S603
        [
            FFMPEG, "-v", "error", "-f", "lavfi",
            "-i", f"testsrc2=size={CLIP_W}x{CLIP_H}:rate={CLIP_FPS}:duration={CLIP_SEC}",
            "-vf", "format=yuv420p", "-y", str(out),
        ],
        check=True,
    )
    return out


class _CountingBrollProvider:
    """Đếm số lần ``generate`` — bằng chứng resume không gọi lại provider."""

    def __init__(self, source: Path, *, billable: bool = True) -> None:
        self._source = source
        self._billable = billable
        self.generate_calls = 0
        self.all_written: list[Path] = []

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="counting-paid-broll", kind=ProviderKind.BROLL, model="fake-veo",
            version="test", mode=ProviderMode.REAL, billable=self._billable, gate="D01",
        )

    def quote(self, request: BrollRequest) -> CostQuote:
        return CostQuote(
            stage=RenderStage.BROLL, provider="counting-paid-broll", model="fake-veo",
            unit="second", units=request.duration_sec, unit_price_usd=0.0,
            estimated_usd=0.0, billable=self._billable,
        )

    def generate(self, request: BrollRequest, out_path: Path) -> BrollResult:
        del request
        self.generate_calls += 1
        # Mỗi lần gọi sinh nội dung KHÁC nhau — đúng như model sinh video thật:
        # gọi lại là ra clip khác, hash khác, phê duyệt cũ hết hiệu lực.
        actual = out_path.parent / f"ACTUAL-{out_path.name}"
        actual.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self._source, actual)
        with actual.open("ab") as fh:
            fh.write(f"\n# generation {self.generate_calls}".encode())
        self.all_written.append(actual)
        return BrollResult(
            path=actual, duration_sec=CLIP_SEC, width=CLIP_W, height=CLIP_H,
            fps=CLIP_FPS, is_placeholder=False, actual_cost_usd=0.0,
        )


class _CountingComposer(MockComposer):
    """Đếm số lần ghép — bằng chứng cổng chặn TRƯỚC composer."""

    def __init__(self) -> None:
        super().__init__()
        self.compose_calls = 0

    def compose(self, spec: object):  # type: ignore[override]
        self.compose_calls += 1
        return super().compose(spec)  # type: ignore[arg-type]


def _pipeline(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    broll: object, composer: _CountingComposer,
) -> Pipeline:
    return Pipeline(
        repository=repo,
        providers=ProviderSet(
            tts=MockVieNeuTtsProvider(), avatar=MockDuixAvatarProvider(), broll=broll  # type: ignore[arg-type]
        ),
        config=config,
        composer=composer,
        now=clock.now_utc,
        make_run_id=clock.new_run_id,
    )


def _enable_broll(storyboard: Storyboard) -> None:
    for shot in storyboard.shots:
        shot.broll.kind = BrollKind.VIDEO_API
        shot.broll.prompt_vi = "Cảnh flycam khu đất"


def _approve_project(project: Project, storyboard: Storyboard) -> None:
    if project.state is not ProjectState.APPROVED:
        project.transition_to(ProjectState.PLANNED)
    project.approval = Approval(
        approved_by="Chủ máy", approved_at=now_utc(),
        storyboard_sha256=storyboard.sha256(),
    )
    if project.state is not ProjectState.APPROVED:
        project.transition_to(ProjectState.APPROVED)


def _approve_all_clips(provider: _CountingBrollProvider) -> None:
    for clip in provider.all_written:
        path = qc_report_path_for(clip)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["human_approval"] = APPROVED
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


#: run_id cố định để test bám đúng một run, không phải dò thư mục.
RUN_ID = "runtest01"


def _initial_render(
    pipeline: Pipeline, project: Project, storyboard: Storyboard, assets: AssetManifest,
    run_id: str = RUN_ID,
):
    return pipeline.render(
        project, storyboard, assets,
        RenderOptions(dry_run=False, allow_paid=True, run_id=run_id),
    )


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


# =========================================================================
# a) Render đầu: sinh B-roll + QC, tạm dừng vì chưa duyệt. generate = 1
# =========================================================================


@needs_ffmpeg
def test_a_render_dau_tam_dung_cho_duyet_va_generate_dung_mot_lan(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    provider = _CountingBrollProvider(real_clip)
    composer = _CountingComposer()
    pipeline = _pipeline(repo, config, clock, provider, composer)
    _enable_broll(storyboard)
    _approve_project(project, storyboard)
    repo.save_project(project)

    with pytest.raises(HumanApprovalRequiredError):
        _initial_render(pipeline, project, storyboard, granted_assets)

    assert provider.generate_calls == len(storyboard.shots)
    assert composer.compose_calls == 0, "cổng phải chặn TRƯỚC composer"

    # Tạm dừng có chủ đích, KHÔNG phải lỗi provider
    manifest = repo.load_render_manifest(project.id, RUN_ID)
    assert manifest.status == "awaiting_approval"
    assert project.state is ProjectState.APPROVED, "không được đẩy sang FAILED"
    assert any("render-resume" in w for w in manifest.warnings)


# =========================================================================
# b) Duyệt rồi resume: composer chạy, generate KHÔNG tăng
# =========================================================================


@needs_ffmpeg
def test_b_resume_ghep_duoc_ma_khong_goi_lai_provider(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    provider = _CountingBrollProvider(real_clip)
    composer = _CountingComposer()
    pipeline = _pipeline(repo, config, clock, provider, composer)
    _enable_broll(storyboard)
    _approve_project(project, storyboard)
    repo.save_project(project)

    with pytest.raises(HumanApprovalRequiredError):
        _initial_render(pipeline, project, storyboard, granted_assets)
    calls_after_render = provider.generate_calls
    run_id = RUN_ID

    _approve_all_clips(provider)
    manifest = pipeline.resume(project, storyboard, granted_assets, run_id)

    assert manifest.status == "succeeded"
    assert composer.compose_calls == 1
    assert provider.generate_calls == calls_after_render, (
        "RESUME KHÔNG được gọi lại provider — gọi lại là trả tiền lần hai"
    )
    assert manifest.outputs
    assert any("RESUME" in w for w in manifest.warnings), "phải có audit trail"
    assert project.state is ProjectState.DONE


# =========================================================================
# c) Clip đổi một byte sau khi duyệt: resume chặn, composer = 0
# =========================================================================


@needs_ffmpeg
def test_c_clip_doi_mot_byte_sau_duyet_thi_resume_bi_chan(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    provider = _CountingBrollProvider(real_clip)
    composer = _CountingComposer()
    pipeline = _pipeline(repo, config, clock, provider, composer)
    _enable_broll(storyboard)
    _approve_project(project, storyboard)
    repo.save_project(project)

    with pytest.raises(HumanApprovalRequiredError):
        _initial_render(pipeline, project, storyboard, granted_assets)
    calls_after_render = provider.generate_calls
    run_id = RUN_ID

    _approve_all_clips(provider)
    with provider.all_written[0].open("ab") as fh:
        fh.write(b"!")  # đúng một byte

    with pytest.raises(HumanApprovalRequiredError, match="đã ĐỔI sau khi được duyệt"):
        pipeline.resume(project, storyboard, granted_assets, run_id)

    assert composer.compose_calls == 0
    assert provider.generate_calls == calls_after_render


# =========================================================================
# d) Mismatch: storyboard đổi, artifact thiếu, report thiếu -> fail closed
# =========================================================================


@needs_ffmpeg
def test_d_storyboard_doi_thi_resume_bi_chan(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    provider = _CountingBrollProvider(real_clip)
    composer = _CountingComposer()
    pipeline = _pipeline(repo, config, clock, provider, composer)
    _enable_broll(storyboard)
    _approve_project(project, storyboard)
    repo.save_project(project)

    with pytest.raises(HumanApprovalRequiredError):
        _initial_render(pipeline, project, storyboard, granted_assets)
    calls = provider.generate_calls
    run_id = RUN_ID
    _approve_all_clips(provider)

    storyboard.shots[0].narration_vi = "Thoại đã bị sửa sau khi render."

    with pytest.raises(ValidationError, match="Storyboard đã đổi"):
        pipeline.resume(project, storyboard, granted_assets, run_id)
    assert composer.compose_calls == 0
    assert provider.generate_calls == calls


@needs_ffmpeg
def test_d_artifact_bien_mat_thi_resume_bi_chan(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    provider = _CountingBrollProvider(real_clip)
    composer = _CountingComposer()
    pipeline = _pipeline(repo, config, clock, provider, composer)
    _enable_broll(storyboard)
    _approve_project(project, storyboard)
    repo.save_project(project)

    with pytest.raises(HumanApprovalRequiredError):
        _initial_render(pipeline, project, storyboard, granted_assets)
    calls = provider.generate_calls
    run_id = RUN_ID
    _approve_all_clips(provider)

    provider.all_written[0].unlink()

    with pytest.raises(ValidationError, match="không còn trên đĩa"):
        pipeline.resume(project, storyboard, granted_assets, run_id)
    assert composer.compose_calls == 0
    assert provider.generate_calls == calls


@needs_ffmpeg
def test_d_bao_cao_qc_bien_mat_thi_resume_bi_chan(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    provider = _CountingBrollProvider(real_clip)
    composer = _CountingComposer()
    pipeline = _pipeline(repo, config, clock, provider, composer)
    _enable_broll(storyboard)
    _approve_project(project, storyboard)
    repo.save_project(project)

    with pytest.raises(HumanApprovalRequiredError):
        _initial_render(pipeline, project, storyboard, granted_assets)
    run_id = RUN_ID
    _approve_all_clips(provider)
    qc_report_path_for(provider.all_written[0]).unlink()

    with pytest.raises(HumanApprovalRequiredError, match="Thiếu báo cáo QC"):
        pipeline.resume(project, storyboard, granted_assets, run_id)
    assert composer.compose_calls == 0


@needs_ffmpeg
def test_d_run_khong_ton_tai_thi_bi_chan(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    provider = _CountingBrollProvider(real_clip)
    composer = _CountingComposer()
    pipeline = _pipeline(repo, config, clock, provider, composer)
    repo.save_project(project)
    with pytest.raises(Exception, match=r"(?i)không|not found|no such"):
        pipeline.resume(project, storyboard, granted_assets, "khong-co-run-nay")
    assert provider.generate_calls == 0
    assert composer.compose_calls == 0


# =========================================================================
# e) Render bình thường sau khi duyệt là REQUEST MỚI, không phải resume
# =========================================================================


@needs_ffmpeg
def test_e_render_lai_la_request_moi_chu_khong_phai_resume(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    """Chạy lại ``render`` sinh generation MỚI — đó chính là lý do resume tồn tại."""
    provider = _CountingBrollProvider(real_clip)
    composer = _CountingComposer()
    pipeline = _pipeline(repo, config, clock, provider, composer)
    _enable_broll(storyboard)
    _approve_project(project, storyboard)
    repo.save_project(project)

    with pytest.raises(HumanApprovalRequiredError):
        _initial_render(pipeline, project, storyboard, granted_assets)
    calls_first = provider.generate_calls
    hash_before = _sha(provider.all_written[0])
    _approve_all_clips(provider)

    # render lại (KHÔNG phải resume) — provider bị gọi thêm lần nữa
    _approve_project(project, storyboard)
    with pytest.raises(HumanApprovalRequiredError):
        _initial_render(pipeline, project, storyboard, granted_assets, run_id="runtest02")

    assert provider.generate_calls > calls_first, (
        "render thường PHẢI là request mới, không được giả vờ là resume"
    )
    assert _sha(provider.all_written[-1]) != hash_before, (
        "generation mới phải cho nội dung khác — đây chính là lý do phê duyệt cũ "
        "hết hiệu lực và vì sao resume phải là đường riêng"
    )
    assert composer.compose_calls == 0, "clip mới chưa ai duyệt nên vẫn bị chặn"


# =========================================================================
# f) billable=False: D04 không đổi
# =========================================================================


@needs_ffmpeg
def test_f_broll_khong_tinh_tien_van_ghep_nhu_D04(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    provider = _CountingBrollProvider(real_clip, billable=False)
    composer = _CountingComposer()
    pipeline = _pipeline(repo, config, clock, provider, composer)
    _enable_broll(storyboard)
    _approve_project(project, storyboard)
    repo.save_project(project)

    manifest = _initial_render(pipeline, project, storyboard, granted_assets)

    assert manifest.status == "succeeded"
    assert composer.compose_calls == 1
    assert not qc_report_path_for(provider.all_written[0]).is_file()

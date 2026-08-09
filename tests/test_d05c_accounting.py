"""D05-C FIX 5 — hạch toán khi tạm dừng, provenance bất biến, resume đúng mode.

Ba lỗ hổng batch này bịt:

1. **Chi phí khi pause.** Tiền tiêu ở lúc gọi provider, không phải lúc ghép. Chờ
   tới resume mới hạch toán là để ngân sách nói dối suốt thời gian chờ duyệt.
2. **Provenance.** Cổng từng hỏi ``self.providers.broll`` — nên chỉ cần đổi cấu
   hình project sang provider local sau khi đã trả tiền là mọi artifact trả phí
   lọt qua.
3. **Mode của resume.** Cờ dòng lệnh không được đổi bản chất run gốc.
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
from ai_video_agent.errors import ConfigError, HumanApprovalRequiredError, ValidationError
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
COST_PER_SHOT = 0.25
RUN_ID = "runacct01"


@pytest.fixture(scope="module")
def real_clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not FFMPEG:
        pytest.skip("cần ffmpeg")
    out = tmp_path_factory.mktemp("acct_src") / "src.mp4"
    subprocess.run(  # noqa: S603
        [
            FFMPEG, "-v", "error", "-f", "lavfi",
            "-i", f"testsrc2=size={CLIP_W}x{CLIP_H}:rate={CLIP_FPS}:duration={CLIP_SEC}",
            "-vf", "format=yuv420p", "-y", str(out),
        ],
        check=True,
    )
    return out


class _PaidBrollProvider:
    """B-roll tính tiền thật (giá tượng trưng), đếm số lần gọi."""

    def __init__(self, source: Path, *, billable: bool = True) -> None:
        self._source = source
        self._billable = billable
        self.generate_calls = 0
        self.all_written: list[Path] = []

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="paid-broll", kind=ProviderKind.BROLL, model="fake-veo",
            version="test", mode=ProviderMode.REAL, billable=self._billable, gate="D01",
        )

    def quote(self, request: BrollRequest) -> CostQuote:
        return CostQuote(
            stage=RenderStage.BROLL, provider="paid-broll", model="fake-veo",
            unit="second", units=request.duration_sec, unit_price_usd=COST_PER_SHOT,
            estimated_usd=COST_PER_SHOT, billable=self._billable,
        )

    def generate(self, request: BrollRequest, out_path: Path) -> BrollResult:
        del request
        self.generate_calls += 1
        actual = out_path.parent / f"ACTUAL-{out_path.name}"
        actual.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self._source, actual)
        self.all_written.append(actual)
        return BrollResult(
            path=actual, duration_sec=CLIP_SEC, width=CLIP_W, height=CLIP_H,
            fps=CLIP_FPS, is_placeholder=False,
            actual_cost_usd=COST_PER_SHOT if self._billable else 0.0,
        )


class _CountingComposer(MockComposer):
    def __init__(self) -> None:
        super().__init__()
        self.compose_calls = 0

    def compose(self, spec: object):  # type: ignore[override]
        self.compose_calls += 1
        return super().compose(spec)  # type: ignore[arg-type]


def _pipeline(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    broll: object | None, composer: _CountingComposer,
) -> Pipeline:
    providers = (
        ProviderSet(
            tts=MockVieNeuTtsProvider(), avatar=MockDuixAvatarProvider(), broll=broll  # type: ignore[arg-type]
        )
        if broll is not None
        else ProviderSet(tts=MockVieNeuTtsProvider(), avatar=MockDuixAvatarProvider())
    )
    return Pipeline(
        repository=repo, config=config, providers=providers,
        composer=composer, now=clock.now_utc, make_run_id=clock.new_run_id,
    )


def _enable_broll(storyboard: Storyboard) -> None:
    for shot in storyboard.shots:
        shot.broll.kind = BrollKind.VIDEO_API
        shot.broll.prompt_vi = "Cảnh flycam"


def _approve_project(project: Project, storyboard: Storyboard) -> None:
    if project.state is not ProjectState.APPROVED:
        project.transition_to(ProjectState.PLANNED)
    project.approval = Approval(
        approved_by="Chủ máy", approved_at=now_utc(), storyboard_sha256=storyboard.sha256()
    )
    if project.state is not ProjectState.APPROVED:
        project.transition_to(ProjectState.APPROVED)


def _approve_clips(provider: _PaidBrollProvider) -> None:
    for clip in provider.all_written:
        path = qc_report_path_for(clip)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["human_approval"] = APPROVED
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _render(
    pipeline: Pipeline, project: Project, storyboard: Storyboard,
    assets: AssetManifest, run_id: str = RUN_ID,
):
    project.budget.cap_usd = 100.0
    return pipeline.render(
        project, storyboard, assets,
        RenderOptions(dry_run=False, allow_paid=True, run_id=run_id),
    )


# =========================================================================
# 1. Pause: chi phí và ngân sách đúng NGAY, có dấu vết hạch toán
# =========================================================================


@needs_ffmpeg
def test_1_pause_hach_toan_chi_phi_ngay_lap_tuc(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    provider = _PaidBrollProvider(real_clip)
    composer = _CountingComposer()
    pipeline = _pipeline(repo, config, clock, provider, composer)
    _enable_broll(storyboard)
    _approve_project(project, storyboard)
    repo.save_project(project)

    with pytest.raises(HumanApprovalRequiredError):
        _render(pipeline, project, storyboard, granted_assets)

    expected = round(COST_PER_SHOT * len(storyboard.shots), 4)
    manifest = repo.load_render_manifest(project.id, RUN_ID)
    assert manifest.status == "awaiting_approval"
    assert manifest.actual_cost_usd == expected, "chi phí phải đúng NGAY lúc tạm dừng"

    saved = repo.load_project(project.id)
    assert saved.budget.spent_usd == expected, "ngân sách phải phản ánh ngay"
    assert saved.budget.already_charged(RUN_ID), "phải có dấu vết hạch toán theo run"
    assert saved.budget.charged_runs[RUN_ID].usd == expected
    assert saved.budget.charged_runs[RUN_ID].at is not None


# =========================================================================
# 2 + 3. Resume và resume lặp: compose chạy, spent KHÔNG tăng
# =========================================================================


@needs_ffmpeg
def test_2_3_resume_va_resume_lap_khong_cong_tien_lan_hai(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    provider = _PaidBrollProvider(real_clip)
    composer = _CountingComposer()
    pipeline = _pipeline(repo, config, clock, provider, composer)
    _enable_broll(storyboard)
    _approve_project(project, storyboard)
    repo.save_project(project)

    with pytest.raises(HumanApprovalRequiredError):
        _render(pipeline, project, storyboard, granted_assets)
    spent_after_pause = repo.load_project(project.id).budget.spent_usd
    calls = provider.generate_calls
    _approve_clips(provider)

    manifest = pipeline.resume(project, storyboard, granted_assets, RUN_ID)
    assert manifest.status == "succeeded"
    assert composer.compose_calls == 1
    assert provider.generate_calls == calls
    assert repo.load_project(project.id).budget.spent_usd == spent_after_pause

    # 3. Resume lặp lại — vẫn không cộng tiền
    project.transition_to(ProjectState.RENDERING, reason="thu lai", at=clock.now_utc())
    project.transition_to(ProjectState.APPROVED, reason="thu lai", at=clock.now_utc())
    repo.load_render_manifest(project.id, RUN_ID)
    saved_manifest = repo.load_render_manifest(project.id, RUN_ID)
    saved_manifest.status = "awaiting_approval"
    repo.save_render_manifest(saved_manifest)

    pipeline.resume(project, storyboard, granted_assets, RUN_ID)
    assert repo.load_project(project.id).budget.spent_usd == spent_after_pause, (
        "resume lặp KHÔNG được cộng tiền lần nữa"
    )
    assert provider.generate_calls == calls


def test_3_charge_once_idempotent_theo_run() -> None:
    """Bản chất của tính idempotent, tách khỏi pipeline cho dễ đọc."""
    from datetime import UTC, datetime

    from ai_video_agent.domain.project import BudgetPolicy

    at = datetime(2026, 8, 7, tzinfo=UTC)
    budget = BudgetPolicy(cap_usd=10.0)
    assert budget.charge_once("run-1", 3.20, at) is True
    assert budget.spent_usd == 3.20
    for _ in range(5):
        assert budget.charge_once("run-1", 3.20, at) is False
    assert budget.spent_usd == 3.20, "cộng lại nhiều lần vẫn phải bằng một lần"
    assert budget.charge_once("run-2", 1.00, at) is True
    assert budget.spent_usd == 4.20


# =========================================================================
# 4. Provenance thắng cấu hình hiện tại
# =========================================================================


@needs_ffmpeg
def test_4_doi_provider_sang_none_sau_pause_van_bi_chan(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    """Sau khi tạm dừng, dựng Pipeline KHÔNG có broll provider — vẫn phải chặn."""
    provider = _PaidBrollProvider(real_clip)
    composer = _CountingComposer()
    pipeline = _pipeline(repo, config, clock, provider, composer)
    _enable_broll(storyboard)
    _approve_project(project, storyboard)
    repo.save_project(project)

    with pytest.raises(HumanApprovalRequiredError):
        _render(pipeline, project, storyboard, granted_assets)

    # Pipeline mới: KHÔNG provider nào cả. Nếu cổng còn hỏi provider hiện tại,
    # artifact trả phí sẽ lọt qua — đó chính là lỗ hổng FIX 5 bịt.
    naked = Pipeline(repository=repo, config=config, composer=_CountingComposer())
    with pytest.raises(HumanApprovalRequiredError, match="chưa có người duyệt"):
        naked.resume(project, storyboard, granted_assets, RUN_ID)
    assert provider.generate_calls == len(storyboard.shots), "không được gọi provider thêm"


@needs_ffmpeg
def test_4_pipeline_khong_provider_thi_render_bao_loi_ro(
    repo: ProjectRepository, config: Config,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
) -> None:
    """Pipeline dựng cho resume mà đem đi render phải báo lỗi rõ, không im lặng."""
    naked = Pipeline(repository=repo, config=config)
    with pytest.raises(ConfigError, match="KHÔNG có provider"):
        naked.render(project, storyboard, granted_assets)


# =========================================================================
# 5. Resume bám mode của run gốc, không dựng provider set
# =========================================================================


@needs_ffmpeg
def test_5_resume_khong_dung_provider_set_va_khong_goi_costguard(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    provider = _PaidBrollProvider(real_clip)
    pipeline = _pipeline(repo, config, clock, provider, _CountingComposer())
    _enable_broll(storyboard)
    _approve_project(project, storyboard)
    repo.save_project(project)
    with pytest.raises(HumanApprovalRequiredError):
        _render(pipeline, project, storyboard, granted_assets)
    _approve_clips(provider)

    # Pipeline resume KHÔNG có provider — chứng minh không cần build_provider_set
    composer = _CountingComposer()
    naked = Pipeline(repository=repo, config=config, composer=composer)
    manifest = naked.resume(project, storyboard, granted_assets, RUN_ID)

    assert manifest.status == "succeeded"
    assert composer.compose_calls == 1
    assert naked.providers is None
    # costguard.enforce không bao giờ được gọi ở resume: nếu có, cap 0 sẽ chặn
    assert manifest.provider_mode is ProviderMode.MOCK


def test_5_cli_resume_chon_composer_theo_manifest() -> None:
    """CLI đọc manifest TRƯỚC, chọn composer theo ``manifest.provider_mode``."""
    source = Path("src/ai_video_agent/cli/main.py").read_text(encoding="utf-8")
    block = source[source.index("def render_resume("):]
    block = block[: block.index("def status(")]
    assert "load_render_manifest" in block
    assert "original.provider_mode is ProviderMode.REAL" in block
    assert "awaiting_approval" in block
    # bỏ dòng bình luận rồi mới soi lời gọi thật
    code = "\n".join(
        line for line in block.splitlines() if not line.lstrip().startswith("#")
    )
    assert "build_provider_set(" not in code, "resume KHÔNG được dựng provider set"
    assert "costguard" not in code, "resume KHÔNG được gọi costguard"
    assert ".generate(" not in code and ".synthesize(" not in code


@needs_ffmpeg
def test_5_resume_tu_choi_run_khong_phai_awaiting_approval(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    provider = _PaidBrollProvider(real_clip, billable=False)
    pipeline = _pipeline(repo, config, clock, provider, _CountingComposer())
    _enable_broll(storyboard)
    _approve_project(project, storyboard)
    repo.save_project(project)
    _render(pipeline, project, storyboard, granted_assets)  # succeeded

    naked = Pipeline(repository=repo, config=config, composer=_CountingComposer())
    with pytest.raises(ValidationError, match="chỉ resume được run"):
        naked.resume(project, storyboard, granted_assets, RUN_ID)


# =========================================================================
# 6. Mismatch vẫn fail-closed
# =========================================================================


@needs_ffmpeg
def test_6_hash_lech_van_fail_closed(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    provider = _PaidBrollProvider(real_clip)
    pipeline = _pipeline(repo, config, clock, provider, _CountingComposer())
    _enable_broll(storyboard)
    _approve_project(project, storyboard)
    repo.save_project(project)
    with pytest.raises(HumanApprovalRequiredError):
        _render(pipeline, project, storyboard, granted_assets)
    _approve_clips(provider)
    with provider.all_written[0].open("ab") as fh:
        fh.write(b"!")

    composer = _CountingComposer()
    naked = Pipeline(repository=repo, config=config, composer=composer)
    with pytest.raises(HumanApprovalRequiredError, match="đã ĐỔI"):
        naked.resume(project, storyboard, granted_assets, RUN_ID)
    assert composer.compose_calls == 0


# =========================================================================
# FIX 6. Verdict không phải PASS ⇒ resume chặn trước composer
# =========================================================================


@needs_ffmpeg
@pytest.mark.parametrize("verdict", ["WARN", "", "UNKNOWN"])
def test_fix6_resume_chan_khi_verdict_khong_phai_pass(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path, verdict: str,
) -> None:
    """Approval đúng, hash đúng, nhưng verdict không PASS ⇒ vẫn chặn.

    Resume là chỗ điều này quan trọng nhất: resume **không** chạy lại QC, nên
    một verdict cũ/hỏng/bị sửa tay sẽ được dùng nguyên xi nếu cổng không tự chặn.
    """
    provider = _PaidBrollProvider(real_clip)
    pipeline = _pipeline(repo, config, clock, provider, _CountingComposer())
    _enable_broll(storyboard)
    _approve_project(project, storyboard)
    repo.save_project(project)

    with pytest.raises(HumanApprovalRequiredError):
        _render(pipeline, project, storyboard, granted_assets)
    calls = provider.generate_calls
    spent_after_pause = repo.load_project(project.id).budget.spent_usd

    # duyệt đúng, hash đúng, chỉ verdict bị đổi
    for clip in provider.all_written:
        path = qc_report_path_for(clip)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["human_approval"] = APPROVED
        data["verdict"] = verdict
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    composer = _CountingComposer()
    naked = Pipeline(repository=repo, config=config, composer=composer)
    with pytest.raises(HumanApprovalRequiredError, match="verdict"):
        naked.resume(project, storyboard, granted_assets, RUN_ID)

    assert composer.compose_calls == 0, "phải chặn TRƯỚC composer"
    assert provider.generate_calls == calls, "không được gọi provider"
    assert repo.load_project(project.id).budget.spent_usd == spent_after_pause, (
        "bị chặn thì ngân sách không được đổi"
    )


@needs_ffmpeg
def test_fix6_resume_van_qua_khi_verdict_pass_va_da_duyet(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    """Đối chứng: siết verdict KHÔNG làm hỏng đường đi hợp lệ."""
    provider = _PaidBrollProvider(real_clip)
    pipeline = _pipeline(repo, config, clock, provider, _CountingComposer())
    _enable_broll(storyboard)
    _approve_project(project, storyboard)
    repo.save_project(project)
    with pytest.raises(HumanApprovalRequiredError):
        _render(pipeline, project, storyboard, granted_assets)
    _approve_clips(provider)

    composer = _CountingComposer()
    naked = Pipeline(repository=repo, config=config, composer=composer)
    manifest = naked.resume(project, storyboard, granted_assets, RUN_ID)
    assert manifest.status == "succeeded"
    assert composer.compose_calls == 1


# =========================================================================
# FIX 7. Resume bị chặn KHÔNG được xoá chi phí đã hạch toán
# =========================================================================


@needs_ffmpeg
def test_fix7_resume_bi_chan_van_giu_nguyen_actual_cost(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    """Resume bị chặn thì manifest lưu đè — không được làm mất tiền đã tiêu.

    ``resume()`` dựng một ``RenderManifest`` mới từ run gốc. Nếu không mang theo
    ``actual_cost_usd``, nhánh ``except`` sẽ lưu bản 0.0 đè lên bản đã hạch toán,
    và nhật ký sẽ nói rằng run này không tốn đồng nào — trong khi tiền đã tiêu.
    """
    provider = _PaidBrollProvider(real_clip)
    pipeline = _pipeline(repo, config, clock, provider, _CountingComposer())
    _enable_broll(storyboard)
    _approve_project(project, storyboard)
    repo.save_project(project)

    # 1. Pause: chi phí phải > 0
    with pytest.raises(HumanApprovalRequiredError):
        _render(pipeline, project, storyboard, granted_assets)

    paused = repo.load_render_manifest(project.id, RUN_ID)
    cost_at_pause = paused.actual_cost_usd
    assert cost_at_pause > 0, "run trả phí phải có chi phí > 0 lúc pause"
    saved = repo.load_project(project.id)
    spent_at_pause = saved.budget.spent_usd
    charged_at_pause = saved.budget.charged_runs[RUN_ID].usd
    calls = provider.generate_calls

    # 2. Approval và hash đúng, chỉ verdict bị đổi thành WARN
    for clip in provider.all_written:
        path = qc_report_path_for(clip)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["human_approval"] = APPROVED
        data["verdict"] = "WARN"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    # 3. Resume bị chặn
    composer = _CountingComposer()
    naked = Pipeline(repository=repo, config=config, composer=composer)
    with pytest.raises(HumanApprovalRequiredError):
        naked.resume(project, storyboard, granted_assets, RUN_ID)

    # 4. Nạp lại: chi phí và ngân sách phải nguyên vẹn
    after = repo.load_render_manifest(project.id, RUN_ID)
    assert after.actual_cost_usd == cost_at_pause, (
        "resume bị chặn KHÔNG được xoá actual_cost_usd đã hạch toán"
    )
    reloaded = repo.load_project(project.id)
    assert reloaded.budget.spent_usd == spent_at_pause
    assert reloaded.budget.charged_runs[RUN_ID].usd == charged_at_pause
    assert composer.compose_calls == 0
    assert provider.generate_calls == calls


@needs_ffmpeg
def test_fix7_resume_thanh_cong_cung_giu_dung_chi_phi(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    """Đối chứng: đường thành công cũng phải giữ đúng chi phí, không nhân đôi."""
    provider = _PaidBrollProvider(real_clip)
    pipeline = _pipeline(repo, config, clock, provider, _CountingComposer())
    _enable_broll(storyboard)
    _approve_project(project, storyboard)
    repo.save_project(project)
    with pytest.raises(HumanApprovalRequiredError):
        _render(pipeline, project, storyboard, granted_assets)
    cost_at_pause = repo.load_render_manifest(project.id, RUN_ID).actual_cost_usd
    spent_at_pause = repo.load_project(project.id).budget.spent_usd
    _approve_clips(provider)

    naked = Pipeline(repository=repo, config=config, composer=_CountingComposer())
    manifest = naked.resume(project, storyboard, granted_assets, RUN_ID)

    assert manifest.status == "succeeded"
    assert manifest.actual_cost_usd == cost_at_pause
    assert repo.load_project(project.id).budget.spent_usd == spent_at_pause


# =========================================================================
# 7. billable=False: D04 không đổi
# =========================================================================


@needs_ffmpeg
def test_7_local_billable_false_giu_hanh_vi_D04(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    provider = _PaidBrollProvider(real_clip, billable=False)
    composer = _CountingComposer()
    pipeline = _pipeline(repo, config, clock, provider, composer)
    _enable_broll(storyboard)
    _approve_project(project, storyboard)
    repo.save_project(project)

    manifest = _render(pipeline, project, storyboard, granted_assets)

    assert manifest.status == "succeeded"
    assert composer.compose_calls == 1
    assert not qc_report_path_for(provider.all_written[0]).is_file()
    # provenance ghi rõ: không tính tiền, không cần duyệt
    broll_records = [r for r in manifest.records if r.stage is RenderStage.BROLL]
    assert broll_records
    for record in broll_records:
        assert record.billable is False
        assert record.requires_human_approval is False


@needs_ffmpeg
def test_7_provenance_duoc_ghi_vao_manifest_khi_tra_phi(
    repo: ProjectRepository, config: Config, clock: FixedClock,
    project: Project, storyboard: Storyboard, granted_assets: AssetManifest,
    real_clip: Path,
) -> None:
    provider = _PaidBrollProvider(real_clip)
    pipeline = _pipeline(repo, config, clock, provider, _CountingComposer())
    _enable_broll(storyboard)
    _approve_project(project, storyboard)
    repo.save_project(project)
    with pytest.raises(HumanApprovalRequiredError):
        _render(pipeline, project, storyboard, granted_assets)

    manifest = repo.load_render_manifest(project.id, RUN_ID)
    broll_records = [r for r in manifest.records if r.stage is RenderStage.BROLL]
    assert broll_records
    for record in broll_records:
        assert record.billable is True
        assert record.requires_human_approval is True

"""Chạy pipeline render từ storyboard.

Ba tính chất được thiết kế có chủ đích:

* **Dry-run là mặc định.** Ở chế độ này không provider nào bị gọi; hệ thống chỉ
  ghi ra kế hoạch và bảng chi phí (brief §D01.5).
* **Cache theo shot.** Artifact của mỗi shot nằm dưới hash nội dung của chính
  shot đó. Sửa thoại của một shot thì chỉ shot đó chạy lại, phần còn lại được
  dùng lại — đúng yêu cầu "sửa riêng thoại/cảnh và chỉ chạy lại phần phụ thuộc"
  (brief §9) và "không tự tạo lại cảnh vì lý do thẩm mỹ" (brief §4).
* **Bước ghép luôn chạy lại.** Ghép là thao tác rẻ, và chỉ khi ghép lại toàn bộ
  thì phụ đề cùng mốc thời gian mới còn đúng.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ai_video_agent.clock import new_run_id, now_utc
from ai_video_agent.composer.ffmpeg import (
    ComposeSpec,
    DrawTextSpec,
    build_concat_file,
    default_font_file,
)
from ai_video_agent.composer.runner import Composer, MockComposer
from ai_video_agent.composer.subtitles import build_cues, write_srt
from ai_video_agent.config import Config
from ai_video_agent.domain.assets import AssetEntry, AssetManifest
from ai_video_agent.domain.enums import (
    AssetKind,
    BrollKind,
    ProjectState,
    ProviderMode,
    RenderStage,
    StageStatus,
)
from ai_video_agent.domain.project import Project
from ai_video_agent.domain.render import (
    AvatarProvenanceRecord,
    RenderManifest,
    RenderRecord,
    ResourceUsage,
)
from ai_video_agent.domain.storyboard import Shot, Storyboard
from ai_video_agent.errors import (
    BrollQcFailedError,
    ConfigError,
    ConsentMissingError,
    HumanApprovalRequiredError,
    ProviderError,
    ValidationError,
)
from ai_video_agent.orchestrator import costguard
from ai_video_agent.orchestrator.estimator import Estimate, estimate_storyboard
from ai_video_agent.orchestrator.repository import ProjectRepository
from ai_video_agent.providers._placeholder import read_wav_duration
from ai_video_agent.providers.avatar_capability import (
    describe_language_fit,
    language_is_verified,
)
from ai_video_agent.providers.base import (
    AvatarCapability,
    AvatarRequest,
    AvatarResult,
    BrollRequest,
    BrollResult,
    ProviderInfo,
    ProviderSet,
    TtsRequest,
    fingerprint_file,
)
from ai_video_agent.providers.resource_budget import (
    ResourceBudget,
    ResourcePreflight,
    check_resources,
)
from ai_video_agent.qc.approval import assert_shot_approved, qc_report_path_for
from ai_video_agent.qc.broll import run_qc

#: Tiền tố của cảnh báo ngôn ngữ trong ``manifest.warnings``. CLI dùng nó để in
#: nổi bật thay vì chìm lẫn trong các ghi chú thường lệ. Định nghĩa một chỗ để
#: hai bên không tự gõ lại chuỗi rồi lệch nhau.
LANGUAGE_WARNING_PREFIX = "CẢNH BÁO NGÔN NGỮ"

#: Khoảng cách dọc giữa hai lớp chữ chính xác xếp chồng.
_TEXT_STACK_STEP = 70
_TEXT_BASE_Y = 180


@dataclass(frozen=True)
class RenderOptions:
    """Tuỳ chọn của một lần chạy ``aiva render``."""

    #: Mặc định True — phải nói rõ mới thực thi (brief §D01.5).
    dry_run: bool = True
    provider_mode: ProviderMode = ProviderMode.MOCK
    allow_paid: bool = False
    #: Chỉ render lại các shot này; các shot khác dùng lại artifact đã có.
    only_shots: tuple[str, ...] = ()
    run_id: str | None = None
    #: Bỏ qua cache, render lại tất cả.
    force: bool = False


@dataclass
class _ShotArtifacts:
    """Kết quả trung gian của một shot."""

    shot: Shot
    audio: Path
    audio_duration_sec: float
    video: Path
    broll: Path | None = None
    start_sec: float = 0.0
    #: Lấy từ provider **lúc sinh**, hoặc từ nhật ký run gốc khi resume. Cố ý
    #: KHÔNG hỏi ``self._provider_set`` ở thời điểm ghép: đổi cấu hình project sang
    #: provider local sau khi đã trả tiền không được biến artifact trả phí thành
    #: artifact miễn kiểm duyệt.
    broll_requires_approval: bool = False


@dataclass
class Pipeline:
    """Điều phối TTS -> avatar -> (B-roll) -> phụ đề -> ghép."""

    repository: ProjectRepository
    config: Config
    #: ``None`` là hợp lệ và có ý nghĩa: đường :meth:`resume` **không được phép**
    #: gọi provider nào, nên nó cũng không cần provider nào. Dựng Pipeline không
    #: có provider là cách biến ràng buộc đó thành thứ máy tự thực thi thay vì
    #: một lời hứa trong tài liệu.
    providers: ProviderSet | None = None
    composer: Composer = field(default_factory=MockComposer)
    now: Callable[[], datetime] = now_utc
    make_run_id: Callable[[], str] = new_run_id

    @property
    def _provider_set(self) -> ProviderSet:
        """Provider set cho đường render. Ném lỗi rõ nếu ai đó quên truyền."""
        if self.providers is None:
            msg = (
                "Pipeline này được dựng KHÔNG có provider (chế độ resume). "
                "Đường render cần provider — dựng lại Pipeline với providers=..."
            )
            raise ConfigError(msg)
        return self.providers

    # ----- ước tính ------------------------------------------------------------

    def estimate(self, project: Project, storyboard: Storyboard) -> Estimate:
        return estimate_storyboard(project, storyboard, self._provider_set)

    # ----- render --------------------------------------------------------------

    def render(
        self,
        project: Project,
        storyboard: Storyboard,
        assets: AssetManifest,
        options: RenderOptions | None = None,
    ) -> RenderManifest:
        opts = options or RenderOptions()
        self._validate_only_shots(storyboard, opts.only_shots)

        estimate = self.estimate(project, storyboard)
        decision = costguard.enforce(
            project,
            storyboard,
            assets,
            estimate,
            execute=not opts.dry_run,
            provider_mode=opts.provider_mode,
            allow_paid=opts.allow_paid,
        )

        manifest = RenderManifest(
            project_id=project.id,
            run_id=opts.run_id or self.make_run_id(),
            dry_run=opts.dry_run,
            provider_mode=opts.provider_mode,
            storyboard_sha256=storyboard.sha256(),
            created_at=self.now(),
            status="planned" if opts.dry_run else "running",
            estimated_cost_usd=estimate.total_usd,
            ai_disclosure_applied=project.ai_disclosure.enabled,
            tool_versions=self._tool_versions(),
            warnings=[*estimate.warnings, *decision.warnings],
        )

        # Trước cả dry-run: đây là những câu trả lời được mà không cần chạy gì,
        # nên không có lý do gì bắt người dùng thêm --execute mới biết.
        preflight = self._avatar_prechecks(manifest, project, storyboard)

        if opts.dry_run:
            self._fill_dry_run(manifest, project, storyboard, estimate)
            self.repository.save_render_manifest(manifest)
            return manifest

        return self._execute(manifest, project, storyboard, assets, opts, preflight)

    # ----- dry-run -------------------------------------------------------------

    def _fill_dry_run(
        self,
        manifest: RenderManifest,
        project: Project,
        storyboard: Storyboard,
        estimate: Estimate,
    ) -> None:
        """Ghi kế hoạch từng bước mà không gọi bất kỳ provider nào."""
        cost_by_key = {(line.stage, line.provider): line.estimated_usd for line in estimate.lines}
        tts_info = self._provider_set.tts.info()
        avatar_info = self._provider_set.avatar.info()

        for shot in storyboard.shots:
            manifest.add(
                RenderRecord(
                    stage=RenderStage.TTS,
                    shot_id=shot.id,
                    provider=tts_info.name,
                    model=tts_info.model,
                    version=tts_info.version,
                    mode=tts_info.mode,
                    status=StageStatus.PLANNED,
                    estimated_cost_usd=cost_by_key.get((RenderStage.TTS, tts_info.name), 0.0),
                    message="Dry-run: chưa gọi provider.",
                )
            )
            manifest.add(
                RenderRecord(
                    stage=RenderStage.AVATAR,
                    shot_id=shot.id,
                    provider=avatar_info.name,
                    model=avatar_info.model,
                    version=avatar_info.version,
                    mode=avatar_info.mode,
                    status=StageStatus.PLANNED,
                    estimated_cost_usd=cost_by_key.get((RenderStage.AVATAR, avatar_info.name), 0.0),
                    message="Dry-run: chưa gọi provider.",
                )
            )
            if shot.broll.kind is not BrollKind.NONE and self._provider_set.broll is not None:
                broll_info = self._provider_set.broll.info()
                manifest.add(
                    RenderRecord(
                        stage=RenderStage.BROLL,
                        shot_id=shot.id,
                        provider=broll_info.name,
                        model=broll_info.model,
                        version=broll_info.version,
                        mode=broll_info.mode,
                        status=StageStatus.PLANNED,
                        estimated_cost_usd=cost_by_key.get(
                            (RenderStage.BROLL, broll_info.name), 0.0
                        ),
                        message="Dry-run: chưa gọi provider (bước này TÍNH TIỀN khi chạy thật).",
                    )
                )

        composer_info = self.composer.info()
        for stage in (RenderStage.SUBTITLE, RenderStage.COMPOSE):
            manifest.add(
                RenderRecord(
                    stage=stage,
                    provider=composer_info.name,
                    model=composer_info.model,
                    version=composer_info.version,
                    mode=composer_info.mode,
                    status=StageStatus.PLANNED,
                    message="Dry-run: chưa thực thi.",
                )
            )
        manifest.status = "planned"
        manifest.finished_at = self.now()
        manifest.warnings.append(
            f"Dry-run cho {len(storyboard.shots)} shot, tổng {storyboard.total_duration_sec:.2f}s. "
            f"Thêm --execute để chạy thật (project {project.state.value})."
        )

    # ----- thực thi ------------------------------------------------------------

    def _execute(
        self,
        manifest: RenderManifest,
        project: Project,
        storyboard: Storyboard,
        assets: AssetManifest,
        opts: RenderOptions,
        preflight: ResourcePreflight,
    ) -> RenderManifest:
        paths = self.repository.paths(project.id)
        run_dir = paths.run_dir(manifest.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        project.transition_to(
            ProjectState.RENDERING, reason=f"render {manifest.run_id}", at=self.now()
        )
        self.repository.save_project(project)

        try:
            artifacts = self._render_shots(manifest, project, storyboard, assets, opts, preflight)
            subtitles = self._write_subtitles(manifest, run_dir, artifacts)
            output = self._compose(manifest, project, assets, artifacts, subtitles)
        except (HumanApprovalRequiredError, BrollQcFailedError) as exc:
            # Tạm dừng CÓ CHỦ ĐÍCH, không phải lỗi provider. Artifact đã sinh xong
            # và đã tốn tiền; đẩy project sang FAILED sẽ khiến người dùng tưởng
            # phải chạy lại từ đầu, mà chạy lại là trả tiền lần hai.
            manifest.status = "awaiting_approval"
            manifest.finished_at = self.now()
            # Tiền đã tiêu ở lúc gọi provider, KHÔNG phải lúc ghép. Chờ tới resume
            # mới hạch toán là để ngân sách nói dối trong suốt thời gian chờ duyệt.
            manifest.actual_cost_usd = self._sum_actual_cost(manifest)
            manifest.warnings.append(
                f"Tạm dừng chờ người duyệt B-roll: {exc} "
                f"Sau khi duyệt, chạy: aiva render-resume {project.id} {manifest.run_id}"
            )
            self.repository.save_render_manifest(manifest)
            charged = project.budget.charge_once(
                manifest.run_id, manifest.actual_cost_usd, self.now()
            )
            manifest.warnings.append(
                f"Hạch toán run {manifest.run_id}: {manifest.actual_cost_usd} USD"
                if charged
                else f"Run {manifest.run_id} đã được hạch toán trước đó, không cộng lại."
            )
            self.repository.save_render_manifest(manifest)
            project.transition_to(
                ProjectState.APPROVED,
                reason=f"chờ duyệt B-roll của run {manifest.run_id}",
                at=self.now(),
            )
            self.repository.save_project(project)
            raise
        except Exception as exc:
            manifest.status = "failed"
            manifest.finished_at = self.now()
            manifest.warnings.append(f"Render thất bại: {exc}")
            self.repository.save_render_manifest(manifest)
            project.transition_to(ProjectState.FAILED, reason=str(exc)[:200], at=self.now())
            self.repository.save_project(project)
            raise

        manifest.status = "succeeded"
        manifest.finished_at = self.now()
        manifest.outputs = [str(output)]
        manifest.actual_cost_usd = self._sum_actual_cost(manifest)
        self.repository.save_render_manifest(manifest)

        project.transition_to(ProjectState.COMPOSED, reason="ghép xong", at=self.now())
        project.transition_to(ProjectState.DONE, reason=f"output {output.name}", at=self.now())
        # Idempotent theo run: nếu run này đã bị hạch toán lúc tạm dừng trước đó
        # thì không cộng lần hai.
        project.budget.charge_once(manifest.run_id, manifest.actual_cost_usd, self.now())
        self.repository.save_project(project)
        return manifest

    @staticmethod
    def _sum_actual_cost(manifest: RenderManifest) -> float:
        return round(sum(record.actual_cost_usd or 0.0 for record in manifest.records), 4)

    def _render_shots(
        self,
        manifest: RenderManifest,
        project: Project,
        storyboard: Storyboard,
        assets: AssetManifest,
        opts: RenderOptions,
        preflight: ResourcePreflight,
    ) -> list[_ShotArtifacts]:
        width, height = project.aspect_ratio.size
        mock = opts.provider_mode is ProviderMode.MOCK
        audio_name = "audio.mock.wav" if mock else "audio.wav"
        video_name = "avatar.mock.mp4" if mock else "avatar.mp4"
        broll_name = "broll.mock.mp4" if mock else "broll.mp4"

        avatar_asset = next(iter(assets.of_kind(AssetKind.AVATAR_SOURCE)), None)
        avatar_source = (
            self.repository.paths(project.id).assets_dir / avatar_asset.path
            if avatar_asset is not None
            else None
        )
        voice_asset = self._select_voice_asset(project, assets)
        ref_audio = (
            self.repository.paths(project.id).assets_dir / voice_asset.path
            if voice_asset is not None
            else None
        )

        tts_info = self._provider_set.tts.info()
        avatar_info = self._provider_set.avatar.info()
        avatar_capability = self._provider_set.avatar.capability()
        results: list[_ShotArtifacts] = []
        cursor = 0.0

        for shot in storyboard.shots:
            cache = self.repository.paths(project.id).shot_cache_dir(shot.id, shot.content_hash())
            audio_path = cache / audio_name
            video_path = cache / video_name
            targeted = not opts.only_shots or shot.id in opts.only_shots
            # Dùng lại theo TỪNG BƯỚC, không phải tất-cả-hoặc-không. Audio đã sinh
            # cho đúng nội dung shot này vẫn còn giá trị kể cả khi bước avatar
            # hỏng ở lần trước — sinh lại giọng chỉ vì thế là phí công và làm đổi
            # giọng (TTS có lấy mẫu ngẫu nhiên). Cũng nhờ vậy mà đưa sẵn một WAV
            # đã được duyệt vào cache là bỏ qua được bước TTS, không cần đường vòng.
            can_reuse = not opts.force and not targeted
            reuse_audio = can_reuse and audio_path.is_file()
            reuse_video = reuse_audio and video_path.is_file()

            # Shot chốt sẵn audio đã duyệt thì KHÔNG chạy TTS: sinh lại sẽ ra
            # giọng khác (TTS có lấy mẫu ngẫu nhiên) và làm hỏng bản đã nghiệm thu.
            approved_audio = self._approved_audio(shot, assets, project)
            if approved_audio is not None:
                audio_path.parent.mkdir(parents=True, exist_ok=True)
                if not audio_path.is_file():
                    shutil.copyfile(approved_audio, audio_path)
                    audio_path.chmod(0o666)
                duration = read_wav_duration(audio_path)
                manifest.add(
                    self._record(
                        RenderStage.TTS,
                        shot.id,
                        tts_info,
                        StageStatus.SKIPPED,
                        outputs=[str(audio_path)],
                        message=(
                            f"Bỏ qua TTS: shot dùng audio đã duyệt "
                            f"{shot.narration_audio_asset_id!r} ({approved_audio.name})."
                        ),
                    )
                )
            elif reuse_audio:
                duration = read_wav_duration(audio_path)
                manifest.add(
                    self._record(
                        RenderStage.TTS,
                        shot.id,
                        tts_info,
                        StageStatus.REUSED,
                        outputs=[str(audio_path)],
                        message="Dùng lại audio đã có (nội dung shot không đổi).",
                    )
                )
            else:
                started = self.now()
                tts_result = self._provider_set.tts.synthesize(
                    TtsRequest(
                        shot_id=shot.id,
                        text_vi=shot.narration_vi,
                        ref_audio=ref_audio,
                        sample_rate=self.config.vieneu_sample_rate,
                        target_duration_sec=shot.duration_sec,
                    ),
                    audio_path,
                )
                duration = tts_result.duration_sec
                manifest.add(
                    self._record(
                        RenderStage.TTS,
                        shot.id,
                        tts_info,
                        StageStatus.SUCCEEDED,
                        started_at=started,
                        finished_at=self.now(),
                        outputs=[str(tts_result.path)],
                        is_placeholder=tts_result.is_placeholder,
                        actual_cost_usd=tts_result.actual_cost_usd,
                    )
                )

            if reuse_video:
                manifest.add(
                    self._record(
                        RenderStage.AVATAR,
                        shot.id,
                        avatar_info,
                        StageStatus.REUSED,
                        inputs=[str(audio_path)],
                        outputs=[str(video_path)],
                        message="Dùng lại video đã có.",
                    )
                )
            else:
                avatar_request = AvatarRequest(
                    shot_id=shot.id,
                    audio_path=audio_path,
                    avatar_source=avatar_source,
                    width=width,
                    height=height,
                    fps=project.fps,
                    duration_sec=duration,
                )
                started = self.now()
                avatar_result = self._provider_set.avatar.generate(avatar_request, video_path)
                # Provider thật (Duix) ghi kết quả vào thư mục của riêng nó, không
                # theo đường dẫn ta đưa. Đưa về cache của shot để bước ghép và lần
                # chạy sau đều tìm thấy ở một chỗ duy nhất.
                if Path(avatar_result.path).resolve() != video_path.resolve():
                    video_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(avatar_result.path, video_path)
                manifest.add(
                    self._record(
                        RenderStage.AVATAR,
                        shot.id,
                        avatar_info,
                        StageStatus.SUCCEEDED,
                        started_at=started,
                        finished_at=self.now(),
                        inputs=[str(audio_path)],
                        outputs=[str(video_path)],
                        is_placeholder=avatar_result.is_placeholder,
                        actual_cost_usd=avatar_result.actual_cost_usd,
                        avatar_provenance=self._avatar_provenance_record(
                            avatar_info, avatar_capability, avatar_result, video_path, preflight
                        ),
                        message=(
                            f"provider ghi tại {avatar_result.path}"
                            if Path(avatar_result.path).resolve() != video_path.resolve()
                            else ""
                        ),
                    )
                )

            broll_path: Path | None = None
            broll_requires_approval = False
            if shot.broll.kind is not BrollKind.NONE and self._provider_set.broll is not None:
                broll_info = self._provider_set.broll.info()
                requested_broll = cache / broll_name
                started = self.now()
                broll_result = self._provider_set.broll.generate(
                    BrollRequest(
                        shot_id=shot.id,
                        prompt_vi=shot.broll.prompt_vi or shot.narration_vi,
                        duration_sec=duration,
                        width=width,
                        height=height,
                        fps=project.fps,
                    ),
                    requested_broll,
                )
                # Dùng đường provider THỰC SỰ ghi, không phải đường ta yêu cầu.
                # Duix từng ghi ra chỗ khác rồi trả về đường thật qua kết quả;
                # tin vào đường yêu cầu sẽ khiến QC soi nhầm file hoặc soi file rỗng.
                broll_path = Path(broll_result.path)
                broll_requires_approval = broll_info.billable
                qc_report = self._run_broll_qc(broll_info, broll_path, broll_result)
                record = self._record(
                    RenderStage.BROLL,
                    shot.id,
                    broll_info,
                    StageStatus.SUCCEEDED,
                    started_at=started,
                    finished_at=self.now(),
                    outputs=[str(broll_result.path)],
                    is_placeholder=broll_result.is_placeholder,
                    actual_cost_usd=broll_result.actual_cost_usd,
                    message=(f"QC: {qc_report}" if qc_report else ""),
                )
                # Đóng dấu provenance vào nhật ký: đây là sự thật của RUN NÀY.
                record.billable = broll_info.billable
                record.requires_human_approval = broll_requires_approval
                manifest.add(record)

            results.append(
                _ShotArtifacts(
                    shot=shot,
                    audio=audio_path,
                    audio_duration_sec=duration,
                    video=video_path,
                    broll=broll_path,
                    start_sec=round(cursor, 3),
                    broll_requires_approval=broll_requires_approval,
                )
            )
            cursor += duration

        return results

    def _write_subtitles(
        self,
        manifest: RenderManifest,
        run_dir: Path,
        artifacts: list[_ShotArtifacts],
    ) -> Path | None:
        segments = [
            (item.shot.narration_vi, item.audio_duration_sec)
            for item in artifacts
            if item.shot.subtitle
        ]
        composer_info = self.composer.info()
        if not segments:
            manifest.add(
                self._record(
                    RenderStage.SUBTITLE,
                    None,
                    composer_info,
                    StageStatus.SKIPPED,
                    message="Không shot nào bật phụ đề.",
                )
            )
            return None

        cues = build_cues(segments)
        path = write_srt(run_dir / "subtitles.srt", cues)
        manifest.add(
            self._record(
                RenderStage.SUBTITLE,
                None,
                composer_info,
                StageStatus.SUCCEEDED,
                started_at=self.now(),
                finished_at=self.now(),
                outputs=[str(path)],
                is_placeholder=False,
                message=f"{len(cues)} dòng phụ đề.",
            )
        )
        return path

    # ----- resume ---------------------------------------------------------------

    def resume(
        self,
        project: Project,
        storyboard: Storyboard,
        assets: AssetManifest,
        run_id: str,
    ) -> RenderManifest:
        """Ghép lại từ artifact CÓ SẴN của một run đã tạm dừng chờ duyệt.

        Đây là đường đi riêng, không phải ``render`` ngầm đổi hành vi. Nó **không
        gọi** TTS, avatar, B-roll provider, transport hay cost guard cho lần chạy
        thật — vì mọi thứ tốn tiền đã xảy ra ở run gốc rồi. Gọi lại chúng chính là
        thứ khiến người dùng trả tiền lần hai.

        Fail-closed ở mọi điểm nghi ngờ: storyboard đổi, thiếu artifact, báo cáo QC
        thiếu hoặc cũ, clip đổi dù một byte — đều dừng, không ghép.
        """
        original = self.repository.load_render_manifest(project.id, run_id)

        if original.status != "awaiting_approval":
            msg = (
                f"Run {run_id} đang ở trạng thái {original.status!r}, chỉ resume được run "
                "'awaiting_approval'. Resume không phải cách chạy lại một run đã xong, "
                "đã hỏng, hay chưa từng thực thi."
            )
            raise ValidationError(msg)

        if original.storyboard_sha256 != storyboard.sha256():
            msg = (
                f"Storyboard đã đổi kể từ run {run_id} "
                f"(run ghi {original.storyboard_sha256[:16]}…, hiện tại "
                f"{storyboard.sha256()[:16]}…). Artifact cũ không còn khớp kịch bản — "
                "phải render lại thay vì resume."
            )
            raise ValidationError(msg)

        if original.dry_run:
            msg = f"Run {run_id} là dry-run nên không có artifact nào để ghép."
            raise ValidationError(msg)

        artifacts = self._restore_artifacts(original, storyboard)

        manifest = RenderManifest(
            project_id=project.id,
            run_id=run_id,
            dry_run=False,
            provider_mode=original.provider_mode,
            storyboard_sha256=original.storyboard_sha256,
            created_at=self.now(),
            status="running",
            estimated_cost_usd=original.estimated_cost_usd,
            # Mang theo chi phí đã hạch toán ở lần pause NGAY TỪ ĐẦU. Nếu resume
            # bị chặn ở QC/duyệt, nhánh except lưu manifest này đè lên bản cũ —
            # để mặc định 0.0 là xoá mất dấu vết của tiền đã tiêu thật.
            actual_cost_usd=original.actual_cost_usd,
            ai_disclosure_applied=original.ai_disclosure_applied,
            tool_versions=self._tool_versions(),
            # Giữ nguyên nhật ký của run gốc: đây là cùng một run được nối tiếp,
            # không phải một lần chạy mới.
            records=list(original.records),
            warnings=[
                *original.warnings,
                f"RESUME: ghép lại từ artifact có sẵn của run {run_id}. "
                "Không gọi lại TTS/avatar/B-roll provider.",
            ],
        )
        for item in artifacts:
            manifest.warnings.append(
                f"RESUME dùng shot {item.shot.id}: audio={item.audio.name}, "
                f"video={item.video.name}"
                + (f", broll={item.broll.name}" if item.broll else "")
            )

        run_dir = self.repository.paths(project.id).run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        project.transition_to(
            ProjectState.RENDERING, reason=f"resume {run_id}", at=self.now()
        )
        self.repository.save_project(project)

        try:
            subtitles = self._write_subtitles(manifest, run_dir, artifacts)
            output = self._compose(manifest, project, assets, artifacts, subtitles)
        except (HumanApprovalRequiredError, BrollQcFailedError) as exc:
            manifest.status = "awaiting_approval"
            manifest.finished_at = self.now()
            manifest.warnings.append(f"Resume vẫn bị chặn: {exc}")
            self.repository.save_render_manifest(manifest)
            project.transition_to(
                ProjectState.APPROVED, reason="resume bị chặn", at=self.now()
            )
            self.repository.save_project(project)
            raise
        except Exception as exc:
            manifest.status = "failed"
            manifest.finished_at = self.now()
            manifest.warnings.append(f"Resume thất bại: {exc}")
            self.repository.save_render_manifest(manifest)
            project.transition_to(ProjectState.FAILED, reason=str(exc)[:200], at=self.now())
            self.repository.save_project(project)
            raise

        manifest.status = "succeeded"
        manifest.finished_at = self.now()
        manifest.outputs = [str(output)]
        # KHÔNG cộng chi phí lần nữa. Run gốc đã hạch toán lúc tạm dừng; ngân sách
        # project đã phản ánh đúng từ lúc đó. Resume không gọi provider nên không
        # tiêu thêm đồng nào, và cũng KHÔNG chạm tới costguard execution.
        manifest.actual_cost_usd = original.actual_cost_usd
        manifest.warnings.append(
            f"Chi phí giữ nguyên {original.actual_cost_usd} USD của run gốc; "
            f"đã hạch toán từ trước: {project.budget.already_charged(run_id)}."
        )
        self.repository.save_render_manifest(manifest)

        project.transition_to(ProjectState.COMPOSED, reason="resume ghép xong", at=self.now())
        project.transition_to(ProjectState.DONE, reason=f"output {output.name}", at=self.now())
        self.repository.save_project(project)
        return manifest

    def _restore_artifacts(
        self, original: RenderManifest, storyboard: Storyboard
    ) -> list[_ShotArtifacts]:
        """Dựng lại ``_ShotArtifacts`` từ nhật ký đã persist. Không sinh lại gì."""
        by_shot: dict[str, dict[RenderStage, Path]] = {}
        #: Provenance đọc từ nhật ký run gốc, KHÔNG suy từ cấu hình hiện tại.
        needs_approval: dict[str, bool] = {}
        for record in original.records:
            if record.shot_id is None or not record.outputs:
                continue
            if record.stage in {RenderStage.TTS, RenderStage.AVATAR, RenderStage.BROLL}:
                by_shot.setdefault(record.shot_id, {})[record.stage] = Path(record.outputs[0])
            if record.stage is RenderStage.BROLL:
                needs_approval[record.shot_id] = bool(
                    record.requires_human_approval or record.billable
                )

        restored: list[_ShotArtifacts] = []
        cursor = 0.0
        for shot in storyboard.shots:
            found = by_shot.get(shot.id)
            if not found:
                msg = (
                    f"Run {original.run_id} không có artifact nào cho shot {shot.id}. "
                    "Không ghép từ dữ liệu thiếu."
                )
                raise ValidationError(msg)

            audio = found.get(RenderStage.TTS)
            video = found.get(RenderStage.AVATAR)
            if audio is None or video is None:
                msg = f"Shot {shot.id} thiếu audio hoặc video trong run {original.run_id}."
                raise ValidationError(msg)
            for kind, path in (("audio", audio), ("video", video)):
                if not path.is_file():
                    msg = (
                        f"Artifact {kind} của shot {shot.id} không còn trên đĩa: {path}. "
                        "Không ghép từ artifact thiếu."
                    )
                    raise ValidationError(msg)

            broll = found.get(RenderStage.BROLL)
            if broll is not None and not broll.is_file():
                msg = (
                    f"B-roll của shot {shot.id} không còn trên đĩa: {broll}. "
                    "Không ghép từ artifact thiếu."
                )
                raise ValidationError(msg)

            duration = read_wav_duration(audio)
            restored.append(
                _ShotArtifacts(
                    shot=shot,
                    audio=audio,
                    audio_duration_sec=duration,
                    video=video,
                    broll=broll,
                    start_sec=round(cursor, 3),
                    broll_requires_approval=needs_approval.get(shot.id, False),
                )
            )
            cursor += duration
        return restored

    def _run_broll_qc(
        self,
        broll_info: ProviderInfo,
        broll_path: Path,
        broll_result: BrollResult,
    ) -> str:
        """Chạy QC local trên B-roll trả phí rồi ghi báo cáo cạnh chính clip.

        Chỉ chạy cho provider **tính tiền**. Provider local hoặc mock có
        ``billable=False`` nên không bị đụng — D04 giữ nguyên hành vi.

        Đối chiếu file với **những gì provider tự khai** (``broll_result``), chứ
        không phải với những gì pipeline yêu cầu. Provider có thể trả về thứ khác
        yêu cầu một cách hợp lệ — Veo 3.1 luôn xuất 24 fps bất kể ta xin bao
        nhiêu. Điều QC cần bắt là *provider khai một đằng, file một nẻo*.

        ``human_approval`` luôn được ghi là ``None``. Không nhánh nào ở đây được
        phép đặt giá trị khác: QC ``PASS`` chỉ nghĩa là không đo được lỗi, không
        phải là duyệt thẩm mỹ.
        """
        if not broll_info.billable:
            return ""

        report = run_qc(
            clip=broll_path,
            ffmpeg=self.config.ffmpeg_bin,
            ffprobe=self.config.ffprobe_bin,
            want_width=broll_result.width,
            want_height=broll_result.height,
            want_fps=broll_result.fps,
            want_duration_sec=broll_result.duration_sec,
        )
        report.human_approval = None  # bất biến: máy không tự duyệt
        report_path = qc_report_path_for(broll_path)

        # Phê duyệt gắn với NỘI DUNG clip. Nếu lần chạy này sinh ra đúng clip cũ
        # (cùng sha256) thì giữ lại phê duyệt đã có — nếu không, mỗi lần render
        # lại sẽ xoá sạch phê duyệt và người dùng không bao giờ đi qua được cổng.
        # Clip đổi một byte là sha256 đổi, phê duyệt cũ mất hiệu lực ngay.
        if report_path.is_file():
            try:
                previous = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                previous = {}
            if previous.get("clip_sha256") and previous["clip_sha256"] == report.clip_sha256:
                report.human_approval = previous.get("human_approval")

        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report.to_json(), encoding="utf-8")
        return f"{report.verdict}, human_approval={report.human_approval!r}"

    def _assert_paid_broll_approved(self, artifacts: list[_ShotArtifacts]) -> None:
        """Chặn composer khi B-roll trả phí chưa qua QC và chưa được người duyệt.

        Chỉ áp cho B-roll sinh bởi provider **tính tiền**. Đường Duix/VieNeu và
        mọi provider local đều có ``billable=False`` nên không bị đụng — D04 giữ
        nguyên hành vi.

        Ghi nhận trung thực về phạm vi: ở bản hiện tại ``_compose`` mới dựng
        concat từ ``item.video``, **chưa** tiêu thụ ``item.broll``. Cổng này vì
        vậy đặt ở ranh giới ngay trước composer để không một artifact trả phí nào
        đi qua được mà thiếu duyệt, kể cả khi sau này composer bắt đầu dùng nó.

        Quyết định "có cần duyệt không" lấy từ **provenance đã persist của run**
        (:attr:`_ShotArtifacts.broll_requires_approval`), **không** hỏi
        ``self._provider_set.broll``. Nếu hỏi provider hiện tại, chỉ cần đổi cấu hình
        project sang provider local sau khi đã trả tiền là mọi artifact trả phí
        lọt qua cổng — đúng loại lỗ hổng mà cổng này sinh ra để bịt.
        """
        for item in artifacts:
            if item.broll is None or not item.broll_requires_approval:
                continue
            # Truyền cả clip để cổng tự băm lại tại đây, thay vì tin con số đã ghi
            # lúc QC chạy. Clip có thể đã đổi giữa lúc duyệt và lúc ghép.
            assert_shot_approved(qc_report_path_for(item.broll), item.broll)

    def _compose(
        self,
        manifest: RenderManifest,
        project: Project,
        assets: AssetManifest,
        artifacts: list[_ShotArtifacts],
        subtitles: Path | None,
    ) -> Path:
        self._assert_paid_broll_approved(artifacts)

        project_paths = self.repository.paths(project.id)
        run_dir = project_paths.run_dir(manifest.run_id)
        width, height = project.aspect_ratio.size
        mock = manifest.provider_mode is ProviderMode.MOCK

        concat_file = run_dir / "concat.txt"
        concat_file.write_text(
            build_concat_file([item.video for item in artifacts]), encoding="utf-8", newline="\n"
        )

        logo_asset = next(iter(assets.of_kind(AssetKind.LOGO)), None)
        logo_path = project_paths.assets_dir / logo_asset.path if logo_asset else None

        suffix = ".mock.mp4" if mock else ".mp4"
        output = project_paths.outputs_dir / f"{project.id}-{manifest.run_id}{suffix}"
        spec = ComposeSpec(
            concat_file=concat_file,
            output=output,
            width=width,
            height=height,
            fps=project.fps,
            subtitles=subtitles,
            logo=logo_path,
            draw_texts=self._draw_texts(project, artifacts, height),
            ffmpeg_bin=self.config.ffmpeg_bin,
        )

        composer_info = self.composer.info()
        started = self.now()
        outcome = self.composer.compose(spec)
        manifest.add(
            self._record(
                RenderStage.COMPOSE,
                None,
                composer_info,
                StageStatus.SUCCEEDED,
                started_at=started,
                finished_at=self.now(),
                inputs=[str(item.video) for item in artifacts],
                outputs=[str(outcome.output)],
                is_placeholder=outcome.is_placeholder,
                message=outcome.message,
            )
        )
        manifest.warnings.append("Lệnh FFmpeg: " + " ".join(outcome.command))
        return outcome.output

    # ----- chữ hiển thị --------------------------------------------------------

    def _draw_texts(
        self,
        project: Project,
        artifacts: list[_ShotArtifacts],
        height: int,
    ) -> list[DrawTextSpec]:
        """Chuyển ``on_screen_text`` thành lớp drawtext có mốc thời gian tuyệt đối.

        Đây là chỗ hiện thực brief §D04.2: chữ chính xác do composer chèn.
        """
        font = default_font_file()
        specs: list[DrawTextSpec] = []
        for item in artifacts:
            for level, text in enumerate(item.shot.on_screen_text):
                start = item.start_sec + text.start_offset_sec
                span = text.duration_sec or max(
                    0.5, item.audio_duration_sec - text.start_offset_sec
                )
                specs.append(
                    DrawTextSpec(
                        text=text.text,
                        y=f"h-text_h-{_TEXT_BASE_Y + level * _TEXT_STACK_STEP}",
                        start_sec=round(start, 3),
                        end_sec=round(start + span, 3),
                        font_file=font,
                    )
                )

        if project.ai_disclosure.enabled and project.ai_disclosure.burn_in:
            specs.append(
                DrawTextSpec(
                    text=project.ai_disclosure.label_vi,
                    x="(w-text_w)/2",
                    y="60",
                    font_size=34,
                    box_color="black@0.35",
                    box_border=12,
                    font_file=font,
                )
            )
        return specs

    # ----- tiện ích ------------------------------------------------------------

    def _approved_audio(self, shot: Shot, assets: AssetManifest, project: Project) -> Path | None:
        """Đường dẫn audio đã duyệt cho shot, hoặc ``None`` nếu shot dùng TTS."""
        wanted = shot.narration_audio_asset_id
        if not wanted:
            return None

        entry = assets.get(wanted)
        if entry is None:
            available = ", ".join(a.id for a in assets.assets) or "(không có)"
            msg = (
                f"Shot {shot.id} chốt dùng audio {wanted!r} nhưng manifest không có. "
                f"Đang có: {available}."
            )
            raise ValidationError(msg)
        if not entry.consent.usable:
            msg = (
                f"Audio {wanted!r} có consent={entry.consent.status.value}, "
                "chưa được phép dùng để render."
            )
            raise ConsentMissingError(msg)

        path = self.repository.paths(project.id).assets_dir / entry.path
        if not path.is_file():
            msg = f"Audio đã duyệt {wanted!r} không có trên đĩa: {path}"
            raise ValidationError(msg)
        return path

    @staticmethod
    def _select_voice_asset(project: Project, assets: AssetManifest) -> AssetEntry | None:
        """Chọn mẫu giọng theo ID đã chốt trong project.

        Khi ``providers.voice_asset_id`` được đặt, chỉ đúng tài sản đó được dùng
        — thêm giọng mới vào manifest sẽ không âm thầm đổi giọng đầu ra. Sai ID
        thì báo lỗi ngay thay vì lặng lẽ quay về tài sản đầu tiên.
        """
        wanted = project.providers.voice_asset_id
        samples = assets.of_kind(AssetKind.VOICE_SAMPLE)
        if not wanted:
            return next(iter(samples), None)

        chosen = next((asset for asset in samples if asset.id == wanted), None)
        if chosen is None:
            available = ", ".join(asset.id for asset in samples) or "(không có)"
            msg = (
                f"Project chốt dùng mẫu giọng {wanted!r} nhưng manifest không có. "
                f"Đang có: {available}."
            )
            raise ValidationError(msg)
        return chosen

    @staticmethod
    def _validate_only_shots(storyboard: Storyboard, only_shots: tuple[str, ...]) -> None:
        known = {shot.id for shot in storyboard.shots}
        unknown = sorted(set(only_shots) - known)
        if unknown:
            msg = f"Không có shot: {', '.join(unknown)}. Shot hợp lệ: {', '.join(sorted(known))}"
            raise ValidationError(msg)

    def _avatar_prechecks(
        self, manifest: RenderManifest, project: Project, storyboard: Storyboard
    ) -> ResourcePreflight:
        """Hai kiểm tra chạy TRƯỚC mọi thứ, giống hệt nhau ở dry-run và execute.

        Đặt ở đây thay vì trong vòng lặp shot vì cả hai câu hỏi đều thuộc về *lần
        chạy*, không thuộc về từng shot: backend nào, ngôn ngữ nào, máy có bao
        nhiêu tài nguyên. Nhờ vậy ``aiva render`` không có ``--execute`` trả lời
        được đúng những câu mà bản có ``--execute`` trả lời — mà không chạm
        provider, GPU hay HTTP.

        Chia đôi rất rõ:

        * **Ngôn ngữ** chỉ cảnh báo. Chạy Duix cho tiếng Việt là lựa chọn có ý
          thức (PO đã chọn ở bake-off D04), không phải lỗi cấu hình.
        * **Tài nguyên** thì chặn — nhưng chỉ khi *biết chắc* là thiếu.
        """
        avatar = self._provider_set.avatar
        info = avatar.info()
        capability = avatar.capability()

        if not language_is_verified(capability, storyboard.language):
            manifest.warnings.append(
                f"{LANGUAGE_WARNING_PREFIX} — {info.name} ({info.model}@{info.version}): "
                f"{describe_language_fit(capability, storyboard.language)} "
                f"Đã kiểm chứng: {sorted(capability.languages_verified)}. "
                "Vẫn render bình thường; đây là trần chất lượng đã biết, không phải lỗi."
            )

        preflight = check_resources(
            info.name,
            avatar.estimate_resources(self._worst_case_request(project, storyboard)),
            ResourceBudget.detect(self.config),
        )
        preflight.raise_if_insufficient()
        manifest.warnings.append(preflight.warning())
        return preflight

    @staticmethod
    def _worst_case_request(project: Project, storyboard: Storyboard) -> AvatarRequest:
        """Shot dài nhất — preflight phải trả lời cho trường hợp nặng nhất.

        Duix tốn VRAM theo kích thước khung chứ không theo thời lượng, nên với
        backend hiện tại chọn shot nào cũng ra một kết quả. Nhưng một backend
        sau này có thể giữ toàn bộ khung trong VRAM; lúc đó lấy shot đầu tiên sẽ
        cho ra con số đẹp rồi OOM ở shot dài nhất.
        """
        longest = max(storyboard.shots, key=lambda shot: shot.duration_sec)
        width, height = project.aspect_ratio.size
        return AvatarRequest(
            shot_id=longest.id,
            # Dry-run chưa có WAV nào. `estimate_resources()` không được đọc file
            # — hợp đồng D04-A đã có test canh đúng điều đó, nên đường dẫn này
            # không tồn tại là chuyện bình thường, không phải thiếu sót.
            audio_path=Path("chua-sinh.wav"),
            avatar_source=None,
            width=width,
            height=height,
            fps=project.fps,
            duration_sec=longest.duration_sec,
        )

    @staticmethod
    def _avatar_provenance_record(
        info: ProviderInfo,
        capability: AvatarCapability,
        result: AvatarResult,
        output_path: Path,
        preflight: ResourcePreflight,
    ) -> AvatarProvenanceRecord:
        """Đổi provenance của provider sang model lưu trữ của ``domain/``.

        Ghi ``None`` khi provider không khai là che lỗi: nhìn manifest sẽ không
        phân biệt được "backend không hỗ trợ truy vết" với "có hỗ trợ nhưng ai đó
        quên nối dây". Nên thiếu là hỏng ngay, kèm tên backend để biết đi sửa ở đâu.
        """
        provenance = result.provenance
        if provenance is None:
            msg = (
                f"Provider avatar {info.name!r} ({info.model}@{info.version}) trả về "
                "kết quả KHÔNG có provenance. Hợp đồng AvatarProvider bắt buộc "
                "trường này để truy ngược video về model và đầu vào đã sinh ra nó. "
                "Sửa adapter để trả AvatarProvenance, đừng ghi manifest rỗng."
            )
            raise ProviderError(msg)

        needed = preflight.needed
        return AvatarProvenanceRecord(
            backend_id=provenance.backend_id,
            backend_version=provenance.backend_version,
            model=provenance.model,
            model_version=provenance.model_version,
            audio_encoder=provenance.audio_encoder,
            #: Ảnh chụp năng lực tại LÚC CHẠY. Backend nâng cấp sau này không được
            #: làm đổi nghĩa của một manifest đã ghi.
            languages_verified=sorted(capability.languages_verified),
            native_fps=capability.native_fps,
            source_fps=provenance.source_fps,
            audio_sha256=provenance.audio_sha256,
            source_asset_sha256=provenance.source_asset_sha256,
            #: Băm file ĐÃ NẰM TRONG CACHE, không phải file provider tự ghi ra —
            #: đây mới là file bước ghép sẽ đọc.
            output_sha256=fingerprint_file(output_path),
            checkpoint_sha256=provenance.checkpoint_sha256,
            image_digest=provenance.image_digest,
            output_width=result.width,
            output_height=result.height,
            output_fps=result.fps,
            output_duration_sec=result.duration_sec,
            params=dict(provenance.params),
            resources=ResourceUsage(
                est_vram_mib=needed.vram_mib,
                est_ram_mib=needed.ram_mib,
                est_storage_mib=needed.storage_mib,
                estimate_measured=needed.measured,
                estimate_measured_on=needed.measured_on,
                peak_vram_mib=provenance.peak_vram_mib,
                render_seconds=provenance.render_seconds,
            ),
        )

    def _record(
        self,
        stage: RenderStage,
        shot_id: str | None,
        info: ProviderInfo,
        status: StageStatus,
        *,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        inputs: list[str] | None = None,
        outputs: list[str] | None = None,
        is_placeholder: bool = False,
        actual_cost_usd: float | None = None,
        avatar_provenance: AvatarProvenanceRecord | None = None,
        message: str = "",
    ) -> RenderRecord:
        return RenderRecord(
            stage=stage,
            shot_id=shot_id,
            provider=info.name,
            model=info.model,
            version=info.version,
            mode=info.mode,
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            inputs=inputs or [],
            outputs=outputs or [],
            is_placeholder=is_placeholder,
            actual_cost_usd=actual_cost_usd,
            avatar_provenance=avatar_provenance,
            message=message,
        )

    def _tool_versions(self) -> dict[str, str]:
        import platform

        from ai_video_agent import __version__

        versions = {
            "ai_video_agent": __version__,
            "python": platform.python_version(),
        }
        # Resume dựng Pipeline không có provider — không có gì để liệt kê, và đó
        # chính là điều cần ghi nhận: lần chạy này không chạm provider nào.
        if self.providers is not None:
            for info in self.providers.infos():
                versions[f"provider:{info.name}"] = f"{info.model}@{info.version}"
        composer_info = self.composer.info()
        versions[f"composer:{composer_info.name}"] = (
            f"{composer_info.model}@{composer_info.version}"
        )
        return versions

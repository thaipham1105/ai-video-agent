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
from ai_video_agent.domain.render import RenderManifest, RenderRecord
from ai_video_agent.domain.storyboard import Shot, Storyboard
from ai_video_agent.errors import ConsentMissingError, ValidationError
from ai_video_agent.orchestrator import costguard
from ai_video_agent.orchestrator.estimator import Estimate, estimate_storyboard
from ai_video_agent.orchestrator.repository import ProjectRepository
from ai_video_agent.providers._placeholder import read_wav_duration
from ai_video_agent.providers.base import (
    AvatarRequest,
    BrollRequest,
    ProviderInfo,
    ProviderSet,
    TtsRequest,
)

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


@dataclass
class Pipeline:
    """Điều phối TTS -> avatar -> (B-roll) -> phụ đề -> ghép."""

    repository: ProjectRepository
    providers: ProviderSet
    config: Config
    composer: Composer = field(default_factory=MockComposer)
    now: Callable[[], datetime] = now_utc
    make_run_id: Callable[[], str] = new_run_id

    # ----- ước tính ------------------------------------------------------------

    def estimate(self, project: Project, storyboard: Storyboard) -> Estimate:
        return estimate_storyboard(project, storyboard, self.providers)

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

        if opts.dry_run:
            self._fill_dry_run(manifest, project, storyboard, estimate)
            self.repository.save_render_manifest(manifest)
            return manifest

        return self._execute(manifest, project, storyboard, assets, opts)

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
        tts_info = self.providers.tts.info()
        avatar_info = self.providers.avatar.info()

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
            if shot.broll.kind is not BrollKind.NONE and self.providers.broll is not None:
                broll_info = self.providers.broll.info()
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
    ) -> RenderManifest:
        paths = self.repository.paths(project.id)
        run_dir = paths.run_dir(manifest.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        project.transition_to(
            ProjectState.RENDERING, reason=f"render {manifest.run_id}", at=self.now()
        )
        self.repository.save_project(project)

        try:
            artifacts = self._render_shots(manifest, project, storyboard, assets, opts)
            subtitles = self._write_subtitles(manifest, run_dir, artifacts)
            output = self._compose(manifest, project, assets, artifacts, subtitles)
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
        manifest.actual_cost_usd = round(
            sum(record.actual_cost_usd or 0.0 for record in manifest.records), 4
        )
        self.repository.save_render_manifest(manifest)

        project.transition_to(ProjectState.COMPOSED, reason="ghép xong", at=self.now())
        project.transition_to(ProjectState.DONE, reason=f"output {output.name}", at=self.now())
        project.budget.spent_usd = round(project.budget.spent_usd + manifest.actual_cost_usd, 4)
        self.repository.save_project(project)
        return manifest

    def _render_shots(
        self,
        manifest: RenderManifest,
        project: Project,
        storyboard: Storyboard,
        assets: AssetManifest,
        opts: RenderOptions,
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

        tts_info = self.providers.tts.info()
        avatar_info = self.providers.avatar.info()
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
                tts_result = self.providers.tts.synthesize(
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
                started = self.now()
                avatar_result = self.providers.avatar.generate(
                    AvatarRequest(
                        shot_id=shot.id,
                        audio_path=audio_path,
                        avatar_source=avatar_source,
                        width=width,
                        height=height,
                        fps=project.fps,
                        duration_sec=duration,
                    ),
                    video_path,
                )
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
                        message=(
                            f"provider ghi tại {avatar_result.path}"
                            if Path(avatar_result.path).resolve() != video_path.resolve()
                            else ""
                        ),
                    )
                )

            broll_path: Path | None = None
            if shot.broll.kind is not BrollKind.NONE and self.providers.broll is not None:
                broll_info = self.providers.broll.info()
                broll_path = cache / broll_name
                started = self.now()
                broll_result = self.providers.broll.generate(
                    BrollRequest(
                        shot_id=shot.id,
                        prompt_vi=shot.broll.prompt_vi or shot.narration_vi,
                        duration_sec=duration,
                        width=width,
                        height=height,
                        fps=project.fps,
                    ),
                    broll_path,
                )
                manifest.add(
                    self._record(
                        RenderStage.BROLL,
                        shot.id,
                        broll_info,
                        StageStatus.SUCCEEDED,
                        started_at=started,
                        finished_at=self.now(),
                        outputs=[str(broll_result.path)],
                        is_placeholder=broll_result.is_placeholder,
                        actual_cost_usd=broll_result.actual_cost_usd,
                    )
                )

            results.append(
                _ShotArtifacts(
                    shot=shot,
                    audio=audio_path,
                    audio_duration_sec=duration,
                    video=video_path,
                    broll=broll_path,
                    start_sec=round(cursor, 3),
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

    def _compose(
        self,
        manifest: RenderManifest,
        project: Project,
        assets: AssetManifest,
        artifacts: list[_ShotArtifacts],
        subtitles: Path | None,
    ) -> Path:
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
            message=message,
        )

    def _tool_versions(self) -> dict[str, str]:
        import platform

        from ai_video_agent import __version__

        versions = {
            "ai_video_agent": __version__,
            "python": platform.python_version(),
        }
        for info in self.providers.infos():
            versions[f"provider:{info.name}"] = f"{info.model}@{info.version}"
        composer_info = self.composer.info()
        versions[f"composer:{composer_info.name}"] = (
            f"{composer_info.model}@{composer_info.version}"
        )
        return versions

"""CLI ``aiva`` — cửa vào duy nhất của hệ thống.

Lệnh tối thiểu theo brief §D01.3: ``doctor``, ``plan``, ``estimate``,
``render --dry-run``, ``status``. Thêm ``approve`` (vì brief §9 đòi người dùng
duyệt trước render) và ``validate`` (kiểm tra file theo ``schemas/``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from ai_video_agent import CURRENT_GATE, __version__
from ai_video_agent.cli.doctor import Status, run_checks, worst_status
from ai_video_agent.cli.preflight import blocking, check_duix_ready
from ai_video_agent.clock import now_utc
from ai_video_agent.composer.runner import FfmpegComposer, MockComposer
from ai_video_agent.config import Config
from ai_video_agent.domain.enums import AspectRatio, AssetKind, ProjectState, ProviderMode
from ai_video_agent.domain.project import Approval, BudgetPolicy, Project, ProviderSelection
from ai_video_agent.domain.render import RenderManifest
from ai_video_agent.errors import AivaError, ProjectNotFoundError
from ai_video_agent.jsonschemas import SchemaName, iter_errors
from ai_video_agent.orchestrator.estimator import Estimate
from ai_video_agent.orchestrator.pipeline import (
    LANGUAGE_WARNING_PREFIX,
    Pipeline,
    RenderOptions,
)
from ai_video_agent.orchestrator.planner import RuleBasedPlanner
from ai_video_agent.orchestrator.repository import ProjectRepository
from ai_video_agent.orchestrator.textutil import slugify
from ai_video_agent.providers.base import TtsRequest
from ai_video_agent.providers.registry import build_provider_set
from ai_video_agent.webui import DEFAULT_PORT, HOST
from ai_video_agent.webui.launcher import ensure_duix_ready
from ai_video_agent.webui.report import write_report

app = typer.Typer(
    name="aiva",
    help="AI-VIDEO-AGENT — dựng video tiếng Việt chạy local.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

_STATUS_STYLE = {
    Status.PASS: "green",
    Status.WARN: "yellow",
    Status.FAIL: "red",
    Status.INFO: "cyan",
}


def _repo(config: Config | None = None) -> ProjectRepository:
    cfg = config or Config.from_env()
    return ProjectRepository(cfg.runtime_dir)


def _fail(message: str) -> None:
    console.print(f"[red]Lỗi:[/red] {message}")
    raise typer.Exit(code=1)


def _kiem_tra_van_hanh() -> bool:
    """In kết quả kiểm tra vận hành; trả ``False`` nếu có thứ chặn.

    Chạy **trước** bước duyệt: hỏng ở đây thì chưa có gì bị đổi trạng thái, chạy
    lại đúng lệnh cũ là đi tiếp. Duyệt xong mới phát hiện thiếu Docker thì project
    đã ở APPROVED trong khi chưa dựng được gì.
    """
    console.print("[bold]•[/bold] Kiểm tra máy trước khi dựng…")
    ket_qua = check_duix_ready(Config.from_env())
    for r in ket_qua:
        mau = _STATUS_STYLE[r.status]
        console.print(f"  [{mau}]{r.status.value:4}[/] {r.name:9} {escape(r.detail)}")
    chan = blocking(ket_qua)
    if chan:
        console.print(
            f"\n[red]Dừng lại:[/red] còn {len(chan)} thứ chưa sẵn sàng. "
            "Xử xong rồi chạy lại đúng lệnh này."
        )
        return False
    return True


def _print_warnings(warnings: list[str]) -> None:
    """In cảnh báo của manifest, **giữ nguyên từng ký tự** của nội dung.

    Phải ``escape``: Rich đọc ``[...]`` trong chuỗi là thẻ định dạng. Cảnh báo
    "Lệnh FFmpeg: …" chứa ``-map [vout]``, và Rich nuốt mất ``[vout]`` — người
    dùng chép lệnh in ra sẽ được một lệnh hỏng. Lệnh thật trong manifest vẫn
    luôn đúng; hỏng chỉ ở khâu hiển thị.

    Markup bao ngoài (``[dim]``, ``[yellow]``) là của ta nên vẫn sống.
    """
    for warning in warnings:
        # Cảnh báo ngôn ngữ nói về trần chất lượng khẩu hình — in [dim] cùng các
        # ghi chú thường lệ thì đúng là có hiện, nhưng không ai đọc.
        noi_dung = escape(warning)
        if warning.startswith(LANGUAGE_WARNING_PREFIX):
            console.print(f"[yellow]![/yellow] {noi_dung}")
        else:
            console.print(f"[dim]• {noi_dung}[/dim]")


@app.callback(invoke_without_command=True)
def _root(
    version: Annotated[bool, typer.Option("--version", help="In phiên bản rồi thoát.")] = False,
) -> None:
    if version:
        console.print(f"ai-video-agent {__version__} (gate {CURRENT_GATE})")
        raise typer.Exit


# ---------------------------------------------------------------- doctor -----


@app.command()
def doctor(
    as_json: Annotated[bool, typer.Option("--json", help="Xuất JSON thay vì bảng.")] = False,
) -> None:
    """Kiểm tra môi trường. Chỉ đọc, không sửa gì."""
    results = run_checks()

    if as_json:
        console.print_json(
            json.dumps(
                [{"name": r.name, "status": r.status.value, "detail": r.detail} for r in results],
                ensure_ascii=False,
            )
        )
    else:
        table = Table(title="aiva doctor", show_lines=False)
        table.add_column("Mục", style="bold")
        table.add_column("Trạng thái")
        table.add_column("Chi tiết")
        for result in results:
            table.add_row(
                result.name,
                f"[{_STATUS_STYLE[result.status]}]{result.status.value}[/]",
                result.detail,
            )
        console.print(table)

    if worst_status(results) is Status.FAIL:
        raise typer.Exit(code=1)


# ------------------------------------------------------------------ plan -----


@app.command()
def plan(
    brief: Annotated[str, typer.Option("--brief", "-b", help="Yêu cầu bằng tiếng Việt.")],
    title: Annotated[str, typer.Option("--title", help="Tiêu đề project.")] = "",
    project_id: Annotated[
        str, typer.Option("--id", help="ID project (mặc định tạo từ tiêu đề).")
    ] = "",
    duration: Annotated[
        float, typer.Option("--duration", "-d", help="Thời lượng mục tiêu (giây).")
    ] = 45.0,
    aspect: Annotated[
        str, typer.Option("--aspect", help="Tỷ lệ khung hình: 9:16 | 16:9 | 1:1.")
    ] = "9:16",
    fps: Annotated[int, typer.Option("--fps", help="Khung hình/giây.")] = 30,
    budget: Annotated[
        float, typer.Option("--budget", help="Trần chi phí USD cho API tính tiền.")
    ] = 0.0,
    ai_label: Annotated[
        bool, typer.Option("--ai-label/--no-ai-label", help="Gắn nhãn nội dung AI.")
    ] = True,
) -> None:
    """Biến brief tiếng Việt thành ``storyboard.json`` có schema hợp lệ."""
    try:
        ratio = AspectRatio(aspect)
    except ValueError:
        _fail(f"--aspect không hợp lệ: {aspect!r}. Hợp lệ: 9:16, 16:9, 1:1")
        return

    resolved_title = title or brief.strip().splitlines()[0][:80]
    pid = project_id or slugify(resolved_title)
    repo = _repo()

    try:
        project = (
            repo.load_project(pid)
            if repo.exists(pid)
            else Project(
                id=pid,
                title=resolved_title,
                brief_vi=brief,
                aspect_ratio=ratio,
                target_duration_sec=duration,
                fps=fps,
                budget=BudgetPolicy(cap_usd=budget),
                providers=ProviderSelection(),
            )
        )
        project.brief_vi = brief
        project.title = resolved_title
        project.aspect_ratio = ratio
        project.target_duration_sec = duration
        project.fps = fps
        project.budget.cap_usd = budget
        project.ai_disclosure.enabled = ai_label

        storyboard = RuleBasedPlanner().plan(
            project_id=project.id,
            brief_vi=brief,
            target_duration_sec=duration,
            aspect_ratio=ratio,
        )

        # Kịch bản mới thì phê duyệt cũ hết hiệu lực (brief §9).
        if project.approval is not None and not project.approval_matches(storyboard.sha256()):
            project.revoke_approval(reason="storyboard được lập lại")
        if project.state is ProjectState.DRAFT:
            project.transition_to(ProjectState.PLANNED, reason="plan", at=now_utc())
        elif project.state is not ProjectState.PLANNED:
            project.transition_to(ProjectState.PLANNED, reason="lập lại kế hoạch", at=now_utc())

        storyboard_path = repo.save_storyboard(storyboard)
        project_path = repo.save_project(project)
    except AivaError as exc:
        _fail(str(exc))
        return

    console.print(f"[green]✓[/green] Project [bold]{project.id}[/bold] — {project.state.value}")
    console.print(f"  {project_path}")
    console.print(f"  {storyboard_path}")

    table = Table(
        title=f"Storyboard: {len(storyboard.shots)} shot / {storyboard.total_duration_sec:.1f}s"
    )
    table.add_column("Shot")
    table.add_column("Scene")
    table.add_column("Giây", justify="right")
    table.add_column("Thoại")
    table.add_column("Chữ chính xác")
    for scene, shot in storyboard.iter_shots():
        table.add_row(
            shot.id,
            scene.role.value,
            f"{shot.duration_sec:.1f}",
            shot.narration_vi[:60] + ("…" if len(shot.narration_vi) > 60 else ""),
            ", ".join(f"{t.text} [{t.kind.value}]" for t in shot.on_screen_text) or "—",
        )
    console.print(table)
    console.print("[dim]Xem lại rồi chạy: aiva approve " + project.id + ' --by "Tên bạn"[/dim]')


# --------------------------------------------------------------- approve -----


@app.command()
def approve(
    project_id: Annotated[str, typer.Argument(help="ID project.")],
    by: Annotated[str, typer.Option("--by", help="Người duyệt.")],
    note: Annotated[str, typer.Option("--note", help="Ghi chú.")] = "",
) -> None:
    """Duyệt kịch bản. Phê duyệt được neo vào hash của storyboard hiện tại."""
    repo = _repo()
    try:
        project = repo.load_project(project_id)
        storyboard = repo.load_storyboard(project_id)
        digest = storyboard.sha256()
        if project.state is not ProjectState.PLANNED:
            project.transition_to(ProjectState.PLANNED, reason="chuẩn bị duyệt", at=now_utc())
        project.approval = Approval(
            approved_by=by,
            approved_at=now_utc(),
            storyboard_sha256=digest,
            note=note,
        )
        project.transition_to(ProjectState.APPROVED, reason=f"duyệt bởi {by}", at=now_utc())
        repo.save_project(project)
    except AivaError as exc:
        _fail(str(exc))
        return

    console.print(f"[green]✓[/green] {project_id} → APPROVED (bởi {by})")
    console.print(f"  storyboard sha256: {digest[:16]}…")
    console.print("[dim]Sửa storyboard sau bước này sẽ làm phê duyệt hết hiệu lực.[/dim]")


# -------------------------------------------------------------- estimate -----


def _estimate_table(estimate: Estimate) -> Table:
    table = Table(title=f"Chi phí dự kiến — {estimate.total_duration_sec:.1f}s")
    table.add_column("Bước")
    table.add_column("Provider")
    table.add_column("Đơn vị", justify="right")
    table.add_column("Đơn giá USD", justify="right")
    table.add_column("Thành tiền USD", justify="right")
    table.add_column("Tính tiền")
    for line in estimate.lines:
        table.add_row(
            line.stage.value,
            f"{line.provider}/{line.model}",
            f"{line.units:.1f} {line.unit}",
            f"{line.unit_price_usd:.4f}",
            f"{line.estimated_usd:.4f}",
            "[red]CÓ[/red]" if line.billable else "không",
        )
    return table


@app.command()
def estimate(
    project_id: Annotated[str, typer.Argument(help="ID project.")],
    provider_mode: Annotated[str, typer.Option("--provider-mode", help="mock | real")] = "mock",
    detail: Annotated[bool, typer.Option("--detail", help="Liệt kê từng dòng chi phí.")] = False,
) -> None:
    """Ước tính chi phí mà không chạy provider nào."""
    repo = _repo()
    config = Config.from_env()
    try:
        project = repo.load_project(project_id)
        storyboard = repo.load_storyboard(project_id)
        providers = build_provider_set(
            project.providers, mode=ProviderMode(provider_mode), config=config
        )
        result = Pipeline(
            repository=repo, providers=providers, config=config, composer=MockComposer()
        ).estimate(project, storyboard)
    except (AivaError, ValueError) as exc:
        _fail(str(exc))
        return

    if detail:
        console.print(_estimate_table(result))

    console.print(
        f"Tổng dự kiến: [bold]{result.total_usd:.4f} USD[/bold] "
        f"(phần tính tiền: {result.billable_usd:.4f} USD, "
        f"trần còn lại: {project.budget.remaining_usd:.4f} USD)"
    )
    for line in {line.assumption for line in result.lines if line.assumption}:
        console.print(f"[dim]• {escape(line)}[/dim]")
    for warning in result.warnings:
        console.print(f"[yellow]![/yellow] {escape(warning)}")


# ---------------------------------------------------------------- render -----


@app.command()
def render(
    project_id: Annotated[str, typer.Argument(help="ID project.")],
    execute: Annotated[
        bool,
        typer.Option("--execute", help="Chạy thật. Không có cờ này thì luôn là dry-run."),
    ] = False,
    provider_mode: Annotated[str, typer.Option("--provider-mode", help="mock | real")] = "mock",
    allow_paid: Annotated[
        bool, typer.Option("--allow-paid", help="Cho phép provider TÍNH TIỀN.")
    ] = False,
    only_shot: Annotated[
        list[str] | None,
        typer.Option("--only-shot", help="Chỉ render lại shot này (lặp lại được)."),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Bỏ qua cache, render lại tất cả.")
    ] = False,
) -> None:
    """Chạy pipeline. **Mặc định là dry-run** — không provider nào được gọi."""
    repo = _repo()
    config = Config.from_env()
    try:
        mode = ProviderMode(provider_mode)
        project = repo.load_project(project_id)
        storyboard = repo.load_storyboard(project_id)
        assets = repo.load_assets(project_id)
        providers = build_provider_set(project.providers, mode=mode, config=config)
        # Composer đi cùng chế độ provider: mock thì chỉ dựng lệnh, real thì chạy
        # FFmpeg thật. Nhờ vậy `--provider-mode` là một công tắc duy nhất cho cả
        # đường ống, không có chỗ nào lệch pha.
        composer = (
            FfmpegComposer(ffmpeg_bin=config.ffmpeg_bin)
            if mode is ProviderMode.REAL
            else MockComposer()
        )
        pipeline = Pipeline(repository=repo, providers=providers, config=config, composer=composer)
        manifest = pipeline.render(
            project,
            storyboard,
            assets,
            RenderOptions(
                dry_run=not execute,
                provider_mode=mode,
                allow_paid=allow_paid,
                only_shots=tuple(only_shot or ()),
                force=force,
            ),
        )
    except (AivaError, ValueError) as exc:
        _fail(str(exc))
        return

    label = "DRY-RUN" if manifest.dry_run else "ĐÃ CHẠY"
    console.print(
        f"[green]✓[/green] {label} — run [bold]{manifest.run_id}[/bold] "
        f"({manifest.status}, provider={manifest.provider_mode.value})"
    )

    table = Table(show_header=True)
    table.add_column("Bước")
    table.add_column("Shot")
    table.add_column("Provider")
    table.add_column("Kết quả")
    table.add_column("USD", justify="right")
    for record in manifest.records:
        cost = (
            record.actual_cost_usd
            if record.actual_cost_usd is not None
            else record.estimated_cost_usd
        )
        table.add_row(
            record.stage.value,
            record.shot_id or "—",
            record.provider,
            record.status.value,
            f"{cost:.4f}",
        )
    console.print(table)

    if manifest.outputs:
        console.print(f"Output: {manifest.outputs[0]}")
    if manifest.has_placeholder_output:
        console.print(
            "[yellow]![/yellow] Output là file GIẢ do mock sinh ra, không phải video thật."
        )
    bao_cao = _viet_bao_cao(repo, manifest)
    if bao_cao is not None:
        console.print(f"Báo cáo: {bao_cao}")
    _print_warnings(manifest.warnings)


def _viet_bao_cao(repo: ProjectRepository, manifest: RenderManifest) -> Path | None:
    """Sinh ``report.html`` cạnh manifest sau khi render xong.

    Đặt ở tầng CLI chứ không trong ``pipeline``: pipeline đã nghiệm thu và báo
    cáo không phải việc của nó. Ở đây thì cả ``aiva render``, ``aiva make`` lẫn
    giao diện web đều có báo cáo mà không ai phải nhớ gọi thêm lệnh.

    Không bao giờ làm hỏng một lượt render đã thành công: viết báo cáo lỗi thì
    nói ra rồi thôi.
    """
    if manifest.status != "succeeded":
        return None
    try:
        return write_report(repo.paths(manifest.project_id).run_dir(manifest.run_id), manifest)
    except OSError as exc:
        console.print(f"[yellow]![/yellow] Không viết được report.html: {exc}")
        return None


# --------------------------------------------------------- render-resume -----


@app.command("render-resume")
def render_resume(
    project_id: Annotated[str, typer.Argument(help="ID project.")],
    run_id: Annotated[str, typer.Argument(help="Run đang chờ duyệt, xem ở 'aiva status'.")],
) -> None:
    """Ghép lại từ artifact CÓ SẴN của một run đã tạm dừng chờ duyệt B-roll.

    Không gọi lại TTS, avatar hay B-roll provider — mọi thứ tốn tiền đã xảy ra ở
    run gốc. Đây là lý do lệnh này tồn tại riêng thay vì để ``render`` tự đoán:
    chạy lại ``render`` sẽ sinh clip mới và có thể trả tiền lần hai.

    Chế độ lấy từ **manifest của run gốc**, không phải từ cờ dòng lệnh hay cấu
    hình hiện tại: một run chạy thật thì ghép thật, một run mock thì ghép mock.
    Cho cờ ngoài quyết định sẽ khiến bản chất run gốc bị đổi sau lưng người dùng.
    """
    repo = _repo()
    config = Config.from_env()
    try:
        project = repo.load_project(project_id)
        storyboard = repo.load_storyboard(project_id)
        assets = repo.load_assets(project_id)

        # Đọc manifest TRƯỚC để biết run này là gì, rồi mới chọn composer.
        original = repo.load_render_manifest(project_id, run_id)
        if original.status != "awaiting_approval":
            _fail(
                f"Run {run_id} đang ở trạng thái '{original.status}'. "
                "Chỉ resume được run đang chờ duyệt ('awaiting_approval')."
            )
            return
        if original.dry_run:
            _fail(f"Run {run_id} là dry-run nên không có artifact nào để ghép.")
            return

        composer = (
            FfmpegComposer(ffmpeg_bin=config.ffmpeg_bin)
            if original.provider_mode is ProviderMode.REAL
            else MockComposer()
        )
        # KHÔNG build_provider_set: resume không được gọi provider nào, nên
        # Pipeline ở đây cố tình dựng KHÔNG có provider. Nếu có đường code nào
        # lỡ gọi provider, nó sẽ ném ConfigError chứ không âm thầm tiêu tiền.
        pipeline = Pipeline(repository=repo, config=config, composer=composer)
        manifest = pipeline.resume(project, storyboard, assets, run_id)
    except (AivaError, ValueError) as exc:
        _fail(str(exc))
        return

    console.print(
        f"[green]✓[/green] RESUME — run [bold]{manifest.run_id}[/bold] ({manifest.status}, "
        f"mode={manifest.provider_mode.value} theo run gốc)"
    )
    if manifest.outputs:
        console.print(f"Output: {manifest.outputs[0]}")
    _print_warnings(manifest.warnings)


# ---------------------------------------------------------------- status -----


@app.command()
def status(
    project_id: Annotated[str | None, typer.Argument(help="Bỏ trống để liệt kê tất cả.")] = None,
) -> None:
    """Xem trạng thái project và các lần render."""
    repo = _repo()

    if project_id is None:
        ids = repo.list_project_ids()
        if not ids:
            console.print(f"[dim]Chưa có project nào trong {repo.projects_dir}[/dim]")
            return
        table = Table(title=f"Projects — {repo.projects_dir}")
        table.add_column("ID")
        table.add_column("Trạng thái")
        table.add_column("Tỷ lệ")
        table.add_column("Giây", justify="right")
        table.add_column("Trần USD", justify="right")
        table.add_column("Tiêu đề")
        for pid in ids:
            item = repo.load_project(pid)
            table.add_row(
                item.id,
                item.state.value,
                item.aspect_ratio.value,
                f"{item.target_duration_sec:.0f}",
                f"{item.budget.cap_usd:.2f}",
                item.title[:40],
            )
        console.print(table)
        return

    try:
        project = repo.load_project(project_id)
    except ProjectNotFoundError as exc:
        _fail(str(exc))
        return

    console.print(f"[bold]{project.id}[/bold] — {project.title}")
    console.print(f"  trạng thái : {project.state.value}")
    console.print(f"  khung hình : {project.aspect_ratio.value} @ {project.fps}fps")
    console.print(f"  thời lượng : {project.target_duration_sec:.0f}s")
    console.print(
        f"  ngân sách  : đã dùng {project.budget.spent_usd:.4f} / trần "
        f"{project.budget.cap_usd:.4f} USD"
    )
    console.print(
        f"  nhãn AI    : {'bật' if project.ai_disclosure.enabled else 'tắt'} "
        f"({project.ai_disclosure.label_vi})"
    )
    if project.approval:
        console.print(
            f"  duyệt bởi  : {project.approval.approved_by} lúc "
            f"{project.approval.approved_at:%Y-%m-%d %H:%M} UTC"
        )
        try:
            fresh = project.approval_matches(repo.load_storyboard(project.id).sha256())
            console.print(
                "  hiệu lực   : [green]còn[/green]"
                if fresh
                else "  hiệu lực   : [red]hết (storyboard đã đổi, cần duyệt lại)[/red]"
            )
        except ProjectNotFoundError:
            console.print("  hiệu lực   : [yellow]chưa có storyboard[/yellow]")
    else:
        console.print("  duyệt      : [yellow]chưa[/yellow]")

    runs = repo.list_run_ids(project.id)
    if runs:
        table = Table(title="Các lần render")
        table.add_column("Run")
        table.add_column("Kiểu")
        table.add_column("Trạng thái")
        table.add_column("USD thực", justify="right")
        for run_id in runs:
            manifest = repo.load_render_manifest(project.id, run_id)
            table.add_row(
                run_id,
                "dry-run" if manifest.dry_run else manifest.provider_mode.value,
                manifest.status,
                f"{manifest.actual_cost_usd:.4f}",
            )
        console.print(table)

    if project.history:
        console.print(
            "[dim]Lịch sử: " + " → ".join(h.to_state.value for h in project.history) + "[/dim]"
        )


# ------------------------------------------------------------- voice-add -----


@app.command("voice-add")
def voice_add(
    source: Annotated[str, typer.Argument(help="File mẫu giọng (.wav) trên máy.")],
    project_id: Annotated[str, typer.Option("--project", help="ID project.")],
    owner: Annotated[str, typer.Option("--owner", help="Ai sở hữu giọng nói này.")],
    asset_id: Annotated[str, typer.Option("--id", help="ID tài sản.")] = "voice-chinh",
    scope: Annotated[
        str, typer.Option("--scope", help="Phạm vi được phép dùng.")
    ] = "Video marketing của chính chủ",
    evidence: Annotated[str, typer.Option("--evidence", help="Mã hồ sơ đồng ý.")] = "",
) -> None:
    """Đưa mẫu giọng vào thư mục runtime và khai báo đồng ý sử dụng.

    Nhận WAV, MP3, FLAC, OGG, AIFF, CAF — mọi định dạng ``libsndfile`` đọc được,
    **không cần FFmpeg**. File được chuẩn hoá về WAV mono 16-bit một lần lúc
    nhập, rồi tính SHA-256 và ghi vào ``asset-manifest.json`` với
    ``consent = granted``. Mẫu giọng không bao giờ được đặt trong repo Git.
    """
    from ai_video_agent.composer.audio import convert_to_wav, inspect_wav
    from ai_video_agent.domain.assets import AssetEntry, Consent, sha256_file
    from ai_video_agent.domain.enums import AssetKind, ConsentStatus

    src = Path(source).expanduser()
    if not src.is_file():
        _fail(f"Không có file: {src}")
        return

    repo = _repo()
    if not repo.exists(project_id):
        _fail(
            f"Chưa có project {project_id!r}. Tạo trước bằng:\n"
            f'  aiva plan --brief "..." --id {project_id}'
        )
        return

    paths = repo.paths(project_id)
    relative = f"voice/{asset_id}.wav"
    destination = paths.assets_dir / relative
    destination.parent.mkdir(parents=True, exist_ok=True)

    # WAV mà thư viện chuẩn đọc được thì chép thẳng; còn lại chuyển đổi một lần.
    direct = inspect_wav(src) if src.suffix.lower() in {".wav", ".wave"} else None
    readable_as_is = direct is not None and not any(
        "Không đọc được WAV" in p or "Độ sâu mẫu" in p for p in direct.problems
    )
    try:
        if readable_as_is:
            destination.write_bytes(src.read_bytes())
            report = inspect_wav(destination)
            converted = False
        else:
            report = convert_to_wav(src, destination)
            converted = True
    except AivaError as exc:
        _fail(str(exc))
        return

    manifest = repo.load_assets(project_id)
    entry = AssetEntry(
        id=asset_id,
        path=relative,
        sha256=sha256_file(destination),
        kind=AssetKind.VOICE_SAMPLE,
        bytes=destination.stat().st_size,
        source=f"Do người dùng cung cấp: {src.name}",
        notes=f"{report.duration_sec:.1f}s @ {report.sample_rate} Hz",
        consent=Consent(
            status=ConsentStatus.GRANTED,
            owner=owner,
            granted_by=owner,
            granted_at=now_utc(),
            scope=scope,
            evidence_ref=evidence,
        ),
    )
    manifest.assets = [a for a in manifest.assets if a.id != asset_id] + [entry]

    try:
        manifest_path = repo.save_assets(manifest)
    except AivaError as exc:
        _fail(str(exc))
        return

    console.print(f"[green]✓[/green] Đã đăng ký mẫu giọng [bold]{asset_id}[/bold]")
    if converted:
        console.print(f"  nguồn     : {src.name} → chuyển sang WAV mono 16-bit")
    console.print(f"  file      : {destination}")
    console.print(f"  sha256    : {entry.sha256[:16]}…")
    console.print(f"  thời lượng: {report.duration_sec:.2f}s @ {report.sample_rate} Hz")
    console.print(f"  đỉnh/RMS  : {report.peak:.3f} / {report.rms:.4f}")
    console.print(f"  chủ sở hữu: {owner} (consent = granted)")
    console.print(f"  manifest  : {manifest_path}")

    if report.is_silent:
        console.print("[red]![/red] Mẫu gần như câm — kiểm tra lại micro rồi thu lại.")
    if report.duration_sec < 3.0:
        console.print("[yellow]![/yellow] Mẫu ngắn hơn 3 giây — VieNeu nhân bản kém chính xác.")
    if report.duration_sec > 30.0:
        console.print("[dim]Mẫu dài; VieNeu chỉ dùng 8 giây đầu sau khi cắt khoảng lặng.[/dim]")
    if report.clipping_ratio > 0.001:
        console.print(
            f"[yellow]![/yellow] Mẫu bị clipping {report.clipping_ratio * 100:.2f}% — "
            "thu lại nhỏ tiếng hơn sẽ cho giọng sạch hơn."
        )
    console.print(f'\n[dim]Thử nhân bản: aiva tts-check --ref-audio "{destination}"[/dim]')


# ------------------------------------------------------------------ make -----


@app.command()
def make(
    brief: Annotated[str, typer.Option("--brief", "-b", help="Nội dung video, tiếng Việt.")],
    project_id: Annotated[str, typer.Option("--id", help="ID project.")],
    by: Annotated[
        str, typer.Option("--by", help="Tên người duyệt kịch bản. Bỏ trống thì chỉ lập kế hoạch.")
    ] = "",
    duration: Annotated[
        float, typer.Option("--duration", "-d", help="Thời lượng mục tiêu (giây).")
    ] = 45.0,
    aspect: Annotated[str, typer.Option("--aspect", help="9:16 | 16:9 | 1:1.")] = "9:16",
    fps: Annotated[int, typer.Option("--fps", help="Khung hình/giây.")] = 30,
    mock: Annotated[
        bool,
        typer.Option("--mock", help="Chạy thử bằng file giả — không GPU, không Docker."),
    ] = False,
) -> None:
    """Chạy trọn một video bằng backend production: lập kế hoạch → duyệt → dựng.

    Gộp ``plan`` + ``approve`` + ``render --provider-mode real --execute`` thành
    một lệnh, và **dừng lại chỉ ra việc cần làm** khi còn thiếu tài sản, thay vì
    hỏng giữa chừng. Chạy lại đúng lệnh cũ sau khi bổ sung là nó đi tiếp.

    Backend chốt cứng là **Duix**. MuseTalk là research candidate và không chọn
    được ở đường này (bake-off D04-G §10).

    Không có ``--by`` thì dừng sau bước lập kế hoạch: duyệt kịch bản là việc của
    người, không phải thứ để một lệnh tự làm thay.
    """
    repo = _repo()

    if not repo.exists(project_id):
        console.print("[bold]1/4[/bold] Lập kế hoạch…")
        plan(brief=brief, title="", project_id=project_id, duration=duration,
             aspect=aspect, fps=fps, budget=0.0, ai_label=True)
    else:
        console.print(f"[dim]1/4 Project {project_id} đã có — dùng lại kịch bản hiện tại.[/dim]")

    project = repo.load_project(project_id)
    if project.providers.avatar != "duix":
        _fail(
            f"Project chốt avatar = {project.providers.avatar!r}. Đường production chỉ "
            "chạy Duix. Sửa providers.avatar trong project.json về \"duix\"."
        )
        return

    console.print("[bold]2/4[/bold] Kiểm tài sản…")
    assets = repo.load_assets(project_id)
    thieu: list[str] = []
    if not assets.of_kind(AssetKind.AVATAR_SOURCE):
        thieu.append(
            f'  aiva avatar-add "<video.mp4>" --project {project_id} --owner "<Tên>"'
        )
    if not assets.of_kind(AssetKind.VOICE_SAMPLE):
        thieu.append(f'  aiva voice-add "<giong.wav>" --project {project_id} --owner "<Tên>"')
    if thieu:
        console.print("[yellow]![/yellow] Còn thiếu tài sản. Chạy các lệnh sau rồi lặp lại:")
        for dong in thieu:
            console.print(f"[bold]{dong}[/bold]")
        console.print(f"\n[dim]Sau đó: aiva make --id {project_id} --brief "
                      f'"..." --by "<Tên>"[/dim]')
        return
    chua_dong_y = assets.blocking()
    if chua_dong_y:
        _fail(
            "Tài sản chưa có đồng ý sử dụng: "
            + ", ".join(a.id for a in chua_dong_y)
            + ". Không render khi chưa được phép dùng hình/giọng của người khác."
        )
        return
    console.print(f"  [green]✓[/green] {len(assets.assets)} tài sản, consent đầy đủ")

    if not by:
        console.print("\n[bold]Dừng ở bước lập kế hoạch.[/bold] Xem kịch bản rồi duyệt:")
        console.print(f"[bold]  aiva validate {project_id}[/bold]")
        console.print(
            f'[bold]  aiva make --id {project_id} --brief "{brief[:40]}…" --by "<Tên bạn>"[/bold]'
        )
        return

    if not mock and not _kiem_tra_van_hanh():
        return

    console.print(f"[bold]3/4[/bold] Duyệt kịch bản (bởi {by})…")
    approve(project_id=project_id, by=by, note="aiva make")

    che_do = "mock" if mock else "real"
    nhan = "file GIẢ, không GPU" if mock else "Duix, chạy local"
    console.print(f"[bold]4/4[/bold] Dựng video ({nhan})…")
    render(
        project_id=project_id,
        execute=True,
        provider_mode=che_do,
        allow_paid=False,
        only_shot=None,
        force=False,
    )
    if mock:
        console.print(
            "\n[yellow]![/yellow] Đây là bản chạy thử bằng file giả. Bỏ [bold]--mock[/bold] "
            "để dựng video thật."
        )


# ------------------------------------------------------------ avatar-add -----


@app.command("avatar-add")
def avatar_add(
    source: Annotated[str, typer.Argument(help="Video người đại diện (.mp4) trên máy.")],
    project_id: Annotated[str, typer.Option("--project", help="ID project.")],
    owner: Annotated[str, typer.Option("--owner", help="Ai xuất hiện trong video này.")],
    asset_id: Annotated[str, typer.Option("--id", help="ID tài sản.")] = "avatar-chinh",
    scope: Annotated[
        str, typer.Option("--scope", help="Phạm vi được phép dùng.")
    ] = "Video marketing của chính chủ",
    evidence: Annotated[str, typer.Option("--evidence", help="Mã hồ sơ đồng ý.")] = "",
) -> None:
    """Đưa video người đại diện vào runtime và khai báo đồng ý sử dụng.

    Trước lệnh này, việc đăng ký avatar phải làm bằng tay: chép file, tính SHA-256,
    sửa ``asset-manifest.json``. Sai một bước là render hỏng ở giữa chừng.

    Backend production (Duix) **chỉ nhận video**, không nhận ảnh tĩnh — lệnh này
    kiểm luôn điều đó thay vì để người dùng phát hiện sau khi đã chờ render.
    """
    from ai_video_agent.domain.assets import AssetEntry, Consent, sha256_file
    from ai_video_agent.domain.enums import AssetKind, ConsentStatus
    from ai_video_agent.qc.broll import _probe

    src = Path(source).expanduser()
    if not src.is_file():
        _fail(f"Không có file: {src}")
        return

    repo = _repo()
    if not repo.exists(project_id):
        _fail(
            f"Chưa có project {project_id!r}. Tạo trước bằng:\n"
            f'  aiva plan --brief "..." --id {project_id}'
        )
        return

    cfg = Config.from_env()
    kich_thuoc = _probe(cfg.ffprobe_bin, src, "stream=width,height")
    parts = [p for p in kich_thuoc.replace("\n", ",").split(",") if p]
    if len(parts) < 2:
        _fail(
            f"Không đọc được kích thước video từ {src.name}. Cần {cfg.ffprobe_bin!r} "
            "chạy được — kiểm bằng: aiva doctor"
        )
        return
    rong, cao = int(parts[0]), int(parts[1])

    fps_raw = _probe(cfg.ffprobe_bin, src, "stream=r_frame_rate").split("\n")[0]
    thoi_luong = _probe(cfg.ffprobe_bin, src, "format=duration", stream=None)
    khung = _probe(cfg.ffprobe_bin, src, "stream=nb_frames").split("\n")[0]

    if khung.strip() in {"", "N/A", "0", "1"}:
        _fail(
            f"{src.name} chỉ có {khung or 'không'} khung hình — đây là ảnh tĩnh. "
            "Duix là mô hình face2face, cần VIDEO làm nguồn. Quay một đoạn ngắn "
            "người nói rồi thử lại."
        )
        return

    relative = f"avatar/{asset_id}{src.suffix.lower()}"
    destination = repo.paths(project_id).assets_dir / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(src.read_bytes())

    try:
        giay = float(thoi_luong)
    except ValueError:
        giay = 0.0

    manifest = repo.load_assets(project_id)
    entry = AssetEntry(
        id=asset_id,
        path=relative,
        sha256=sha256_file(destination),
        kind=AssetKind.AVATAR_SOURCE,
        bytes=destination.stat().st_size,
        source=f"Do người dùng cung cấp: {src.name}",
        notes=f"{rong}x{cao} @ {fps_raw}, {giay:.2f}s, {khung} khung",
        consent=Consent(
            status=ConsentStatus.GRANTED,
            owner=owner,
            granted_by=owner,
            granted_at=now_utc(),
            scope=scope,
            evidence_ref=evidence,
        ),
    )
    manifest.assets = [a for a in manifest.assets if a.id != asset_id] + [entry]

    try:
        manifest_path = repo.save_assets(manifest)
    except AivaError as exc:
        _fail(str(exc))
        return

    console.print(f"[green]✓[/green] Đã đăng ký avatar [bold]{asset_id}[/bold]")
    console.print(f"  file      : {destination}")
    console.print(f"  sha256    : {entry.sha256[:16]}…")
    console.print(f"  kích thước: {rong}x{cao} @ {fps_raw}")
    console.print(f"  thời lượng: {giay:.2f}s ({khung} khung)")
    console.print(f"  chủ sở hữu: {owner} (consent = granted)")
    console.print(f"  manifest  : {manifest_path}")

    project = repo.load_project(project_id)
    want_w, want_h = project.aspect_ratio.size
    if (rong, cao) != (want_w, want_h):
        console.print(
            f"[yellow]![/yellow] Project cần {want_w}x{want_h} nhưng video là {rong}x{cao}. "
            "Composer sẽ co giãn và chèn viền đen."
        )
    if giay < 5.0:
        console.print(
            "[yellow]![/yellow] Video ngắn hơn 5 giây — nguồn quá ngắn thì khẩu hình "
            "hay bị lặp thấy rõ."
        )


# ------------------------------------------------------------- tts-check -----

#: Câu kiểm tra: trung tính, không nhạy cảm, có đủ thanh điệu tiếng Việt (brief §D02.2).
HEALTHCHECK_TEXT = "Xin chào, đây là bản kiểm tra giọng đọc tiếng Việt của hệ thống dựng video."


@app.command("tts-check")
def tts_check(
    text: Annotated[str, typer.Option("--text", help="Câu cần đọc thử.")] = HEALTHCHECK_TEXT,
    voice: Annotated[str, typer.Option("--voice", help="Tên giọng dựng sẵn.")] = "",
    ref_audio: Annotated[
        str,
        typer.Option(
            "--ref-audio",
            help="Đường dẫn mẫu giọng để nhân bản. Phải nằm trong thư mục runtime.",
        ),
    ] = "",
    out: Annotated[str, typer.Option("--out", help="Nơi ghi WAV. Mặc định trong runtime.")] = "",
    list_voices: Annotated[
        bool, typer.Option("--list-voices", help="Chỉ liệt kê giọng dựng sẵn rồi thoát.")
    ] = False,
) -> None:
    """Health check VieNeu-TTS: sinh WAV thật rồi kiểm tra file, thời lượng, sample rate, clipping.

    Lần chạy đầu sẽ tải ~312 MB model ONNX int8 về cache Hugging Face.
    Chạy hoàn toàn trên CPU, không đụng GPU.
    """
    from ai_video_agent.composer.audio import inspect_wav
    from ai_video_agent.paths import assert_writable
    from ai_video_agent.providers.vieneu.adapter import (
        NATIVE_SAMPLE_RATE,
        VieNeuTtsProvider,
    )

    config = Config.from_env()
    provider = VieNeuTtsProvider(device=config.vieneu_device)

    try:
        if list_voices:
            console.print("Đang nạp engine để đọc danh sách giọng…")
            for name in provider.preset_voices():
                console.print(f"  • {name}")
            return

        if ref_audio and voice:
            _fail("Chỉ được chọn một: --voice (giọng dựng sẵn) hoặc --ref-audio (nhân bản).")
            return

        destination = (
            Path(out)
            if out
            else config.runtime_dir
            / "healthcheck"
            / ("tts-clone.wav" if ref_audio else "tts-preset.wav")
        )
        # Chặn ghi đè file đối chứng của PO, kể cả khi --out trỏ thẳng vào đó.
        assert_writable(destination)

        label = (
            f"nhân bản từ mẫu {Path(ref_audio).name}" if ref_audio else (voice or "giọng mặc định")
        )
        console.print(f"Đang sinh giọng ({label})… lần đầu sẽ tải model ~312 MB.")

        result = provider.synthesize(
            TtsRequest(
                shot_id="healthcheck",
                text_vi=text,
                voice=voice or None,
                ref_audio=Path(ref_audio) if ref_audio else None,
                sample_rate=NATIVE_SAMPLE_RATE,
            ),
            destination,
        )
    except AivaError as exc:
        _fail(str(exc))
        return

    report = inspect_wav(result.path, expected_sample_rate=NATIVE_SAMPLE_RATE)

    table = Table(title="Kiểm tra WAV (brief §D02.5)")
    table.add_column("Mục")
    table.add_column("Giá trị")
    table.add_column("Kết luận")
    table.add_row(
        "file tồn tại", str(report.path), "[green]PASS[/]" if report.exists else "[red]FAIL[/]"
    )
    table.add_row("dung lượng", f"{report.size_bytes / 1024:.0f} KB", "—")
    table.add_row(
        "thời lượng",
        f"{report.duration_sec:.2f} s",
        "[green]PASS[/]" if report.duration_sec > 0.3 else "[red]FAIL[/]",
    )
    table.add_row(
        "sample rate",
        f"{report.sample_rate} Hz",
        "[green]PASS[/]" if report.sample_rate == NATIVE_SAMPLE_RATE else "[red]FAIL[/]",
    )
    table.add_row("kênh / độ sâu", f"{report.channels}ch / {report.sample_width_bits}-bit", "—")
    table.add_row("đỉnh biên độ", f"{report.peak:.3f}", "—")
    table.add_row(
        "RMS", f"{report.rms:.4f}", "[red]CÂM[/]" if report.is_silent else "[green]PASS[/]"
    )
    table.add_row(
        "clipping",
        f"{report.clipping_ratio * 100:.3f}% ({report.clipped_samples} mẫu)",
        "[green]PASS[/]" if report.clipping_ratio <= 0.001 else "[red]FAIL[/]",
    )
    console.print(table)

    if report.ok:
        console.print(f"[green]✓[/green] Health check ĐẠT — {report.summary()}")
        console.print(f"[dim]Nghe thử: {report.path}[/dim]")
    else:
        for problem in report.problems:
            console.print(f"[red]✗[/red] {problem}")
        raise typer.Exit(code=1)


# -------------------------------------------------------------- validate -----


@app.command()
def validate(
    project_id: Annotated[str, typer.Argument(help="ID project.")],
) -> None:
    """Đối chiếu các file JSON của project với ``schemas/``."""
    repo = _repo()
    paths = repo.paths(project_id)
    targets = [
        (SchemaName.PROJECT, paths.project_json),
        (SchemaName.STORYBOARD, paths.storyboard_json),
        (SchemaName.ASSET_MANIFEST, paths.asset_manifest_json),
    ]
    for run_id in repo.list_run_ids(project_id):
        targets.append((SchemaName.RENDER_MANIFEST, paths.run_dir(run_id) / "render-manifest.json"))

    failures = 0
    for schema, path in targets:
        if not path.is_file():
            console.print(f"[dim]—[/dim] {path.name}: không có")
            continue
        errors = iter_errors(schema, json.loads(Path(path).read_text(encoding="utf-8")))
        if errors:
            failures += 1
            console.print(f"[red]✗[/red] {path}")
            for error in errors:
                console.print(f"    {error}")
        else:
            console.print(f"[green]✓[/green] {path.name} khớp {schema.value}.schema.json")

    if failures:
        raise typer.Exit(code=1)


@app.command()
def ui(
    port: Annotated[int, typer.Option("--port", help="Cổng local.")] = DEFAULT_PORT,
    open_browser: Annotated[
        bool, typer.Option("--open/--no-open", help="Tự mở trình duyệt.")
    ] = True,
    start_duix: Annotated[
        bool,
        typer.Option("--start-duix/--no-start-duix", help="Bật container Duix nếu chưa chạy."),
    ] = False,
) -> None:
    """Mở giao diện web **chạy trên chính máy này** để dựng video.

    Không có tuỳ chọn ``--host``: server luôn bind ``127.0.0.1``. Máy này dựng
    video từ hình và giọng thật của người dùng, mở ra LAN là biến nó thành một
    dịch vụ không xác thực cho cả mạng.

    Giao diện chỉ là vỏ — mọi việc thật đều gọi lại đúng lệnh CLI, nên mọi hàng
    rào (gate, consent, cost guard, preflight tài nguyên) vẫn nguyên hiệu lực.
    """
    #: Import **trong hàm**: ``webui.app`` kéo theo ``webui.service``, mà module
    #: đó lại import ngược ``cli.main`` (đó chính là seam "UI gọi lại CLI").
    #: Import ở cấp module sẽ thành vòng. Đồng thời giữ đúng AGENTS.md: fastapi
    #: chỉ nạp khi thật sự chạy UI.
    from ai_video_agent.webui.app import serve

    config = Config.from_env()
    if start_duix:
        console.print("[bold]•[/bold] Kiểm tra Duix…")
        ket_qua = ensure_duix_ready(config.duix_base_url)
        mau = "green" if ket_qua.ready else "red"
        console.print(f"  [{mau}]{ket_qua.reason}[/] {ket_qua.detail}")
        if not ket_qua.ready:
            _fail("Chưa bật được Duix. UI vẫn mở được, nhưng render thật sẽ hỏng.")
            return

    console.print(f"Giao diện: [bold]http://{HOST}:{port}/[/bold]  (Ctrl+C để dừng)")
    try:
        serve(config, port=port, open_browser=open_browser)
    except AivaError as exc:
        _fail(str(exc))


if __name__ == "__main__":  # pragma: no cover
    app()

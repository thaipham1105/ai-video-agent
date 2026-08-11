"""Cầu nối UI → CLI. **Không có logic render nào ở đây.**

Mỗi hàm dưới đây gọi đúng hàm mà ``aiva make`` / ``aiva avatar-add`` /
``aiva voice-add`` gọi, rồi dịch kết quả sang dạng JSON cho trang web. Việc duy
nhất nó thêm vào là bắt log và tìm ra run vừa sinh.

Vì sao không gọi CLI bằng subprocess: cùng tiến trình thì lỗi giữ nguyên kiểu
(``ConsentMissingError``, ``CapabilityError``…) thay vì rơi về một mã thoát và
một đống chữ, nên UI báo được đúng nguyên nhân.

Vì sao import **module** ``cli.main`` chứ không import từng hàm: đó là seam để
test khẳng định "UI gọi lại CLI" thay vì tự dựng pipeline.
"""

from __future__ import annotations

import contextlib
import io
import os
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer

from ai_video_agent.cli import main as cli_main
from ai_video_agent.cli.preflight import check_duix_ready
from ai_video_agent.orchestrator.repository import ProjectRepository
from ai_video_agent.webui import intake
from ai_video_agent.webui.report import REPORT_FILENAME

if TYPE_CHECKING:
    from ai_video_agent.config import Config


@dataclass(frozen=True)
class CliOutcome:
    """Kết quả một lệnh CLI chạy trong tiến trình này."""

    ok: bool
    log: str
    message: str = ""


def _capture(fn: Any, /, **kwargs: Any) -> CliOutcome:
    """Chạy một lệnh CLI, gom mọi thứ nó in ra.

    ``rich.Console`` phân giải ``sys.stdout`` lúc ghi chứ không giữ tham chiếu
    từ lúc dựng, nên ``redirect_stdout`` bắt được đúng những gì terminal thấy.
    An toàn vì :class:`~ai_video_agent.webui.jobs.JobRunner` chỉ cho một job
    chạy — không có hai lượt cùng ghi vào một luồng.

    ``typer.Exit`` là cách CLI báo lỗi đã-in-ra-rồi; đổi nó thành ``ok=False``
    và giữ nguyên log, đừng để nó thoát cả tiến trình web.
    """
    dem = io.StringIO()
    try:
        with contextlib.redirect_stdout(dem), contextlib.redirect_stderr(dem):
            fn(**kwargs)
    except typer.Exit as exc:
        return CliOutcome(ok=exc.exit_code == 0, log=dem.getvalue(), message="")
    except Exception as exc:  # noqa: BLE001 - đổi lỗi thành trạng thái cho UI đọc
        return CliOutcome(
            ok=False, log=dem.getvalue(), message=f"{type(exc).__name__}: {exc}"
        )
    return CliOutcome(ok=True, log=dem.getvalue())


def _run_ids(repo: ProjectRepository, project_id: str) -> set[str]:
    if not repo.exists(project_id):
        return set()
    return set(repo.list_run_ids(project_id))


def check_machine(config: Config) -> list[dict[str, str]]:
    """Bốn đèn kiểm tra vận hành — cùng hàm mà ``aiva make`` dùng trước khi dựng."""
    return [
        {"name": r.name, "status": r.status.value, "detail": r.detail}
        for r in check_duix_ready(config)
    ]


def add_avatar(config: Config, *, project_id: str, source: Path, owner: str) -> dict[str, Any]:
    intake.check_project_id(project_id)
    ket = _capture(
        cli_main.avatar_add, source=str(source), project_id=project_id, owner=owner
    )
    return {"ok": ket.ok, "log": ket.log, "message": ket.message}


def add_voice(config: Config, *, project_id: str, source: Path, owner: str) -> dict[str, Any]:
    intake.check_project_id(project_id)
    ket = _capture(
        cli_main.voice_add, source=str(source), project_id=project_id, owner=owner
    )
    return {"ok": ket.ok, "log": ket.log, "message": ket.message}


def plan_only(
    config: Config, *, project_id: str, brief: str, duration: float, aspect: str, fps: int
) -> dict[str, Any]:
    """Lập kế hoạch và kiểm tài sản, **không duyệt, không dựng**.

    Đây là ``aiva make`` không có ``--by`` — bỏ tham số đó là cách CLI diễn đạt
    "chỉ xem thôi", và UI dùng lại đúng cơ chế ấy thay vì tự nghĩ ra cái khác.
    """
    intake.check_project_id(project_id)
    ket = _capture(
        cli_main.make,
        brief=brief,
        project_id=project_id,
        by="",
        duration=duration,
        aspect=aspect,
        fps=fps,
        mock=False,
    )
    out: dict[str, Any] = {"ok": ket.ok, "log": ket.log, "message": ket.message}
    out.update(read_project(config, project_id))
    return out


def read_project(config: Config, project_id: str) -> dict[str, Any]:
    """Kịch bản và tài sản của **đúng một** project.

    Không có lối nào đọc sang project khác: ``project_id`` đã qua whitelist, và
    mọi đường dẫn đều dựng từ ``ProjectRepository``.
    """
    intake.check_project_id(project_id)
    repo = ProjectRepository(config.runtime_dir)
    if not repo.exists(project_id):
        return {"exists": False, "shots": [], "assets": []}
    storyboard = repo.load_storyboard(project_id)
    assets = repo.load_assets(project_id)
    return {
        "exists": True,
        "shots": [
            {
                "id": s.id,
                "duration_sec": s.duration_sec,
                "narration": s.narration_vi,
                "on_screen_text": [t.text for t in s.on_screen_text],
            }
            for s in storyboard.shots
        ],
        "assets": [
            {"id": a.id, "kind": a.kind.value, "owner": a.consent.owner} for a in assets.assets
        ],
    }


def run_make(
    config: Config,
    *,
    project_id: str,
    brief: str,
    by: str,
    duration: float,
    aspect: str,
    fps: int,
    mock: bool,
) -> dict[str, Any]:
    """Dựng video: **gọi thẳng** ``aiva make``, rồi chỉ ra run vừa sinh.

    Tìm run bằng cách so tập run trước/sau thay vì lấy cái mới nhất theo tên:
    ``run_id`` là chuỗi hex, sắp theo tên không ra thứ tự thời gian.
    """
    intake.check_project_id(project_id)
    repo = ProjectRepository(config.runtime_dir)
    truoc = _run_ids(repo, project_id)

    ket = _capture(
        cli_main.make,
        brief=brief,
        project_id=project_id,
        by=by,
        duration=duration,
        aspect=aspect,
        fps=fps,
        mock=mock,
    )

    ket_qua: dict[str, Any] = {"ok": ket.ok, "log": ket.log, "message": ket.message}
    moi = sorted(_run_ids(repo, project_id) - truoc)
    if not moi:
        ket_qua.setdefault("message", "")
        return ket_qua

    run_id = moi[-1]
    manifest = repo.load_render_manifest(project_id, run_id)
    run_dir = repo.paths(project_id).run_dir(run_id)
    bao_cao = run_dir / REPORT_FILENAME
    ket_qua.update(
        {
            "ok": ket.ok and manifest.status == "succeeded",
            "run_id": run_id,
            "status": manifest.status,
            "provider_mode": manifest.provider_mode.value,
            "actual_cost_usd": manifest.actual_cost_usd,
            "output": manifest.outputs[0] if manifest.outputs else "",
            "output_dir": str(repo.paths(project_id).outputs_dir),
            "report": str(bao_cao) if bao_cao.is_file() else "",
            "warnings": list(manifest.warnings),
        }
    )
    return ket_qua


def open_folder(path: Path) -> dict[str, Any]:
    """Mở thư mục bằng trình quản lý file của hệ điều hành.

    Chỉ Windows mới mở được ở đây; nơi khác trả về đường dẫn để người dùng tự
    copy — đúng yêu cầu D06-A số 2. Không bao giờ ném lỗi: không mở được thì
    đường dẫn vẫn là câu trả lời dùng được.
    """
    duong = str(path)
    if platform.system() != "Windows":
        return {"opened": False, "path": duong, "reason": "Chỉ mở tự động được trên Windows."}
    explorer = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "explorer.exe"
    try:
        subprocess.run(  # noqa: S603 - đường dẫn cố định từ SYSTEMROOT
            [str(explorer), duong], check=False, timeout=15
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"opened": False, "path": duong, "reason": str(exc)}
    return {"opened": True, "path": duong}

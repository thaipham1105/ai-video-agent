"""Định nghĩa route FastAPI. Mọi route đều mỏng — việc thật ở :mod:`service`.

**Module này cố ý KHÔNG có ``from __future__ import annotations``.** FastAPI đọc
annotation lúc chạy để biết tham số nào là form, tham số nào là file. Hoãn
annotation thành chuỗi thì nó phải phân giải ngược lại từ globals của module, và
``UploadFile`` import trong hàm sẽ không có ở đó — lỗi hiện ra dưới dạng
``PydanticUserError: is not fully defined``, rất khó lần.

Đó cũng là lý do fastapi được import ở **cấp module** tại đây, còn việc giữ đúng
AGENTS.md ("không import nặng ở cấp module") do :mod:`ai_video_agent.webui.app`
lo: nó chỉ import module này bên trong hàm.
"""

from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, PackageLoader, select_autoescape

from ai_video_agent.config import Config
from ai_video_agent.errors import AivaError, ValidationError
from ai_video_agent.webui import HOST, intake, service
from ai_video_agent.webui.jobs import JobBusyError, JobRunner

TEMPLATE_DIR = "templates"


def build_app(config: Config, runner: JobRunner | None = None) -> FastAPI:
    """Dựng ứng dụng. Không mở cổng nào — test gọi thẳng được."""
    jobs = runner or JobRunner()
    env = Environment(
        loader=PackageLoader("ai_video_agent.webui", TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
    )
    app = FastAPI(title="AI-VIDEO-AGENT", docs_url=None, redoc_url=None, openapi_url=None)

    def _loi(exc: Exception, ma: int = 400) -> JSONResponse:
        """Lỗi nghiệp vụ thành JSON đọc được, không thành trang 500 trống trơn."""
        return JSONResponse(status_code=ma, content={"ok": False, "message": str(exc)})

    @app.get("/", response_class=HTMLResponse)
    def trang_chu() -> HTMLResponse:
        mau = env.get_template("index.html")
        return HTMLResponse(mau.render(runtime_dir=str(config.runtime_dir), host=HOST))

    @app.post("/api/check")
    def kiem_tra_may() -> dict[str, Any]:
        return {"ok": True, "checks": service.check_machine(config)}

    @app.get("/api/project/{project_id}")
    def doc_project(project_id: str) -> Any:
        try:
            return {"ok": True, **service.read_project(config, project_id)}
        except AivaError as exc:
            return _loi(exc)

    @app.post("/api/plan")
    def lap_ke_hoach(
        project_id: str = Form(...),
        brief: str = Form(...),
        duration: float = Form(45.0),
        aspect: str = Form("9:16"),
        fps: int = Form(30),
    ) -> Any:
        try:
            return service.plan_only(
                config,
                project_id=project_id,
                brief=brief,
                duration=duration,
                aspect=aspect,
                fps=fps,
            )
        except AivaError as exc:
            return _loi(exc)

    def _nhan_file(
        project_id: str, owner: str, tep: UploadFile, duoi: frozenset[str], *, la_avatar: bool
    ) -> Any:
        try:
            intake.check_project_id(project_id)
            tam = intake.stage_upload(
                config.runtime_dir,
                filename=tep.filename or "",
                stream=tep.file,
                allowed=duoi,
            )
        except ValidationError as exc:
            return _loi(exc)
        try:
            them = service.add_avatar if la_avatar else service.add_voice
            return them(config, project_id=project_id, source=tam, owner=owner)
        finally:
            intake.discard(tam)

    @app.post("/api/avatar")
    def them_avatar(
        project_id: str = Form(...), owner: str = Form(...), file: UploadFile = File(...)
    ) -> Any:
        return _nhan_file(project_id, owner, file, intake.AVATAR_SUFFIXES, la_avatar=True)

    @app.post("/api/voice")
    def them_giong(
        project_id: str = Form(...), owner: str = Form(...), file: UploadFile = File(...)
    ) -> Any:
        return _nhan_file(project_id, owner, file, intake.VOICE_SUFFIXES, la_avatar=False)

    @app.post("/api/render")
    def dung_video(
        project_id: str = Form(...),
        brief: str = Form(...),
        by: str = Form(...),
        duration: float = Form(45.0),
        aspect: str = Form("9:16"),
        fps: int = Form(30),
        mock: bool = Form(False),
    ) -> Any:
        try:
            intake.check_project_id(project_id)
        except ValidationError as exc:
            return _loi(exc)
        if not by.strip():
            return _loi(
                ValidationError(
                    "Thiếu tên người duyệt. Duyệt kịch bản là việc của người, "
                    "không phải thứ giao diện tự làm thay."
                )
            )
        try:
            trang_thai = jobs.start(
                "render",
                lambda: service.run_make(
                    config,
                    project_id=project_id,
                    brief=brief,
                    by=by,
                    duration=duration,
                    aspect=aspect,
                    fps=fps,
                    mock=mock,
                ),
            )
        except JobBusyError as exc:
            #: 409 chứ không phải 400: yêu cầu hợp lệ, chỉ là sai thời điểm.
            return _loi(exc, ma=409)
        return {"ok": True, "job": trang_thai.as_dict()}

    @app.get("/api/job")
    def trang_thai_job() -> dict[str, Any]:
        hien = jobs.current()
        return {"ok": True, "job": hien.as_dict() if hien else None}

    @app.post("/api/open")
    def mo_thu_muc(path: str = Form(...)) -> Any:
        """Chỉ mở thư mục **nằm trong runtime dir**, không mở đường dẫn tuỳ ý."""
        muon = Path(path).resolve()
        goc = config.runtime_dir.resolve()
        if goc != muon and goc not in muon.parents:
            raise HTTPException(status_code=400, detail="Đường dẫn nằm ngoài thư mục runtime.")
        return service.open_folder(muon)

    return app

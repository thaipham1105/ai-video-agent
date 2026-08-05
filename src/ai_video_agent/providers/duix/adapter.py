"""Adapter Duix-Avatar thật — mở từ Gate D03.

Duix chạy bằng Docker Compose và phơi HTTP API local, nên adapter chỉ là HTTP
client — **không sửa mã upstream** (brief §3).

Hợp đồng API dưới đây đọc trực tiếp từ ``/code/app_local.py`` trong image đã
ghim, không phải suy đoán từ tài liệu::

    POST /easy/submit   {code, audio_url, video_url,
                         watermark_switch?, digital_auth?, chaofen?, pn?}
                        -> {code: 10000} nghĩa là đã NHẬN, xử lý chạy nền
    GET  /easy/query?code=...
                        -> {status, progress, result, msg, cost,
                            video_duration, width, height}

Vài điểm rút ra khi đọc code thật của image:

* ``audio_url``/``video_url`` chỉ được tải về khi chuỗi bắt đầu bằng ``http``;
  còn lại coi là **đường dẫn local trong container**. Nhờ vậy ta gắn tài sản vào
  bằng volume chỉ đọc thay vì sao chép file.
* Duix **tự chuẩn hoá** đầu vào trước khi xử lý::

      ffmpeg -i <audio> -ac 1 -ar 16000 -acodec pcm_s16le -y <out>
      ffmpeg -i <video> -c:v libx264 -crf 15 -an -y <out>

  Nên không có ngưỡng cứng nào về độ phân giải, FPS hay codec đầu vào.
* Server chạy **một job tại một thời điểm**: ``get_run_flag()`` trả mã 10001
  (bận) nếu đang có việc.

Volume của upstream hardcode ``d:/duix_avatar_data/...`` mà máy này **không có ổ
D**, nên dùng compose override cục bộ trỏ sang ``F:\\``. Xem
``deploy/duix/README.md``.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai_video_agent import gate_is_open
from ai_video_agent.domain.enums import ProviderKind, ProviderMode, RenderStage
from ai_video_agent.errors import ConsentMissingError, GateNotReachedError, ProviderError
from ai_video_agent.providers._placeholder import read_wav_duration
from ai_video_agent.providers.base import (
    AvatarRequest,
    AvatarResult,
    CostQuote,
    ProviderInfo,
)
from ai_video_agent.providers.pricing import DUIX_LOCAL

GATE = "D03"

SUBMIT_PATH = "/easy/submit"
QUERY_PATH = "/easy/query"

#: Mã trả về của Duix, đọc từ ``ResponseCode`` trong ``app_local.py``.
CODE_SUCCESS = 10000
CODE_BUSY = 10001
CODE_BAD_PARAM = 10002
CODE_LOCK_ERROR = 10003
CODE_TASK_NOT_FOUND = 10004
CODE_SYSTEM_ERROR = 9999

#: Giá trị ``status`` trong phản hồi ``/easy/query``.
STATUS_RUN = 1
STATUS_SUCCESS = 2
STATUS_FAILED = 3

POLL_INTERVAL_SEC = 5.0


@dataclass
class DuixJob:
    """Nhật ký một lần gọi Duix, đủ để truy vết và đưa vào render-manifest."""

    code: str
    payload: dict[str, Any]
    submitted_at: float
    finished_at: float | None = None
    status: int | None = None
    result_path: str = ""
    message: str = ""
    cost_sec: float | None = None
    video_duration: float | None = None
    width: int | None = None
    height: int | None = None
    polls: int = 0
    progress_log: list[str] = field(default_factory=list)

    @property
    def elapsed_sec(self) -> float:
        return (self.finished_at or time.monotonic()) - self.submitted_at

    @property
    def succeeded(self) -> bool:
        return self.status == STATUS_SUCCESS


class DuixAvatarProvider:
    """HTTP client tới container Duix chạy local."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8383",
        timeout_sec: int = 900,
        model: str = "duix.avatar",
        image_digest: str | None = None,
        #: Ánh xạ đường dẫn trên host -> đường dẫn trong container. Duix nhận
        #: đường dẫn local, nhưng là local THEO GÓC NHÌN CỦA CONTAINER.
        path_map: tuple[tuple[str, str], ...] = (
            ("F:/AI-VIDEO-AGENT-RUNTIME/projects", "/inputs"),
        ),
        #: Thư mục kết quả của container, nhìn từ host.
        result_dir_host: Path | None = None,
        poll_interval_sec: float = POLL_INTERVAL_SEC,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_sec = timeout_sec
        self._model = model
        self._image_digest = image_digest
        self._path_map = path_map
        self._result_dir_host = result_dir_host
        self._poll_interval_sec = poll_interval_sec
        #: Nhật ký lần chạy gần nhất, để pipeline/báo cáo đọc lại.
        self.last_job: DuixJob | None = None

    def to_container_path(self, host_path: Path) -> str:
        """Đổi đường dẫn host sang đường dẫn container theo volume đã mount."""
        raw = str(host_path).replace("\\", "/")
        for host_prefix, container_prefix in self._path_map:
            prefix = host_prefix.replace("\\", "/").rstrip("/")
            if raw.lower().startswith(prefix.lower()):
                return container_prefix.rstrip("/") + raw[len(prefix) :]
        msg = (
            f"Đường dẫn {host_path} không nằm trong volume nào đã mount vào container "
            f"Duix. Đã mount: {[h for h, _ in self._path_map]}. Thêm volume vào "
            "deploy/duix/docker-compose.yml hoặc để tài sản dưới thư mục đó."
        )
        raise ProviderError(msg)

    @property
    def submit_url(self) -> str:
        return f"{self._base_url}{SUBMIT_PATH}"

    @property
    def query_url(self) -> str:
        return f"{self._base_url}{QUERY_PATH}"

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="duix",
            kind=ProviderKind.AVATAR,
            model=self._model,
            version=self._image_digest or "unpinned-until-D03",
            mode=ProviderMode.REAL,
            billable=False,
            gate=GATE,
        )

    def quote(self, request: AvatarRequest) -> CostQuote:
        """Báo giá chạy được ở mọi gate — không chạm container."""
        seconds = request.duration_sec or (
            read_wav_duration(request.audio_path) if request.audio_path.is_file() else 0.0
        )
        return CostQuote(
            stage=RenderStage.AVATAR,
            provider="duix",
            model=self._model,
            unit=DUIX_LOCAL.unit,
            units=seconds,
            unit_price_usd=DUIX_LOCAL.unit_price_usd,
            estimated_usd=0.0,
            billable=False,
            assumption=DUIX_LOCAL.assumption,
        )

    # ----- HTTP -------------------------------------------------------------

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(  # noqa: S310 - URL cố định, http local
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
                parsed: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
                return parsed
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            msg = (
                f"Không gọi được Duix tại {url}: {exc}. Container còn chạy không? "
                "Kiểm tra: docker ps --filter name=duix-avatar-gen-video"
            )
            raise ProviderError(msg) from exc

    def _get_json(self, url: str) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310
                parsed: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
                return parsed
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            msg = f"Không hỏi được tiến độ Duix tại {url}: {exc}"
            raise ProviderError(msg) from exc

    def submit(self, job_code: str, video_url: str, audio_url: str, **options: Any) -> DuixJob:
        """Gửi đúng một job. Trả về ngay, xử lý chạy nền trong container."""
        payload: dict[str, Any] = {
            "code": job_code,
            "video_url": video_url,
            "audio_url": audio_url,
            "watermark_switch": options.get("watermark_switch", 0),
            "digital_auth": options.get("digital_auth", 0),
            "chaofen": options.get("chaofen", 0),
            "pn": options.get("pn", 1),
        }
        response = self._post_json(self.submit_url, payload)
        code = int(response.get("code", CODE_SYSTEM_ERROR))

        if code == CODE_BUSY:
            msg = "Duix đang bận với job khác. Server chỉ chạy một job tại một thời điểm."
            raise ProviderError(msg)
        if code != CODE_SUCCESS:
            msg = f"Duix từ chối job (code={code}): {response.get('msg', '')}"
            raise ProviderError(msg)

        job = DuixJob(code=job_code, payload=payload, submitted_at=time.monotonic())
        self.last_job = job
        return job

    def wait(self, job: DuixJob, *, timeout_sec: int | None = None) -> DuixJob:
        """Chờ đúng job đó xong. Không tự gửi lại khi thất bại (brief §D03.5)."""
        limit = timeout_sec if timeout_sec is not None else self._timeout_sec
        url = f"{self.query_url}?{urllib.parse.urlencode({'code': job.code})}"

        while True:
            response = self._get_json(url)
            job.polls += 1
            data = response.get("data") or {}
            status = data.get("status")

            if status is not None:
                job.status = int(status)
                job.message = str(data.get("msg", ""))
                job.result_path = str(data.get("result", "") or "")
                progress = str(data.get("progress", ""))
                if progress and (not job.progress_log or job.progress_log[-1] != progress):
                    job.progress_log.append(progress)

                if job.status == STATUS_SUCCESS:
                    job.finished_at = time.monotonic()
                    job.cost_sec = data.get("cost")
                    job.video_duration = data.get("video_duration")
                    job.width = data.get("width")
                    job.height = data.get("height")
                    return job
                if job.status == STATUS_FAILED:
                    job.finished_at = time.monotonic()
                    detail = job.message or "(không có thông điệp)"
                    msg = f"Duix báo job {job.code} THẤT BẠI: {detail}"
                    raise ProviderError(msg)

            elif int(response.get("code", 0)) == CODE_TASK_NOT_FOUND and job.polls > 2:
                # Job xong rồi thì Duix xoá khỏi bảng; mất job ngay từ đầu là bất thường.
                job.finished_at = time.monotonic()
                msg = f"Duix không còn thấy job {job.code}. Xem log container để biết vì sao."
                raise ProviderError(msg)

            if job.elapsed_sec > limit:
                job.finished_at = time.monotonic()
                msg = f"Quá {limit}s mà job {job.code} chưa xong. KHÔNG tự gửi lại."
                raise ProviderError(msg)

            time.sleep(self._poll_interval_sec)

    def generate(self, request: AvatarRequest, out_path: Path) -> AvatarResult:
        """Sinh video người nói. Gửi ĐÚNG MỘT job, không tự thử lại."""
        self._assert_gate_open()
        self._assert_avatar_source(request)
        assert request.avatar_source is not None  # noqa: S101 - đã kiểm tra ở trên

        job = self.submit(
            job_code=f"aiva-{request.shot_id}-{int(time.time())}",
            video_url=self.to_container_path(request.avatar_source),
            audio_url=self.to_container_path(request.audio_path),
        )
        self.wait(job)

        produced = self._resolve_result(job)
        return AvatarResult(
            path=produced,
            duration_sec=self.duration_seconds(job) or read_wav_duration(request.audio_path),
            width=int(job.width or request.width),
            height=int(job.height or request.height),
            fps=request.fps,
            is_placeholder=False,
            actual_cost_usd=0.0,
        )

    @staticmethod
    def duration_seconds(job: DuixJob) -> float:
        """Đổi ``video_duration`` của Duix sang giây.

        Duix trả về **mili-giây** (quan sát thật: 7680 cho một clip 7,68 s), còn
        cả hệ thống này dùng giây. Không đổi đơn vị thì phụ đề và mốc thời gian
        của composer sẽ lệch đi một nghìn lần.
        """
        raw = job.video_duration
        if raw is None:
            return 0.0
        return round(float(raw) / 1000.0, 3)

    def _resolve_result(self, job: DuixJob) -> Path:
        """Đổi đường dẫn kết quả (theo góc nhìn container) về đường dẫn host.

        Duix trả về đường dẫn dạng ``/<tên>-r.mp4`` — chỉ có tên file, không có
        thư mục thật. File thực nằm trong ``temp/`` hoặc ``result/`` dưới thư mục
        dữ liệu, nên ở đây dò cả hai thay vì tin vào chuỗi trả về.
        """
        if not job.result_path:
            msg = f"Job {job.code} báo thành công nhưng không kèm đường dẫn kết quả."
            raise ProviderError(msg)

        name = Path(job.result_path.replace("\\", "/")).name
        if self._result_dir_host is None:
            return Path(job.result_path)

        base = self._result_dir_host
        candidates = [base / name, base / "temp" / name, base / "result" / name]
        for candidate in candidates:
            if candidate.is_file():
                return candidate

        looked = ", ".join(str(c) for c in candidates)
        msg = (
            f"Job {job.code} báo thành công nhưng không tìm thấy file kết quả {name!r}. "
            f"Đã tìm ở: {looked}"
        )
        raise ProviderError(msg)

    # ----- hàng rào ----------------------------------------------------------

    @staticmethod
    def _assert_gate_open() -> None:
        if not gate_is_open(GATE):
            raise GateNotReachedError(
                "Duix-Avatar thật (Docker + GPU + ~70 GB image)",
                GATE,
                hint="Dùng --provider-mode mock cho tới khi D03 được duyệt.",
            )

    @staticmethod
    def _assert_avatar_source(request: AvatarRequest) -> None:
        """Không dùng hình ảnh người khác khi chưa có đồng ý (brief §4)."""
        if request.avatar_source is None or not request.avatar_source.is_file():
            msg = (
                "Thiếu tài sản avatar hợp lệ. Video/ảnh nguồn phải nằm trong thư mục "
                "runtime và có consent=granted trong asset-manifest.json."
            )
            raise ConsentMissingError(msg)

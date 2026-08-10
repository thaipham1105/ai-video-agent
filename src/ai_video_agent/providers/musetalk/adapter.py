"""Adapter MuseTalk 1.5 thật — gate D04G, **chưa mở**.

Khác Duix ở đúng một chỗ về cơ chế: Duix là HTTP client tới container, còn
MuseTalk chạy bằng **subprocess vào venv WSL**. Mọi thứ còn lại — thứ tự hàng
rào, provenance, cách khai đường ghi thật — giữ nguyên hợp đồng D04-A→D04-D.

Hợp đồng dòng lệnh dưới đây đọc từ ``scripts/inference.py`` của repo đã ghim và
từ lệnh đã chạy thật ở bake-off, **không phải suy đoán từ README**::

    python -m scripts.inference
        --inference_config <yaml>   # video_path/audio_path nằm TRONG yaml
        --result_dir <dir>
        --unet_model_path ./models/musetalkV15/unet.pth
        --unet_config     ./models/musetalkV15/musetalk.json
        --whisper_dir     ./models/whisper
        --version v15 --fps <n> --use_float16
        --ffmpeg_path <thư mục chứa ffmpeg>

Điểm dễ sai nhất: MuseTalk **không** nhận đường dẫn video/audio qua cờ dòng
lệnh. Chúng nằm trong một file YAML mà ta phải ghi ra trước. Truyền qua cờ sẽ bị
bỏ qua im lặng và model chạy trên đầu vào của lần trước.

Adapter này **không bao giờ** tự cài venv, tự tải weights hay tự khởi động WSL.
Thiếu thứ gì thì hỏng ngay với thông điệp chỉ rõ thiếu cái nào — vì tự cài là
cách chắc chắn nhất để một batch "chỉ thử nghiệm" biến thành một batch cài đặt.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shlex
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ai_video_agent import gate_is_open
from ai_video_agent.domain.enums import ProviderKind, ProviderMode, RenderStage
from ai_video_agent.errors import ConsentMissingError, GateNotReachedError, ProviderError
from ai_video_agent.providers._placeholder import read_wav_duration
from ai_video_agent.providers.avatar_capability import check_avatar_request
from ai_video_agent.providers.base import (
    AvatarCapability,
    AvatarProvenance,
    AvatarRequest,
    AvatarResult,
    CostQuote,
    ProviderInfo,
    ResourceEstimate,
    fingerprint_file,
)
from ai_video_agent.providers.musetalk.capability import (
    GATE,
    MUSETALK_CAPABILITY,
    MUSETALK_LOCAL,
    MUSETALK_RESOURCES,
    REPO_COMMIT,
    REQUIRED_WEIGHTS,
    UNET_SHA256,
)

#: Wrapper ffprobe **đã có sẵn** của repo. Dùng lại thay vì viết bản thứ hai —
#: hai wrapper là hai chỗ để sai lệch khác nhau. Đây là ngoại lệ layering duy
#: nhất của module này (``providers`` -> ``qc``); nếu về sau còn nơi khác cần,
#: hãy nâng ``_probe`` thành API công khai thay vì nhân bản nó.
from ai_video_agent.qc.broll import _probe as _ffprobe_entries

MODEL = "musetalk-v15"

#: Điểm vào của upstream, chạy như module chứ không phải file — đúng như lệnh đã
#: dùng ở bake-off.
ENTRYPOINT_MODULE = "scripts.inference"

#: Tên file cấu hình, ghi trong **thư mục job** chứ không phải trong repo upstream.
CONFIG_FILENAME = "inference.yaml"

DEFAULT_TIMEOUT_SEC = 1_800

#: ``shot_id`` được nội suy vào **tên thư mục**, nên nó là dữ liệu vào cần kiểm,
#: không phải một chuỗi tin được. Dùng đúng pattern mà ``Shot.id`` của pydantic
#: đã ràng — nhưng kiểm **lại ở đây**: ``AvatarRequest`` là dataclass thuần, ai
#: cũng dựng được, và adapter không được phụ thuộc vào việc tầng trên đã lọc.
#: Duix không có phơi nhiễm này vì shot_id của nó chỉ vào payload HTTP.
SHOT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")

#: Dung sai khi so mtime của output với mốc bắt đầu job.
#:
#: Vì sao cần dung sai: mtime do **filesystem** đặt, còn mốc bắt đầu do tiến
#: trình này đọc. Hai đồng hồ đó không trùng nhau tuyệt đối — WSL ghi qua lớp
#: 9p/virtiofs sang NTFS, và một số filesystem chỉ lưu mtime với độ phân giải
#: 1 tới 2 giây. Chọn 2,0 s là đủ che sai lệch đó mà vẫn nhỏ hơn nhiều so với thời
#: gian một lượt render (~4 phút), nên file cũ thật vẫn bị bắt.
MTIME_TOLERANCE_SEC = 2.0


def _to_wsl_path(path: Path) -> str:
    """Đổi đường dẫn Windows sang đường dẫn WSL: ``X:\\thu-muc`` -> ``/mnt/x/thu-muc``.

    Đường đã ở dạng POSIX thì giữ nguyên, để adapter chạy được cả khi ai đó gọi
    nó từ trong WSL.
    """
    raw = str(path).replace("\\", "/")
    if len(raw) > 1 and raw[1] == ":":
        return f"/mnt/{raw[0].lower()}{raw[2:]}"
    return raw


@dataclass
class MuseTalkJob:
    """Nhật ký một lần chạy, đủ để truy vết và đưa vào render-manifest."""

    code: str
    command: tuple[str, ...]
    config_yaml: str
    config_path: Path
    config_sha256: str
    result_dir: Path
    #: Đồng hồ đơn điệu — dùng để **đo khoảng thời gian**. Không so được với mtime.
    started_monotonic: float
    #: Đồng hồ tường — dùng để **so với mtime của filesystem**. Hai loại đồng hồ
    #: này không thay nhau được; giữ cả hai là cách duy nhất làm đúng cả hai việc.
    started_wall: float
    finished_at: float | None = None
    return_code: int | None = None
    peak_vram_mib: int | None = None
    stderr_tail: str = ""
    produced: Path | None = None
    params: dict[str, str] = field(default_factory=dict)

    @property
    def elapsed_sec(self) -> float:
        return (self.finished_at or time.monotonic()) - self.started_monotonic


class MuseTalkAvatarProvider:
    """Chạy MuseTalk trong venv WSL qua subprocess. Gate ``D04G``."""

    def __init__(
        self,
        *,
        install_dir: Path | None = None,
        venv_python: str = "~/bakeoff-envs/musetalk/bin/python",
        wsl_distro: str = "Ubuntu",
        wsl_bin: str = "wsl.exe",
        fps: int = 30,
        batch_size: int = 8,
        use_float16: bool = True,
        ffmpeg_dir_wsl: str = "/usr/bin",
        #: Chạy trên HOST để đo video đầu ra — khác ``ffmpeg_dir_wsl`` (dùng bên
        #: trong WSL cho chính MuseTalk). Hai thứ khác nhau, đừng gộp.
        ffprobe_bin: str = "ffprobe",
        hf_home: Path | None = None,
        timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    ) -> None:
        #: ``None`` là hợp lệ và có nghĩa: provider dựng được để hỏi
        #: ``info()``/``quote()``/``capability()`` mà không cần cài gì. Chỉ khi
        #: chạy thật mới đòi đường dẫn — và lúc đó thiếu là hỏng rõ ràng.
        self._install_dir = install_dir
        self._venv_python = venv_python
        self._wsl_distro = wsl_distro
        self._wsl_bin = wsl_bin
        self._fps = fps
        self._batch_size = batch_size
        self._use_float16 = use_float16
        self._ffmpeg_dir_wsl = ffmpeg_dir_wsl
        self._ffprobe_bin = ffprobe_bin
        self._hf_home = hf_home
        self._timeout_sec = timeout_sec
        self.last_job: MuseTalkJob | None = None

    # ----- danh tính, năng lực, báo giá ---------------------------------------

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="musetalk",
            kind=ProviderKind.AVATAR,
            model=MODEL,
            version=f"{REPO_COMMIT[:8]}+unet:{UNET_SHA256[:8]}",
            mode=ProviderMode.REAL,
            billable=False,
            gate=GATE,
        )

    def capability(self) -> AvatarCapability:
        return MUSETALK_CAPABILITY

    def estimate_resources(self, request: AvatarRequest) -> ResourceEstimate:
        """VRAM do kích thước khung và model quyết định, không do thời lượng.

        Bake-off đo 9.798 MiB @30fps cho clip 7,6 s. Nhân theo ``duration_sec``
        sẽ là một công thức bịa — tệ hơn một số đo.
        """
        del request
        return MUSETALK_RESOURCES

    def quote(self, request: AvatarRequest) -> CostQuote:
        """Báo giá chạy được ở mọi gate — không chạm WSL, không nạp model."""
        seconds = request.duration_sec or (
            read_wav_duration(request.audio_path) if request.audio_path.is_file() else 0.0
        )
        return CostQuote(
            stage=RenderStage.AVATAR,
            provider="musetalk",
            model=MODEL,
            unit=MUSETALK_LOCAL.unit,
            units=seconds,
            unit_price_usd=MUSETALK_LOCAL.unit_price_usd,
            estimated_usd=0.0,
            billable=False,
            assumption=MUSETALK_LOCAL.assumption,
        )

    # ----- dựng lệnh (thuần, kiểm được mà không chạy gì) ----------------------

    def config_yaml(self, request: AvatarRequest) -> str:
        """Nội dung file cấu hình mà upstream đọc đường dẫn vào/ra từ đó.

        Sinh bằng :func:`json.dumps` chứ **không** ghép chuỗi: YAML 1.2 là tập
        cha của JSON, nên PyYAML của upstream đọc được nguyên vẹn, mà việc thoát
        ký tự thì do thư viện chuẩn lo. Tự viết escape cho dấu nháy, backslash và
        Unicode là loại code trông đúng cho tới lúc gặp một đường dẫn lạ.

        Cố ý không thêm phụ thuộc PyYAML: dự án không có nó, và không cần có.
        """
        if request.avatar_source is None:
            msg = "Thiếu avatar_source — không dựng được cấu hình MuseTalk."
            raise ProviderError(msg)
        payload = {
            "task_0": {
                "video_path": _to_wsl_path(request.avatar_source),
                "audio_path": _to_wsl_path(request.audio_path),
            }
        }
        return json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n"

    def build_command(self, config_path: Path, result_dir: Path) -> tuple[str, ...]:
        """Dòng lệnh đầy đủ, dựng được **mà không chạy gì** — nên test kiểm được.

        Tách khỏi :meth:`generate` có chủ đích: sai một cờ ở đây là hỏng cả lượt
        render, mà lượt render thì không được thử lại (D04-G §9.2).

        Mọi giá trị động đi qua :func:`shlex.quote`. Không có nó thì một đường
        dẫn chứa khoảng trắng sẽ bị bash tách thành nhiều tham số — và hỏng theo
        kiểu tệ nhất: lệnh vẫn chạy, nhưng chạy sai.
        """
        repo = self._require_install_dir()
        argv = [
            self._venv_python,
            "-m",
            ENTRYPOINT_MODULE,
            "--inference_config",
            _to_wsl_path(config_path),
            "--result_dir",
            _to_wsl_path(result_dir),
            "--unet_model_path",
            "./models/musetalkV15/unet.pth",
            "--unet_config",
            "./models/musetalkV15/musetalk.json",
            "--whisper_dir",
            "./models/whisper",
            "--version",
            "v15",
            "--fps",
            str(self._fps),
            "--batch_size",
            str(self._batch_size),
            "--ffmpeg_path",
            self._ffmpeg_dir_wsl,
        ]
        if self._use_float16:
            argv.append("--use_float16")

        parts = [f"cd {shlex.quote(_to_wsl_path(repo))}"]
        if self._hf_home is not None:
            parts.append(f"export HF_HOME={shlex.quote(_to_wsl_path(self._hf_home))}")
        parts.append(shlex.join(argv))
        script = " && ".join(parts)
        return (self._wsl_bin, "-d", self._wsl_distro, "--", "bash", "-lc", script)

    def inference_params(self) -> dict[str, str]:
        """Tham số thật, ghi vào provenance để tái lập được."""
        return {
            "version": "v15",
            "fps": str(self._fps),
            "batch_size": str(self._batch_size),
            "use_float16": str(self._use_float16).lower(),
            "bbox_shift": "0",
            "extra_margin": "10",
            "parsing_mode": "jaw",
            "cheek_width": "90/90",
            "audio_padding": "2/2",
        }

    # ----- hàng rào -----------------------------------------------------------

    @staticmethod
    def _assert_gate_open() -> None:
        if not gate_is_open(GATE):
            raise GateNotReachedError(
                "MuseTalk 1.5 thật (WSL2 + GPU + ~15 GB weights)",
                GATE,
                hint=(
                    "Gate D04G chưa được mở. Dùng --provider-mode mock, hoặc chờ PO duyệt "
                    "bước chạy thật của D04-G."
                ),
            )

    def _require_install_dir(self) -> Path:
        if self._install_dir is None:
            msg = (
                "MuseTalkAvatarProvider được dựng không có install_dir. Adapter KHÔNG tự "
                "đoán đường dẫn cài đặt và KHÔNG tự cài. Truyền install_dir trỏ tới repo "
                "MuseTalk đã ghim (commit "
                f"{REPO_COMMIT[:8]})."
            )
            raise ProviderError(msg)
        return self._install_dir

    def _assert_runtime_ready(self) -> None:
        """Kiểm repo, weights và WSL — **không** cài, không tải, không khởi động.

        Thiếu thứ gì thì nói thiếu đúng thứ đó. Một thông điệp "chạy hỏng" chung
        chung sẽ tốn hàng giờ để lần ra là do quên một file weights.
        """
        repo = self._require_install_dir()
        if not repo.is_dir():
            msg = (
                f"Không thấy repo MuseTalk tại {repo}. Adapter không tự clone. "
                f"Cần repo ở commit {REPO_COMMIT[:8]} (xem D04G design §3.1)."
            )
            raise ProviderError(msg)

        missing = [rel for rel in REQUIRED_WEIGHTS if not (repo / rel).is_file()]
        if missing:
            msg = (
                f"Thiếu {len(missing)}/{len(REQUIRED_WEIGHTS)} file weights của MuseTalk "
                f"trong {repo}: {', '.join(missing)}. Adapter KHÔNG tự tải. "
                "Đối chiếu weights/musetalk-weights-manifest.json."
            )
            raise ProviderError(msg)

        if shutil.which(self._wsl_bin) is None:
            msg = (
                f"Không thấy {self._wsl_bin!r} trên PATH. Adapter không tự khởi động WSL "
                "và không tự cài đặt gì."
            )
            raise ProviderError(msg)

        # Kiểm ffprobe **ở đây**, không đợi tới lúc đo. Thiếu nó thì lỗi chỉ lộ ra
        # SAU khi đã tốn ~4 phút GPU — mà lượt render của D04-G không được thử lại.
        if shutil.which(self._ffprobe_bin) is None:
            msg = (
                f"Không thấy {self._ffprobe_bin!r} trên PATH. Cần nó để đo thời lượng "
                "video đầu ra; thiếu thì kết quả không kiểm chứng được. Dừng trước khi "
                "chạy GPU thay vì hỏng sau khi đã chạy xong."
            )
            raise ProviderError(msg)

    @staticmethod
    def _assert_shot_id_safe(request: AvatarRequest) -> None:
        """Chặn ``shot_id`` không dựng được thành một đoạn đường dẫn an toàn.

        ``Path("x") / "a/../../b"`` **tách theo dấu gạch chéo** thành nhiều đoạn,
        nên một ``shot_id`` chứa ``/`` hay ``..`` sẽ thoát khỏi thư mục cache.
        Ký tự Windows cấm (``: * ? " < > |``) thì làm ``mkdir`` ném OSError thô.
        Chặn cả hai ở đây, trước khi có bất kỳ thao tác đĩa nào.
        """
        if not SHOT_ID_PATTERN.fullmatch(request.shot_id):
            msg = (
                f"shot_id {request.shot_id!r} không hợp lệ. Chỉ chấp nhận "
                f"{SHOT_ID_PATTERN.pattern} — giá trị này được dùng để dựng tên thư mục "
                "job, nên không được chứa dấu phân cách đường dẫn hay ký tự đặc biệt."
            )
            raise ProviderError(msg)

    @staticmethod
    def _assert_avatar_source(request: AvatarRequest) -> None:
        """Không dùng hình ảnh người khác khi chưa có đồng ý (brief §4)."""
        if request.avatar_source is None or not request.avatar_source.is_file():
            msg = (
                "Thiếu tài sản avatar hợp lệ. Video/ảnh nguồn phải nằm trong thư mục "
                "runtime và có consent=granted trong asset-manifest.json."
            )
            raise ConsentMissingError(msg)
        if not request.audio_path.is_file():
            msg = f"Không thấy file audio {request.audio_path} — không có gì để lip-sync."
            raise ProviderError(msg)

    # ----- chạy ---------------------------------------------------------------

    def generate(self, request: AvatarRequest, out_path: Path) -> AvatarResult:
        """Sinh video người nói. Gửi ĐÚNG MỘT lượt, không tự thử lại.

        Thứ tự hàng rào cố định: gate -> tài sản/consent -> runtime -> năng lực
        -> mới chạy. Mỗi bước rẻ hơn bước sau nó, và bước đắt nhất đứng cuối.
        """
        self._assert_gate_open()
        self._assert_shot_id_safe(request)
        self._assert_avatar_source(request)
        self._assert_runtime_ready()
        check_avatar_request(self.capability(), request, source_is_image=False)

        # Mã job phải duy nhất **thật sự**. Chỉ dùng timestamp theo giây thì hai
        # lượt cùng shot trong cùng một giây sẽ dùng chung thư mục, và lượt sau
        # có thể nhặt output của lượt trước.
        code = f"aiva-{request.shot_id}-{int(time.time())}-{uuid.uuid4().hex[:12]}"
        result_dir = out_path.parent / f"musetalk-{code}"
        try:
            # `exist_ok=False`: thư mục job đã tồn tại là bất thường, không phải
            # chuyện để im lặng dùng lại. Dọn sạch rồi chạy tiếp cũng không được —
            # nó biến một tình huống đáng điều tra thành một lượt chạy trông bình thường.
            result_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            msg = (
                f"Thư mục job {result_dir} đã tồn tại. Không dùng lại và không dọn để "
                "chạy tiếp — output cũ trong đó có thể bị nhận nhầm là kết quả mới."
            )
            raise ProviderError(msg) from exc
        except OSError as exc:
            # Tên quá dài, đĩa đầy, quyền bị từ chối… Hợp đồng nói lỗi provider
            # phải là ProviderError; để OSError thô lọt ra là buộc người đọc log
            # tự đoán nó đến từ đâu trong đường ống.
            msg = f"Không tạo được thư mục job {result_dir}: {exc}"
            raise ProviderError(msg) from exc

        # Config nằm trong THƯ MỤC JOB, không ghi vào repo upstream đã ghim: làm
        # bẩn repo đó khiến việc xác minh "đúng commit" về sau khó hơn.
        config_path = result_dir / CONFIG_FILENAME
        yaml_text = self.config_yaml(request)
        config_bytes = yaml_text.encode("utf-8")
        config_path.write_bytes(config_bytes)

        command = self.build_command(config_path, result_dir)
        job = MuseTalkJob(
            code=code,
            command=command,
            config_yaml=yaml_text,
            config_path=config_path,
            #: Băm ĐÚNG bytes đã ghi ra đĩa, không phải bản dựng trong bộ nhớ.
            config_sha256=hashlib.sha256(config_bytes).hexdigest(),
            result_dir=result_dir,
            started_monotonic=time.monotonic(),
            started_wall=time.time(),
            params=self.inference_params(),
        )
        self.last_job = job

        self._run(job)
        produced = self._resolve_result(job)
        job.produced = produced

        #: Thời lượng của VIDEO ĐẦU RA, đo bằng ffprobe, ưu tiên stream ``v:0``.
        #: Không lấy thời lượng WAV thay thế: trường này chảy vào
        #: ``output_duration_sec`` của manifest, và cổng kiểm lệch A/V của
        #: D04-G §6.3 sẽ luôn bằng 0 nếu hai vế cùng đến từ một nguồn.
        duration_sec, duration_source = self._probe_video_duration(produced)
        return AvatarResult(
            path=produced,
            duration_sec=duration_sec,
            width=request.width,
            height=request.height,
            fps=self._fps,
            is_placeholder=False,
            actual_cost_usd=0.0,
            provenance=self._provenance(request, job, duration_source),
        )

    def _run(self, job: MuseTalkJob) -> None:
        """Chạy đúng một lần. Thất bại là hỏng, **không thử lại** (D04-G §9.2)."""
        try:
            completed = subprocess.run(  # noqa: S603 - lệnh dựng từ hằng số + đường dẫn đã kiểm
                list(job.command),
                capture_output=True,
                text=True,
                timeout=self._timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            job.finished_at = time.monotonic()
            msg = (
                f"MuseTalk quá {self._timeout_sec}s chưa xong (job {job.code}). "
                "KHÔNG tự chạy lại."
            )
            raise ProviderError(msg) from exc
        except OSError as exc:
            job.finished_at = time.monotonic()
            msg = f"Không gọi được WSL cho job {job.code}: {exc}"
            raise ProviderError(msg) from exc

        job.finished_at = time.monotonic()
        job.return_code = completed.returncode
        job.stderr_tail = (completed.stderr or "")[-2000:]

        if completed.returncode != 0:
            msg = (
                f"MuseTalk báo job {job.code} THẤT BẠI (exit {completed.returncode}). "
                f"stderr (2000 ký tự cuối): {job.stderr_tail or '(rỗng)'}"
            )
            raise ProviderError(msg)

    @staticmethod
    def _resolve_result(job: MuseTalkJob) -> Path:
        """Tìm file MP4 mà lượt chạy NÀY thực sự sinh ra.

        Upstream đặt tên theo cấu hình chứ không theo đường ta yêu cầu, nên phải
        dò thư mục kết quả thay vì tin vào một cái tên đoán trước — bài học FIX 3
        đã gặp với Duix. Nhưng "dò" thì phải kèm bằng chứng file thuộc lượt này,
        không chỉ "có một file .mp4 ở đây".

        Ba điều kiện, thiếu một là hỏng: nằm **trong thư mục job**, khác rỗng, và
        **mới hơn mốc bắt đầu job**.
        """
        candidates = sorted(job.result_dir.rglob("*.mp4"))
        if not candidates:
            msg = (
                f"Job {job.code} báo thành công (exit 0) nhưng không có file .mp4 nào trong "
                f"{job.result_dir}. Không suy đoán kết quả — coi như thất bại."
            )
            raise ProviderError(msg)
        if len(candidates) > 1:
            names = ", ".join(p.name for p in candidates)
            msg = (
                f"Job {job.code} sinh {len(candidates)} file .mp4 ({names}). Không đoán "
                "file nào là kết quả."
            )
            raise ProviderError(msg)

        produced = candidates[0]
        # `stat()` ĐI THEO symlink, nên một liên kết trỏ ra ngoài job dir sẽ mượn
        # size/mtime của đích và qua được cả ba điều kiện bên dưới. Chặn trước khi
        # hỏi stat, và chặn cả trường hợp file nằm trong một thư mục symlink.
        if produced.is_symlink():
            msg = (
                f"{produced} là symlink. Không đi theo — output phải là file thật do "
                f"job {job.code} ghi ra trong thư mục của chính nó."
            )
            raise ProviderError(msg)
        job_root = job.result_dir.resolve()
        if not produced.resolve().is_relative_to(job_root):
            msg = (
                f"{produced} giải ra ngoài thư mục job {job_root}. Không nhận output "
                "nằm ngoài phạm vi của lượt chạy này."
            )
            raise ProviderError(msg)

        stat = produced.stat()
        if stat.st_size == 0:
            msg = f"Job {job.code} sinh file rỗng: {produced}."
            raise ProviderError(msg)

        oldest_allowed = job.started_wall - MTIME_TOLERANCE_SEC
        if stat.st_mtime < oldest_allowed:
            tre = job.started_wall - stat.st_mtime
            msg = (
                f"{produced} có mtime cũ hơn lúc job {job.code} bắt đầu {tre:.1f}s "
                f"(dung sai {MTIME_TOLERANCE_SEC}s). Đây là output CŨ, không phải kết quả "
                "của lượt này. Không xoá và không nhận — dừng để điều tra."
            )
            raise ProviderError(msg)
        return produced

    def _probe_entries(self, produced: Path, entries: str, stream: str | None) -> str:
        """Gọi wrapper ffprobe và biến **mọi** lỗi thành ``ProviderError``.

        ``qc.broll._run`` không bắt ``OSError``, nên thiếu binary ffprobe sẽ ném
        ``FileNotFoundError`` xuyên thẳng ra ngoài. Hợp đồng đòi lỗi provider là
        ``ProviderError``; để OSError thô lọt ra là buộc người đọc log tự lần.
        """
        try:
            return _ffprobe_entries(self._ffprobe_bin, produced, entries, stream=stream)
        except OSError as exc:
            msg = (
                f"Không chạy được {self._ffprobe_bin!r} để đo {produced}: {exc}. "
                "Adapter không tự cài công cụ."
            )
            raise ProviderError(msg) from exc

    def _probe_video_duration(self, produced: Path) -> tuple[float, str]:
        """Thời lượng MP4 đầu ra, **ưu tiên stream video** ``v:0``.

        Vì sao không lấy ``format=duration`` làm chính: đó là thời lượng
        **container**, thường bằng stream dài nhất. Với file muxed video+audio nó
        có thể chính là thời lượng audio — và cổng kiểm lệch A/V của D04-G §6.3
        sẽ đọc phải một con số che mất đúng độ lệch cần đo.

        Vẫn giữ ``format=duration`` làm dự phòng vì một số MP4 không ghi
        ``duration`` ở cấp stream. Nhưng nguồn nào được dùng thì **ghi vào
        provenance**, không để manifest im lặng về việc đó.

        Cố ý **không** có nhánh lùi về thời lượng WAV: nó sẽ biến "chưa đo được"
        thành một con số trông như đã đo.

        Trả về ``(giây, nguồn)``.
        """
        for entries, stream, nguon in (
            ("stream=duration", "v:0", "video-stream:v:0"),
            ("format=duration", None, "container-format"),
        ):
            raw = self._probe_entries(produced, entries, stream)
            first = raw.strip().splitlines()[0].strip() if raw.strip() else ""
            if not first or first.upper() == "N/A":
                continue
            try:
                value = float(first)
            except ValueError:
                continue
            if math.isfinite(value) and value > 0:
                return round(value, 3), nguon
            msg = f"Thời lượng video không hợp lệ từ {produced} ({nguon}): {value!r}."
            raise ProviderError(msg)

        msg = (
            f"Không đọc được thời lượng video từ {produced}: cả stream v:0 lẫn container "
            "đều không cho giá trị dùng được. Không thay bằng thời lượng WAV — manifest "
            "không được khẳng định một số đo chưa thực hiện."
        )
        raise ProviderError(msg)

    @staticmethod
    def _input_audio_duration(request: AvatarRequest) -> float:
        """Thời lượng WAV đầu vào — ghi riêng, **không** thay cho thời lượng video."""
        if request.audio_path.is_file():
            return read_wav_duration(request.audio_path)
        return request.duration_sec

    def _provenance(
        self, request: AvatarRequest, job: MuseTalkJob, duration_source: str
    ) -> AvatarProvenance:
        """Dấu vết đủ để truy ngược video này về model và đầu vào đã sinh ra nó."""
        cap = self.capability()
        params = dict(job.params)
        params["job_code"] = job.code
        #: SHA-256 THẬT của đúng bytes file cấu hình đã ghi ra đĩa. Trước đây khoá
        #: này mang tên "...sha256..." nhưng chứa một danh sách đường dẫn — tên nói
        #: dối về nội dung là lỗi nặng trong một bản ghi kiểm chứng.
        params["config_yaml_sha256"] = job.config_sha256
        #: Ghi riêng, tên nói đúng nó là gì. Không được dùng thay cho thời lượng
        #: video đầu ra.
        params["input_audio_duration_sec"] = f"{self._input_audio_duration(request):.3f}"
        #: Nói rõ ``output_duration_sec`` đo từ đâu. Nếu phải lùi về container thì
        #: người đọc manifest phải biết, chứ không đoán.
        params["output_duration_source"] = duration_source
        return AvatarProvenance(
            backend_id=cap.backend_id,
            backend_version=cap.backend_version,
            model=MODEL,
            model_version=REPO_COMMIT,
            audio_encoder=cap.audio_encoder,
            source_fps=self._fps,
            audio_sha256=fingerprint_file(request.audio_path),
            source_asset_sha256=fingerprint_file(request.avatar_source),
            #: Khác Duix: MuseTalk có file checkpoint RỜI nên băm được thật.
            checkpoint_sha256=UNET_SHA256,
            #: Không chạy Docker.
            image_digest="",
            params=params,
            render_seconds=round(job.elapsed_sec, 3),
            #: Đo được bằng vòng lặp nvidia-smi bên ngoài; ``None`` khi chưa đo.
            peak_vram_mib=job.peak_vram_mib,
        )

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
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ai_video_agent import gate_is_open
from ai_video_agent.domain.enums import ProviderKind, ProviderMode, RenderStage
from ai_video_agent.errors import ConsentMissingError, GateNotReachedError, ProviderError

#: Import **module** chứ không phải hàm: ``probe_free_vram_mib`` được thay ở cấp
#: module trong ``tests/conftest.py`` để không test nào chạm ``nvidia-smi`` thật.
#: Bind thẳng vào tên hàm sẽ vô hiệu hoá lớp chặn đó.
from ai_video_agent.providers import resource_budget
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
    MUSETALK_RESOURCES_BY_FPS,
    REPO_COMMIT,
    REQUIRED_WEIGHTS,
    UNET_SHA256,
)

#: Wrapper ffprobe **đã có sẵn** của repo. Dùng lại thay vì viết bản thứ hai —
#: hai wrapper là hai chỗ để sai lệch khác nhau. Đây là ngoại lệ layering duy
#: nhất của module này (``providers`` -> ``qc``); nếu về sau còn nơi khác cần,
#: hãy nâng ``_probe`` thành API công khai thay vì nhân bản nó.
from ai_video_agent.qc.broll import _probe as _ffprobe_entries

if TYPE_CHECKING:
    from collections.abc import Callable

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

#: Khoảng lấy mẫu VRAM trong lúc render. 1 s là nhịp mà bake-off đã dùng —
#: đủ dày để bắt đỉnh của một lượt ~4 phút, đủ thưa để không quấy máy.
VRAM_SAMPLE_INTERVAL_SEC = 1.0

#: Truy vấn tổng VRAM của card. Cố ý tách khỏi ``resource_budget`` (chỉ hỏi phần
#: **trống**) và cố ý **không** sửa file đó — nó nằm ngoài allowlist của D04-G.
#: Đây là một trùng lặp nhỏ có ý thức; gộp chung với LOW-3 khi nâng cả hai probe
#: thành API công khai.
_NVIDIA_SMI_TOTAL_ARGS = ("--query-gpu=memory.total", "--format=csv,noheader,nounits")


def _probe_total_vram_mib() -> int | None:
    """Tổng VRAM của card rảnh nhất, hoặc ``None`` nếu không hỏi được.

    Chỉ đọc, không nạp gì — cùng kỹ thuật ``cli/doctor.py`` và
    ``resource_budget.probe_free_vram_mib`` đang dùng.
    """
    binary = shutil.which("nvidia-smi")
    if binary is None:
        return None
    try:
        completed = subprocess.run(  # noqa: S603 - đường dẫn do shutil.which giải, tham số cố định
            [binary, *_NVIDIA_SMI_TOTAL_ARGS],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    values = [int(line.strip()) for line in completed.stdout.splitlines() if line.strip().isdigit()]
    return max(values) if values else None


def _wsl_file_is_executable(wsl_bin: str, distro: str, posix_path: str) -> bool:
    """``test -x <path>`` bên trong WSL. Chỉ hỏi, **không chạy** file đó.

    Truyền argv thẳng cho ``wsl.exe`` nên không qua shell nào — đường dẫn có
    khoảng trắng cũng không cần quote, và không có bề mặt injection.

    Không phân biệt được "không có file" với "không gọi được WSL": cả hai đều
    trả ``False``, và ở nơi gọi thì cả hai đều là lý do chính đáng để dừng
    trước khi tiêu thời gian GPU.
    """
    try:
        completed = subprocess.run(  # noqa: S603 - argv cố định, không shell
            [wsl_bin, "-d", distro, "--", "test", "-x", posix_path],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


class _VramSampler:
    """Lấy mẫu VRAM trống ở luồng nền trong lúc subprocess render chạy.

    Cổng G3 của D04-G §4.1 nói rõ: giai đoạn này **ghi nhận, không chặn**. Nên
    mọi lỗi lấy mẫu đều bị nuốt — một lượt render 4 phút không được hỏng chỉ vì
    ``nvidia-smi`` bận. Không đo được thì ``peak()`` trả ``None``, giữ đúng nghĩa
    "chưa đo" mà ``AvatarProvenance`` đã định.
    """

    def __init__(
        self,
        sampler: Callable[[], int | None],
        total_probe: Callable[[], int | None],
        interval_sec: float,
    ) -> None:
        self._sampler = sampler
        self._total_probe = total_probe
        self._interval_sec = interval_sec
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._min_free_mib: int | None = None

    def __enter__(self) -> _VramSampler:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="musetalk-vram")
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval_sec * 3)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                free = self._sampler()
            except Exception:  # noqa: BLE001 - G3 ghi nhận, không được làm hỏng lượt render
                free = None
            if free is not None and (self._min_free_mib is None or free < self._min_free_mib):
                self._min_free_mib = free
            self._stop.wait(self._interval_sec)

    def peak_used_mib(self) -> int | None:
        """Đỉnh VRAM **đã dùng** = tổng trừ đi lượng trống thấp nhất quan sát được.

        Trả về lượng dùng của **cả card**, không riêng MuseTalk — đúng như cách
        bake-off đã đo (``nvidia-smi --query-gpu=memory.used``), nên con số này so
        được trực tiếp với 9.798 MiB trong ``MUSETALK_RESOURCES``.
        """
        if self._min_free_mib is None:
            return None
        try:
            total = self._total_probe()
        except Exception:  # noqa: BLE001 - cùng lý do với vòng lấy mẫu
            total = None
        if total is None or total <= self._min_free_mib:
            return None
        return total - self._min_free_mib


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
    #: Tỷ số fps thô của file đầu ra (``30/1``, ``30000/1001``…). Giữ nguyên vì
    #: làm tròn về int là mất thông tin mà schema manifest chỉ nhận int.
    output_fps_raw: str = ""
    source_fps_raw: str = ""
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
        #: Đường **tuyệt đối** trong WSL. Rỗng là mặc định có chủ đích — xem
        #: ``Config.musetalk_venv_python``. Hàng rào ở :meth:`_assert_venv_python`
        #: từ chối cả chuỗi rỗng lẫn ``~`` chưa nở.
        venv_python: str = "",
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
        #: Tiêm được để test không chạm ``nvidia-smi`` thật. Mặc định ``None``
        #: nghĩa là dùng probe chung của dự án, gọi qua **module attribute** nên
        #: lớp chặn trong ``tests/conftest.py`` vẫn có hiệu lực.
        vram_sampler: Callable[[], int | None] | None = None,
        vram_total_probe: Callable[[], int | None] | None = None,
        vram_sample_interval_sec: float = VRAM_SAMPLE_INTERVAL_SEC,
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
        self._vram_sampler = vram_sampler
        self._vram_total_probe = vram_total_probe or _probe_total_vram_mib
        self._vram_sample_interval_sec = vram_sample_interval_sec
        self.last_job: MuseTalkJob | None = None

    def _sample_free_vram_mib(self) -> int | None:
        """Một lần lấy mẫu VRAM trống, qua probe đã tiêm hoặc probe chung."""
        if self._vram_sampler is not None:
            return self._vram_sampler()
        return resource_budget.probe_free_vram_mib()

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
        """VRAM theo **fps đã cấu hình**, không do thời lượng clip.

        Bake-off đo 9.118 MiB @25fps và 9.798 MiB @30fps cho cùng clip 7,6 s —
        fps đổi thì số khung đổi, và VRAM đổi theo. Nhân theo ``duration_sec``
        thì ngược lại sẽ là một công thức bịa, tệ hơn một số đo.

        fps lạ (không có số đo) thì lấy mức **cao nhất** đã đo: thà chặn nhầm
        một lượt chạy được còn hơn cho qua rồi OOM giữa chừng.
        """
        del request
        if self._fps in MUSETALK_RESOURCES_BY_FPS:
            return MUSETALK_RESOURCES_BY_FPS[self._fps]
        return max(MUSETALK_RESOURCES_BY_FPS.values(), key=lambda r: r.vram_mib)

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

        # ffmpeg của MuseTalk nằm TRONG WSL và chỉ được dùng ở bước mux **cuối
        # cùng**. Sai đường dẫn ⇒ hỏng sau khi GPU đã chạy xong — đúng kịch bản
        # tệ nhất cho một lượt không được thử lại. Nên hỏi ngay bây giờ.
        # Interpreter kiểm ngay sau WSL: thiếu nó thì mọi thứ sau đều vô nghĩa.
        self._assert_venv_python()

        ffmpeg_path = f"{self._ffmpeg_dir_wsl.rstrip('/')}/ffmpeg"
        if not _wsl_file_is_executable(self._wsl_bin, self._wsl_distro, ffmpeg_path):
            msg = (
                f"Không thấy ffmpeg chạy được tại {ffmpeg_path!r} trong WSL "
                f"{self._wsl_distro!r}. MuseTalk nhận thư mục này qua --ffmpeg_path và "
                "chỉ dùng nó ở bước ghép cuối, nên sai đường dẫn sẽ hỏng SAU khi đã tốn "
                "hết thời gian GPU. Khai AIVA_MUSETALK_FFMPEG_DIR trỏ đúng thư mục "
                "chứa ffmpeg (adapter không tự cài)."
            )
            raise ProviderError(msg)

    def _assert_venv_python(self) -> None:
        """Interpreter phải là đường **tuyệt đối** và chạy được, kiểm trước GPU.

        Bài học từ lượt render hỏng exit 127: mặc định cũ là ``~/bakeoff-envs/…``,
        và ``build_command`` bọc nó bằng :func:`shlex.quote` để chịu được khoảng
        trắng — nhưng **bash không nở ``~`` bên trong dấu nháy**. Lệnh chạy với
        một đường dẫn ký tự thật không tồn tại, và chết ngay dòng đầu.

        Hai yêu cầu đối nhau ở đây: quote thì an toàn với khoảng trắng nhưng giết
        tilde; không quote thì nở tilde nhưng vỡ với khoảng trắng. Cách thoát là
        **đòi đường tuyệt đối** — lúc đó quote luôn đúng và không cần nở gì.
        """
        path = self._venv_python.strip()
        if not path:
            msg = (
                "Chưa khai python của venv MuseTalk. Adapter không đoán: "
                "'/usr/bin/python3' tồn tại thật nhưng thiếu toàn bộ gói MuseTalk, "
                "và lỗi sẽ chỉ lộ ra sau khi đã nạp nửa chừng. Khai "
                "AIVA_MUSETALK_VENV_PYTHON bằng đường dẫn tuyệt đối trong WSL."
            )
            raise ProviderError(msg)
        if "~" in path:
            msg = (
                f"venv python {path!r} chứa '~'. Dòng lệnh được quote để chịu khoảng "
                "trắng, mà bash KHÔNG nở '~' trong dấu nháy — lệnh sẽ chết với "
                "exit 127. Khai đường dẫn tuyệt đối, ví dụ /home/<user>/.../bin/python."
            )
            raise ProviderError(msg)
        if not path.startswith("/"):
            msg = (
                f"venv python {path!r} không phải đường tuyệt đối. Lệnh chạy sau "
                "'cd <repo>' nên đường tương đối sẽ trỏ nhầm chỗ."
            )
            raise ProviderError(msg)
        if not _wsl_file_is_executable(self._wsl_bin, self._wsl_distro, path):
            msg = (
                f"Không thấy python chạy được tại {path!r} trong WSL "
                f"{self._wsl_distro!r}. Adapter không tự tạo venv và không tự cài gì."
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

        Thứ tự hàng rào cố định: gate -> shot_id -> tài sản/consent -> runtime
        -> năng lực -> mới chạy. Mỗi bước rẻ hơn bước sau nó, và bước đắt nhất
        đứng cuối. ``shot_id`` đứng thứ hai vì nó là dữ liệu vào được dùng để
        dựng đường dẫn, phải chặn trước mọi thao tác đĩa.
        """
        self._assert_gate_open()
        self._assert_shot_id_safe(request)
        self._assert_avatar_source(request)
        self._assert_runtime_ready()
        check_avatar_request(self.capability(), request, source_is_image=False)
        self._assert_source_fps_matches(request)

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
        try:
            config_path.write_bytes(config_bytes)
        except OSError as exc:
            # Cùng lý do với `mkdir` ngay trên: lỗi provider phải là ProviderError.
            # Đĩa có thể đầy ngay giữa hai lệnh ghi này.
            msg = f"Không ghi được file cấu hình {config_path}: {exc}"
            raise ProviderError(msg) from exc

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
        #: fps ĐO TỪ FILE, không lấy ``self._fps``. Cờ ``--fps`` không quyết định
        #: fps đầu ra khi đầu vào là video — xem :meth:`_probe_video_fps`.
        output_fps, output_fps_raw = self._probe_video_fps(produced)
        job.output_fps_raw = output_fps_raw
        return AvatarResult(
            path=produced,
            duration_sec=duration_sec,
            width=request.width,
            height=request.height,
            fps=output_fps,
            is_placeholder=False,
            actual_cost_usd=0.0,
            provenance=self._provenance(request, job, duration_source),
        )

    def _run(self, job: MuseTalkJob) -> None:
        """Chạy đúng một lần. Thất bại là hỏng, **không thử lại** (D04-G §9.2).

        Lấy mẫu VRAM chạy song song trong ``finally`` để đỉnh được ghi **kể cả khi
        job hỏng** — với một lỗi OOM thì con số đó chính là bằng chứng cần nhất.
        """
        sampler = _VramSampler(
            self._sample_free_vram_mib,
            self._vram_total_probe,
            self._vram_sample_interval_sec,
        )
        try:
            with sampler:
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
        finally:
            # Ghi đỉnh trên MỌI nhánh thoát, kể cả timeout và OOM — với một lượt
            # hỏng vì hết VRAM thì đây chính là con số cần nhất để chẩn đoán.
            job.peak_vram_mib = sampler.peak_used_mib()

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

    def _probe_video_fps(self, path: Path) -> tuple[int, str]:
        """fps **đo từ file**, trả ``(số nguyên đã làm tròn, tỷ số thô)``.

        Vì sao không dùng ``self._fps``: cờ ``--fps`` của MuseTalk **không quyết
        định fps đầu ra khi đầu vào là video** — nó lấy fps của video nguồn. Lượt
        ``f16bd2a245d4`` đã lộ ra điều đó: truyền ``--fps 25`` nhưng file sinh ra
        là 30/1, trong khi manifest vẫn khai 25 vì đọc từ cấu hình.

        Giữ cả tỷ số thô (``30000/1001``) vì làm tròn về int là mất thông tin, mà
        schema manifest lại chỉ nhận int.
        """
        raw = self._probe_entries(path, "stream=r_frame_rate", "v:0").strip()
        first = raw.splitlines()[0].strip() if raw else ""
        if "/" not in first:
            msg = f"Không đọc được fps từ {path} (ffprobe trả {raw!r})."
            raise ProviderError(msg)
        num, den = first.split("/", 1)
        try:
            value = float(num) / float(den)
        except (ValueError, ZeroDivisionError) as exc:
            msg = f"fps không hợp lệ từ {path}: {first!r}."
            raise ProviderError(msg) from exc
        if not math.isfinite(value) or value <= 0:
            msg = f"fps không hợp lệ từ {path}: {value!r}."
            raise ProviderError(msg)
        return round(value), first

    def _assert_source_fps_matches(self, request: AvatarRequest) -> None:
        """fps yêu cầu phải **khớp fps của video nguồn**, kiểm trước khi chạm GPU.

        MuseTalk kế thừa fps từ nguồn. Cho hai giá trị lệch nhau đi qua nghĩa là
        đặc trưng audio băm theo một nhịp còn khung ghi theo nhịp khác — và kết
        quả trông vẫn "thành công" trong khi điều kiện thí nghiệm đã hỏng.

        Muốn chạy fps khác thì phải **convert nguồn trước**, thành một tài sản
        riêng ghi rõ trong manifest, chứ không phải đổi một con số trên dòng lệnh.
        """
        if request.avatar_source is None:
            return
        source_fps, raw = self._probe_video_fps(request.avatar_source)
        if source_fps != self._fps:
            msg = (
                f"fps yêu cầu {self._fps} khác fps của video nguồn {source_fps} "
                f"({raw}). MuseTalk lấy fps TỪ NGUỒN, không từ cờ --fps — chạy tiếp "
                "sẽ ra video ở fps nguồn trong khi đặc trưng tiếng băm theo fps yêu "
                "cầu. Hãy convert nguồn sang fps mong muốn và đăng ký nó như một tài "
                "sản riêng, thay vì chỉ đổi tham số."
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
        #: fps yêu cầu qua cờ **khác** fps thật của file. Ghi cả hai: cờ để tái
        #: lập lệnh, số đo để biết chuyện gì thực sự xảy ra.
        params["requested_fps_flag"] = str(self._fps)
        params["output_fps_raw"] = job.output_fps_raw
        params["source_fps_raw"] = job.source_fps_raw

        source_fps = self._fps
        if request.avatar_source is not None:
            source_fps, raw = self._probe_video_fps(request.avatar_source)
            params["source_fps_raw"] = raw

        return AvatarProvenance(
            backend_id=cap.backend_id,
            backend_version=cap.backend_version,
            model=MODEL,
            model_version=REPO_COMMIT,
            audio_encoder=cap.audio_encoder,
            #: ĐO từ video nguồn, không lấy từ cờ ``--fps``.
            source_fps=source_fps,
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

"""Cấu hình đọc từ biến môi trường (tiền tố ``AIVA_``).

Nguyên tắc bảo mật (CLAUDE.md §4): module này **không bao giờ đọc giá trị** của
biến chứa secret. Với các biến nhạy cảm nó chỉ ghi nhận *sự tồn tại* thông qua
:func:`secret_present`, đủ để ``doctor`` báo cáo mà không làm lộ nội dung.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ai_video_agent.domain.enums import ProviderMode

#: Thư mục dữ liệu runtime mặc định — nằm NGOÀI repo Git.
DEFAULT_RUNTIME_DIR = Path("F:/AI-VIDEO-AGENT-RUNTIME")

#: Tên các biến môi trường chứa secret. Chỉ được kiểm tra tồn tại.
SECRET_ENV_NAMES: tuple[str, ...] = (
    "AIVA_VIDEO_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)


def secret_present(name: str) -> bool:
    """Trả về ``True`` nếu biến tồn tại, **không** đọc giá trị của nó."""
    return name in os.environ


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_int_or_none(name: str) -> int | None:
    """Số nguyên dương, hoặc ``None`` khi không khai / khai sai.

    Cố ý không có giá trị mặc định: đây là ngưỡng tài nguyên, mà một mặc định
    bịa ra sẽ chặn nhầm hoặc để lọt. Giá trị rác cũng về ``None`` — thà không
    biết còn hơn tin một con số vô nghĩa.
    """
    raw = os.environ.get(name)
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    """Cấu hình runtime đã được giải nghĩa."""

    runtime_dir: Path = DEFAULT_RUNTIME_DIR
    provider_mode: ProviderMode = ProviderMode.MOCK
    allow_paid_apis: bool = False

    vieneu_device: str = "cpu"
    vieneu_sample_rate: int = 48_000

    duix_base_url: str = "http://127.0.0.1:8383"
    duix_timeout_sec: int = 900
    #: Điểm gắn của thư mục projects bên trong container Duix. Phải khớp volume
    #: khai trong ``deploy/duix/docker-compose.yml``; lệch là Duix không thấy file.
    duix_inputs_mount: str = "/inputs"
    #: Digest image đang chạy, ghi vào render-manifest để truy vết (brief §D03.2).
    duix_image_digest: str = (
        "sha256:1970424d219cbb6aebc7566f069041f057ccad618a395139dce002e1fb25d5ed"
    )

    @property
    def duix_data_dir(self) -> Path:
        """Thư mục dữ liệu Duix trên host — nơi nó ghi kết quả."""
        return self.runtime_dir / "duix_avatar_data" / "face2face"

    #: Ngưỡng tài nguyên do người vận hành khai, dùng cho preflight avatar.
    #: ``None`` = **không khai**, khác hẳn 0. Preflight sẽ dò máy (chỉ đọc) rồi
    #: báo "chưa xác minh được" nếu vẫn không biết — không bao giờ giả định 0
    #: hay giả định vô hạn. Khai số thấp hơn thực tế là cách chừa chỗ cho việc
    #: khác đang dùng chung GPU.
    vram_budget_mib: int | None = None
    ram_budget_mib: int | None = None
    storage_budget_mib: int | None = None

    #: Thư mục chứa ``ffmpeg`` **bên trong WSL**, truyền cho MuseTalk qua
    #: ``--ffmpeg_path``. Khác hẳn ``ffmpeg_bin`` (chạy trên host Windows).
    #:
    #: Mặc định ``/usr/bin`` là nơi ``apt`` cài. Máy nào cài bằng cách khác —
    #: ví dụ ``pip install --user`` bỏ nó ở ``~/.local/bin`` — thì phải khai
    #: ``AIVA_MUSETALK_FFMPEG_DIR``. Sai đường dẫn này chỉ lộ ra ở bước mux
    #: **cuối cùng**, tức sau khi đã tốn hết thời gian GPU.
    musetalk_ffmpeg_dir: str = "/usr/bin"

    #: fps cho MuseTalk. **Mặc định 30** vì D04G design §5.2 chốt 30 fps là lượt
    #: chính thức duy nhất — đổi mặc định sẽ làm lượt sau lặng lẽ chạy sai điều
    #: kiện. Lượt 25 fps (fps huấn luyện gốc của model) phải khai tường minh
    #: ``AIVA_MUSETALK_FPS=25``, và kết quả **không so trực tiếp từng khung**
    #: với bản Duix 30 fps được nếu chưa chuẩn hoá fps.
    musetalk_fps: int = 30

    #: Đường dẫn **tuyệt đối** tới python của venv MuseTalk, nhìn từ trong WSL.
    #:
    #: Mặc định để **rỗng** có chủ đích: mọi giá trị đoán sẵn đều sai theo một
    #: kiểu khó thấy. ``~/...`` thì bash không nở trong dấu nháy (đã làm hỏng
    #: một lượt render với exit 127); ``/usr/bin/python3`` thì tồn tại thật nhưng
    #: thiếu toàn bộ gói của MuseTalk, và lỗi chỉ lộ ra sau khi đã nạp nửa chừng.
    #: Rỗng thì hàng rào báo ngay phải khai ``AIVA_MUSETALK_VENV_PYTHON``.
    musetalk_venv_python: str = ""

    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"

    video_api_provider: str = "none"
    video_api_max_usd_per_run: float = 0.0

    #: Tên secret -> có mặt hay không (không kèm giá trị).
    secrets_present: dict[str, bool] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> Config:
        """Dựng cấu hình từ môi trường hiện tại."""
        raw_mode = _env_str("AIVA_PROVIDER_MODE", ProviderMode.MOCK.value).strip().lower()
        mode = ProviderMode(raw_mode) if raw_mode in set(ProviderMode) else ProviderMode.MOCK

        max_usd_raw = _env_str("AIVA_VIDEO_API_MAX_USD_PER_RUN", "0")
        try:
            max_usd = max(0.0, float(max_usd_raw))
        except ValueError:
            max_usd = 0.0

        return cls(
            runtime_dir=Path(_env_str("AIVA_RUNTIME_DIR", str(DEFAULT_RUNTIME_DIR))),
            provider_mode=mode,
            allow_paid_apis=_env_bool("AIVA_ALLOW_PAID_APIS", default=False),
            vieneu_device=_env_str("AIVA_VIENEU_DEVICE", "cpu"),
            vieneu_sample_rate=_env_int("AIVA_VIENEU_SAMPLE_RATE", 48_000),
            duix_base_url=_env_str("AIVA_DUIX_BASE_URL", "http://127.0.0.1:8383"),
            duix_timeout_sec=_env_int("AIVA_DUIX_TIMEOUT_SEC", 900),
            duix_inputs_mount=_env_str("AIVA_DUIX_INPUTS_MOUNT", "/inputs"),
            vram_budget_mib=_env_int_or_none("AIVA_VRAM_BUDGET_MIB"),
            ram_budget_mib=_env_int_or_none("AIVA_RAM_BUDGET_MIB"),
            storage_budget_mib=_env_int_or_none("AIVA_STORAGE_BUDGET_MIB"),
            musetalk_ffmpeg_dir=_env_str("AIVA_MUSETALK_FFMPEG_DIR", "/usr/bin"),
            musetalk_fps=_env_int("AIVA_MUSETALK_FPS", 30),
            musetalk_venv_python=_env_str("AIVA_MUSETALK_VENV_PYTHON", ""),
            ffmpeg_bin=_env_str("AIVA_FFMPEG_BIN", "ffmpeg"),
            ffprobe_bin=_env_str("AIVA_FFPROBE_BIN", "ffprobe"),
            video_api_provider=_env_str("AIVA_VIDEO_API_PROVIDER", "none"),
            video_api_max_usd_per_run=max_usd,
            secrets_present={name: secret_present(name) for name in SECRET_ENV_NAMES},
        )

    def redacted_summary(self) -> dict[str, str]:
        """Tóm tắt an toàn để in ra màn hình / ghi log."""
        summary = {
            "runtime_dir": str(self.runtime_dir),
            "provider_mode": self.provider_mode.value,
            "allow_paid_apis": str(self.allow_paid_apis),
            "vieneu_device": self.vieneu_device,
            "duix_base_url": self.duix_base_url,
            "ffmpeg_bin": self.ffmpeg_bin,
            "video_api_provider": self.video_api_provider,
        }
        for name, present in sorted(self.secrets_present.items()):
            summary[f"secret:{name}"] = "present (giá trị không được đọc)" if present else "absent"
        return summary

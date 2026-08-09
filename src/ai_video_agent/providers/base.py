"""Giao diện chung cho mọi provider.

Mỗi provider phải trả lời được ba câu hỏi trước khi làm bất cứ việc gì:

1. ``info()``  — tôi là ai, model/version nào, mock hay thật, có tính tiền không.
2. ``quote()`` — việc này tốn bao nhiêu, dựa trên giả định gì.
3. hàm chạy    — thực thi và trả về artifact đã ghi ra đĩa.

Nhờ ``quote()`` tách khỏi hàm chạy, ``aiva estimate`` và ``aiva render --dry-run``
lấy được toàn bộ bảng chi phí mà **không** chạm vào provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from ai_video_agent.domain.assets import sha256_file
from ai_video_agent.domain.enums import ProviderKind, ProviderMode, RenderStage


def fingerprint_file(path: Path | None) -> str:
    """Vân tay SHA-256 của một file đầu vào, dùng cho provenance.

    Trả về chuỗi rỗng khi không có file. Provenance thà **thiếu** một trường còn
    hơn mang một giá trị bịa: một băm sai còn tệ hơn không có băm, vì nó trông
    như bằng chứng.
    """
    if path is None or not path.is_file():
        return ""
    return sha256_file(path)


@dataclass(frozen=True)
class ProviderInfo:
    """Danh tính provider, ghi thẳng vào ``render-manifest.json``."""

    name: str
    kind: ProviderKind
    model: str
    version: str
    mode: ProviderMode
    #: ``True`` nếu provider gọi API tính tiền. Cost guard chặn dựa vào cờ này.
    billable: bool = False
    #: Gate mở tính năng thật của provider (``D02``/``D03``/``D05``).
    gate: str = "D01"


@dataclass(frozen=True)
class CostQuote:
    """Báo giá cho một đơn vị công việc, kèm giả định để người dùng kiểm chứng."""

    stage: RenderStage
    provider: str
    model: str
    unit: str
    units: float
    unit_price_usd: float
    estimated_usd: float
    billable: bool
    assumption: str = ""


@dataclass(frozen=True)
class TtsRequest:
    """Yêu cầu tổng hợp giọng nói."""

    shot_id: str
    text_vi: str
    #: Giọng dựng sẵn, hoặc ``None`` nếu dùng ``ref_audio``.
    voice: str | None = None
    #: Đường dẫn mẫu giọng đã có đồng ý sử dụng (chỉ mở từ D02).
    ref_audio: Path | None = None
    sample_rate: int = 48_000
    speed: float = 1.0
    target_duration_sec: float | None = None


@dataclass(frozen=True)
class TtsResult:
    """Kết quả WAV đã ghi ra đĩa."""

    path: Path
    duration_sec: float
    sample_rate: int
    channels: int = 1
    is_placeholder: bool = False
    actual_cost_usd: float | None = None


@dataclass(frozen=True)
class AvatarRequest:
    """Yêu cầu sinh video người đại diện nói."""

    shot_id: str
    audio_path: Path
    #: Video/ảnh nguồn của avatar — bắt buộc đã có ``consent = granted``.
    avatar_source: Path | None
    width: int
    height: int
    fps: int = 30
    seed: int | None = None
    #: Thời lượng dự kiến, để ``quote()`` chạy được khi file WAV chưa tồn tại
    #: (trường hợp ``estimate`` và ``render --dry-run``).
    duration_sec: float = 0.0


@dataclass(frozen=True)
class ResourceEstimate:
    """Tài nguyên một backend cần cho một lần chạy.

    **Mọi trường đều bắt buộc.** Cố ý không cho mặc định 0: một backend quên khai
    VRAM mà vẫn hợp lệ sẽ khiến hàng rào tài nguyên im lặng cho qua, và lỗi chỉ
    lộ ra lúc OOM giữa chừng — sau khi đã tốn thời gian GPU.

    ``measured`` phân biệt số **đo thật trên máy này** với số chép từ tài liệu
    upstream. Bake-off D04 cho thấy khoảng cách đó là 34%: LatentSync 1.6 ghi
    18 GB trong README nhưng đo thật 11.942 MiB. Tin tài liệu là loại nhầm một
    ứng viên chạy được.
    """

    vram_mib: int
    ram_mib: int
    storage_mib: int
    #: ``True`` khi cùng đầu vào + cùng seed cho ra cùng đầu ra, chạy hoàn toàn local.
    deterministic_local: bool
    #: ``True`` = đo thật trên máy này; ``False`` = ước tính từ tài liệu.
    measured: bool
    #: Ngày đo, dạng ISO. Rỗng khi ``measured=False``.
    measured_on: str = ""

    def __post_init__(self) -> None:
        if self.vram_mib < 0 or self.ram_mib < 0 or self.storage_mib < 0:
            msg = "Tài nguyên ước tính không được âm."
            raise ValueError(msg)
        if self.ram_mib == 0:
            msg = "ram_mib = 0 gần như chắc chắn là quên khai, không phải sự thật."
            raise ValueError(msg)
        if self.measured and not self.measured_on:
            msg = "measured=True thì phải có measured_on — không có ngày thì số liệu vô nghĩa."
            raise ValueError(msg)


@dataclass(frozen=True)
class AvatarCapability:
    """Năng lực đã xác minh của một backend lip-sync.

    Lấy từ **hành vi model thật**, không phải từ việc SDK có field tương ứng —
    bài học D05-C §1: ``GenerateVideosConfig`` có ``fps`` nhưng Veo vẫn cố định
    24 fps, gửi tham số đi chỉ tạo ảo giác điều khiển được.
    """

    backend_id: str
    backend_version: str
    #: FPS model xuất ra khi không bị ép. Duix 30, MuseTalk 25.
    native_fps: int
    supported_fps: frozenset[int]
    max_width: int
    max_height: int
    audio_sample_rate_hz: int
    audio_channels: int
    #: Bộ mã hoá tiếng — thứ quyết định chất lượng khẩu hình theo ngôn ngữ.
    audio_encoder: str
    #: Ngôn ngữ đã kiểm chứng. ``{"zh"}`` khác hẳn ``{"multi"}`` về ý nghĩa.
    languages_verified: frozenset[str]
    accepts_image_source: bool
    accepts_video_source: bool
    #: Gate phải mở thì adapter thật mới chạy.
    requires_gate: str
    resources: ResourceEstimate
    source_url: str = ""

    def __post_init__(self) -> None:
        if not self.backend_id or not self.backend_version:
            msg = "Capability phải khai backend_id và backend_version."
            raise ValueError(msg)
        if self.native_fps <= 0:
            msg = "native_fps phải dương."
            raise ValueError(msg)
        if self.native_fps not in self.supported_fps:
            msg = f"native_fps={self.native_fps} phải nằm trong supported_fps."
            raise ValueError(msg)
        if not self.audio_encoder:
            msg = "Phải khai audio_encoder — nó quyết định chất lượng theo ngôn ngữ."
            raise ValueError(msg)
        if not self.languages_verified:
            msg = "Phải khai languages_verified, kể cả khi chỉ có một ngôn ngữ."
            raise ValueError(msg)
        if not (self.accepts_image_source or self.accepts_video_source):
            msg = "Backend phải nhận được ít nhất một loại nguồn."
            raise ValueError(msg)


@dataclass(frozen=True)
class AvatarProvenance:
    """Dấu vết đủ để truy ngược một video về model và đầu vào đã sinh ra nó.

    Không có khối này thì nhìn một file `avatar.mp4` bất kỳ sẽ không biết được
    model nào, checkpoint nào, tham số gì đã tạo ra nó.
    """

    backend_id: str
    backend_version: str
    model: str
    model_version: str
    audio_encoder: str
    #: FPS model THỰC SỰ xuất ra, có thể khác ``AvatarRequest.fps``.
    source_fps: int
    #: Vân tay đầu vào. Rỗng khi file không tồn tại lúc chạy (đường mock).
    audio_sha256: str = ""
    source_asset_sha256: str = ""
    #: Băm checkpoint. Rỗng khi trọng số nằm trong Docker image.
    checkpoint_sha256: str = ""
    #: Digest image với backend chạy container.
    image_digest: str = ""
    #: Tham số inference thật, để tái lập.
    params: dict[str, str] = field(default_factory=dict)
    render_seconds: float | None = None
    peak_vram_mib: int | None = None


@dataclass(frozen=True)
class AvatarResult:
    path: Path
    duration_sec: float
    width: int
    height: int
    fps: int
    is_placeholder: bool = False
    actual_cost_usd: float | None = None
    #: Bắt buộc với backend thật; mock cũng khai để hợp đồng đồng nhất.
    provenance: AvatarProvenance | None = None


@dataclass(frozen=True)
class BrollRequest:
    """Yêu cầu sinh cảnh minh hoạ (ViMax hoặc API video, chỉ từ D05)."""

    shot_id: str
    prompt_vi: str
    duration_sec: float
    width: int
    height: int
    fps: int = 30
    seed: int | None = None


@dataclass(frozen=True)
class BrollResult:
    path: Path
    duration_sec: float
    width: int
    height: int
    fps: int
    is_placeholder: bool = False
    actual_cost_usd: float | None = None


@runtime_checkable
class TtsProvider(Protocol):
    """Provider sinh giọng đọc tiếng Việt."""

    def info(self) -> ProviderInfo: ...

    def quote(self, request: TtsRequest) -> CostQuote: ...

    def synthesize(self, request: TtsRequest, out_path: Path) -> TtsResult: ...


@runtime_checkable
class AvatarProvider(Protocol):
    """Provider sinh video người nói từ WAV + tài sản avatar.

    Năm phương thức, mỗi cái trả lời một câu hỏi phải trả lời được **trước** khi
    chạm GPU: tôi là ai (``info``), tôi làm được gì (``capability``), tôi tốn bao
    nhiêu tiền (``quote``), tôi tốn bao nhiêu tài nguyên (``estimate_resources``),
    và cuối cùng mới là chạy (``generate``).
    """

    def info(self) -> ProviderInfo: ...

    def capability(self) -> AvatarCapability: ...

    def quote(self, request: AvatarRequest) -> CostQuote: ...

    def estimate_resources(self, request: AvatarRequest) -> ResourceEstimate: ...

    def generate(self, request: AvatarRequest, out_path: Path) -> AvatarResult: ...


@runtime_checkable
class BrollProvider(Protocol):
    """Provider sinh B-roll / cảnh nhiều shot."""

    def info(self) -> ProviderInfo: ...

    def quote(self, request: BrollRequest) -> CostQuote: ...

    def generate(self, request: BrollRequest, out_path: Path) -> BrollResult: ...


@dataclass
class ProviderSet:
    """Bộ provider đã chọn cho một lần chạy."""

    tts: TtsProvider
    avatar: AvatarProvider
    broll: BrollProvider | None = None
    notes: list[str] = field(default_factory=list)

    def infos(self) -> list[ProviderInfo]:
        found = [self.tts.info(), self.avatar.info()]
        if self.broll is not None:
            found.append(self.broll.info())
        return found

    @property
    def any_billable(self) -> bool:
        return any(info.billable for info in self.infos())

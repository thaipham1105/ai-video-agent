"""``render-manifest.json`` — nhật ký kiểm chứng của một lần render (brief §7)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ai_video_agent.clock import now_utc
from ai_video_agent.domain.enums import ProviderMode, RenderStage, StageStatus


class CostLine(BaseModel):
    """Một dòng chi phí ước tính, kèm giả định để người dùng kiểm chứng được."""

    model_config = ConfigDict(extra="forbid")

    stage: RenderStage
    provider: str
    model: str
    unit: str
    units: float = Field(ge=0.0)
    unit_price_usd: float = Field(ge=0.0)
    estimated_usd: float = Field(ge=0.0)
    billable: bool = False
    assumption: str = ""


class ResourceUsage(BaseModel):
    """Tài nguyên đã khai và số đo thật của một lần chạy.

    Tách ``est_*`` khỏi ``peak_vram_mib`` vì hai thứ này trả lời hai câu khác
    nhau: cái đầu là **lời hứa** của backend trước khi chạy, cái sau là **quan
    sát** sau khi chạy. Gộp lại thì không bao giờ biết được lời hứa có đúng không.
    """

    model_config = ConfigDict(extra="forbid")

    est_vram_mib: int = Field(ge=0)
    #: ``gt=0`` chứ không phải ``ge=0``: RAM bằng 0 là quên khai, không phải sự thật.
    est_ram_mib: int = Field(gt=0)
    est_storage_mib: int = Field(ge=0)
    #: ``True`` = đo thật trên máy này; ``False`` = chép từ tài liệu upstream.
    #: Bake-off D04 cho thấy khoảng cách giữa hai loại số này là 34%.
    estimate_measured: bool = False
    estimate_measured_on: str = ""
    #: Số đo THẬT của lần chạy này. ``None`` = không quan sát được — **không phải
    #: 0**. Duix chạy trong container nên adapter không nhìn thấy VRAM đỉnh.
    peak_vram_mib: int | None = Field(default=None, ge=0)
    render_seconds: float | None = Field(default=None, ge=0.0)


class AvatarProvenanceRecord(BaseModel):
    """Truy vết một ``avatar.mp4`` về model, checkpoint và đầu vào đã sinh ra nó.

    Bản sao dạng pydantic của ``providers.base.AvatarProvenance``. Hai model tồn
    tại song song **có chủ đích**: ``domain/`` không được import ``providers/``
    (docs/ARCHITECTURE.md), đúng theo cặp ``CostQuote`` ↔ ``CostLine`` đã có.
    """

    model_config = ConfigDict(extra="forbid")

    backend_id: str = Field(min_length=1)
    backend_version: str = Field(min_length=1)
    model: str = Field(min_length=1)
    model_version: str = ""
    #: Bộ mã hoá tiếng — thứ quyết định chất lượng khẩu hình theo ngôn ngữ.
    audio_encoder: str = Field(min_length=1)
    #: Ngôn ngữ backend đã kiểm chứng. Đây là lý do trần khẩu hình tiếng Việt của
    #: Duix, ghi lại để sau này không phải đo lại mới biết.
    languages_verified: list[str] = Field(default_factory=list)
    native_fps: int = Field(gt=0)
    #: FPS thực sự dùng cho lần chạy này, có thể khác ``native_fps``.
    source_fps: int = Field(gt=0)
    #: Vân tay đầu vào/đầu ra. Rỗng = không có file lúc chạy, KHÔNG phải băm bịa.
    audio_sha256: str = ""
    source_asset_sha256: str = ""
    output_sha256: str = ""
    #: Rỗng khi trọng số nằm trong Docker image thay vì file checkpoint rời.
    checkpoint_sha256: str = ""
    image_digest: str = ""
    output_width: int = Field(gt=0)
    output_height: int = Field(gt=0)
    output_fps: int = Field(gt=0)
    output_duration_sec: float = Field(ge=0.0)
    #: Tham số inference thật, để tái lập.
    params: dict[str, str] = Field(default_factory=dict)
    resources: ResourceUsage | None = None


class RenderRecord(BaseModel):
    """Kết quả của một bước render, đủ để tái lập và đối chiếu."""

    model_config = ConfigDict(extra="forbid")

    stage: RenderStage
    shot_id: str | None = None
    provider: str
    model: str
    version: str
    mode: ProviderMode
    seed: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: StageStatus
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    actual_cost_usd: float | None = Field(default=None, ge=0.0)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    #: Provider này có TÍNH TIỀN tại thời điểm chạy hay không. Ghi lại vì cấu
    #: hình project có thể đổi sau đó; artifact đã trả tiền thì vẫn là artifact
    #: đã trả tiền, bất kể sau này project trỏ sang provider local.
    billable: bool = False
    #: Artifact này có bắt buộc người duyệt trước khi vào composer hay không.
    #: Cùng lý do: đây là tính chất **của run**, không phải của cấu hình hiện tại.
    requires_human_approval: bool = False
    #: ``True`` khi output do mock sinh ra — KHÔNG phải video/audio thật.
    is_placeholder: bool = False
    #: Chỉ có ở bước ``avatar``. Đặt tên theo bước thay vì ``provenance`` chung
    #: để sau này thêm ``tts_provenance`` không phải đoán khối này nói về cái gì.
    avatar_provenance: AvatarProvenanceRecord | None = None
    message: str = ""


class RenderManifest(BaseModel):
    """Toàn bộ nhật ký của một lần chạy ``aiva render``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    project_id: str
    run_id: str
    dry_run: bool = True
    provider_mode: ProviderMode = ProviderMode.MOCK
    storyboard_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: datetime = Field(default_factory=now_utc)
    finished_at: datetime | None = None
    #: ``awaiting_approval`` là tạm dừng có chủ đích khi B-roll trả phí chưa được
    #: người duyệt — cố ý tách khỏi ``failed`` để không bị đọc nhầm thành lỗi provider.
    status: Literal[
        "planned", "running", "succeeded", "failed", "awaiting_approval"
    ] = "planned"
    records: list[RenderRecord] = Field(default_factory=list)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    actual_cost_usd: float = Field(default=0.0, ge=0.0)
    ai_disclosure_applied: bool = False
    #: Phiên bản công cụ quan sát được lúc chạy, để tái lập môi trường.
    tool_versions: dict[str, str] = Field(default_factory=dict)
    outputs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def add(self, record: RenderRecord) -> None:
        self.records.append(record)

    @property
    def failed_records(self) -> list[RenderRecord]:
        return [r for r in self.records if r.status is StageStatus.FAILED]

    @property
    def has_placeholder_output(self) -> bool:
        return any(r.is_placeholder for r in self.records)

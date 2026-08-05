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
    #: ``True`` khi output do mock sinh ra — KHÔNG phải video/audio thật.
    is_placeholder: bool = False
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
    status: Literal["planned", "running", "succeeded", "failed"] = "planned"
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

"""``project.json`` — hợp đồng dữ liệu cấp project (brief §7)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ai_video_agent.clock import now_utc
from ai_video_agent.domain.enums import AspectRatio, ProjectState, ProviderMode
from ai_video_agent.domain.state import assert_transition

PROJECT_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{1,62}$"


class BudgetPolicy(BaseModel):
    """Trần ngân sách của project.

    Mặc định ``cap_usd = 0`` — nghĩa là **không đồng nào** được phép chi cho API
    tính tiền cho tới khi người dùng nâng trần một cách rõ ràng.
    """

    model_config = ConfigDict(extra="forbid")

    currency: Literal["USD"] = "USD"
    cap_usd: float = Field(default=0.0, ge=0.0)
    spent_usd: float = Field(default=0.0, ge=0.0)
    hard_stop: bool = True

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.cap_usd - self.spent_usd)


class AiDisclosure(BaseModel):
    """Nhãn nội dung AI (brief §4: video AI công khai phải có tuỳ chọn gắn nhãn)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    label_vi: str = "Nội dung có sử dụng AI"
    #: Nếu ``True``, composer khắc nhãn vào khung hình thay vì chỉ ghi metadata.
    burn_in: bool = True


class ProviderSelection(BaseModel):
    """Provider dự kiến cho từng khâu."""

    model_config = ConfigDict(extra="forbid")

    tts: str = "vieneu"
    avatar: str = "duix"
    #: ``none`` ở MVP; ``vimax``/``video_api`` chỉ mở ở D05.
    broll: str = "none"
    mode: ProviderMode = ProviderMode.MOCK
    #: ID tài sản giọng mẫu dùng để nhân bản. Khi bỏ trống, pipeline lấy tài sản
    #: ``voice_sample`` đầu tiên trong manifest — thứ tự đó đổi là giọng đổi
    #: thầm lặng, nên project đã chốt giọng thì PHẢI ghi rõ ID vào đây.
    voice_asset_id: str | None = None


class Approval(BaseModel):
    """Dấu vết phê duyệt kịch bản của người dùng."""

    model_config = ConfigDict(extra="forbid")

    approved_by: str
    approved_at: datetime
    #: Hash storyboard tại thời điểm duyệt. Storyboard đổi -> phê duyệt hết hiệu lực.
    storyboard_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    note: str = ""


class TransitionRecord(BaseModel):
    """Một bước chuyển trạng thái, phục vụ truy vết."""

    model_config = ConfigDict(extra="forbid")

    at: datetime
    from_state: ProjectState
    to_state: ProjectState
    reason: str = ""


class Project(BaseModel):
    """Trạng thái và chính sách của một project video."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    schema_version: Literal[1] = 1
    id: str = Field(pattern=PROJECT_ID_PATTERN)
    title: str = Field(min_length=1, max_length=200)
    brief_vi: str = Field(min_length=1)
    language: str = "vi"
    aspect_ratio: AspectRatio = AspectRatio.VERTICAL
    target_duration_sec: float = Field(gt=0.0, le=600.0)
    fps: int = Field(default=30, ge=24, le=60)

    budget: BudgetPolicy = Field(default_factory=BudgetPolicy)
    providers: ProviderSelection = Field(default_factory=ProviderSelection)
    ai_disclosure: AiDisclosure = Field(default_factory=AiDisclosure)

    state: ProjectState = ProjectState.DRAFT
    approval: Approval | None = None

    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
    history: list[TransitionRecord] = Field(default_factory=list)

    def transition_to(
        self,
        target: ProjectState,
        *,
        reason: str = "",
        at: datetime | None = None,
    ) -> None:
        """Chuyển trạng thái sau khi kiểm tra tính hợp lệ.

        Ném :class:`~ai_video_agent.errors.InvalidTransitionError` nếu cạnh sai.
        """
        assert_transition(self.state, target)
        moment = at or now_utc()
        record = TransitionRecord(at=moment, from_state=self.state, to_state=target, reason=reason)
        self.state = target
        self.updated_at = moment
        self.history = [*self.history, record]

    def approval_matches(self, storyboard_sha256: str) -> bool:
        """``True`` nếu phê duyệt hiện tại còn đúng với storyboard đang có."""
        return self.approval is not None and self.approval.storyboard_sha256 == storyboard_sha256

    def revoke_approval(self, *, reason: str = "storyboard changed") -> None:
        """Gỡ phê duyệt và đưa project về ``PLANNED``."""
        self.approval = None
        if self.state is not ProjectState.PLANNED:
            self.transition_to(ProjectState.PLANNED, reason=reason)

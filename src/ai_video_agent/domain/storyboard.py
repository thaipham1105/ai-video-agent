"""``storyboard.json`` — scene/shot, thoại, hình minh hoạ, thời lượng, provider."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ai_video_agent.clock import now_utc
from ai_video_agent.domain.enums import AspectRatio, BrollKind, OnScreenTextKind, SceneRole


class OnScreenText(BaseModel):
    """Chữ hiển thị trên khung hình.

    ``exact = True`` nghĩa là chuỗi này **phải** do composer chèn bằng FFmpeg,
    tuyệt đối không giao cho model sinh video tự vẽ (brief §D04.2). Số điện
    thoại, giá và câu chữ pháp lý luôn thuộc nhóm này.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    kind: OnScreenTextKind = OnScreenTextKind.GENERIC
    start_offset_sec: float = Field(default=0.0, ge=0.0)
    duration_sec: float | None = Field(default=None, gt=0.0)
    exact: bool = True


class BrollPlan(BaseModel):
    """Nguồn hình minh hoạ dự kiến cho một shot."""

    model_config = ConfigDict(extra="forbid")

    kind: BrollKind = BrollKind.NONE
    #: Trỏ tới ``AssetEntry.id`` khi ``kind = local_asset``.
    asset_id: str | None = None
    #: Mô tả tiếng Việt khi dùng provider sinh video (chỉ mở ở D05).
    prompt_vi: str | None = None
    notes: str = ""


class Shot(BaseModel):
    """Đơn vị render nhỏ nhất. Có thể render lại riêng lẻ."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,62}$")
    order: int = Field(ge=0)
    duration_sec: float = Field(gt=0.0, le=120.0)
    narration_vi: str = Field(min_length=1)
    on_screen_text: list[OnScreenText] = Field(default_factory=list)
    broll: BrollPlan = Field(default_factory=BrollPlan)
    #: Provider dự kiến cho khâu avatar của shot này.
    provider_hint: str = "duix"
    subtitle: bool = True
    #: ID tài sản audio đã được duyệt sẵn cho lời thoại này. Khi có giá trị,
    #: pipeline **bỏ qua TTS** và dùng đúng file đó. Dùng khi người dùng đã nghe
    #: và chốt một bản thu — sinh lại sẽ ra giọng khác vì TTS có lấy mẫu ngẫu nhiên.
    narration_audio_asset_id: str | None = None

    def content_hash(self) -> str:
        """Hash nội dung ảnh hưởng tới kết quả render của shot.

        Dùng làm khoá cache: sửa thoại/chữ/thời lượng thì hash đổi và shot sẽ
        được render lại; sửa thứ khác thì artifact cũ vẫn dùng được.
        """
        payload = {
            "narration_vi": self.narration_vi,
            "duration_sec": round(self.duration_sec, 3),
            "on_screen_text": [t.model_dump(mode="json") for t in self.on_screen_text],
            "broll": self.broll.model_dump(mode="json"),
            "provider_hint": self.provider_hint,
        }
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class Scene(BaseModel):
    """Nhóm shot cùng mục đích kể chuyện."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,62}$")
    title: str = Field(min_length=1)
    role: SceneRole = SceneRole.BODY
    shots: list[Shot] = Field(min_length=1)

    @property
    def duration_sec(self) -> float:
        return round(sum(shot.duration_sec for shot in self.shots), 3)


class Storyboard(BaseModel):
    """Kịch bản đã cấu trúc hoá, là đầu vào của toàn bộ pipeline render."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    project_id: str
    created_at: datetime = Field(default_factory=now_utc)
    language: str = "vi"
    aspect_ratio: AspectRatio = AspectRatio.VERTICAL
    scenes: list[Scene] = Field(min_length=1)

    @property
    def total_duration_sec(self) -> float:
        return round(sum(scene.duration_sec for scene in self.scenes), 3)

    @property
    def shots(self) -> list[Shot]:
        """Toàn bộ shot theo đúng thứ tự trình chiếu."""
        return [shot for scene in self.scenes for shot in scene.shots]

    def iter_shots(self) -> Iterator[tuple[Scene, Shot]]:
        for scene in self.scenes:
            for shot in scene.shots:
                yield scene, shot

    def find_shot(self, shot_id: str) -> Shot | None:
        return next((shot for shot in self.shots if shot.id == shot_id), None)

    @property
    def narration_chars(self) -> int:
        return sum(len(shot.narration_vi) for shot in self.shots)

    def sha256(self) -> str:
        """Hash ổn định của toàn bộ storyboard, dùng để neo phê duyệt.

        ``created_at`` bị loại khỏi hash để việc ghi lại file không làm mất hiệu
        lực phê duyệt khi nội dung không đổi.
        """
        payload = self.model_dump(mode="json", exclude={"created_at"})
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

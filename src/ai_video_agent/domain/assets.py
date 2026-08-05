"""``asset-manifest.json`` — nguồn gốc và quyền sử dụng tài sản.

Brief §4 và §7: mọi hình ảnh/giọng nói phải ghi nhận **chủ sở hữu** và **trạng
thái đồng ý sử dụng**. Cost guard sẽ chặn render thật nếu còn tài sản chưa có
đồng ý.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_video_agent.domain.enums import AssetKind, ConsentStatus

_CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    """SHA-256 của một file, đọc theo khối để không nạp cả file vào RAM."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


class Consent(BaseModel):
    """Bằng chứng cho phép sử dụng tài sản.

    ``evidence_ref`` chỉ là **con trỏ** (mã hồ sơ, tên file giấy đồng ý nằm ngoài
    repo). Không bao giờ nhúng nội dung bằng chứng vào đây.
    """

    model_config = ConfigDict(extra="forbid")

    status: ConsentStatus = ConsentStatus.PENDING
    owner: str = Field(min_length=1)
    granted_by: str | None = None
    granted_at: datetime | None = None
    scope: str = ""
    evidence_ref: str = ""

    @property
    def usable(self) -> bool:
        return self.status.usable


class AssetEntry(BaseModel):
    """Một tài sản đầu vào (giọng mẫu, video avatar, logo, nhạc, font…)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,62}$")
    #: Đường dẫn **tương đối** so với thư mục assets của project (brief §7).
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    kind: AssetKind
    bytes: int = Field(ge=0)
    consent: Consent
    source: str = ""
    notes: str = ""

    @field_validator("path")
    @classmethod
    def _reject_absolute_or_escaping(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        pure = PurePosixPath(normalized)
        if (
            pure.is_absolute()
            or ".." in pure.parts
            or (len(normalized) > 1 and normalized[1] == ":")
        ):
            msg = f"path phải là đường dẫn tương đối, không thoát khỏi thư mục assets: {value!r}"
            raise ValueError(msg)
        return normalized


class AssetManifest(BaseModel):
    """Danh mục tài sản của một project."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    project_id: str
    assets: list[AssetEntry] = Field(default_factory=list)

    def get(self, asset_id: str) -> AssetEntry | None:
        return next((asset for asset in self.assets if asset.id == asset_id), None)

    def blocking(self) -> list[AssetEntry]:
        """Tài sản chưa được phép dùng — chặn mọi lần render thật."""
        return [asset for asset in self.assets if not asset.consent.usable]

    def of_kind(self, kind: AssetKind) -> list[AssetEntry]:
        return [asset for asset in self.assets if asset.kind is kind]

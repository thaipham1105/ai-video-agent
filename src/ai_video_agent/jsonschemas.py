"""Kiểm tra dữ liệu theo 4 JSON Schema trong ``schemas/``.

Model pydantic và JSON Schema được viết **độc lập** với nhau một cách có chủ ý:
schema là hợp đồng đối ngoại, model là hiện thực. Test đối chiếu hai bên nên mọi
sai lệch (drift) sẽ lộ ra ngay thay vì âm thầm trôi đi.
"""

from __future__ import annotations

import json
from enum import StrEnum
from functools import cache
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from ai_video_agent.errors import ValidationError
from ai_video_agent.paths import schemas_dir


class SchemaName(StrEnum):
    """Tên 4 hợp đồng dữ liệu bắt buộc (brief §7)."""

    PROJECT = "project"
    STORYBOARD = "storyboard"
    ASSET_MANIFEST = "asset-manifest"
    RENDER_MANIFEST = "render-manifest"

    @property
    def filename(self) -> str:
        return f"{self.value}.schema.json"


@cache
def load_schema(name: SchemaName) -> dict[str, Any]:
    """Nạp một JSON Schema từ đĩa (có cache)."""
    path = schemas_dir() / name.filename
    if not path.is_file():
        msg = f"Thiếu schema: {path}"
        raise ValidationError(msg)
    with path.open(encoding="utf-8") as handle:
        data: dict[str, Any] = json.load(handle)
    return data


@cache
def validator_for(name: SchemaName) -> Draft202012Validator:
    """Validator draft 2020-12 kèm kiểm tra ``format: date-time``."""
    return Draft202012Validator(load_schema(name), format_checker=FormatChecker())


def iter_errors(name: SchemaName, payload: Any) -> list[str]:
    """Danh sách lỗi dạng chuỗi đọc được, rỗng nếu hợp lệ."""
    validator = validator_for(name)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.absolute_path))
    return [
        f"{'/'.join(str(part) for part in err.absolute_path) or '<root>'}: {err.message}"
        for err in errors
    ]


def validate(name: SchemaName, payload: Any) -> None:
    """Ném :class:`ValidationError` kèm toàn bộ lỗi nếu ``payload`` không hợp lệ."""
    errors = iter_errors(name, payload)
    if errors:
        detail = "\n  - ".join(errors)
        msg = f"Dữ liệu không khớp schema '{name.value}':\n  - {detail}"
        raise ValidationError(msg)

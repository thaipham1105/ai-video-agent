"""Định vị thư mục gốc của repo và thư mục ``schemas/``.

``schemas/`` nằm ở gốc repo (theo cấu trúc bắt buộc trong brief §6) chứ không
nằm trong package, nên cần một hàm dò tìm thay vì đường dẫn cứng.
"""

from __future__ import annotations

import os
from pathlib import Path

from ai_video_agent.errors import ConfigError

_MARKER = Path("schemas") / "project.schema.json"


def _has_marker(candidate: Path) -> bool:
    return (candidate / _MARKER).is_file()


def repo_root() -> Path:
    """Thư mục gốc của repo AI-VIDEO-AGENT.

    Thứ tự ưu tiên: biến ``AIVA_REPO_ROOT`` → đi ngược từ vị trí module →
    đi ngược từ thư mục làm việc hiện tại.
    """
    override = os.environ.get("AIVA_REPO_ROOT")
    if override:
        candidate = Path(override).resolve()
        if _has_marker(candidate):
            return candidate
        msg = f"AIVA_REPO_ROOT={candidate} không chứa {_MARKER.as_posix()}"
        raise ConfigError(msg)

    for start in (Path(__file__).resolve(), Path.cwd().resolve()):
        for candidate in (start, *start.parents):
            if _has_marker(candidate):
                return candidate

    msg = (
        "Không tìm thấy thư mục gốc repo (cần có schemas/project.schema.json). "
        "Chạy lệnh từ trong repo hoặc đặt biến AIVA_REPO_ROOT."
    )
    raise ConfigError(msg)


def schemas_dir() -> Path:
    """Thư mục chứa 4 JSON Schema là hợp đồng dữ liệu."""
    return repo_root() / "schemas"


#: Tên thư mục chứa file đối chứng đã được PO chốt. Không được ghi vào đây.
#: `giong-toi-A-mo-dau.wav` là golden reference của D02; ghi đè nó là mất luôn
#: cơ sở để đối chiếu mọi thay đổi về sau.
PROTECTED_DIR_NAMES: frozenset[str] = frozenset({"giu-lai"})


def is_protected(path: Path) -> bool:
    """``True`` nếu đường dẫn nằm trong thư mục đối chứng được bảo vệ."""
    return any(part in PROTECTED_DIR_NAMES for part in Path(path).parts)


def assert_writable(path: Path) -> None:
    """Chặn mọi lệnh ghi vào thư mục đối chứng.

    Đây là hàng rào cứng cho yêu cầu "tuyệt đối không ghi đè golden reference".
    """
    if is_protected(path):
        protected = ", ".join(sorted(PROTECTED_DIR_NAMES))
        msg = (
            f"Từ chối ghi vào {path}: nằm trong thư mục đối chứng được bảo vệ "
            f"({protected}). File đối chứng của PO không được ghi đè."
        )
        raise ConfigError(msg)

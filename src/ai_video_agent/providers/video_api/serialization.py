"""Chuẩn hoá usage metadata của SDK về JSON an toàn.

Bối cảnh: ở D05-B, ``json.dumps`` chết với
``TypeError: Object of type ModalityTokens is not JSON serializable`` **sau khi**
video đã tải xong. Video vẫn còn, nhưng đối tượng usage do API trả về thì mất —
nên chi phí phải suy ra từ thời lượng thay vì đọc số thật.

Bài học được mã hoá ở đây: *thứ đã tốn tiền phải chạm đĩa trước mọi bước có thể
hỏng*, và **lỗi ghi báo cáo không bao giờ được phép làm mất kết quả đã lưu**.

Cố ý **không** giả định Veo trả cùng kiểu usage với Omni Flash: đó là hai đường
API khác nhau (``models.generate_videos`` so với ``interactions.create``).
"""

from __future__ import annotations

import enum
import json
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

#: Chặn đệ quy vô hạn với đối tượng tự tham chiếu.
_MAX_DEPTH = 12


def normalize(obj: object, *, _depth: int = 0) -> object:
    """Đổi một đối tượng bất kỳ của SDK sang cấu trúc JSON được.

    Thứ tự thử, từ cụ thể nhất tới tổng quát nhất:

    1. ``model_dump(mode="json")`` — pydantic, thứ ``google-genai`` đang dùng.
    2. ``asdict`` — dataclass.
    3. Enum, Decimal, Path, kiểu nguyên thuỷ, dict/list.
    4. ``vars()`` — object thường.
    5. ``str()`` — lưới cuối, không bao giờ ném lỗi.
    """
    if _depth > _MAX_DEPTH:
        return f"<quá sâu: {type(obj).__name__}>"

    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, enum.Enum):
        return normalize(obj.value, _depth=_depth + 1)
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (bytes, bytearray)):
        return f"<{len(obj)} bytes>"

    # pydantic — đường chính của google-genai
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            return normalize(dump(mode="json"), _depth=_depth + 1)
        except Exception:  # noqa: BLE001 - rơi xuống cách kế tiếp
            try:
                return normalize(dump(), _depth=_depth + 1)
            except Exception:  # noqa: BLE001, S110 - cố tình im lặng, còn cách khác phía dưới
                pass

    if is_dataclass(obj) and not isinstance(obj, type):
        try:
            return normalize(asdict(obj), _depth=_depth + 1)
        except Exception:  # noqa: BLE001, S110 - cố tình im lặng, còn cách khác phía dưới
            pass

    if isinstance(obj, dict):
        return {str(k): normalize(v, _depth=_depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [normalize(v, _depth=_depth + 1) for v in obj]

    attrs = getattr(obj, "__dict__", None)
    if isinstance(attrs, dict) and attrs:
        return {
            str(k): normalize(v, _depth=_depth + 1)
            for k, v in attrs.items()
            if not str(k).startswith("_")
        }

    return str(obj)


def to_json_text(obj: object) -> str:
    """Sinh JSON từ bất kỳ đối tượng nào. **Không bao giờ ném lỗi.**"""
    try:
        return json.dumps(normalize(obj), indent=2, ensure_ascii=False)
    except Exception:  # noqa: BLE001 - lưới cuối cùng
        return json.dumps({"_unserializable": str(obj)}, indent=2, ensure_ascii=False)


def write_usage_safely(
    *,
    raw_usage: object,
    raw_path: Path,
    normalized_path: Path,
) -> dict[str, Any]:
    """Ghi usage ra đĩa sao cho không bước nào có thể làm mất kết quả đã trả tiền.

    Ghi ``repr`` thô **trước**. Nếu bước chuẩn hoá hỏng, dữ liệu tính tiền vẫn
    còn trên đĩa để đối chiếu thủ công.

    Trả về báo cáo về chính việc ghi — bản thân hàm này không ném lỗi ra ngoài.
    """
    report: dict[str, Any] = {"raw_written": False, "normalized_written": False, "error": None}

    try:
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(repr(raw_usage), encoding="utf-8")
        report["raw_written"] = True
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"ghi raw hỏng: {type(exc).__name__}: {exc}"

    try:
        normalized_path.parent.mkdir(parents=True, exist_ok=True)
        normalized_path.write_text(to_json_text(raw_usage), encoding="utf-8")
        report["normalized_written"] = True
    except Exception as exc:  # noqa: BLE001
        previous = report["error"]
        detail = f"ghi normalized hỏng: {type(exc).__name__}: {exc}"
        report["error"] = f"{previous}; {detail}" if previous else detail

    return report

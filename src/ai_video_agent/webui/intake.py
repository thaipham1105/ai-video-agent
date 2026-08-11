"""Nhận file người dùng tải lên, an toàn theo mặc định.

Nguyên tắc gốc: **tên file của người dùng không bao giờ trở thành đường dẫn.**
Lọc ``..`` rồi vẫn ghép tên vào đường dẫn là trò đuổi bắt không bao giờ thắng
(``..\\``, ``%2e%2e``, NTFS ADS ``a.mp4:x``, tên dành riêng của Windows như
``CON``/``NUL``, unicode nhìn giống dấu gạch chéo…). Ở đây tên đích **do ta sinh
ra**: ``<uuid4>.<đuôi đã whitelist>``. Không có gì của người dùng lọt vào đường
dẫn, nên duyệt thư mục là chuyện bất khả thi về mặt cấu trúc chứ không phải nhờ
bộ lọc.

Đuôi file cũng theo whitelist, không blacklist: danh sách cấm luôn thiếu một cái.
"""

from __future__ import annotations

import contextlib
import re
import shutil
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING

from ai_video_agent.domain.project import PROJECT_ID_PATTERN
from ai_video_agent.errors import ValidationError

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import BinaryIO

#: Định dạng Duix nhận làm nguồn avatar. Phải là **video**, không phải ảnh —
#: capability của Duix khai ``accepts_image_source=False``.
AVATAR_SUFFIXES = frozenset({".mp4", ".mov", ".mkv", ".webm", ".m4v"})

#: Định dạng ffprobe đọc được để làm mẫu giọng.
VOICE_SUFFIXES = frozenset({".wav", ".mp3", ".flac", ".m4a", ".ogg", ".opus"})

#: Nơi file tải lên đáp xuống trước khi ``avatar-add``/``voice-add`` nhận. Nằm
#: dưới ``AIVA_RUNTIME_DIR``, không phải thư mục tạm của hệ điều hành và tuyệt
#: đối không phải trong repo (AGENTS.md).
STAGING_DIRNAME = "_uploads"

_PROJECT_ID = re.compile(PROJECT_ID_PATTERN)


def check_project_id(project_id: str) -> str:
    """Chỉ nhận đúng dạng ``Project.id`` đã ràng ở pydantic.

    Kiểm **ở đây nữa** dù model cũng ràng: chuỗi này đi vào đường dẫn thư mục
    trước khi có model nào được dựng, nên nó là dữ liệu vào cần lọc, không phải
    giá trị đã được tin.
    """
    if not _PROJECT_ID.fullmatch(project_id):
        msg = (
            f"Project ID không hợp lệ: {project_id!r}. Chỉ nhận chữ thường, số và "
            "dấu gạch ngang, dài 2 tới 63 ký tự."
        )
        raise ValidationError(msg)
    return project_id


def safe_suffix(filename: str, allowed: Iterable[str]) -> str:
    """Lấy đuôi file, **chỉ** để chọn trong whitelist. Không dùng phần tên còn lại.

    Tách bằng cả hai kiểu đường dẫn: trình duyệt trên Windows có thể gửi
    ``C:\\quay\\a.mp4`` còn nơi khác gửi ``/tmp/a.mp4``.
    """
    hop_le = {s.lower() for s in allowed}
    tho = (filename or "").strip()
    if "\x00" in tho:
        msg = "Tên file chứa ký tự NUL."
        raise ValidationError(msg)
    ten = PureWindowsPath(PurePosixPath(tho).name).name
    duoi = Path(ten).suffix.lower()
    if duoi not in hop_le:
        msg = (
            f"Định dạng không nhận: {duoi or '(không có đuôi)'}. "
            f"Chỉ nhận: {', '.join(sorted(hop_le))}."
        )
        raise ValidationError(msg)
    return duoi


def staging_dir(runtime_dir: Path) -> Path:
    return runtime_dir / STAGING_DIRNAME


def stage_upload(
    runtime_dir: Path, *, filename: str, stream: BinaryIO, allowed: Iterable[str]
) -> Path:
    """Ghi luồng tải lên xuống một tên **do ta sinh**, trả về đường dẫn đó.

    Tên đích không mượn một ký tự nào từ ``filename`` ngoài phần đuôi đã được
    whitelist — nên không có đầu vào nào của người dùng ảnh hưởng tới vị trí ghi.
    """
    duoi = safe_suffix(filename, allowed)
    dich_thu_muc = staging_dir(runtime_dir)
    dich_thu_muc.mkdir(parents=True, exist_ok=True)
    dich = dich_thu_muc / f"{uuid.uuid4().hex}{duoi}"
    with dich.open("wb") as ra:
        shutil.copyfileobj(stream, ra)
    return dich


def discard(path: Path) -> None:
    """Xoá file trung chuyển sau khi đã đăng ký vào project.

    Nuốt lỗi: file rác trong ``_uploads`` là phiền, còn làm hỏng một lượt đăng
    ký thành công vì không xoá được file tạm thì tệ hơn.
    """
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)

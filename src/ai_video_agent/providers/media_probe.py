"""Đo thông số media **từ file thật**, dùng chung cho mọi avatar provider.

Vì sao có module này thay vì để mỗi adapter tự khai: một adapter ghi vào
provenance con số **nó yêu cầu** thay vì con số **file thật có** là đủ để làm
hỏng cả một đợt đo. Lượt ``f16bd2a245d4`` của D04-G bị huỷ đúng vì thế
(MuseTalk), rồi lượt ``2b11f490b425`` của D05-B lộ ra Duix mắc y hệt: nguồn
25 fps, manifest khai 30 vì đọc từ cấu hình.

Cùng một cái bẫy, hai adapter độc lập ⇒ để một bản cho cả hai dùng.
"""

from __future__ import annotations

import math
from pathlib import Path

from ai_video_agent.errors import ProviderError

#: Wrapper ffprobe **đã có sẵn** của repo. Dùng lại thay vì viết bản thứ hai —
#: hai bản sẽ trôi khỏi nhau.
from ai_video_agent.qc.broll import _probe as _ffprobe_entries


def probe_entries(ffprobe_bin: str, path: Path, entries: str, stream: str | None) -> str:
    """Gọi wrapper ffprobe và biến **mọi** lỗi thành ``ProviderError``.

    ``qc.broll._run`` không bắt ``OSError``, nên thiếu binary ffprobe sẽ ném
    ``FileNotFoundError`` xuyên thẳng ra ngoài. Hợp đồng đòi lỗi provider là
    ``ProviderError``; để OSError thô lọt ra là buộc người đọc log tự lần.
    """
    try:
        return _ffprobe_entries(ffprobe_bin, path, entries, stream=stream)
    except OSError as exc:
        msg = (
            f"Không chạy được {ffprobe_bin!r} để đo {path}: {exc}. "
            "Adapter không tự cài công cụ."
        )
        raise ProviderError(msg) from exc


def probe_video_fps(ffprobe_bin: str, path: Path) -> tuple[int, str]:
    """fps **đo từ file**, trả ``(số nguyên đã làm tròn, tỷ số thô)``.

    Giữ cả tỷ số thô (``30000/1001``) vì làm tròn về int là mất thông tin, mà
    schema manifest lại chỉ nhận int.
    """
    raw = probe_entries(ffprobe_bin, path, "stream=r_frame_rate", "v:0").strip()
    first = raw.splitlines()[0].strip() if raw else ""
    if "/" not in first:
        msg = f"Không đọc được fps từ {path} (ffprobe trả {raw!r})."
        raise ProviderError(msg)
    num, den = first.split("/", 1)
    try:
        value = float(num) / float(den)
    except (ValueError, ZeroDivisionError) as exc:
        msg = f"fps không hợp lệ từ {path}: {first!r}."
        raise ProviderError(msg) from exc
    if not math.isfinite(value) or value <= 0:
        msg = f"fps không hợp lệ từ {path}: {value!r}."
        raise ProviderError(msg)
    return round(value), first

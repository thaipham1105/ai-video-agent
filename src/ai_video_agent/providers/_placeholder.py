"""Tiện ích ghi artifact giả cho các provider mock.

Ràng buộc của D01: mock phải chạy được **toàn bộ** đường đi mà không tải model,
không dùng GPU và không cần FFmpeg. Vì vậy:

* Audio giả là file WAV **thật và hợp lệ** (im lặng), dựng bằng module ``wave``
  của thư viện chuẩn — nhờ đó thời lượng và sample rate kiểm tra được thật sự.
* Video giả chỉ là file đánh dấu, vì không thể tạo MP4 hợp lệ khi chưa có FFmpeg.
  Mọi file giả đều mang đuôi ``.mock.*`` và được đánh ``is_placeholder = True``
  trong ``render-manifest.json`` để không ai nhầm với sản phẩm thật.
"""

from __future__ import annotations

import json
import wave
from pathlib import Path
from typing import Any

#: Chữ ký ở đầu file video giả, giúp nhận ra ngay khi mở bằng editor.
MOCK_VIDEO_MAGIC = b"AIVA-MOCK-VIDEO-v1\n"

_SAMPLE_WIDTH_BYTES = 2  # PCM 16-bit
_MAX_SILENCE_CHUNK = 1 << 16


def write_silent_wav(
    path: Path,
    *,
    duration_sec: float,
    sample_rate: int = 48_000,
    channels: int = 1,
) -> int:
    """Ghi một file WAV im lặng hợp lệ. Trả về số frame đã ghi."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = max(1, round(duration_sec * sample_rate))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(_SAMPLE_WIDTH_BYTES)
        handle.setframerate(sample_rate)
        remaining = frames
        block = b"\x00" * (_SAMPLE_WIDTH_BYTES * channels * _MAX_SILENCE_CHUNK)
        while remaining > 0:
            take = min(remaining, _MAX_SILENCE_CHUNK)
            handle.writeframes(block[: _SAMPLE_WIDTH_BYTES * channels * take])
            remaining -= take
    return frames


def read_wav_duration(path: Path) -> float:
    """Đọc thời lượng thật của một file WAV (giây)."""
    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        frames = handle.getnframes()
    if rate <= 0:
        return 0.0
    return round(frames / rate, 3)


def write_placeholder_video(path: Path, metadata: dict[str, Any]) -> int:
    """Ghi file video giả kèm metadata đọc được. Trả về số byte đã ghi."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    payload = MOCK_VIDEO_MAGIC + body + b"\n"
    path.write_bytes(payload)
    return len(payload)


def is_placeholder_video(path: Path) -> bool:
    """``True`` nếu file là video giả do mock sinh ra."""
    if not path.is_file():
        return False
    with path.open("rb") as handle:
        return handle.read(len(MOCK_VIDEO_MAGIC)) == MOCK_VIDEO_MAGIC

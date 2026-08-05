"""Sinh phụ đề SRT tiếng Việt từ storyboard và thời lượng audio thật.

Thời lượng lấy từ WAV do TTS sinh ra chứ không từ con số dự kiến trong
storyboard, nên phụ đề luôn khớp với tiếng nói kể cả khi TTS đọc nhanh/chậm hơn
kế hoạch.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

#: Giới hạn dễ đọc trên màn hình dọc: 2 dòng, mỗi dòng ~42 ký tự.
MAX_CHARS_PER_LINE = 42
MAX_LINES = 2
MAX_CHARS_PER_CUE = MAX_CHARS_PER_LINE * MAX_LINES

#: Khoảng hở nhỏ giữa hai cue để chữ không dính vào nhau khi chuyển.
CUE_GAP_SEC = 0.04
MIN_CUE_SEC = 0.6


@dataclass(frozen=True)
class SubtitleCue:
    """Một dòng phụ đề đã có mốc thời gian tuyệt đối."""

    index: int
    start_sec: float
    end_sec: float
    text: str

    @property
    def duration_sec(self) -> float:
        return round(self.end_sec - self.start_sec, 3)


def format_timestamp(seconds: float) -> str:
    """Định dạng mốc thời gian SRT: ``HH:MM:SS,mmm``."""
    clamped = max(0.0, seconds)
    total_ms = round(clamped * 1000)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def wrap_text(text: str, *, max_chars: int = MAX_CHARS_PER_LINE, max_lines: int = MAX_LINES) -> str:
    """Ngắt dòng theo từ, không cắt giữa từ tiếng Việt."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
            if len(lines) == max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    return "\n".join(lines)


def split_for_cues(text: str, *, max_chars: int = MAX_CHARS_PER_CUE) -> list[str]:
    """Chia một đoạn thoại dài thành nhiều cue vừa màn hình."""
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars or not current:
            current = candidate
        else:
            chunks.append(current)
            current = word
    if current:
        chunks.append(current)
    return chunks


def build_cues(
    segments: Sequence[tuple[str, float]], *, start_at: float = 0.0
) -> list[SubtitleCue]:
    """Dựng danh sách cue từ các cặp ``(thoại, thời lượng thật tính bằng giây)``.

    Trong một shot, thời gian được chia theo độ dài chữ của từng cue nên tốc độ
    chữ chạy bám sát tốc độ đọc.
    """
    cues: list[SubtitleCue] = []
    cursor = start_at
    index = 1

    for text, duration in segments:
        shot_end = cursor + duration
        chunks = split_for_cues(text)
        if not chunks:
            cursor = shot_end
            continue

        weights = [max(1, len(chunk)) for chunk in chunks]
        total_weight = sum(weights)
        local_start = cursor

        for chunk, weight in zip(chunks, weights, strict=True):
            span = duration * weight / total_weight
            local_end = min(shot_end, local_start + span)
            if local_end - local_start < MIN_CUE_SEC:
                local_end = min(shot_end, local_start + MIN_CUE_SEC)
            cues.append(
                SubtitleCue(
                    index=index,
                    start_sec=round(local_start, 3),
                    end_sec=round(max(local_start, local_end - CUE_GAP_SEC), 3),
                    text=wrap_text(chunk),
                )
            )
            index += 1
            local_start = local_end

        cursor = shot_end

    return cues


def render_srt(cues: Iterable[SubtitleCue]) -> str:
    """Kết xuất nội dung file ``.srt`` (UTF-8, xuống dòng kiểu LF)."""
    blocks = [
        f"{cue.index}\n"
        f"{format_timestamp(cue.start_sec)} --> {format_timestamp(cue.end_sec)}\n"
        f"{cue.text}"
        for cue in cues
    ]
    return "\n\n".join(blocks) + "\n" if blocks else ""


def write_srt(path: Path, cues: Iterable[SubtitleCue]) -> Path:
    """Ghi file SRT bằng UTF-8 để hiển thị đúng dấu tiếng Việt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_srt(cues), encoding="utf-8", newline="\n")
    return path

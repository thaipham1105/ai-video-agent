"""Ghép video: phụ đề, chữ chính xác, logo, nhãn AI.

Nguyên tắc quan trọng nhất của gói này (brief §D04.2): **chữ chính xác — số điện
thoại, giá, câu chữ pháp lý — do FFmpeg chèn**, không bao giờ giao cho model
sinh video tự vẽ.
"""

from __future__ import annotations

from ai_video_agent.composer.audio import WavReport, inspect_wav
from ai_video_agent.composer.ffmpeg import (
    ComposeSpec,
    DrawTextSpec,
    build_compose_command,
    build_concat_file,
)
from ai_video_agent.composer.subtitles import (
    SubtitleCue,
    build_cues,
    format_timestamp,
    render_srt,
    write_srt,
)

__all__ = [
    "ComposeSpec",
    "DrawTextSpec",
    "SubtitleCue",
    "WavReport",
    "build_compose_command",
    "build_concat_file",
    "build_cues",
    "format_timestamp",
    "inspect_wav",
    "render_srt",
    "write_srt",
]

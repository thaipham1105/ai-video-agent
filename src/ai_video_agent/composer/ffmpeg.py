"""Dựng lệnh FFmpeg. **Module này không bao giờ thực thi lệnh.**

Tách "dựng lệnh" khỏi "chạy lệnh" cho phép kiểm thử đầy đủ chuỗi tham số ở D01
trên máy chưa cài FFmpeg. Việc thực thi được mở ở D04 (xem AGENTS.md).

Cấu hình xuất bản nhắm tới Facebook / TikTok / Zalo (brief §D04.4): H.264 High
profile, ``yuv420p``, AAC-LC, ``+faststart``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

#: Ký tự phải escape trong giá trị tham số của filter FFmpeg.
_FILTER_ESCAPES = {
    "\\": r"\\",
    ":": r"\:",
    "'": r"\'",
    "[": r"\[",
    "]": r"\]",
    ",": r"\,",
    ";": r"\;",
}


def escape_filter_value(text: str) -> str:
    """Escape một chuỗi để nhúng an toàn vào filtergraph."""
    return "".join(_FILTER_ESCAPES.get(ch, ch) for ch in text)


def escape_filter_path(path: Path | str) -> str:
    """Escape đường dẫn Windows cho filter ``subtitles``/``ass``.

    FFmpeg đọc đường dẫn trong filtergraph theo cú pháp riêng: dấu ``\\`` phải
    đổi thành ``/`` và dấu ``:`` sau tên ổ đĩa phải được escape, nếu không
    ``C:\\video.mp4`` sẽ bị hiểu là hai tham số.
    """
    text = str(path).replace("\\", "/")
    return text.replace(":", r"\:").replace("'", r"\'")


@dataclass(frozen=True)
class DrawTextSpec:
    """Một lớp chữ do composer chèn (số điện thoại, giá, pháp lý, nhãn AI)."""

    text: str
    x: str = "(w-text_w)/2"
    y: str = "h-text_h-180"
    font_size: int = 54
    font_color: str = "white"
    box: bool = True
    box_color: str = "black@0.55"
    box_border: int = 18
    start_sec: float | None = None
    end_sec: float | None = None
    font_file: Path | None = None

    def to_filter(self) -> str:
        parts = [
            f"text='{escape_filter_value(self.text)}'",
            f"x={self.x}",
            f"y={self.y}",
            f"fontsize={self.font_size}",
            f"fontcolor={self.font_color}",
        ]
        if self.font_file is not None:
            parts.append(f"fontfile='{escape_filter_path(self.font_file)}'")
        if self.box:
            parts.extend(["box=1", f"boxcolor={self.box_color}", f"boxborderw={self.box_border}"])
        if self.start_sec is not None or self.end_sec is not None:
            start = self.start_sec if self.start_sec is not None else 0.0
            condition = f"gte(t,{start:.3f})"
            if self.end_sec is not None:
                condition = f"between(t,{start:.3f},{self.end_sec:.3f})"
            parts.append(f"enable='{condition}'")
        return "drawtext=" + ":".join(parts)


@dataclass(frozen=True)
class ComposeSpec:
    """Mọi thứ cần để dựng một lệnh ghép video hoàn chỉnh."""

    concat_file: Path
    output: Path
    width: int
    height: int
    fps: int = 30
    audio: Path | None = None
    subtitles: Path | None = None
    logo: Path | None = None
    logo_margin: int = 40
    draw_texts: list[DrawTextSpec] = field(default_factory=list)
    ffmpeg_bin: str = "ffmpeg"
    crf: int = 20
    preset: str = "medium"
    audio_bitrate: str = "192k"
    overwrite: bool = True
    subtitle_style: str = (
        "FontName=Arial,FontSize=18,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H80000000,BorderStyle=3,Outline=2,Shadow=0,MarginV=90"
    )


#: Font ưu tiên cho ``drawtext``, theo thứ tự. Đều có sẵn trên Windows và đều
#: đủ dấu tiếng Việt. Bắt buộc phải chỉ font tường minh: bản FFmpeg cho Windows
#: dùng fontconfig, mà máy Windows không có file cấu hình fontconfig mặc định —
#: thiếu nó thì ``drawtext`` làm FFmpeg crash (exit 0xC0000005).
FONT_CANDIDATES: tuple[str, ...] = (
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/tahoma.ttf",
    "C:/Windows/Fonts/calibri.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def default_font_file() -> Path | None:
    """Font đầu tiên tìm thấy trên máy, hoặc ``None`` nếu không có cái nào."""
    for candidate in FONT_CANDIDATES:
        path = Path(candidate)
        if path.is_file():
            return path
    return None


def build_concat_file(clips: list[Path]) -> str:
    """Nội dung file cho ``-f concat``.

    Đường dẫn để nguyên kiểu POSIX và bọc nháy đơn; FFmpeg chấp nhận dấu ``/``
    trên Windows nên tránh được rắc rối với dấu ``\\``.
    """
    lines = [f"file '{str(clip).replace(chr(92), '/')}'" for clip in clips]
    return "\n".join(lines) + "\n" if lines else ""


def build_video_filter(spec: ComposeSpec) -> str:
    """Chuỗi filter cho nhánh video, theo thứ tự: khung → phụ đề → chữ chính xác."""
    stages = [
        f"scale={spec.width}:{spec.height}:force_original_aspect_ratio=decrease",
        f"pad={spec.width}:{spec.height}:(ow-iw)/2:(oh-ih)/2:color=black",
        f"fps={spec.fps}",
        "setsar=1",
    ]
    if spec.subtitles is not None:
        style = escape_filter_value(spec.subtitle_style)
        stages.append(f"subtitles='{escape_filter_path(spec.subtitles)}':force_style='{style}'")
    stages.extend(draw.to_filter() for draw in spec.draw_texts)
    return ",".join(stages)


def build_compose_command(spec: ComposeSpec) -> list[str]:
    """Dựng danh sách tham số ``ffmpeg`` (argv), **không** chạy nó."""
    argv: list[str] = [spec.ffmpeg_bin, "-hide_banner", "-nostdin"]
    argv.append("-y" if spec.overwrite else "-n")

    # Input 0: chuỗi clip đã nối.
    argv += ["-f", "concat", "-safe", "0", "-i", str(spec.concat_file)]

    audio_index: int | None = None
    logo_index: int | None = None
    next_index = 1

    if spec.audio is not None:
        argv += ["-i", str(spec.audio)]
        audio_index = next_index
        next_index += 1

    if spec.logo is not None:
        argv += ["-i", str(spec.logo)]
        logo_index = next_index
        next_index += 1

    video_filter = build_video_filter(spec)
    if logo_index is None:
        filter_complex = f"[0:v]{video_filter}[vout]"
    else:
        margin = spec.logo_margin
        filter_complex = (
            f"[0:v]{video_filter}[base];[base][{logo_index}:v]overlay=W-w-{margin}:{margin}[vout]"
        )

    argv += ["-filter_complex", filter_complex, "-map", "[vout]"]
    argv += ["-map", f"{audio_index}:a" if audio_index is not None else "0:a?"]

    argv += [
        "-c:v",
        "libx264",
        "-profile:v",
        "high",
        "-preset",
        spec.preset,
        "-crf",
        str(spec.crf),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        spec.audio_bitrate,
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        "-shortest",
        str(spec.output),
    ]
    return argv
